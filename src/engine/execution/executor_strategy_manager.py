from __future__ import annotations

from dataclasses import asdict, dataclass

from engine.execution.execution_tactics import ExecutionTactic
from engine.execution.risk_state import RiskState


@dataclass(frozen=True)
class TacticInput:
    side: str
    action: str
    spread_bps: float
    depth_notional: float
    volatility_bps: float
    order_flow_imbalance: float
    funding_seconds: int
    mark_index_divergence_bps: float
    target_drift_bps: float
    risk_state: RiskState
    fill_probability: float
    adverse_selection_bps: float
    open_order_count: int


@dataclass(frozen=True)
class TacticDecision:
    tactic: ExecutionTactic
    side: str
    reasons: list[str]
    creates_alpha: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["tactic"] = self.tactic.value
        return payload


class ExecutorStrategyManager:
    def choose_tactic(self, inputs: TacticInput) -> TacticDecision:
        if inputs.risk_state == RiskState.HALT:
            return TacticDecision(ExecutionTactic.SKIP, inputs.side, ["risk_state_halt"])
        if inputs.risk_state in {RiskState.REDUCE_ONLY, RiskState.LOCKDOWN}:
            tactic = ExecutionTactic.CLOSE if inputs.action == "close" else ExecutionTactic.REDUCE_ONLY
            return TacticDecision(tactic, inputs.side, [f"risk_state:{inputs.risk_state.value}"])
        if inputs.spread_bps <= 2.0 and inputs.fill_probability >= 0.7 and inputs.adverse_selection_bps <= 2.0:
            return TacticDecision(ExecutionTactic.POST_ONLY_GTX, inputs.side, ["cheap_passive_path"])
        if inputs.target_drift_bps > 100.0 or inputs.fill_probability < 0.3:
            return TacticDecision(ExecutionTactic.IOC, inputs.side, ["urgent_or_low_fill_probability"])
        if inputs.open_order_count > 3:
            return TacticDecision(ExecutionTactic.DELAY, inputs.side, ["open_order_pressure"])
        return TacticDecision(ExecutionTactic.AGGRESSIVE_LIMIT, inputs.side, ["default_executor_tactic"])
