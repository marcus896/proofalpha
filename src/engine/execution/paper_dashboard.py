from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from engine.io.artifacts import write_json_atomic
from engine.io.sqlite import connect_sqlite
from engine.memory.store import initialize_memory_db


@dataclass(frozen=True)
class PaperSessionDashboardConfig:
    db_path: Path
    session_id: str | None = None
    now_utc: str | None = None
    max_stream_staleness_seconds: int = 300


def build_paper_session_dashboard(config: PaperSessionDashboardConfig) -> dict[str, object]:
    initialize_memory_db(config.db_path)
    snapshot = _load_dashboard_snapshot(config.db_path, config.session_id)
    if snapshot["session"] is None:
        raise ValueError(f"paper session not found: {config.session_id or '<latest>'}")

    now_utc = config.now_utc or _utc_now()
    session = snapshot["session"]
    streams = _stream_section(
        snapshot["streams"],
        expected_streams=_loads_list(session.get("streams_json")),
        now_utc=now_utc,
        max_staleness_seconds=config.max_stream_staleness_seconds,
    )
    orders = _order_section(snapshot["telemetry"])
    risk = _risk_section(snapshot["risks"])
    calibration = _calibration_section(snapshot["calibration"])
    storage = _storage_section(config.db_path, snapshot["backup"], now_utc=now_utc)
    status = _dashboard_status(
        session_status=str(session.get("status") or ""),
        stale_streams=streams["stale_streams"],  # type: ignore[arg-type]
        missing_streams=streams["missing_streams"],  # type: ignore[arg-type]
        risk_block_count=int(risk["risk_block_count"]),
        calibration_ready=bool(calibration["ready_for_model_update"]),
    )
    payload: dict[str, object] = {
        "artifact_type": "paper_session_dashboard",
        "schema_version": 1,
        "created_at_utc": now_utc,
        "status": status,
        "session": _session_section(session, snapshot["summary"]),
        "artifacts": _artifact_section(snapshot["artifacts"]),
        "streams": streams,
        "orders": orders,
        "positions": _position_section(snapshot["telemetry"]),
        "risk": risk,
        "pnl": _pnl_section(snapshot["summary"]),
        "calibration": calibration,
        "storage": storage,
    }
    payload["artifact_id"] = "paper-dashboard-" + _stable_hash(payload)[:16]
    payload["artifact_sha256"] = _stable_hash(payload)
    persist_paper_session_dashboard(config.db_path, payload)
    return payload


