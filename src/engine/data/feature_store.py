from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from engine.config.models import DataSnapshot
from engine.data.snapshots import clone_snapshot
from engine.forecasting.artifacts import ForecastArtifact, validate_forecast_artifact


FEATURE_STORE_VERSION = "v3_phase2_feature_store_v1"

_TIMEFRAME_SECONDS = {
    "15Min": 900,
    "15m": 900,
    "1Hour": 3_600,
    "1h": 3_600,
}

_EXACT_15M_FIELDS = {
    "ts_open",
    "ts_close",
    "venue",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trade_count",
    "mark_price",
    "index_price",
    "premium_index",
    "funding_rate_last_known",
    "next_funding_time_last_known",
    "open_interest_value",
    "open_interest_units",
    "oi_confidence",
    "best_bid",
    "best_ask",
    "spread_bps",
    "liq_long_notional",
    "liq_short_notional",
    "liq_confidence",
    "rule_tick_size",
    "rule_step_size",
    "rule_min_notional",
    "source_snapshot_id",
}

_TIMING_GUARD_FIELDS = {
    "funding_rate_last_known",
    "next_funding_time_last_known",
    "open_interest_value",
    "liq_long_notional",
    "liq_short_notional",
    "regime_id",
    "one_hour_signal_close",
    "timesfm_forecast_context_end",
}

FORECAST_FEATURE_CONFIDENCE = "model_derived_research_only"

_FORECAST_FEATURE_FIELD_NAMES = {
    "timesfm_q50_return",
    "timesfm_direction",
    "timesfm_interval_width",
    "timesfm_uncertainty_ratio",
    "timesfm_skew",
    "timesfm_confidence_bucket",
    "timesfm_horizon",
    "timesfm_symbol",
    "timesfm_forecast_artifact_id",
    "timesfm_model_id",
}


@dataclass(frozen=True)
class NormalizedFeatureRow:
    ts_open: datetime
    ts_close: datetime
    venue: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int
    mark_price: float
    index_price: float
    premium_index: float
    funding_rate_last_known: float
    next_funding_time_last_known: str | None
    open_interest_value: float
    open_interest_units: str
    oi_confidence: str
    best_bid: float | None
    best_ask: float | None
    spread_bps: float | None
    liq_long_notional: float
    liq_short_notional: float
    liq_confidence: str
    rule_tick_size: float | None
    rule_step_size: float | None
    rule_min_notional: float | None
    source_snapshot_id: str
    timeframe: str
    field_confidence: dict[str, str] = field(default_factory=dict)
    source_ts_by_field: dict[str, datetime | None] = field(default_factory=dict)
    regime_id: str | None = None
    forecast_features: dict[str, object] = field(default_factory=dict)

    def contract_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["ts_open"] = self.ts_open.isoformat()
        payload["ts_close"] = self.ts_close.isoformat()
        payload.pop("timeframe", None)
        payload.pop("field_confidence", None)
        payload.pop("source_ts_by_field", None)
        payload.pop("regime_id", None)
        payload.pop("forecast_features", None)
        return {key: payload.get(key) for key in sorted(_EXACT_15M_FIELDS)}

    def with_forecast_features(
        self,
        forecast_features: dict[str, object],
        *,
        field_confidence: dict[str, str] | None = None,
        source_ts_by_field: dict[str, datetime | None] | None = None,
    ) -> NormalizedFeatureRow:
        merged_features = {**self.forecast_features, **forecast_features}
        merged_confidence = {**self.field_confidence, **(field_confidence or {})}
        merged_source_ts = {**self.source_ts_by_field, **(source_ts_by_field or {})}
        return replace(
            self,
            forecast_features=merged_features,
            field_confidence=merged_confidence,
            source_ts_by_field=merged_source_ts,
        )


