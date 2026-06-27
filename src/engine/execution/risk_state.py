from __future__ import annotations

from enum import StrEnum


class RiskState(StrEnum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    DEFENSIVE = "DEFENSIVE"
    REDUCE_ONLY = "REDUCE_ONLY"
    LOCKDOWN = "LOCKDOWN"
    HALT = "HALT"


def allowed_actions_for_state(state: RiskState) -> set[str]:
    if state == RiskState.NORMAL:
        return {"open", "increase", "reduce", "close"}
    if state == RiskState.CAUTION:
        return {"open", "increase", "reduce", "close"}
    if state == RiskState.DEFENSIVE:
        return {"reduce", "close"}
    if state == RiskState.REDUCE_ONLY:
        return {"reduce", "close"}
    if state == RiskState.LOCKDOWN:
        return {"cancel", "reconcile", "close"}
    return set()
