from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from statistics import mean
from typing import Any

from engine.io.artifacts import write_json_atomic
from engine.memory.store import initialize_memory_db


@dataclass(frozen=True)
class PaperPostRunSummaryConfig:
    db_path: Path
    session_id: str
    max_items: int = 5


def build_paper_post_run_summary(config: PaperPostRunSummaryConfig) -> dict[str, object]:
    initialize_memory_db(config.db_path)
    max_items = max(1, int(config.max_items))
    snapshot = _load_session_snapshot(config.db_path, config.session_id)
    if snapshot["session"] is None:
        raise ValueError(f"paper session not found: {config.session_id}")

    telemetry = snapshot["telemetry"]
    risks = snapshot["risks"]
    top_failure_reasons = _top_failure_reasons(risks, max_items=max_items)
    risk_block_clusters = _risk_block_clusters(risks, max_items=max_items)
    weak_artifacts = _weak_artifacts(snapshot["artifacts"], telemetry, risks, max_items=max_items)
    regime_performance = _regime_performance(telemetry)
    fill_model_mismatch = _fill_model_mismatch(telemetry)
    calibration_readiness = _calibration_readiness(snapshot["calibration"])
    suggested_next_experiments = _suggested_next_experiments(
        top_failure_reasons=top_failure_reasons,
        weak_artifacts=weak_artifacts,
        fill_model_mismatch=fill_model_mismatch,
        calibration_readiness=calibration_readiness,
    )
    status = "actionable" if suggested_next_experiments or top_failure_reasons or weak_artifacts else "clean"
    payload: dict[str, object] = {
        "artifact_type": "paper_post_run_summary",
        "schema_version": 1,
        "session_id": config.session_id,
        "created_at_utc": _created_at(snapshot),
        "status": status,
        "compact": True,
        "session": _session_digest(snapshot),
        "top_failure_reasons": top_failure_reasons,
        "weak_artifacts": weak_artifacts,
        "fill_model_mismatch": fill_model_mismatch,
        "risk_block_clusters": risk_block_clusters,
        "regime_performance": regime_performance,
        "calibration_readiness": calibration_readiness,
        "suggested_next_experiments": suggested_next_experiments,
    }
    payload["artifact_id"] = "paper-postrun-" + _stable_hash(payload)[:16]
    payload["artifact_sha256"] = _stable_hash(payload)
    persist_paper_post_run_summary(config.db_path, payload)
    return payload