@dataclass(frozen=True)
class LabelMetadata:
    label_type: str
    t_i: datetime
    T_i: datetime
    horizon_bars: int
    horizon_seconds: int
    label_resolution: str
    source_columns: list[str]
    row_index: int
    value: float | None = None
    meta_label: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureQualityReport:
    report_id: str
    snapshot_id: str
    status: str
    passed: bool
    issues: list[str]
    metrics: dict[str, object]
    field_confidence: dict[str, str]
    feature_store_version: str = FEATURE_STORE_VERSION

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_normalized_feature_rows(
    snapshot: DataSnapshot,
    *,
    timeframe: str | None = None,
    row_source_timestamps: list[dict[str, datetime | str | None]] | None = None,
) -> list[NormalizedFeatureRow]:
    row_timeframe = timeframe or snapshot.timeframe
    step = _timeframe_delta(row_timeframe)
    field_confidence = _field_confidence(snapshot)
    rows: list[NormalizedFeatureRow] = []
    for index, candle in enumerate(snapshot.candles):
        ts_open = _ensure_aware(candle.timestamp)
        ts_close = ts_open + step
        mark_price = _value_at(snapshot.mark_price, index, candle.close)
        index_price = _value_at(snapshot.index_price, index, candle.close)
        premium_index = ((mark_price - index_price) / index_price) if index_price else 0.0
        spread_bps = _optional_value_at(snapshot.spread_bps, index)
        best_bid, best_ask = _best_bid_ask_from_spread(mark_price, spread_bps)
        source_ts = _default_source_timestamps(ts_close)
        if row_source_timestamps and index < len(row_source_timestamps):
            source_ts.update(
                {
                    key: _parse_optional_ts(value)
                    for key, value in row_source_timestamps[index].items()
                }
            )
        rows.append(
            NormalizedFeatureRow(
                ts_open=ts_open,
                ts_close=ts_close,
                venue=snapshot.venue,
                symbol=snapshot.symbol,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                quote_volume=candle.close * candle.volume,
                trade_count=candle.trade_count,
                mark_price=mark_price,
                index_price=index_price,
                premium_index=premium_index,
                funding_rate_last_known=_value_at(snapshot.funding_rates, index, 0.0),
                next_funding_time_last_known=_string_at(snapshot.next_funding_ts, index),
                open_interest_value=_open_interest_value(snapshot, index),
                open_interest_units=_open_interest_units(snapshot),
                oi_confidence=field_confidence.get("open_interest", "unavailable"),
                best_bid=best_bid,
                best_ask=best_ask,
                spread_bps=spread_bps,
                liq_long_notional=_liquidation_side_value(snapshot, index, "long"),
                liq_short_notional=_liquidation_side_value(snapshot, index, "short"),
                liq_confidence=field_confidence.get("liquidation_notional", "unavailable"),
                rule_tick_size=_venue_rule(snapshot, "tick_size"),
                rule_step_size=_venue_rule(snapshot, "step_size"),
                rule_min_notional=_venue_rule(snapshot, "min_notional"),
                source_snapshot_id=snapshot.snapshot_id,
                timeframe=row_timeframe,
                field_confidence=dict(field_confidence),
                source_ts_by_field=source_ts,
                regime_id=_string_at(snapshot.regime_id, index),
            )
        )
    return rows


def validate_feature_store(
    rows: list[NormalizedFeatureRow],
    *,
    expected_timeframe: str = "15Min",
    labels: list[LabelMetadata] | None = None,
) -> FeatureQualityReport:
    issues: list[str] = []
    if expected_timeframe in {"15Min", "15m"}:
        issues.extend(_validate_15m_contract(rows))
    issues.extend(_validate_timing(rows))
    if labels is not None:
        issues.extend(_validate_labels(rows, labels))
    confidence = _aggregate_confidence(rows)
    metrics = {
        "row_count": len(rows),
        "label_count": len(labels or []),
        "future_source_timestamp_count": sum(1 for issue in issues if issue.startswith("future_")),
        "field_confidence": dict(confidence),
    }
    status = "passed" if not issues else "failed"
    snapshot_id = rows[0].source_snapshot_id if rows else "empty"
    return FeatureQualityReport(
        report_id=f"{snapshot_id}:feature-quality",
        snapshot_id=snapshot_id,
        status=status,
        passed=not issues,
        issues=issues,
        metrics=metrics,
        field_confidence=confidence,
    )


