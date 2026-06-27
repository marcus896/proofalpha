from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from math import sqrt
from pathlib import Path
import sqlite3
from statistics import mean, median
from typing import Iterable

from engine.io.artifacts import write_json_atomic
from engine.memory.store import initialize_memory_db


CAPACITY_MULTIPLIERS = (1, 2, 5, 10)


@dataclass(frozen=True)
class OrderTelemetryMeasurement:
    telemetry_id: str
    symbol: str
    side: str
    regime: str
    funding_window: bool
    qty_submitted: float
    qty_filled: float
    expected_price: float
    live_vwap_price: float
    modeled_fill_price: float
    submitted_notional: float
    filled_notional: float
    adv_notional: float
    participation_rate: float
    sqrt_q_over_adv: float
    fill_completion_rate: float
    realized_vs_modeled_fill_bps: float
    opportunity_loss_bps: float
    spread_bps: float
    depth_notional: float
    vol_15m: float
    latency_rtt_ms: float
    maker_ratio: float


@dataclass(frozen=True)
class CalibrationModel:
    model_version: str
    source_model_version: str
    status: str
    sample_count: int
    bucket_counts: dict[str, int]
    square_root_impact_bps: float
    spread_coefficient: float
    volatility_coefficient: float
    latency_coefficient: float
    funding_window_bps: float
    queue_fill_coefficient: float
    max_participation_rate: float
    notes: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CapacityLadderRow:
    multiplier: int
    modeled_cost_bps: float
    edge_erosion_bps: float
    edge_erosion_ratio: float
    modeled_fill_completion_rate: float
    scaled_participation_rate: float
    passed: bool
    failure_reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CapacityReport:
    baseline_edge_bps: float
    multipliers: list[int]
    rows: list[CapacityLadderRow]
    passed: bool
    failure_reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_edge_bps": self.baseline_edge_bps,
            "multipliers": self.multipliers,
            "rows": [row.to_dict() for row in self.rows],
            "passed": self.passed,
            "failure_reasons": self.failure_reasons,
        }


@dataclass(frozen=True)
class CalibrationUpdateDecision:
    allowed: bool
    selected_model: CalibrationModel
    reasons: list[str]