def persist_paper_post_run_summary(db_path: Path, summary: dict[str, object]) -> None:
    initialize_memory_db(db_path)
    session_id = str(summary["session_id"])
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT status, payload_json FROM paper_session_summaries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        existing_payload = _loads_dict(row[1]) if row else {}
        existing_payload["agent_post_run_summary"] = summary
        if row:
            connection.execute(
                """
                UPDATE paper_session_summaries
                SET created_at_utc = ?, payload_json = ?
                WHERE session_id = ?
                """,
                (summary["created_at_utc"], json.dumps(existing_payload, sort_keys=True), session_id),
            )
        else:
            connection.execute(
                """
                INSERT INTO paper_session_summaries (
                    session_id, created_at_utc, status, payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    summary["created_at_utc"],
                    str(summary.get("status", "completed")),
                    json.dumps(existing_payload, sort_keys=True),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def write_paper_post_run_summary_artifact(path: Path, summary: dict[str, object]) -> Path:
    return write_json_atomic(path, summary)


def _load_session_snapshot(db_path: Path, session_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        session = connection.execute(
            "SELECT * FROM paper_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        summary = connection.execute(
            "SELECT * FROM paper_session_summaries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        artifacts = connection.execute(
            """
            SELECT artifact_id, status, lifecycle_state, payload_json
            FROM paper_session_artifacts
            WHERE session_id = ?
            ORDER BY artifact_id
            """,
            (session_id,),
        ).fetchall()
        telemetry = connection.execute(
            """
            SELECT telemetry_id, symbol, qty_submitted, qty_filled, expected_price,
                   live_vwap_price, slip_bps, was_rejected, risk_blocked, metadata_json
            FROM order_telemetry
            WHERE json_extract(metadata_json, '$.session_id') = ?
            ORDER BY telemetry_id
            """,
            (session_id,),
        ).fetchall()
        risks = connection.execute(
            """
            SELECT reason_code, severity, action, metadata_json
            FROM risk_events
            WHERE json_extract(metadata_json, '$.session_id') = ?
            ORDER BY risk_event_id
            """,
            (session_id,),
        ).fetchall()
        calibration = connection.execute(
            """
            SELECT status, telemetry_quality_score, sample_count, payload_json
            FROM paper_calibration_feedback
            WHERE session_id = ?
            ORDER BY created_at_utc DESC, artifact_id DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    finally:
        connection.close()
    return {
        "session": dict(session) if session else None,
        "summary": dict(summary) if summary else None,
        "artifacts": [dict(row) for row in artifacts],
        "telemetry": [dict(row) for row in telemetry],
        "risks": [dict(row) for row in risks],
        "calibration": dict(calibration) if calibration else None,
    }


def _top_failure_reasons(risks: list[dict[str, Any]], *, max_items: int) -> list[dict[str, object]]:
    counts = Counter(str(row["reason_code"] or "unknown") for row in risks)
    return [{"reason_code": reason, "count": count} for reason, count in counts.most_common(max_items)]


def _risk_block_clusters(risks: list[dict[str, Any]], *, max_items: int) -> list[dict[str, object]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for row in risks:
        metadata = _loads_dict(row.get("metadata_json"))
        intent = metadata.get("intent") if isinstance(metadata.get("intent"), dict) else {}
        artifact_id = str(intent.get("artifact_id") or metadata.get("artifact_id") or "unknown")
        symbol = str(intent.get("symbol") or metadata.get("symbol") or "unknown")
        reason = str(row.get("reason_code") or "unknown")
        counts[(artifact_id, symbol, reason)] += 1
    return [
        {"artifact_id": artifact, "symbol": symbol, "reason_code": reason, "count": count}
        for (artifact, symbol, reason), count in counts.most_common(max_items)
    ]


def _weak_artifacts(
    artifacts: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    *,
    max_items: int,
) -> list[dict[str, object]]:
    artifact_ids = {str(row["artifact_id"]) for row in artifacts}
    stats: dict[str, dict[str, Any]] = {
        artifact_id: {"order_count": 0, "rejected_count": 0, "risk_block_count": 0, "mismatches": []}
        for artifact_id in artifact_ids
    }
    for row in telemetry:
        artifact_id = _artifact_id_from_telemetry(row)
        stats.setdefault(artifact_id, {"order_count": 0, "rejected_count": 0, "risk_block_count": 0, "mismatches": []})
        stats[artifact_id]["order_count"] += 1
        stats[artifact_id]["rejected_count"] += int(bool(row.get("was_rejected")))
        stats[artifact_id]["risk_block_count"] += int(bool(row.get("risk_blocked")))
        stats[artifact_id]["mismatches"].append(_mismatch_bps(row))
    for row in risks:
        artifact_id = _artifact_id_from_risk(row)
        stats.setdefault(artifact_id, {"order_count": 0, "rejected_count": 0, "risk_block_count": 0, "mismatches": []})
        stats[artifact_id]["risk_block_count"] += 1

    scored: list[dict[str, object]] = []
    for artifact_id, values in stats.items():
        avg_mismatch = _mean_float(values["mismatches"])
        rejected = int(values["rejected_count"])
        risk_blocks = int(values["risk_block_count"])
        reasons: list[str] = []
        if risk_blocks:
            reasons.append("risk_blocks")
        if rejected:
            reasons.append("rejected_orders")
        if avg_mismatch > 25.0:
            reasons.append("high_fill_model_mismatch")
        if not reasons:
            continue
        score = risk_blocks * 3.0 + rejected * 2.0 + avg_mismatch / 10.0
        scored.append(
            {
                "artifact_id": artifact_id,
                "score": round(score, 6),
                "order_count": int(values["order_count"]),
                "rejected_count": rejected,
                "risk_block_count": risk_blocks,
                "avg_abs_mismatch_bps": round(avg_mismatch, 6),
                "reasons": reasons,
            }
        )
    return sorted(scored, key=lambda item: (-float(item["score"]), str(item["artifact_id"])))[:max_items]


def _regime_performance(telemetry: list[dict[str, Any]]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in telemetry:
        grouped[_regime_from_telemetry(row)].append(row)
    result: dict[str, dict[str, object]] = {}
    for regime in sorted(grouped):
        rows = grouped[regime]
        result[regime] = {
            "order_count": len(rows),
            "rejected_count": sum(int(bool(row.get("was_rejected"))) for row in rows),
            "avg_slip_bps": round(_mean_float([_float(row.get("slip_bps")) for row in rows]), 6),
            "avg_abs_mismatch_bps": round(_mean_float([_mismatch_bps(row) for row in rows]), 6),
        }
    return result


def _fill_model_mismatch(telemetry: list[dict[str, Any]]) -> dict[str, object]:
    if not telemetry:
        return {"max_abs_mismatch_bps": 0.0, "worst_artifact_id": None, "sample_count": 0}
    worst = max(telemetry, key=_mismatch_bps)
    return {
        "max_abs_mismatch_bps": round(_mismatch_bps(worst), 6),
        "worst_artifact_id": _artifact_id_from_telemetry(worst),
        "sample_count": len(telemetry),
    }


def _calibration_readiness(row: dict[str, Any] | None) -> dict[str, object]:
    if row is None:
        return {
            "status": "missing",
            "ready_for_model_update": False,
            "sample_count": 0,
            "telemetry_quality_score": 0.0,
            "guard_reasons": ["paper_calibration_feedback_missing"],
        }
    payload = _loads_dict(row.get("payload_json"))
    return {
        "status": str(row.get("status") or payload.get("status") or "unknown"),
        "ready_for_model_update": str(row.get("status") or payload.get("status")) == "feedback_ready",
        "sample_count": int(row.get("sample_count") or payload.get("sample_count") or 0),
        "telemetry_quality_score": round(float(row.get("telemetry_quality_score") or 0.0), 6),
        "guard_reasons": list(payload.get("guard_reasons", [])) if isinstance(payload.get("guard_reasons"), list) else [],
    }


def _suggested_next_experiments(
    *,
    top_failure_reasons: list[dict[str, object]],
    weak_artifacts: list[dict[str, object]],
    fill_model_mismatch: dict[str, object],
    calibration_readiness: dict[str, object],
) -> list[str]:
    suggestions: list[str] = []
    if top_failure_reasons:
        reason = str(top_failure_reasons[0]["reason_code"])
        suggestions.append(f"investigate_{reason}_blocks")
    if not calibration_readiness.get("ready_for_model_update"):
        suggestions.append("collect_more_paper_samples")
    if float(fill_model_mismatch.get("max_abs_mismatch_bps") or 0.0) > 25.0:
        artifact_id = str(fill_model_mismatch.get("worst_artifact_id") or "worst_artifact")
        suggestions.append(f"tune_fill_model_for_{artifact_id}")
    if weak_artifacts:
        suggestions.append("review_or_resize_weak_artifacts")
    return list(dict.fromkeys(suggestions))


def _session_digest(snapshot: dict[str, Any]) -> dict[str, object]:
    session = snapshot["session"] or {}
    summary = snapshot["summary"] or {}
    return {
        "status": session.get("status"),
        "host_id": session.get("host_id"),
        "portfolio_plan_id": session.get("portfolio_plan_id"),
        "artifact_count": len(snapshot["artifacts"]) or int(summary.get("artifact_count") or 0),
        "order_count": len(snapshot["telemetry"]) or int(summary.get("order_count") or 0),
        "risk_block_count": len(snapshot["risks"]) or int(summary.get("risk_block_count") or 0),
        "telemetry_quality_score": round(float(summary.get("telemetry_quality_score") or 0.0), 6),
    }


def _created_at(snapshot: dict[str, Any]) -> str:
    summary = snapshot["summary"] or {}
    session = snapshot["session"] or {}
    return str(summary.get("created_at_utc") or session.get("stopped_at_utc") or session.get("heartbeat_at_utc") or "")


def _artifact_id_from_telemetry(row: dict[str, Any]) -> str:
    metadata = _loads_dict(row.get("metadata_json"))
    raw = metadata.get("raw") if isinstance(metadata.get("raw"), dict) else {}
    return str(raw.get("artifact_id") or metadata.get("artifact_id") or "unknown")


def _artifact_id_from_risk(row: dict[str, Any]) -> str:
    metadata = _loads_dict(row.get("metadata_json"))
    intent = metadata.get("intent") if isinstance(metadata.get("intent"), dict) else {}
    return str(intent.get("artifact_id") or metadata.get("artifact_id") or "unknown")


def _regime_from_telemetry(row: dict[str, Any]) -> str:
    metadata = _loads_dict(row.get("metadata_json"))
    raw = metadata.get("raw") if isinstance(metadata.get("raw"), dict) else {}
    return str(raw.get("regime") or metadata.get("regime") or "unknown")


def _mismatch_bps(row: dict[str, Any]) -> float:
    expected = _float(row.get("expected_price"))
    live = _float(row.get("live_vwap_price"))
    if expected == 0.0:
        return 0.0
    return abs((live - expected) / expected) * 10_000.0


def _mean_float(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _loads_dict(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        payload = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _stable_hash(payload: dict[str, object]) -> str:
    canonical = dict(payload)
    canonical.pop("artifact_id", None)
    canonical.pop("artifact_sha256", None)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