def derive_forecast_feature_fields(
    artifact: ForecastArtifact,
    *,
    symbol: str,
    last_observed_value: float,
) -> dict[str, object]:
    validation = validate_forecast_artifact(artifact)
    if not validation.passed:
        raise ValueError(f"invalid_forecast_artifact:{validation.issues[0]}")
    if last_observed_value == 0:
        raise ValueError("last_observed_value_must_be_non_zero")
    q10 = float(artifact.q10[-1])
    q50 = float(artifact.q50[-1])
    q90 = float(artifact.q90[-1])
    interval_width = float(artifact.interval_width[-1])
    denominator = abs(float(last_observed_value))
    q50_return = (q50 / float(last_observed_value)) - 1.0
    uncertainty_ratio = interval_width / max(denominator, 1e-12)
    skew = ((q90 - q50) - (q50 - q10)) / interval_width if interval_width else 0.0
    fields: dict[str, object] = {
        "timesfm_q50_return": q50_return,
        "timesfm_direction": _direction_from_return(q50_return),
        "timesfm_interval_width": interval_width,
        "timesfm_uncertainty_ratio": uncertainty_ratio,
        "timesfm_skew": skew,
        "timesfm_confidence_bucket": _forecast_confidence_bucket(uncertainty_ratio),
        "timesfm_horizon": artifact.horizon,
        "timesfm_symbol": symbol,
        "timesfm_forecast_artifact_id": artifact.artifact_id,
        "timesfm_model_id": artifact.model_id,
    }
    _reject_raw_forecast_feature_fields(fields)
    return fields


def join_forecast_features(
    rows: list[NormalizedFeatureRow],
    artifacts: list[ForecastArtifact],
) -> list[NormalizedFeatureRow]:
    indexed: dict[tuple[str, datetime], ForecastArtifact] = {}
    for artifact in artifacts:
        validation = validate_forecast_artifact(artifact)
        if not validation.passed:
            raise ValueError(f"invalid_forecast_artifact:{validation.issues[0]}")
        indexed[(artifact.source_snapshot_id, _ensure_aware(artifact.feature_timestamp))] = artifact

    joined: list[NormalizedFeatureRow] = []
    for row in rows:
        artifact = indexed.get((row.source_snapshot_id, row.ts_close))
        if artifact is None:
            joined.append(row)
            continue
        if artifact.context_end_ts > row.ts_close:
            raise ValueError("forecast_context_after_feature_row")
        fields = derive_forecast_feature_fields(
            artifact,
            symbol=row.symbol,
            last_observed_value=row.close,
        )
        confidence = {"timesfm_forecast": FORECAST_FEATURE_CONFIDENCE}
        confidence.update({name: FORECAST_FEATURE_CONFIDENCE for name in fields})
        joined.append(
            row.with_forecast_features(
                fields,
                field_confidence=confidence,
                source_ts_by_field={"timesfm_forecast_context_end": _ensure_aware(artifact.context_end_ts)},
            )
        )
    return joined


def attach_feature_quality_report(snapshot: DataSnapshot, report: FeatureQualityReport) -> DataSnapshot:
    return clone_snapshot(
        snapshot,
        snapshot_id=snapshot.snapshot_id,
        provenance_updates={
            "feature_store_version": report.feature_store_version,
            "feature_quality_status": report.status,
            "feature_quality_report": report.to_dict(),
        },
    )