def load_order_telemetry_measurements(
    db_path: Path,
    *,
    symbols: set[str] | None = None,
) -> list[OrderTelemetryMeasurement]:
    initialize_memory_db(db_path)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT
                telemetry_id, symbol, side, qty_submitted, qty_filled, expected_price,
                live_vwap_price, slip_bps, spread_bps, depth_at_price, topn_depth,
                vol_15m, latency_rtt_ms, maker_ratio, was_rejected, risk_blocked,
                metadata_json
            FROM order_telemetry
            WHERE COALESCE(was_rejected, 0) = 0 AND COALESCE(risk_blocked, 0) = 0
            ORDER BY symbol, telemetry_id
            """
        ).fetchall()
    finally:
        connection.close()

    measurements: list[OrderTelemetryMeasurement] = []
    for row in rows:
        symbol = str(row["symbol"] or "")
        if symbols is not None and symbol not in symbols:
            continue
        measurement = _measurement_from_row(row)
        if measurement is not None:
            measurements.append(measurement)
    return measurements


def fit_impact_calibration(
    measurements: Iterable[OrderTelemetryMeasurement],
    *,
    source_model_version: str,
    minimum_orders_per_bucket: int = 200,
    max_participation_rate: float = 0.05,
) -> CalibrationModel:
    rows = list(measurements)
    bucket_counts = _bucket_counts(rows)
    notes: list[str] = []
    if not rows:
        return CalibrationModel(
            model_version=_model_version("empty", source_model_version, {}),
            source_model_version=source_model_version,
            status="blocked",
            sample_count=0,
            bucket_counts={},
            square_root_impact_bps=0.0,
            spread_coefficient=0.0,
            volatility_coefficient=0.0,
            latency_coefficient=0.0,
            funding_window_bps=0.0,
            queue_fill_coefficient=0.0,
            max_participation_rate=max_participation_rate,
            notes=["no_order_telemetry_measurements"],
        )

    for bucket, count in sorted(bucket_counts.items()):
        if count < minimum_orders_per_bucket:
            notes.append(f"insufficient_bucket_sample:{bucket}")
    status = "usable" if not notes else "sample_guarded"

    adjusted_targets = [_adjusted_impact_target_bps(row) for row in rows]
    sqrt_terms = [row.sqrt_q_over_adv for row in rows if row.sqrt_q_over_adv > 0.0]
    square_root_samples = [
        target / max(row.sqrt_q_over_adv, 1e-12)
        for target, row in zip(adjusted_targets, rows, strict=True)
        if row.sqrt_q_over_adv > 0.0
    ]
    square_root_impact_bps = _trimmed_mean(square_root_samples) if square_root_samples else 0.0
    spread_coefficient = _bounded_mean_ratio(adjusted_targets, [row.spread_bps for row in rows], cap=2.0)
    volatility_coefficient = _bounded_mean_ratio(adjusted_targets, [row.vol_15m * 10_000.0 for row in rows], cap=5.0)
    latency_coefficient = _bounded_mean_ratio(adjusted_targets, [row.latency_rtt_ms for row in rows], cap=0.25)
    funding_window_bps = _funding_window_delta(rows, adjusted_targets)
    queue_fill_coefficient = max(0.0, min(1.0, mean(row.fill_completion_rate for row in rows)))

    payload = {
        "source_model_version": source_model_version,
        "sample_count": len(rows),
        "bucket_counts": bucket_counts,
        "sqrt": round(square_root_impact_bps, 12),
        "spread": round(spread_coefficient, 12),
        "volatility": round(volatility_coefficient, 12),
        "latency": round(latency_coefficient, 12),
        "funding": round(funding_window_bps, 12),
        "queue": round(queue_fill_coefficient, 12),
        "max_participation_rate": round(max_participation_rate, 12),
    }
    return CalibrationModel(
        model_version=_model_version("cost-capacity", source_model_version, payload),
        source_model_version=source_model_version,
        status=status,
        sample_count=len(rows),
        bucket_counts=bucket_counts,
        square_root_impact_bps=round(square_root_impact_bps, 12),
        spread_coefficient=round(spread_coefficient, 12),
        volatility_coefficient=round(volatility_coefficient, 12),
        latency_coefficient=round(latency_coefficient, 12),
        funding_window_bps=round(funding_window_bps, 12),
        queue_fill_coefficient=round(queue_fill_coefficient, 12),
        max_participation_rate=float(max_participation_rate),
        notes=notes,
    )


def build_capacity_report(
    measurements: Iterable[OrderTelemetryMeasurement],
    *,
    model: CalibrationModel,
    baseline_edge_bps: float,
    max_participation_rate: float | None = None,
    multipliers: Iterable[int] = CAPACITY_MULTIPLIERS,
) -> CapacityReport:
    rows = list(measurements)
    average_participation = _average([row.participation_rate for row in rows], default=0.0)
    average_spread = _average([row.spread_bps for row in rows], default=0.0)
    average_vol = _average([row.vol_15m for row in rows], default=0.0)
    average_latency = _average([row.latency_rtt_ms for row in rows], default=0.0)
    average_fill = _average([row.fill_completion_rate for row in rows], default=1.0)
    baseline_cost = _modeled_cost_bps(
        model,
        participation_rate=average_participation,
        spread_bps=average_spread,
        vol_15m=average_vol,
        latency_ms=average_latency,
        funding_window=False,
    )
    participation_limit = float(max_participation_rate or model.max_participation_rate)

    ladder_rows: list[CapacityLadderRow] = []
    failure_reasons: list[str] = []
    for multiplier in multipliers:
        scaled_participation = average_participation * int(multiplier)
        modeled_cost = _modeled_cost_bps(
            model,
            participation_rate=scaled_participation,
            spread_bps=average_spread,
            vol_15m=average_vol,
            latency_ms=average_latency,
            funding_window=False,
        )
        edge_erosion_bps = max(0.0, modeled_cost - baseline_cost)
        edge_erosion_ratio = edge_erosion_bps / max(float(baseline_edge_bps), 1e-12)
        depth_fill_pressure = 1.0
        if scaled_participation > participation_limit > 0.0:
            depth_fill_pressure = participation_limit / scaled_participation
        modeled_fill = max(0.0, min(1.0, average_fill * model.queue_fill_coefficient * depth_fill_pressure))
        row_reasons: list[str] = []
        if int(multiplier) == 5 and edge_erosion_ratio > 0.25:
            row_reasons.append("capacity_fail_5x_edge_erosion")
        if int(multiplier) == 5 and modeled_fill < 0.95:
            row_reasons.append("capacity_fail_5x_fill_completion")
        if row_reasons:
            failure_reasons.extend(row_reasons)
        ladder_rows.append(
            CapacityLadderRow(
                multiplier=int(multiplier),
                modeled_cost_bps=round(modeled_cost, 12),
                edge_erosion_bps=round(edge_erosion_bps, 12),
                edge_erosion_ratio=round(edge_erosion_ratio, 12),
                modeled_fill_completion_rate=round(modeled_fill, 12),
                scaled_participation_rate=round(scaled_participation, 12),
                passed=not row_reasons,
                failure_reasons=row_reasons,
            )
        )

    unique_failures = sorted(set(failure_reasons))
    return CapacityReport(
        baseline_edge_bps=float(baseline_edge_bps),
        multipliers=[int(multiplier) for multiplier in multipliers],
        rows=ladder_rows,
        passed=not unique_failures,
        failure_reasons=unique_failures,
    )


def evaluate_calibration_update(
    incumbent: CalibrationModel,
    candidate: CalibrationModel,
    *,
    oos_passed: bool,
    bootstrap_passed: bool,
    minimum_orders_per_bucket: int = 200,
    shrinkage_weight: float | None = None,
) -> CalibrationUpdateDecision:
    reasons: list[str] = []
    if not oos_passed:
        reasons.append("oos_confidence_failed")
    if not bootstrap_passed:
        reasons.append("bootstrap_confidence_failed")
    for bucket, count in sorted(candidate.bucket_counts.items()):
        if count < minimum_orders_per_bucket:
            reasons.append(f"insufficient_bucket_sample:{bucket}")
    lowers_cost = candidate.square_root_impact_bps < incumbent.square_root_impact_bps
    raises_capacity = candidate.max_participation_rate > incumbent.max_participation_rate
    if (lowers_cost or raises_capacity) and reasons:
        return CalibrationUpdateDecision(allowed=False, selected_model=incumbent, reasons=sorted(set(reasons)))

    if reasons:
        return CalibrationUpdateDecision(allowed=False, selected_model=incumbent, reasons=sorted(set(reasons)))

    if shrinkage_weight is None:
        shrinkage_weight = min(0.5, candidate.sample_count / max(candidate.sample_count + incumbent.sample_count, 1))
    shrinkage_weight = max(0.0, min(1.0, float(shrinkage_weight)))
    selected = CalibrationModel(
        model_version=_model_version(
            "cost-capacity-shrunk",
            candidate.source_model_version,
            {"incumbent": incumbent.model_version, "candidate": candidate.model_version, "weight": shrinkage_weight},
        ),
        source_model_version=candidate.source_model_version,
        status=candidate.status,
        sample_count=candidate.sample_count,
        bucket_counts=dict(candidate.bucket_counts),
        square_root_impact_bps=_shrink(incumbent.square_root_impact_bps, candidate.square_root_impact_bps, shrinkage_weight),
        spread_coefficient=_shrink(incumbent.spread_coefficient, candidate.spread_coefficient, shrinkage_weight),
        volatility_coefficient=_shrink(incumbent.volatility_coefficient, candidate.volatility_coefficient, shrinkage_weight),
        latency_coefficient=_shrink(incumbent.latency_coefficient, candidate.latency_coefficient, shrinkage_weight),
        funding_window_bps=_shrink(incumbent.funding_window_bps, candidate.funding_window_bps, shrinkage_weight),
        queue_fill_coefficient=_shrink(incumbent.queue_fill_coefficient, candidate.queue_fill_coefficient, shrinkage_weight),
        max_participation_rate=_shrink(incumbent.max_participation_rate, candidate.max_participation_rate, shrinkage_weight),
        notes=[*candidate.notes, f"shrinkage_weight:{round(shrinkage_weight, 12)}"],
    )
    return CalibrationUpdateDecision(allowed=True, selected_model=selected, reasons=[])


def build_cost_capacity_calibration_artifact(
    *,
    model: CalibrationModel,
    capacity_report: CapacityReport,
    source: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "artifact_type": "cost_capacity_calibration",
        "schema_version": 1,
        "source": source,
        "cost_model_version": model.model_version,
        "source_model_version": model.source_model_version,
        "model": model.to_dict(),
        "capacity_report": capacity_report.to_dict(),
        "status": "passed" if model.status == "usable" and capacity_report.passed else "blocked",
    }
    payload["artifact_sha256"] = _artifact_hash(payload)
    return payload


def write_cost_capacity_calibration_artifact(path: Path, artifact: dict[str, object]) -> None:
    write_json_atomic(path, artifact)


def stamp_cost_model_version(payload: dict[str, object], model: CalibrationModel) -> dict[str, object]:
    stamped = dict(payload)
    stamped["cost_model_version"] = model.model_version
    stamped["cost_model"] = model.model_version
    return stamped


def _measurement_from_row(row: sqlite3.Row) -> OrderTelemetryMeasurement | None:
    qty_submitted = _float(row["qty_submitted"])
    qty_filled = _float(row["qty_filled"])
    expected_price = _float(row["expected_price"])
    live_vwap_price = _float(row["live_vwap_price"])
    if qty_submitted <= 0.0 or expected_price <= 0.0:
        return None
    metadata = _loads_dict(row["metadata_json"])
    raw = metadata.get("raw") if isinstance(metadata.get("raw"), dict) else {}
    metadata_sources = [metadata, raw]
    modeled_fill_price = _first_float(metadata_sources, "modeled_fill_price", default=expected_price)
    adv_notional = _first_float(metadata_sources, "adv_notional", "adv_quote_volume", "average_daily_volume_notional", default=0.0)
    if adv_notional <= 0.0:
        adv_notional = max(_float(row["topn_depth"]) * expected_price * 96.0, qty_submitted * expected_price)
    submitted_notional = qty_submitted * expected_price
    filled_notional = qty_filled * live_vwap_price
    participation = submitted_notional / max(adv_notional, 1e-12)
    fill_completion = qty_filled / qty_submitted
    side = str(row["side"] or "").upper()
    slip_bps = _float(row["slip_bps"])
    if slip_bps == 0.0 and live_vwap_price > 0.0:
        multiplier = 1.0 if side == "BUY" else -1.0
        slip_bps = multiplier * (live_vwap_price - modeled_fill_price) / modeled_fill_price * 10_000.0
    depth_notional = max(_float(row["depth_at_price"]), _float(row["topn_depth"])) * expected_price
    regime = str(_first_value(metadata_sources, "regime", default="unknown") or "unknown")
    funding_window = bool(_first_value(metadata_sources, "funding_window", default=False))
    opportunity_loss = _first_float(
        metadata_sources,
        "opportunity_loss_bps",
        default=max(0.0, 1.0 - fill_completion) * abs(slip_bps),
    )
    return OrderTelemetryMeasurement(
        telemetry_id=str(row["telemetry_id"] or ""),
        symbol=str(row["symbol"] or ""),
        side=side,
        regime=regime,
        funding_window=funding_window,
        qty_submitted=qty_submitted,
        qty_filled=qty_filled,
        expected_price=expected_price,
        live_vwap_price=live_vwap_price,
        modeled_fill_price=modeled_fill_price,
        submitted_notional=submitted_notional,
        filled_notional=filled_notional,
        adv_notional=adv_notional,
        participation_rate=participation,
        sqrt_q_over_adv=sqrt(max(0.0, participation)),
        fill_completion_rate=max(0.0, min(1.0, fill_completion)),
        realized_vs_modeled_fill_bps=slip_bps,
        opportunity_loss_bps=opportunity_loss,
        spread_bps=_float(row["spread_bps"]),
        depth_notional=depth_notional,
        vol_15m=_float(row["vol_15m"]),
        latency_rtt_ms=_float(row["latency_rtt_ms"]),
        maker_ratio=_float(row["maker_ratio"]),
    )


def _adjusted_impact_target_bps(row: OrderTelemetryMeasurement) -> float:
    taker_spread = row.spread_bps * max(0.0, 1.0 - row.maker_ratio)
    return max(0.0, row.realized_vs_modeled_fill_bps - (0.5 * taker_spread))


def _modeled_cost_bps(
    model: CalibrationModel,
    *,
    participation_rate: float,
    spread_bps: float,
    vol_15m: float,
    latency_ms: float,
    funding_window: bool,
) -> float:
    return max(
        0.0,
        (model.square_root_impact_bps * sqrt(max(0.0, participation_rate)))
        + (model.spread_coefficient * max(0.0, spread_bps))
        + (model.volatility_coefficient * max(0.0, vol_15m) * 10_000.0)
        + (model.latency_coefficient * max(0.0, latency_ms))
        + (model.funding_window_bps if funding_window else 0.0),
    )


def _bucket_counts(rows: list[OrderTelemetryMeasurement]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row.symbol}|{row.regime}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _trimmed_mean(values: list[float]) -> float:
    clean = sorted(value for value in values if value >= 0.0)
    if not clean:
        return 0.0
    if len(clean) < 5:
        return mean(clean)
    trim = max(1, int(len(clean) * 0.10))
    trimmed = clean[trim:-trim] or clean
    return mean(trimmed)


def _average(values: list[float], *, default: float) -> float:
    return mean(values) if values else float(default)


def _bounded_mean_ratio(targets: list[float], controls: list[float], *, cap: float) -> float:
    ratios = [target / control for target, control in zip(targets, controls, strict=True) if control > 0.0]
    if not ratios:
        return 0.0
    return max(0.0, min(float(cap), median(ratios)))


def _funding_window_delta(rows: list[OrderTelemetryMeasurement], targets: list[float]) -> float:
    funding_targets = [target for row, target in zip(rows, targets, strict=True) if row.funding_window]
    non_funding_targets = [target for row, target in zip(rows, targets, strict=True) if not row.funding_window]
    if not funding_targets or not non_funding_targets:
        return 0.0
    return max(0.0, mean(funding_targets) - mean(non_funding_targets))


def _shrink(old: float, new: float, weight: float) -> float:
    return round((float(old) * (1.0 - weight)) + (float(new) * weight), 12)


def _model_version(prefix: str, source: str, payload: dict[str, object]) -> str:
    digest = hashlib.sha256(
        json.dumps({"source": source, "payload": payload}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _artifact_hash(payload: dict[str, object]) -> str:
    canonical = dict(payload)
    canonical.pop("artifact_sha256", None)
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


def _first_value(sources: list[dict[str, object]], *keys: str, default: object) -> object:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return default


def _first_float(sources: list[dict[str, object]], *keys: str, default: float) -> float:
    return _float(_first_value(sources, *keys, default=default))


def _float(value: object) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
