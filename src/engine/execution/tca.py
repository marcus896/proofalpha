from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TcaReport:
    order_id: str
    symbol: str
    metrics: dict[str, float]
    learning_row: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_tca_report(
    *,
    order_id: str,
    symbol: str,
    side: str,
    decision_price: float,
    arrival_price: float,
    limit_price: float | None,
    fill_price: float,
    expected_slippage_bps: float,
    maker_taker_fee_bps: float,
    markout_prices: dict[str, float],
    adverse_selection_bps: float,
    missed_fill_cost: float,
) -> TcaReport:
    metrics = {
        "arrival_slippage_bps": _side_bps(side, decision_price, arrival_price),
        "realized_slippage_bps": _side_bps(side, decision_price, fill_price),
        "realized_vs_expected_slippage_bps": _side_bps(side, decision_price, fill_price) - expected_slippage_bps,
        "maker_taker_fee_bps": float(maker_taker_fee_bps),
        "adverse_selection_bps": float(adverse_selection_bps),
        "missed_fill_cost": float(missed_fill_cost),
    }
    if limit_price is not None:
        metrics["limit_slippage_bps"] = _side_bps(side, decision_price, limit_price)
    for horizon, price in sorted(markout_prices.items()):
        metrics[f"markout_{horizon}_bps"] = _side_bps(side, fill_price, price)
    learning_row: dict[str, object] = {
        "order_id": order_id,
        "symbol": symbol,
        "side": side.upper(),
        **metrics,
    }
    return TcaReport(order_id=order_id, symbol=symbol, metrics=metrics, learning_row=learning_row)


def _side_bps(side: str, base_price: float, observed_price: float) -> float:
    multiplier = 1.0 if side.upper() == "BUY" else -1.0
    return round(multiplier * (float(observed_price) - float(base_price)) / max(float(base_price), 1e-9) * 10_000.0, 12)
