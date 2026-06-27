from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class CancelReplaceBudget:
    max_amends: int
    max_cancel_replace: int
    maker_timeout_seconds: int


@dataclass(frozen=True)
class CancelReplaceDecision:
    allowed: bool
    action: str
    reasons: list[str]


class CancelReplaceManager:
    def __init__(self, budget: CancelReplaceBudget) -> None:
        self.budget = budget
        self._amends_by_order: dict[str, int] = {}
        self._cancel_replace_count = 0

    def evaluate(
        self,
        *,
        order_id: str,
        created_at_utc: str,
        now_utc: str,
        amend_count: int,
    ) -> CancelReplaceDecision:
        reasons: list[str] = []
        age_seconds = (_parse_utc(now_utc) - _parse_utc(created_at_utc)).total_seconds()
        effective_amends = max(int(amend_count), self._amends_by_order.get(order_id, 0))
        if age_seconds < self.budget.maker_timeout_seconds:
            reasons.append("maker_timeout_not_reached")
        if effective_amends >= self.budget.max_amends:
            reasons.append("max_amends_reached")
        if self._cancel_replace_count >= self.budget.max_cancel_replace:
            reasons.append("cancel_replace_budget_exhausted")
        return CancelReplaceDecision(
            allowed=not reasons,
            action="cancel_replace" if not reasons else "hold",
            reasons=reasons,
        )

    def record_amend(self, order_id: str) -> None:
        self._amends_by_order[order_id] = self._amends_by_order.get(order_id, 0) + 1
        self._cancel_replace_count += 1


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
