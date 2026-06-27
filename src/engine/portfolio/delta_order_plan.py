from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

from engine.portfolio.symbol_target import SymbolTarget


@dataclass(frozen=True)
class DeltaAction:
    symbol: str
    artifact_id: str | None
    side: str
    current_notional: float
    target_notional: float
    delta_notional: float
    action: str
    reduce_only: bool
    rebalance_reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DeltaOrderPlan:
    delta_order_plan_id: str
    target_portfolio_id: str
    current_positions: dict[str, float]
    target_positions: dict[str, float]
    opens: tuple[DeltaAction, ...]
    increases: tuple[DeltaAction, ...]
    reductions: tuple[DeltaAction, ...]
    closes: tuple[DeltaAction, ...]
    estimated_turnover: float
    estimated_fees: float
    estimated_slippage: float
    estimated_funding: float

    def to_dict(self) -> dict[str, object]:
        return {
            "delta_order_plan_id": self.delta_order_plan_id,
            "target_portfolio_id": self.target_portfolio_id,
            "current_positions": dict(sorted(self.current_positions.items())),
            "target_positions": dict(sorted(self.target_positions.items())),
            "opens": [action.to_dict() for action in self.opens],
            "increases": [action.to_dict() for action in self.increases],
            "reductions": [action.to_dict() for action in self.reductions],
            "closes": [action.to_dict() for action in self.closes],
            "estimated_turnover": self.estimated_turnover,
            "estimated_fees": self.estimated_fees,
            "estimated_slippage": self.estimated_slippage,
            "estimated_funding": self.estimated_funding,
        }

    def to_internal_order_intents(self) -> list[dict[str, object]]:
        intents: list[dict[str, object]] = []
        for action in (*self.opens, *self.increases, *self.reductions, *self.closes):
            intents.append(
                {
                    "symbol": action.symbol,
                    "artifact_id": action.artifact_id,
                    "side": action.side,
                    "qty_notional": abs(action.delta_notional),
                    "reduce_only": action.reduce_only,
                    "source_delta_plan_id": self.delta_order_plan_id,
                    "source_delta_action": action.action,
                }
            )
        return intents


def build_delta_order_plan(
    *,
    plan_id: str,
    current_positions: dict[str, float],
    target_positions: list[SymbolTarget] | tuple[SymbolTarget, ...],
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    funding_cost_bps: float = 0.0,
) -> DeltaOrderPlan:
    current = {str(key): float(value) for key, value in current_positions.items()}
    target_by_symbol = _target_notional_by_symbol(target_positions)
    artifact_by_symbol = {target.symbol: target.artifact_id for target in target_positions}
    reason_by_symbol = {target.symbol: target.rebalance_reason for target in target_positions}
    actions: list[DeltaAction] = []
    for symbol in sorted(set(current) | set(target_by_symbol)):
        current_notional = current.get(symbol, 0.0)
        target_notional = target_by_symbol.get(symbol, 0.0)
        delta = round(target_notional - current_notional, 8)
        if abs(delta) < 1e-9:
            continue
        reduce_only = delta < 0
        if current_notional == 0 and target_notional > 0:
            action_name = "open"
        elif target_notional == 0 and current_notional > 0:
            action_name = "close"
        elif delta > 0:
            action_name = "increase"
        else:
            action_name = "reduction"
        actions.append(
            DeltaAction(
                symbol=symbol,
                artifact_id=artifact_by_symbol.get(symbol),
                side="BUY" if delta > 0 else "SELL",
                current_notional=round(current_notional, 8),
                target_notional=round(target_notional, 8),
                delta_notional=delta,
                action=action_name,
                reduce_only=reduce_only,
                rebalance_reason=reason_by_symbol.get(symbol, "target_delta"),
            )
        )
    opens = tuple(action for action in actions if action.action == "open")
    increases = tuple(action for action in actions if action.action == "increase")
    reductions = tuple(action for action in actions if action.action == "reduction")
    closes = tuple(action for action in actions if action.action == "close")
    turnover = round(sum(abs(action.delta_notional) for action in actions), 8)
    payload = {
        "target_portfolio_id": plan_id,
        "current_positions": dict(sorted(current.items())),
        "target_positions": dict(sorted(target_by_symbol.items())),
        "actions": [action.to_dict() for action in actions],
    }
    return DeltaOrderPlan(
        delta_order_plan_id="delta-order-plan-" + _stable_hash(payload)[:16],
        target_portfolio_id=plan_id,
        current_positions=dict(sorted(current.items())),
        target_positions=dict(sorted(target_by_symbol.items())),
        opens=opens,
        increases=increases,
        reductions=reductions,
        closes=closes,
        estimated_turnover=turnover,
        estimated_fees=round(turnover * float(fee_bps) / 10_000.0, 8),
        estimated_slippage=round(turnover * float(slippage_bps) / 10_000.0, 8),
        estimated_funding=round(turnover * float(funding_cost_bps) / 10_000.0, 8),
    )


def _target_notional_by_symbol(targets: list[SymbolTarget] | tuple[SymbolTarget, ...]) -> dict[str, float]:
    result: dict[str, float] = {}
    for target in targets:
        result[target.symbol] = round(result.get(target.symbol, 0.0) + float(target.target_notional), 8)
    return result


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