def assert_candidate_feature_quality(snapshot: DataSnapshot) -> None:
    report = snapshot.provenance.get("feature_quality_report")
    status = snapshot.provenance.get("feature_quality_status")
    if isinstance(report, dict):
        passed = report.get("passed")
        issues = report.get("issues", [])
        if passed is False:
            raise ValueError(f"feature quality failed: {issues}")
    if status == "failed":
        raise ValueError("feature quality failed")


def build_fixed_horizon_labels(
    rows: list[NormalizedFeatureRow],
    *,
    horizon_bars: int,
    label_type: str = "fixed_horizon_return",
    label_resolution: str | None = None,
) -> list[LabelMetadata]:
    if horizon_bars <= 0:
        raise ValueError("horizon_bars must be positive")
    labels: list[LabelMetadata] = []
    for index, row in enumerate(rows):
        end_index = index + horizon_bars
        if end_index >= len(rows):
            break
        end_row = rows[end_index]
        value = (end_row.close / row.close) - 1.0 if row.close else None
        labels.append(
            LabelMetadata(
                label_type=label_type,
                t_i=row.ts_close,
                T_i=end_row.ts_close,
                horizon_bars=horizon_bars,
                horizon_seconds=int((end_row.ts_close - row.ts_close).total_seconds()),
                label_resolution=label_resolution or row.timeframe,
                source_columns=["close"],
                row_index=index,
                value=value,
            )
        )
    return labels


def build_triple_barrier_label_metadata(
    rows: list[NormalizedFeatureRow],
    *,
    horizon_bars: int,
    source_columns: list[str] | None = None,
) -> list[LabelMetadata]:
    labels = build_fixed_horizon_labels(
        rows,
        horizon_bars=horizon_bars,
        label_type="triple_barrier",
    )
    return [
        LabelMetadata(
            **{
                **asdict(label),
                "source_columns": list(source_columns or ["close", "high", "low"]),
                "meta_label": {"ready": True},
            }
        )
        for label in labels
    ]


def build_meta_label_metadata(
    rows: list[NormalizedFeatureRow],
    *,
    horizon_bars: int,
    primary_signal_column: str = "primary_signal",
    label_resolution: str | None = None,
) -> list[LabelMetadata]:
    labels = build_fixed_horizon_labels(
        rows,
        horizon_bars=horizon_bars,
        label_type="meta_label",
        label_resolution=label_resolution,
    )
    return [
        LabelMetadata(
            **{
                **asdict(label),
                "source_columns": [primary_signal_column, "close"],
                "meta_label": {"ready": True, "primary_signal_column": primary_signal_column},
            }
        )
        for label in labels
    ]


def purge_training_indices_for_label_intervals(
    labels: list[LabelMetadata],
    test_indices: set[int],
    *,
    embargo_bars: int = 0,
) -> list[int]:
    test_labels = [labels[index] for index in sorted(test_indices) if 0 <= index < len(labels)]
    if not test_labels:
        return list(range(len(labels)))
    embargo_cutoff = max(label.T_i for label in test_labels) + _infer_label_step(labels) * max(0, embargo_bars - 1)
    train_indices: list[int] = []
    for index, label in enumerate(labels):
        if index in test_indices:
            continue
        if any(_intervals_overlap(label.t_i, label.T_i, test_label.t_i, test_label.T_i) for test_label in test_labels):
            continue
        if label.t_i >= max(test_label.T_i for test_label in test_labels) and label.t_i <= embargo_cutoff:
            continue
        train_indices.append(index)
    return train_indices


def embargo_bars_from_policy(
    *,
    dataset_length: int,
    label_horizon_bars: int,
    embargo_fraction: float = 0.01,
    horizon_multiplier: float = 1.0,
) -> int:
    if not 0.01 <= embargo_fraction <= 0.05:
        raise ValueError("embargo_fraction must be between 0.01 and 0.05")
    fraction_bars = int(dataset_length * embargo_fraction)
    horizon_bars = int(label_horizon_bars * horizon_multiplier)
    return max(1, fraction_bars, horizon_bars)


