from __future__ import annotations

from dataclasses import asdict, dataclass

from engine.universe.manifest import SymbolState


@dataclass(frozen=True)
class SymbolDemotionDecision:
    target_state: SymbolState
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["target_state"] = self.target_state.value
        return payload


def evaluate_symbol_demotion(
    *,
    data_gap: bool,
    liquidity_failure: bool,
    reconciliation_issue: bool,
    slippage_shock: bool,
    funding_shock: bool,
    repeated_strategy_failure: bool,
) -> SymbolDemotionDecision:
    reasons = [
        name
        for name, flag in {
            "data_gap": data_gap,
            "liquidity_failure": liquidity_failure,
            "reconciliation_issue": reconciliation_issue,
            "slippage_shock": slippage_shock,
            "funding_shock": funding_shock,
            "repeated_strategy_failure": repeated_strategy_failure,
        }.items()
        if flag
    ]
    target = SymbolState.REDUCE_ONLY if reasons else SymbolState.PAPER_ACTIVE
    return SymbolDemotionDecision(target, reasons)
