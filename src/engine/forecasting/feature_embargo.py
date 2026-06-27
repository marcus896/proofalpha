from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime


EXECUTION_MODES = {"paper", "paper_observation", "execution"}
KNOWN_LEAKAGE_RISKS = {"low", "medium", "high", "research_only", "future_timestamp", "embargoed"}


@dataclass(frozen=True)
class ForecastEmbargoResult:
    passed: bool
    reasons: list[str]
    leakage_risk: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ForecastFeatureEmbargo:
    source_timestamp: datetime | str
    earliest_available_at: datetime | str
    execution_availability: bool
    embargo_seconds: int
    leakage_risk: str

    def evaluate(self, *, decision_time: datetime | str, mode: str) -> ForecastEmbargoResult:
        reasons: list[str] = []
        source_ts = _parse_ts(self.source_timestamp)
        available_at = _parse_ts(self.earliest_available_at)
        decision_ts = _parse_ts(decision_time)
        if source_ts > decision_ts:
            reasons.append("forecast_timestamp_after_decision_time")
        if decision_ts < available_at:
            reasons.append("forecast_feature_embargo_active")
        if mode in EXECUTION_MODES and not self.execution_availability:
            reasons.append("forecast_not_execution_available")
        if self.embargo_seconds < 0:
            reasons.append("embargo_seconds_negative")
        if self.leakage_risk not in KNOWN_LEAKAGE_RISKS:
            reasons.append(f"unknown_leakage_risk:{self.leakage_risk}")
        return ForecastEmbargoResult(not reasons, reasons, self.leakage_risk)


def _parse_ts(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
