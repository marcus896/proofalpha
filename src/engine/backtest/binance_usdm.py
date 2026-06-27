from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from math import floor, sqrt
from typing import Literal

from engine.config.models import DataSnapshot


BINANCE_USDM_V3_EXECUTION_MODEL_ID = "binance_usdm_v3"


OrderSide = Literal["BUY", "SELL"]
OrderIntent = Literal["increase", "reduce"]
LiquidityPath = Literal["maker", "taker"]
TimeInForce = Literal["GTC", "IOC", "FOK", "GTX"]


@dataclass(frozen=True)
class BinanceUsdMRuleSet:
    tick_size: float
    step_size: float
    min_notional: float
    maker_fee_bps: float
    taker_fee_bps: float
    max_participation_rate: float = 0.05
    liquidation_fee_bps: float = 0.0


@dataclass(frozen=True)
class MaintenanceMarginTier:
    notional_floor: float
    notional_cap: float | None
    maintenance_margin_ratio: float


@dataclass(frozen=True)
class BinanceUsdMOrderRequest:
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    intent: OrderIntent = "increase"
    liquidity_path: LiquidityPath = "taker"
    time_in_force: TimeInForce = "GTC"
    reduce_only: bool = False
    post_only: bool = False
    current_position_qty: float = 0.0
    book_best_bid: float | None = None
    book_best_ask: float | None = None
    submitted_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class DynamicCostContext:
    symbol: str
    liquidity_path: LiquidityPath
    hour_of_day: int
    volatility_percentile: float
    spread_percentile: float
    order_size_pct_local_liquidity: float
    oi_percentile: float
    liquidation_intensity_percentile: float


@dataclass(frozen=True)
class BinanceUsdMExecutionReport:
    execution_model_id: str
    accepted: bool
    status: str
    reason_codes: list[str] = field(default_factory=list)
    rounded_price: float | None = None
    rounded_quantity: float | None = None
    notional: float = 0.0
    maker_taker: LiquidityPath = "taker"
    fill_ratio: float = 0.0
    fee_bps: float = 0.0
    spread_bps: float = 0.0
    impact_bps: float = 0.0
    total_cost_bps: float = 0.0
    capacity_ok: bool = True
    queue_position_estimate: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def rules_from_snapshot(snapshot: DataSnapshot) -> BinanceUsdMRuleSet:
    return BinanceUsdMRuleSet(
        tick_size=_venue_note_float(snapshot, "tick_size", 0.01),
        step_size=_venue_note_float(snapshot, "step_size", 0.001),
        min_notional=_venue_note_float(snapshot, "min_notional", 5.0),
        maker_fee_bps=float(snapshot.maker_fee_bps),
        taker_fee_bps=float(snapshot.taker_fee_bps),
        max_participation_rate=_venue_note_float(snapshot, "max_participation_rate", 0.05),
        liquidation_fee_bps=_venue_note_float(snapshot, "liquidation_fee_bps", 0.0),
    )


def validate_binance_usdm_order(
    order: BinanceUsdMOrderRequest,
    rules: BinanceUsdMRuleSet,
) -> list[str]:
    reasons: list[str] = []
    if order.quantity <= 0.0:
        reasons.append("quantity_must_be_positive")
    if order.price <= 0.0:
        reasons.append("price_must_be_positive")
    if _round_down(order.quantity, rules.step_size) <= 0.0:
        reasons.append("quantity_below_step_size")
    if order.price != _round_to_tick(order.price, rules.tick_size):
        reasons.append("price_precision_violation")
    rounded_qty = _round_down(order.quantity, rules.step_size)
    if rounded_qty * order.price < rules.min_notional:
        reasons.append("min_notional_violation")
    if order.post_only and order.liquidity_path != "maker":
        reasons.append("post_only_requires_maker_path")
    if order.post_only and _would_cross_book(order):
        reasons.append("post_only_would_take_liquidity")
    if order.time_in_force == "GTX" and not order.post_only:
        reasons.append("gtx_requires_post_only")
    if order.reduce_only and order.intent != "reduce":
        reasons.append("reduce_only_requires_reduce_intent")
    if order.reduce_only and abs(order.current_position_qty) <= 0.0:
        reasons.append("reduce_only_without_position")
    if order.reduce_only and rounded_qty > abs(order.current_position_qty) + 1e-12:
        reasons.append("reduce_only_quantity_exceeds_position")
    if order.expires_at is not None and order.submitted_at is not None and order.expires_at <= order.submitted_at:
        reasons.append("order_expired")
    return reasons


def simulate_binance_usdm_order(
    order: BinanceUsdMOrderRequest,
    *,
    rules: BinanceUsdMRuleSet,
    cost_context: DynamicCostContext,
    local_depth_notional: float,
) -> BinanceUsdMExecutionReport:
    reason_codes = validate_binance_usdm_order(order, rules)
    rounded_price = _round_to_tick(order.price, rules.tick_size)
    rounded_quantity = _round_down(order.quantity, rules.step_size)
    notional = rounded_price * rounded_quantity
    participation = notional / max(float(local_depth_notional), 1e-9)
    capacity_ok = participation <= rules.max_participation_rate
    if not capacity_ok:
        reason_codes.append("capacity_limit_exceeded")

    if reason_codes:
        return BinanceUsdMExecutionReport(
            execution_model_id=BINANCE_USDM_V3_EXECUTION_MODEL_ID,
            accepted=False,
            status="rejected",
            reason_codes=sorted(set(reason_codes)),
            rounded_price=rounded_price,
            rounded_quantity=rounded_quantity,
            notional=notional,
            maker_taker=order.liquidity_path,
            capacity_ok=capacity_ok,
        )

    fee_bps = rules.maker_fee_bps if order.liquidity_path == "maker" else rules.taker_fee_bps
    spread_bps = 0.0 if order.liquidity_path == "maker" else _spread_bps(order)
    impact_bps = dynamic_cost_bps(cost_context)
    fill_ratio = _fill_ratio_from_depth(notional, local_depth_notional, order.liquidity_path)
    queue_position = local_depth_notional if order.liquidity_path == "maker" else None
    return BinanceUsdMExecutionReport(
        execution_model_id=BINANCE_USDM_V3_EXECUTION_MODEL_ID,
        accepted=True,
        status="filled" if fill_ratio >= 1.0 else "partial_fill",
        rounded_price=rounded_price,
        rounded_quantity=rounded_quantity,
        notional=notional,
        maker_taker=order.liquidity_path,
        fill_ratio=fill_ratio,
        fee_bps=fee_bps,
        spread_bps=spread_bps,
        impact_bps=impact_bps,
        total_cost_bps=fee_bps + spread_bps + impact_bps,
        capacity_ok=capacity_ok,
        queue_position_estimate=queue_position,
    )


