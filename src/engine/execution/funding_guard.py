from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class FundingGuardConfig:
    max_cost_bps: float
    block_open_seconds_before_funding: int


@dataclass(frozen=True)
class FundingGuardResult:
    passed: bool
    rejections: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class FundingGuard:
    def __init__(self, config: FundingGuardConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        action: str,
        now_utc: str,
        next_funding_time_utc: str,
        expected_funding_cost_bps: float,
    ) -> FundingGuardResult:
        rejections: list[str] = []
        seconds_to_funding = (_parse_utc(next_funding_time_utc) - _parse_utc(now_utc)).total_seconds()
        if action in {"open", "increase"} and 0 <= seconds_to_funding <= self.config.block_open_seconds_before_funding:
            rejections.append("near_funding_open_block")
        if expected_funding_cost_bps > self.config.max_cost_bps:
            rejections.append("funding_cost_budget_exceeded")
        return FundingGuardResult(not rejections, rejections)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
