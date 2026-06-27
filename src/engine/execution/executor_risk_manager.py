from __future__ import annotations

from dataclasses import asdict, dataclass

from engine.execution.risk_state import RiskState, allowed_actions_for_state


@dataclass(frozen=True)
class ExecutorRiskDecision:
    decision: str
    approved: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ExecutorRiskManager:
    def evaluate(self, *, action: str, state: RiskState, pretrade_rejections: list[str] | None = None) -> ExecutorRiskDecision:
        reasons = list(pretrade_rejections or [])
        if state == RiskState.HALT:
            return ExecutorRiskDecision("halt", False, ["risk_state_halt", *reasons])
        if state == RiskState.LOCKDOWN and action not in allowed_actions_for_state(state):
            return ExecutorRiskDecision("lockdown", False, ["risk_state_lockdown", *reasons])
        if state == RiskState.REDUCE_ONLY and action not in allowed_actions_for_state(state):
            return ExecutorRiskDecision("reduce_only", False, ["risk_state_reduce_only", *reasons])
        if state == RiskState.DEFENSIVE and action not in allowed_actions_for_state(state):
            return ExecutorRiskDecision("rejected", False, ["risk_state_defensive_no_new_exposure", *reasons])
        if reasons:
            return ExecutorRiskDecision("rejected", False, reasons)
        return ExecutorRiskDecision("approved", True, [])