def feature_quality_allows_validation(snapshot: DataSnapshot) -> bool:
    try:
        assert_candidate_feature_quality(snapshot)
    except ValueError:
        return False
    return True


def _validate_15m_contract(rows: list[NormalizedFeatureRow]) -> list[str]:
    issues: list[str] = []
    for index, row in enumerate(rows):
        payload_keys = set(row.contract_payload())
        missing = sorted(_EXACT_15M_FIELDS - payload_keys)
        if missing:
            issues.append(f"row_{index}_missing_15m_contract_fields={','.join(missing)}")
        if int((row.ts_close - row.ts_open).total_seconds()) != 900:
            issues.append(f"row_{index}_not_15m_interval")
        if row.source_snapshot_id == "":
            issues.append(f"row_{index}_missing_source_snapshot_id")
        none_required = [
            key
            for key, value in row.contract_payload().items()
            if key in _EXACT_15M_FIELDS
            and value is None
            and key
            not in {
                "best_bid",
                "best_ask",
                "spread_bps",
                "next_funding_time_last_known",
                "rule_tick_size",
                "rule_step_size",
                "rule_min_notional",
            }
        ]
        if none_required:
            issues.append(f"row_{index}_null_required_15m_fields={','.join(sorted(none_required))}")
    return issues


def _validate_timing(rows: list[NormalizedFeatureRow]) -> list[str]:
    issues: list[str] = []
    for index, row in enumerate(rows):
        for field_name, source_ts in row.source_ts_by_field.items():
            if field_name not in _TIMING_GUARD_FIELDS:
                continue
            if source_ts is not None and source_ts > row.ts_close:
                issues.append(f"future_{field_name}_row={index}")
    return issues


def _validate_labels(rows: list[NormalizedFeatureRow], labels: list[LabelMetadata]) -> list[str]:
    issues: list[str] = []
    if any(label.T_i <= label.t_i for label in labels):
        issues.append("invalid_label_interval_count")
    if any(not label.source_columns for label in labels):
        issues.append("label_missing_source_columns")
    max_ts_close = rows[-1].ts_close if rows else None
    if max_ts_close is not None and any(label.T_i > max_ts_close for label in labels):
        issues.append("label_uses_unavailable_future_bar")
    return issues


def _field_confidence(snapshot: DataSnapshot) -> dict[str, str]:
    provenance_confidence = snapshot.provenance.get("field_confidence")
    if isinstance(provenance_confidence, dict):
        return {str(key): str(value) for key, value in provenance_confidence.items()}
    row_count = max(1, len(snapshot.candles))
    return {
        "ohlcv": "high",
        "trades_or_aggtrades_raw": "high" if any(candle.trade_count > 0 for candle in snapshot.candles) else "low",
        "funding_rate": "high" if _coverage(snapshot.funding_rates) > 0 else "unavailable",
        "mark_index": "high" if snapshot.mark_price and snapshot.index_price else "close_fallback_low",
        "open_interest": "high" if _coverage(snapshot.open_interest) > 0 else "unavailable",
        "live_book_or_trades": "medium_high" if snapshot.spread_bps else "unavailable",
        "liquidation_notional": "medium" if _coverage(snapshot.liquidation_notional) > 0 else "unavailable",
        "historical_l2": "unavailable",
        "row_count": str(row_count),
    }


def _coverage(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value != 0.0) / len(values)


