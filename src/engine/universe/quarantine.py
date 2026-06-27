from __future__ import annotations

from dataclasses import asdict, dataclass

from engine.universe.manifest import SymbolState


@dataclass(frozen=True)
class SymbolQuarantineDecision:
    target_state: SymbolState
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["target_state"] = self.target_state.value
        return payload


def evaluate_symbol_quarantine(*, data_gap: bool, reconciliation_issue: bool, venue_rule_change: bool) -> SymbolQuarantineDecision:
    reasons = [
        name
        for name, flag in {
            "data_gap": data_gap,
            "reconciliation_issue": reconciliation_issue,
            "venue_rule_change": venue_rule_change,
        }.items()
        if flag
    ]
    target = SymbolState.QUARANTINED if reasons else SymbolState.PAPER_ACTIVE
    return SymbolQuarantineDecision(target, reasons)
