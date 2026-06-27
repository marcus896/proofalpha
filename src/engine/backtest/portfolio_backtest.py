from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioBacktest:
    target_portfolio_id: str
    execution_adjusted_pnl: float
    reports: list[dict[str, object]]
