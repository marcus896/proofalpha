from __future__ import annotations

from enum import StrEnum


class PortfolioState(StrEnum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    DEFENSIVE = "DEFENSIVE"
    REDUCE_ONLY = "REDUCE_ONLY"
    LOCKDOWN = "LOCKDOWN"
    HALT = "HALT"


ALLOWED_ACTIONS = {
    PortfolioState.NORMAL: {"open", "increase", "reduce", "close"},
    PortfolioState.CAUTION: {"open", "increase", "reduce", "close"},
    PortfolioState.DEFENSIVE: {"reduce", "close"},
    PortfolioState.REDUCE_ONLY: {"reduce", "close"},
    PortfolioState.LOCKDOWN: {"close"},
    PortfolioState.HALT: set(),
}


def allowed_portfolio_action(state: PortfolioState, action: str) -> bool:
    return action in ALLOWED_ACTIONS[state]
