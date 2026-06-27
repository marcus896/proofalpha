from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import math
from typing import Literal


StaleAction = Literal["ignore", "warn", "disable_feature"]
ModeScope = Literal["research", "validation", "shadow", "paper_observation"]
VALID_STALE_ACTIONS = {"ignore", "warn", "disable_feature"}
VALID_MODE_SCOPES = {"research", "validation", "shadow", "paper_observation"}


@dataclass(frozen=True)
class ForecastTTLResult:
    passed: bool
    status: str
    action: str
    age_seconds: float
    issues: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ForecastJoinResult:
    joined: bool
    status: str
    row: dict[str, object]
    issues: list[str]


@dataclass(frozen=True)
class ForecastTTLPolicy:
    horizon: int
    max_age_seconds: int
    stale_action: StaleAction
    mode_scope: ModeScope

    def evaluate(self, *, forecast_timestamp: datetime | str, decision_time: datetime | str, mode: str) -> ForecastTTLResult:
        issues: list[str] = []
        if self.horizon <= 0:
            issues.append("horizon_must_be_positive")
        if not math.isfinite(float(self.max_age_seconds)):
            issues.append("max_age_seconds_non_finite")
        elif self.max_age_seconds < 0:
            issues.append("max_age_seconds_negative")
        if self.stale_action not in VALID_STALE_ACTIONS:
            issues.append(f"invalid_stale_action:{self.stale_action}")
        if self.mode_scope not in VALID_MODE_SCOPES:
            issues.append(f"invalid_mode_scope:{self.mode_scope}")
        if mode != self.mode_scope:
            issues.append(f"mode_scope_mismatch:{mode}")
        forecast_ts = _parse_ts(forecast_timestamp)
        decision_ts = _parse_ts(decision_time)
        age_seconds = (decision_ts - forecast_ts).total_seconds()
        if age_seconds < 0:
            issues.append("forecast_timestamp_after_decision_time")
        if issues and self.stale_action not in {"ignore", "warn"}:
            return ForecastTTLResult(False, "INVALID_POLICY", "disable_feature", age_seconds, issues)
        stale = math.isfinite(float(self.max_age_seconds)) and age_seconds > float(self.max_age_seconds)
        if stale and self.stale_action == "disable_feature":
            return ForecastTTLResult(False, "STALE", "disable_feature", age_seconds, issues + ["forecast_stale"])
        if stale and self.stale_action == "warn":
            return ForecastTTLResult(not issues, "WARN_STALE", "warn", age_seconds, issues + ["forecast_stale"])
        if stale:
            return ForecastTTLResult(not issues, "STALE_IGNORED", "ignore", age_seconds, issues + ["forecast_stale"])
        return ForecastTTLResult(not issues, "FRESH", "allow", age_seconds, issues)


def join_forecast_feature_if_fresh(
    row: dict[str, object],
    feature_name: str,
    value: object,
    *,
    forecast_timestamp: datetime | str,
    decision_time: datetime | str,
    policy: ForecastTTLPolicy,
    mode: str,
) -> ForecastJoinResult:
    ttl = policy.evaluate(forecast_timestamp=forecast_timestamp, decision_time=decision_time, mode=mode)
    if not ttl.passed and ttl.action == "disable_feature":
        return ForecastJoinResult(False, ttl.status, dict(row), ttl.issues)
    joined = dict(row)
    joined[feature_name] = value
    return ForecastJoinResult(True, ttl.status, joined, ttl.issues)


def _parse_ts(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
