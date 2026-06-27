from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from statistics import mean

from engine.calibration.cost_capacity import OrderTelemetryMeasurement, load_order_telemetry_measurements
from engine.io.artifacts import write_json_atomic
from engine.memory.store import initialize_memory_db


REQUIRED_STREAMS = ("aggTrade", "bookTicker", "depth")


@dataclass(frozen=True)
class PaperCalibrationFeedbackConfig:
    db_path: Path
    session_id: str
    source_model_version: str = "cost-v1"
    minimum_samples_per_bucket: int = 200
    shrinkage_alpha: float = 0.10


def build_paper_calibration_feedback(config: PaperCalibrationFeedbackConfig) -> dict[str, object]:
    initialize_memory_db(config.db_path)
    rows = _session_measurements(config.db_path, config.session_id)
    bucket_counts = _bucket_counts(rows)
    guard_reasons = _sample_guard_reasons(bucket_counts, config.minimum_samples_per_bucket)
    stream_quality = _stream_quality(config.db_path, config.session_id)
    funding_shock_bps = _funding_shock_bps(config.db_path, config.session_id)
    priors = _build_priors(rows, funding_shock_bps=funding_shock_bps, shrinkage_alpha=config.shrinkage_alpha)
    telemetry_quality = _telemetry_quality(rows, stream_quality, guard_reasons)
    status = "feedback_ready" if rows and not guard_reasons else "sample_guarded"
    created_at = _now_utc()
    payload: dict[str, object] = {
        "artifact_type": "paper_calibration_feedback",
        "schema_version": 1,
        "session_id": config.session_id,
        "source_model_version": config.source_model_version,
        "created_at_utc": created_at,
        "status": status,
        "sample_count": len(rows),
        "minimum_samples_per_bucket": int(config.minimum_samples_per_bucket),
        "bucket_counts": bucket_counts,
        "guard_reasons": guard_reasons,
        "telemetry_quality": telemetry_quality,
        "priors": priors,
        "capacity_questions": _capacity_questions(rows),
        "stress_scenario_severity": _stress_scenario_severity(priors, stream_quality),
        "model_update_allowed": bool(status == "feedback_ready"),
        "live_promotion_allowed": False,
        "can_lower_live_costs": False,
        "governance_notes": [
            "paper_feedback_never_approves_live",
            "paper_feedback_cannot_lower_live_costs_without_live_evidence",
            "paper_feedback_updates_simulation_priors_only",
        ],
    }
    payload["artifact_id"] = "paper-feedback-" + _artifact_hash(payload)[:16]
    payload["artifact_sha256"] = _artifact_hash(payload)
    return payload


