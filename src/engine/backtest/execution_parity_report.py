from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ExecutionParityReport:
    signal_pnl: float
    execution_adjusted_pnl: float
    fees: float
    funding: float
    slippage: float
    missed_fills: int
    adverse_selection: float
    cancel_replace_count: int
    order_reject_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_learning_row(self) -> dict[str, object]:
        payload = self.to_dict()
        payload["execution_drag"] = self.signal_pnl - self.execution_adjusted_pnl
        return payload
