from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RebalancePolicy:
    interval_seconds: int
    drift_bps: float = 0.0
    risk_breach: bool = False
    lifecycle_event: str | None = None


@dataclass(frozen=True)
class RebalanceDecision:
    should_rebalance: bool
    triggers: tuple[str, ...]


def evaluate_rebalance_policy(
    policy: RebalancePolicy,
    *,
    last_rebalance_utc: str,
    now_utc: str,
    drift_threshold_bps: float = 25.0,
) -> RebalanceDecision:
    triggers: list[str] = []
    last = _parse_utc(last_rebalance_utc)
    now = _parse_utc(now_utc)
    if (now - last).total_seconds() >= policy.interval_seconds:
        triggers.append("scheduled")
    if abs(policy.drift_bps) >= drift_threshold_bps:
        triggers.append("drift")
    if policy.risk_breach:
        triggers.append("risk")
    if policy.lifecycle_event:
        triggers.append(f"lifecycle:{policy.lifecycle_event}")
    return RebalanceDecision(bool(triggers), tuple(triggers))


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