def persist_paper_calibration_feedback(db_path: Path, artifact: dict[str, object]) -> None:
    initialize_memory_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO paper_calibration_feedback (
                artifact_id, session_id, source_model_version, created_at_utc, status,
                telemetry_quality_score, sample_count, artifact_sha256, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact["artifact_id"],
                artifact["session_id"],
                artifact["source_model_version"],
                artifact["created_at_utc"],
                artifact["status"],
                artifact.get("telemetry_quality", {}).get("score", 0.0) if isinstance(artifact.get("telemetry_quality"), dict) else 0.0,
                artifact["sample_count"],
                artifact["artifact_sha256"],
                json.dumps(artifact, sort_keys=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def write_paper_calibration_feedback_artifact(path: Path, artifact: dict[str, object]) -> None:
    write_json_atomic(path, artifact)


def _session_measurements(db_path: Path, session_id: str) -> list[OrderTelemetryMeasurement]:
    rows = load_order_telemetry_measurements(db_path)
    filtered: list[OrderTelemetryMeasurement] = []
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        metadata_by_id = {
            str(row["telemetry_id"]): _loads_dict(row["metadata_json"])
            for row in connection.execute("SELECT telemetry_id, metadata_json FROM order_telemetry").fetchall()
        }
    finally:
        connection.close()
    for row in rows:
        metadata = metadata_by_id.get(row.telemetry_id, {})
        if metadata.get("session_id") == session_id:
            filtered.append(row)
    return filtered


def _build_priors(
    rows: list[OrderTelemetryMeasurement],
    *,
    funding_shock_bps: float,
    shrinkage_alpha: float,
) -> dict[str, dict[str, float]]:
    alpha = max(0.0, min(1.0, float(shrinkage_alpha)))
    fill_rates = [row.fill_completion_rate for row in rows]
    priors = {
        "spread_bps": _prior([row.spread_bps for row in rows], incumbent=0.0, alpha=alpha),
        "latency_ms": _prior([row.latency_rtt_ms for row in rows], incumbent=0.0, alpha=alpha),
        "queue_fill_probability": _prior(fill_rates, incumbent=1.0, alpha=alpha),
        "non_fill_opportunity_loss_bps": _prior([row.opportunity_loss_bps for row in rows], incumbent=0.0, alpha=alpha),
        "slippage_bps": _prior([abs(row.realized_vs_modeled_fill_bps) for row in rows], incumbent=0.0, alpha=alpha),
        "funding_shock_bps": _prior([funding_shock_bps] if funding_shock_bps else [], incumbent=0.0, alpha=alpha),
        "realized_vs_modeled_fill_bps": _prior([row.realized_vs_modeled_fill_bps for row in rows], incumbent=0.0, alpha=alpha),
        "edge_erosion_bps": _prior(
            [abs(row.realized_vs_modeled_fill_bps) + row.opportunity_loss_bps for row in rows],
            incumbent=0.0,
            alpha=alpha,
        ),
        "participation_rate": _prior([row.participation_rate for row in rows], incumbent=0.0, alpha=alpha),
        "capacity_estimate_participation": _prior([row.participation_rate * row.fill_completion_rate for row in rows], incumbent=0.0, alpha=alpha),
    }
    return priors


def _prior(values: list[float], *, incumbent: float, alpha: float) -> dict[str, float]:
    sample = mean(values) if values else 0.0
    return {
        "sample_mean": round(sample, 12),
        "shrunk_value": round((float(incumbent) * (1.0 - alpha)) + (sample * alpha), 12),
    }


def _telemetry_quality(
    rows: list[OrderTelemetryMeasurement],
    stream_quality: dict[str, object],
    guard_reasons: list[str],
) -> dict[str, object]:
    issues = list(stream_quality["issues"]) if isinstance(stream_quality.get("issues"), list) else []
    issues.extend(guard_reasons)
    sample_component = min(1.0, len(rows) / 50.0)
    stream_component = max(0.0, 1.0 - (len(issues) * 0.10))
    coverage_component = min(1.0, len(_bucket_counts(rows)) / 3.0) if rows else 0.0
    score = round(max(0.0, min(1.0, (0.50 * sample_component) + (0.30 * stream_component) + (0.20 * coverage_component))), 12)
    return {
        "score": score,
        "sample_count": len(rows),
        "bucket_count": len(_bucket_counts(rows)),
        "stream_event_count": stream_quality["stream_event_count"],
        "lag_p95_ms": stream_quality["lag_p95_ms"],
        "issues": sorted(set(issues)),
    }


def _stream_quality(db_path: Path, session_id: str) -> dict[str, object]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT stream_name, lag_ms, parse_status, metadata_json
            FROM paper_stream_events
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchall()
    finally:
        connection.close()
    stream_names = {str(row[0]).split(":")[-1] for row in rows}
    lags = sorted(float(row[1] or 0.0) for row in rows)
    issues: list[str] = []
    for required in REQUIRED_STREAMS:
        if required not in stream_names:
            issues.append(f"missing_stream:{required}")
    parse_errors = sum(1 for row in rows if str(row[2]) != "parsed")
    if parse_errors:
        issues.append(f"parse_errors:{parse_errors}")
    gap_count = 0
    duplicate_count = 0
    dropped_count = 0
    stale_count = 0
    for row in rows:
        metadata = _loads_dict(row[3])
        gap_count += int(float(metadata.get("gap_count", 0) or 0))
        duplicate_count += int(float(metadata.get("duplicate_count", 0) or 0))
        dropped_count += int(float(metadata.get("dropped_count", 0) or 0))
        stale_count += int(float(metadata.get("stale_periods", 0) or 0))
    for name, value in (
        ("book_trade_gaps", gap_count),
        ("duplicate_messages", duplicate_count),
        ("dropped_messages", dropped_count),
        ("stale_book_periods", stale_count),
    ):
        if value:
            issues.append(f"{name}:{value}")
    return {
        "stream_event_count": len(rows),
        "lag_p95_ms": _percentile(lags, 0.95),
        "issues": issues,
    }


def _funding_shock_bps(db_path: Path, session_id: str) -> float:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT funding_rate, metadata_json
            FROM funding_events
            """
        ).fetchall()
    finally:
        connection.close()
    rates: list[float] = []
    for rate, raw_metadata in rows:
        metadata = _loads_dict(raw_metadata)
        if metadata.get("session_id") == session_id:
            rates.append(abs(float(rate or 0.0)) * 10_000.0)
    return round(mean(rates), 12) if rates else 0.0


def _capacity_questions(rows: list[OrderTelemetryMeasurement]) -> dict[str, float]:
    return {
        "max_participation_rate_seen": round(max((row.participation_rate for row in rows), default=0.0), 12),
        "mean_fill_completion_rate": round(mean([row.fill_completion_rate for row in rows]) if rows else 0.0, 12),
        "mean_edge_erosion_bps": round(
            mean([abs(row.realized_vs_modeled_fill_bps) + row.opportunity_loss_bps for row in rows]) if rows else 0.0,
            12,
        ),
    }


def _stress_scenario_severity(priors: dict[str, dict[str, float]], stream_quality: dict[str, object]) -> str:
    slip = priors["slippage_bps"]["sample_mean"]
    funding = priors["funding_shock_bps"]["sample_mean"]
    issues = len(stream_quality.get("issues", [])) if isinstance(stream_quality.get("issues"), list) else 0
    if slip >= 25.0 or funding >= 5.0 or issues >= 5:
        return "severe"
    if slip >= 10.0 or funding > 0.0 or issues:
        return "medium"
    return "mild"


def _sample_guard_reasons(bucket_counts: dict[str, int], minimum: int) -> list[str]:
    if not bucket_counts:
        return ["no_paper_order_samples"]
    return [
        f"insufficient_bucket_sample:{bucket}"
        for bucket, count in sorted(bucket_counts.items())
        if count < minimum
    ]


def _bucket_counts(rows: list[OrderTelemetryMeasurement]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row.symbol}|{row.regime}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * p))))
    return round(values[index], 12)


def _artifact_hash(payload: dict[str, object]) -> str:
    canonical = dict(payload)
    canonical.pop("artifact_sha256", None)
    canonical.pop("artifact_id", None)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _loads_dict(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
