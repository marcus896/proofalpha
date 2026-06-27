from __future__ import annotations


def bps_to_decimal(basis_points: float) -> float:
    return basis_points / 10_000.0


def apply_trade_cost(notional: float, fee_bps: float, slippage_bps: float) -> float:
    total_bps = fee_bps + slippage_bps
    return abs(notional) * bps_to_decimal(total_bps)


def apply_funding(notional: float, funding_rate: float, position_side: str = "long") -> float:
    direction = -1.0 if position_side == "short" else 1.0
    return abs(notional) * funding_rate * direction
