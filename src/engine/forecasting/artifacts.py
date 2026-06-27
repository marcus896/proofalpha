from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Sequence

from engine.forecasting.timesfm_adapter import ForecastResult


REQUIRED_QUANTILES = ("q10", "q50", "q90")


@dataclass(frozen=True)
class ForecastCovariate:
    name: str
    value: object
    available_at: datetime | str
    known_at_decision_time: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "available_at": _iso(_parse_ts(self.available_at)),
            "known_at_decision_time": self.known_at_decision_time,
        }


@dataclass(frozen=True)
class ForecastArtifact:
    artifact_id: str
    source: str
    model_id: str
    point_forecast: list[float]
    q10: list[float]
    q50: list[float]
    q90: list[float]
    interval_width: list[float]
    direction_confidence: float
    context_length: int
    horizon: int
    config_checksum: str
    source_snapshot_id: str
    created_at: datetime
    context_end_ts: datetime
    feature_timestamp: datetime
    future_covariates: list[ForecastCovariate] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "source": self.source,
            "model_id": self.model_id,
            "point_forecast": list(self.point_forecast),
            "q10": list(self.q10),
            "q50": list(self.q50),
            "q90": list(self.q90),
            "interval_width": list(self.interval_width),
            "direction_confidence": self.direction_confidence,
            "context_length": self.context_length,
            "horizon": self.horizon,
            "config_checksum": self.config_checksum,
            "source_snapshot_id": self.source_snapshot_id,
            "created_at": _iso(self.created_at),
            "context_end_ts": _iso(self.context_end_ts),
            "feature_timestamp": _iso(self.feature_timestamp),
            "future_covariates": [covariate.to_dict() for covariate in self.future_covariates],
        }


@dataclass(frozen=True)
class ForecastArtifactValidation:
    passed: bool
    issues: list[str] = field(default_factory=list)
    metrics: dict[str, object] = field(default_factory=dict)


def build_forecast_artifact(
    result: ForecastResult,
    *,
    feature_timestamp: datetime | str,
    created_at: datetime | str,
    config_checksum: str,
    last_observed_value: float | None = None,
    future_covariates: Sequence[ForecastCovariate] | None = None,
) -> ForecastArtifact:
    feature_ts = _parse_ts(feature_timestamp)
    created_ts = _parse_ts(created_at)
    context_end_ts = _parse_ts(_require_metadata(result, "context_end_ts"))
    source_snapshot_id = str(_require_metadata(result, "source_snapshot_id"))
    horizon = int(_require_metadata(result, "horizon"))
    context_length = int(_require_metadata(result, "context_length"))
    q10 = _quantile(result, "q10")
    q50 = _quantile(result, "q50")
    q90 = _quantile(result, "q90")
    interval_width = [upper - lower for lower, upper in zip(q10, q90)]
    artifact_id = f"{source_snapshot_id}:{result.model_id}:{_iso(feature_ts)}:forecast"
    return ForecastArtifact(
        artifact_id=artifact_id,
        source=result.source,
        model_id=result.model_id,
        point_forecast=list(result.point_forecast),
        q10=q10,
        q50=q50,
        q90=q90,
        interval_width=interval_width,
        direction_confidence=_direction_confidence(q50, last_observed_value),
        context_length=context_length,
        horizon=horizon,
        config_checksum=config_checksum,
        source_snapshot_id=source_snapshot_id,
        created_at=created_ts,
        context_end_ts=context_end_ts,
        feature_timestamp=feature_ts,
        future_covariates=list(future_covariates or []),
    )


def validate_forecast_artifact(artifact: ForecastArtifact) -> ForecastArtifactValidation:
    issues: list[str] = []
    if artifact.horizon <= 0:
        issues.append("horizon_must_be_positive")
    if len(artifact.point_forecast) != artifact.horizon:
        issues.append("point_forecast_horizon_mismatch")
    for name in REQUIRED_QUANTILES:
        values = getattr(artifact, name)
        if not values:
            issues.append(f"missing_quantile:{name}")
        elif len(values) != artifact.horizon:
            issues.append(f"quantile_horizon_mismatch:{name}")
    if len(artifact.interval_width) != artifact.horizon:
        issues.append("interval_width_horizon_mismatch")
    for index, (low, median, high) in enumerate(zip(artifact.q10, artifact.q50, artifact.q90)):
        if not low <= median <= high:
            issues.append(f"quantile_order_invalid:{index}")
    if artifact.context_end_ts > artifact.feature_timestamp:
        issues.append("forecast_context_after_feature_timestamp")
    if not artifact.config_checksum:
        issues.append("missing_config_checksum")
    if not artifact.source_snapshot_id:
        issues.append("missing_source_snapshot_id")
    for covariate in artifact.future_covariates:
        available_at = _parse_ts(covariate.available_at)
        if available_at > artifact.feature_timestamp and not covariate.known_at_decision_time:
            issues.append(f"future_covariate_not_known:{covariate.name}")
    metrics = {
        "horizon": artifact.horizon,
        "context_length": artifact.context_length,
        "future_covariate_count": len(artifact.future_covariates),
        "issue_count": len(issues),
    }
    return ForecastArtifactValidation(passed=not issues, issues=issues, metrics=metrics)


def _require_metadata(result: ForecastResult, key: str) -> object:
    value = result.metadata.get(key)
    if value in {None, ""}:
        raise ValueError(f"missing_forecast_metadata:{key}")
    return value


def _quantile(result: ForecastResult, name: str) -> list[float]:
    return [float(value) for value in result.quantiles.get(name, [])]


def _direction_confidence(q50: Sequence[float], last_observed_value: float | None) -> float:
    if not q50 or last_observed_value is None:
        return 0.0
    denominator = max(abs(float(last_observed_value)), 1.0)
    return min(1.0, abs(float(q50[0]) - float(last_observed_value)) / denominator)


def _parse_ts(value: datetime | str | object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