def dynamic_cost_bps(context: DynamicCostContext) -> float:
    """V3 policy cost keyed by symbol, maker/taker path, hour, vol/spread, liquidity, OI, liquidation."""
    maker_discount = 0.35 if context.liquidity_path == "maker" else 1.0
    urgency = 1.0 + _clamp01(context.volatility_percentile) + (0.5 * _clamp01(context.spread_percentile))
    liquidity_term = sqrt(max(0.0, context.order_size_pct_local_liquidity))
    oi_term = 1.0 + (0.25 * _clamp01(context.oi_percentile))
    liquidation_term = 1.0 + (0.75 * _clamp01(context.liquidation_intensity_percentile))
    hour_term = 1.15 if context.hour_of_day in {0, 8, 16} else 1.0
    base_bps = 2.0 + (20.0 * liquidity_term * urgency * oi_term * liquidation_term)
    return min(500.0, max(0.0, base_bps * hour_term * maker_discount))


def funding_cashflow(position_notional: float, funding_rate: float, *, position_side: str) -> float:
    side = str(position_side).lower()
    if side not in {"long", "short"}:
        raise ValueError("position_side must be long or short")
    direction = -1.0 if side == "short" else 1.0
    return abs(float(position_notional)) * float(funding_rate) * direction


def approximate_mark_price_liquidation_price(
    entry_price: float,
    *,
    side: str,
    leverage: float,
    maintenance_margin_ratio: float,
) -> float:
    if leverage <= 0.0:
        raise ValueError("leverage must be positive")
    if not 0.0 <= maintenance_margin_ratio < 1.0:
        raise ValueError("maintenance_margin_ratio must be in [0, 1)")
    if side == "short":
        return entry_price * (1.0 + (1.0 / leverage) - maintenance_margin_ratio)
    if side == "long":
        return entry_price * (1.0 - (1.0 / leverage) + maintenance_margin_ratio)
    raise ValueError("side must be long or short")


def select_maintenance_margin_tier(
    position_notional: float,
    tiers: list[MaintenanceMarginTier],
) -> MaintenanceMarginTier:
    if not tiers:
        raise ValueError("tiers must not be empty")
    notional = abs(float(position_notional))
    ordered = sorted(tiers, key=lambda tier: tier.notional_floor)
    for tier in ordered:
        cap = float("inf") if tier.notional_cap is None else float(tier.notional_cap)
        if float(tier.notional_floor) <= notional < cap:
            return tier
    return ordered[-1]


def liquidation_price_with_maintenance_tiers(
    entry_price: float,
    *,
    side: str,
    leverage: float,
    quantity: float,
    tiers: list[MaintenanceMarginTier],
) -> float:
    notional = abs(float(entry_price) * float(quantity))
    tier = select_maintenance_margin_tier(notional, tiers)
    return approximate_mark_price_liquidation_price(
        entry_price,
        side=side,
        leverage=leverage,
        maintenance_margin_ratio=tier.maintenance_margin_ratio,
    )


def _round_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0.0:
        raise ValueError("tick_size must be positive")
    return round(round(float(price) / float(tick_size)) * float(tick_size), 12)


def _round_down(quantity: float, step_size: float) -> float:
    if step_size <= 0.0:
        raise ValueError("step_size must be positive")
    return floor(float(quantity) / float(step_size)) * float(step_size)


def _would_cross_book(order: BinanceUsdMOrderRequest) -> bool:
    if order.side == "BUY" and order.book_best_ask is not None:
        return order.price >= order.book_best_ask
    if order.side == "SELL" and order.book_best_bid is not None:
        return order.price <= order.book_best_bid
    return False


def _spread_bps(order: BinanceUsdMOrderRequest) -> float:
    if order.book_best_bid is None or order.book_best_ask is None:
        return 0.0
    mid = (order.book_best_bid + order.book_best_ask) / 2.0
    if mid <= 0.0:
        return 0.0
    return ((order.book_best_ask - order.book_best_bid) / mid) * 10_000.0


def _fill_ratio_from_depth(notional: float, local_depth_notional: float, path: LiquidityPath) -> float:
    if notional <= 0.0:
        return 0.0
    if local_depth_notional <= 0.0:
        return 0.0
    multiplier = 0.5 if path == "maker" else 1.0
    return max(0.0, min(1.0, (local_depth_notional * multiplier) / notional))


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _venue_note_float(snapshot: DataSnapshot, key: str, fallback: float) -> float:
    if snapshot.venue_profile is None:
        return fallback
    for note in snapshot.venue_profile.notes:
        if isinstance(note, str) and note.startswith(f"{key}="):
            try:
                return float(note.split("=", 1)[1])
            except ValueError:
                return fallback
    return fallback