def persist_paper_session_dashboard(db_path: Path, dashboard: dict[str, object]) -> None:
    initialize_memory_db(db_path)
    session = dashboard.get("session")
    if not isinstance(session, dict):
        raise ValueError("dashboard session section is missing")
    session_id = str(session["session_id"])
    connection = connect_sqlite(db_path)
    try:
        row = connection.execute(
            "SELECT payload_json FROM paper_session_summaries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        existing_payload = _loads_dict(row[0]) if row else {}
        existing_payload["paper_session_dashboard"] = dashboard
        if row:
            connection.execute(
                """
                UPDATE paper_session_summaries
                SET created_at_utc = ?, payload_json = ?
                WHERE session_id = ?
                """,
                (dashboard["created_at_utc"], json.dumps(existing_payload, sort_keys=True), session_id),
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
                    dashboard["created_at_utc"],
                    str(dashboard.get("status") or "dashboard"),
                    json.dumps(existing_payload, sort_keys=True),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def write_paper_session_dashboard_artifact(path: Path, dashboard: dict[str, object]) -> Path:
    return write_json_atomic(path, dashboard)


def _load_dashboard_snapshot(db_path: Path, session_id: str | None) -> dict[str, Any]:
    connection = connect_sqlite(db_path, read_only=True)
    try:
        if session_id:
            session = connection.execute(
                "SELECT * FROM paper_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        else:
            session = connection.execute(
                "SELECT * FROM paper_sessions ORDER BY started_at_utc DESC, session_id DESC LIMIT 1"
            ).fetchone()
        resolved_session_id = str(session["session_id"]) if session else ""
        summary = connection.execute(
            "SELECT * FROM paper_session_summaries WHERE session_id = ?",
            (resolved_session_id,),
        ).fetchone()
        artifacts = connection.execute(
            """
            SELECT artifact_id, artifact_sha256, lifecycle_state, status, payload_json
            FROM paper_session_artifacts
            WHERE session_id = ?
            ORDER BY artifact_id
            """,
            (resolved_session_id,),
        ).fetchall()
        streams = connection.execute(
            """
            SELECT stream_name, symbol, received_at_utc, parse_status, lag_ms, metadata_json
            FROM paper_stream_events
            WHERE session_id = ?
            ORDER BY received_at_utc, stream_event_id
            """,
            (resolved_session_id,),
        ).fetchall()
        telemetry = connection.execute(
            """
            SELECT telemetry_id, symbol, side, qty_submitted, qty_filled, expected_price,
                   live_vwap_price, slip_bps, fee_quote, latency_rtt_ms, maker_ratio,
                   was_rejected, risk_blocked, metadata_json
            FROM order_telemetry
            WHERE json_extract(metadata_json, '$.session_id') = ?
            ORDER BY telemetry_id
            """,
            (resolved_session_id,),
        ).fetchall()
        risks = connection.execute(
            """
            SELECT reason_code, severity, action, ts_utc, metadata_json
            FROM risk_events
            WHERE json_extract(metadata_json, '$.session_id') = ?
            ORDER BY ts_utc, risk_event_id
            """,
            (resolved_session_id,),
        ).fetchall()
        backup = connection.execute(
            """
            SELECT backup_id, created_at_utc, backup_location, snapshot_digest,
                   table_count, status, metadata_json
            FROM backup_manifests
            WHERE json_extract(metadata_json, '$.session_id') = ?
            ORDER BY created_at_utc DESC, backup_id DESC
            LIMIT 1
            """,
            (resolved_session_id,),
        ).fetchone()
        calibration = connection.execute(
            """
            SELECT status, telemetry_quality_score, sample_count, created_at_utc, payload_json
            FROM paper_calibration_feedback
            WHERE session_id = ?
            ORDER BY created_at_utc DESC, artifact_id DESC
            LIMIT 1
            """,
            (resolved_session_id,),
        ).fetchone()
    finally:
        connection.close()
    return {
        "session": dict(session) if session else None,
        "summary": dict(summary) if summary else None,
        "artifacts": [dict(row) for row in artifacts],
        "streams": [dict(row) for row in streams],
        "telemetry": [dict(row) for row in telemetry],
        "risks": [dict(row) for row in risks],
        "backup": dict(backup) if backup else None,
        "calibration": dict(calibration) if calibration else None,
    }


def _session_section(session: dict[str, Any], summary: dict[str, Any] | None) -> dict[str, object]:
    symbols = _loads_list(session.get("symbols_json"))
    streams = _loads_list(session.get("streams_json"))
    return {
        "session_id": session["session_id"],
        "host_id": session.get("host_id"),
        "status": session.get("status"),
        "started_at_utc": session.get("started_at_utc"),
        "stopped_at_utc": session.get("stopped_at_utc"),
        "heartbeat_at_utc": session.get("heartbeat_at_utc"),
        "uptime_seconds": _float((summary or {}).get("uptime_seconds")),
        "portfolio_plan_id": session.get("portfolio_plan_id"),
        "symbols": symbols,
        "streams": streams,
        "symbol_count": len(symbols),
        "artifact_count": int(_float((summary or {}).get("artifact_count"))),
        "code_hash": session.get("code_hash"),
        "config_checksum": session.get("config_checksum"),
    }


def _artifact_section(artifacts: list[dict[str, Any]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in artifacts:
        payload = _loads_dict(row.get("payload_json"))
        promotion_manifest = _loads_dict(payload.get("promotion_manifest"))
        result.append(
            {
                "artifact_id": row.get("artifact_id"),
                "status": row.get("status"),
                "lifecycle_state": row.get("lifecycle_state"),
                "artifact_sha256": row.get("artifact_sha256"),
                "portfolio_role": payload.get("portfolio_role"),
                "regime_scope": payload.get("regime_scope", []),
                "promotion_manifest_present": bool(promotion_manifest),
                "promotion_manifest_paper_eligibility": bool(
                    promotion_manifest.get("paper_eligibility", False)
                ),
                "promotion_manifest_expiry_time_utc": promotion_manifest.get("expiry_time_utc"),
            }
        )
    return result


def _stream_section(
    streams: list[dict[str, Any]],
    *,
    expected_streams: list[str],
    now_utc: str,
    max_staleness_seconds: int,
) -> dict[str, object]:
    lag_values = [_float(row.get("lag_ms")) for row in streams if row.get("lag_ms") is not None]
    parse_counts = Counter(str(row.get("parse_status") or "unknown") for row in streams)
    event_counts = Counter(str(row.get("stream_name") or "unknown") for row in streams)
    latest_by_stream: dict[str, str] = {}
    gap_count = 0
    dropped_count = 0
    duplicate_count = 0
    for row in streams:
        stream_name = str(row.get("stream_name") or "unknown")
        received_at = str(row.get("received_at_utc") or "")
        if received_at >= latest_by_stream.get(stream_name, ""):
            latest_by_stream[stream_name] = received_at
        metadata = _loads_dict(row.get("metadata_json"))
        gap_count += int(_float(metadata.get("gap_count")))
        dropped_count += int(_float(metadata.get("dropped_count")))
        duplicate_count += int(_float(metadata.get("duplicate_count")))

    seen_streams = set(event_counts)
    expected = [str(value) for value in expected_streams]
    missing_streams = sorted(stream for stream in expected if stream not in seen_streams)
    stale_streams = sorted(
        stream
        for stream, received_at in latest_by_stream.items()
        if _age_seconds(received_at, now_utc) is not None
        and _age_seconds(received_at, now_utc) > max_staleness_seconds
    )
    return {
        "event_count": len(streams),
        "event_counts_by_stream": dict(sorted(event_counts.items())),
        "parse_status_counts": dict(sorted(parse_counts.items())),
        "lag_ms": {
            "p50": _percentile(lag_values, 50),
            "p95": _percentile(lag_values, 95),
            "max": round(max(lag_values), 6) if lag_values else 0.0,
        },
        "latest_received_at_utc": latest_by_stream,
        "missing_streams": missing_streams,
        "stale_streams": stale_streams,
        "gap_count": gap_count,
        "dropped_count": dropped_count,
        "duplicate_count": duplicate_count,
    }


def _order_section(telemetry: list[dict[str, Any]]) -> dict[str, object]:
    filled_rows = [row for row in telemetry if _float(row.get("qty_filled")) > 0.0]
    partial_rows = [
        row
        for row in telemetry
        if 0.0 < _float(row.get("qty_filled")) < _float(row.get("qty_submitted"))
    ]
    slip_values = [_float(row.get("slip_bps")) for row in telemetry if row.get("slip_bps") is not None]
    latency_values = [_float(row.get("latency_rtt_ms")) for row in telemetry if row.get("latency_rtt_ms") is not None]
    maker_values = [_float(row.get("maker_ratio")) for row in telemetry if row.get("maker_ratio") is not None]
    return {
        "order_count": len(telemetry),
        "filled_count": len(filled_rows),
        "partial_count": len(partial_rows),
        "rejected_count": sum(int(bool(row.get("was_rejected"))) for row in telemetry),
        "risk_blocked_count": sum(int(bool(row.get("risk_blocked"))) for row in telemetry),
        "qty_filled": round(sum(_float(row.get("qty_filled")) for row in telemetry), 12),
        "fee_quote": round(sum(_float(row.get("fee_quote")) for row in telemetry), 12),
        "avg_slip_bps": _mean(slip_values),
        "max_abs_slip_bps": round(max((abs(value) for value in slip_values), default=0.0), 6),
        "latency_ms_p95": _percentile(latency_values, 95),
        "maker_ratio_avg": _mean(maker_values),
    }


def _position_section(telemetry: list[dict[str, Any]]) -> dict[str, object]:
    grouped: dict[str, dict[str, float]] = defaultdict(lambda: {"net_qty": 0.0, "notional": 0.0, "last_price": 0.0})
    for row in telemetry:
        symbol = str(row.get("symbol") or "unknown")
        qty = _float(row.get("qty_filled"))
        if qty <= 0.0:
            continue
        side = str(row.get("side") or "").upper()
        signed_qty = -qty if side == "SELL" else qty
        price = _float(row.get("live_vwap_price")) or _float(row.get("expected_price"))
        grouped[symbol]["net_qty"] += signed_qty
        grouped[symbol]["notional"] += abs(qty * price)
        grouped[symbol]["last_price"] = price
    positions = {
        symbol: {
            "net_qty": round(values["net_qty"], 12),
            "notional": round(values["notional"], 12),
            "last_price": round(values["last_price"], 12),
        }
        for symbol, values in sorted(grouped.items())
    }
    return {
        "simulated_positions": positions,
        "gross_notional": round(sum(item["notional"] for item in positions.values()), 12),
    }


def _risk_section(risks: list[dict[str, Any]]) -> dict[str, object]:
    counts = Counter(str(row.get("reason_code") or "unknown") for row in risks)
    return {
        "risk_block_count": len(risks),
        "blocks_by_reason": dict(sorted(counts.items())),
        "recent_events": [
            {
                "reason_code": row.get("reason_code"),
                "severity": row.get("severity"),
                "action": row.get("action"),
                "ts_utc": row.get("ts_utc"),
            }
            for row in risks[-5:]
        ],
    }


def _pnl_section(summary: dict[str, Any] | None) -> dict[str, object]:
    summary = summary or {}
    return {
        "paper_pnl": _float(summary.get("paper_pnl")),
        "drawdown": _float(summary.get("drawdown")),
        "funding_fee": _float(summary.get("funding_fee")),
        "telemetry_quality_score": _float(summary.get("telemetry_quality_score")),
    }


def _calibration_section(calibration: dict[str, Any] | None) -> dict[str, object]:
    if calibration is None:
        return {
            "status": "missing",
            "sample_count": 0,
            "telemetry_quality_score": 0.0,
            "ready_for_model_update": False,
            "guard_reasons": ["missing_paper_calibration_feedback"],
        }
    payload = _loads_dict(calibration.get("payload_json"))
    status = str(calibration.get("status") or payload.get("status") or "unknown")
    return {
        "status": status,
        "sample_count": int(_float(calibration.get("sample_count"))),
        "telemetry_quality_score": _float(calibration.get("telemetry_quality_score")),
        "ready_for_model_update": status == "feedback_ready",
        "guard_reasons": payload.get("guard_reasons", []),
    }


def _storage_section(db_path: Path, backup: dict[str, Any] | None, *, now_utc: str) -> dict[str, object]:
    latest_backup = None
    if backup:
        age_seconds = _age_seconds(str(backup.get("created_at_utc") or ""), now_utc)
        latest_backup = {
            "backup_id": backup.get("backup_id"),
            "created_at_utc": backup.get("created_at_utc"),
            "backup_location": backup.get("backup_location"),
            "status": backup.get("status"),
            "snapshot_digest": backup.get("snapshot_digest"),
            "table_count": int(_float(backup.get("table_count"))),
            "age_seconds": age_seconds,
        }
    return {
        "db_path": str(db_path),
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "latest_backup": latest_backup,
    }


def _dashboard_status(
    *,
    session_status: str,
    stale_streams: list[str],
    missing_streams: list[str],
    risk_block_count: int,
    calibration_ready: bool,
) -> str:
    if session_status in {"failed", "error"}:
        return "critical"
    if stale_streams or missing_streams or risk_block_count or not calibration_ready:
        return "attention"
    return "healthy"


def _loads_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _loads_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in payload] if isinstance(payload, list) else []


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((percentile / 100.0) * len(ordered) + 0.999999) - 1))
    return round(ordered[index], 6)


def _age_seconds(ts_utc: str, now_utc: str) -> float | None:
    try:
        ts = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
        now = datetime.fromisoformat(now_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (now - ts).total_seconds())


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