def _timeframe_delta(timeframe: str) -> timedelta:
    seconds = _TIMEFRAME_SECONDS.get(timeframe)
    if seconds is None:
        raise ValueError(f"unsupported feature-store timeframe: {timeframe!r}")
    return timedelta(seconds=seconds)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_optional_ts(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_aware(value)
    return _ensure_aware(datetime.fromisoformat(str(value)))


def _value_at(values: list[float], index: int, fallback: float) -> float:
    if index < len(values):
        return float(values[index])
    return float(fallback)


def _open_interest_value(snapshot: DataSnapshot, index: int) -> float:
    if index < len(snapshot.open_interest_usd):
        return float(snapshot.open_interest_usd[index])
    return _value_at(snapshot.open_interest, index, 0.0)


def _open_interest_units(snapshot: DataSnapshot) -> str:
    return "quote_notional" if snapshot.open_interest_usd else "contracts"


def _liquidation_side_value(snapshot: DataSnapshot, index: int, side: str) -> float:
    if side == "long" and index < len(snapshot.liq_long_usd):
        return float(snapshot.liq_long_usd[index])
    if side == "short" and index < len(snapshot.liq_short_usd):
        return float(snapshot.liq_short_usd[index])
    total = _value_at(snapshot.liquidation_notional, index, 0.0)
    return total / 2.0 if total else 0.0


def _optional_value_at(values: list[float], index: int) -> float | None:
    if index < len(values):
        return float(values[index])
    return None


def _string_at(values: list[str], index: int) -> str | None:
    if index < len(values) and values[index]:
        return str(values[index])
    return None


def _best_bid_ask_from_spread(mid: float, spread_bps: float | None) -> tuple[float | None, float | None]:
    if spread_bps is None:
        return None, None
    half_spread = mid * (spread_bps / 20_000)
    return mid - half_spread, mid + half_spread


def _venue_rule(snapshot: DataSnapshot, key: str) -> float | None:
    if snapshot.venue_profile is None:
        return None
    for note in snapshot.venue_profile.notes:
        if isinstance(note, str) and note.startswith(f"{key}="):
            try:
                return float(note.split("=", 1)[1])
            except ValueError:
                return None
    return None


def _default_source_timestamps(ts_close: datetime) -> dict[str, datetime | None]:
    return {
        "funding_rate_last_known": ts_close,
        "next_funding_time_last_known": ts_close,
        "open_interest_value": ts_close,
        "liq_long_notional": ts_close,
        "liq_short_notional": ts_close,
        "regime_id": ts_close,
        "one_hour_signal_close": ts_close,
    }


def _aggregate_confidence(rows: list[NormalizedFeatureRow]) -> dict[str, str]:
    if not rows:
        return {}
    confidence: dict[str, str] = {}
    for row in rows:
        for key, value in row.field_confidence.items():
            confidence.setdefault(key, value)
    return confidence


def _direction_from_return(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _forecast_confidence_bucket(uncertainty_ratio: float) -> str:
    if uncertainty_ratio <= 0.01:
        return "high"
    if uncertainty_ratio <= 0.03:
        return "medium"
    return "low"


def _reject_raw_forecast_feature_fields(fields: dict[str, object]) -> None:
    forbidden = {"q10", "q50", "q90", "point_forecast", "order", "trade_action", "position_size"}
    leaked = forbidden.intersection(fields)
    if leaked:
        raise ValueError(f"raw_forecast_feature_field={sorted(leaked)[0]}")
    unknown = set(fields) - _FORECAST_FEATURE_FIELD_NAMES
    if unknown:
        raise ValueError(f"unknown_forecast_feature_field={sorted(unknown)[0]}")


def _intervals_overlap(left_start: datetime, left_end: datetime, right_start: datetime, right_end: datetime) -> bool:
    return left_start < right_end and right_start < left_end


def _infer_label_step(labels: list[LabelMetadata]) -> timedelta:
    if len(labels) >= 2:
        delta = labels[1].t_i - labels[0].t_i
        if delta.total_seconds() > 0:
            return delta
    if labels:
        seconds = max(1, labels[0].horizon_seconds // max(1, labels[0].horizon_bars))
        return timedelta(seconds=seconds)
    return timedelta(seconds=1)
