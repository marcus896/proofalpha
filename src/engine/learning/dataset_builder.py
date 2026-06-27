from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LearningDataset:
    status: str
    rows: list[dict[str, object]]
    direct_trading_change_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_learning_dataset(
    *,
    orders: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
    paper_session_telemetry: list[dict[str, Any]],
    websocket_quality: dict[str, Any],
    book_depth: list[dict[str, Any]],
    spread_history: list[float],
    funding_history: list[float],
    portfolio_exposures: dict[str, float],
    artifact_performance: dict[str, dict[str, Any]],
    validation_history: list[dict[str, Any]],
) -> LearningDataset:
    fills_by_order = {str(row.get("order_id")): row for row in fills}
    depth_by_symbol = {str(row.get("symbol")): row for row in book_depth}
    rows: list[dict[str, object]] = []
    for order in orders:
        order_id = str(order.get("order_id", ""))
        symbol = str(order.get("symbol", ""))
        telemetry = _first_by_order(paper_session_telemetry, order_id)
        fill = fills_by_order.get(order_id, {})
        depth = depth_by_symbol.get(symbol, {})
        rows.append(
            {
                "order_id": order_id,
                "symbol": symbol,
                "side": str(order.get("side", "")),
                "fill_price": float(fill.get("fill_price", 0.0) or 0.0),
                "qty": float(fill.get("qty", 0.0) or 0.0),
                "spread_bps": float(telemetry.get("spread_bps", 0.0) or 0.0),
                "slip_bps": float(telemetry.get("slip_bps", 0.0) or 0.0),
                "websocket_quality_score": float(websocket_quality.get("score", 0.0) or 0.0),
                "depth_notional": float(depth.get("depth_notional", 0.0) or 0.0),
                "avg_spread_bps": _mean(spread_history),
                "avg_funding": _mean(funding_history),
                "portfolio_exposure": float(portfolio_exposures.get(symbol, 0.0)),
                "artifact_performance": artifact_performance,
                "validation_history_count": len(validation_history),
                "reject_count": len(rejects),
            }
        )
    return LearningDataset(status="ready" if rows else "empty", rows=rows)


def _first_by_order(rows: list[dict[str, Any]], order_id: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get("order_id")) == order_id:
            return row
    return {}


def _mean(values: list[float]) -> float:
    return round(sum(float(value) for value in values) / len(values), 12) if values else 0.0
