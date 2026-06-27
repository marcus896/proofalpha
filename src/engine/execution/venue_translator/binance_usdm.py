from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
import math

from engine.data.exchange_rules_cache import ExchangeRulesCache, ExchangeSymbolRules
from engine.execution.order_intent import InternalOrderIntent, validate_internal_order_intent
from engine.execution.venue_order_request import build_venue_order_request
from engine.execution.venue_translator.reports import TranslationReport


class BinanceUsdMTranslator:
    def __init__(
        self,
        rules_cache: ExchangeRulesCache,
        *,
        position_mode: str = "one_way",
        margin_mode: str = "cross",
        leverage: int = 10,
    ) -> None:
        self.rules_cache = rules_cache
        self.position_mode = position_mode
        self.margin_mode = margin_mode
        self.leverage = int(leverage)

    def translate(
        self,
        intent: InternalOrderIntent,
        *,
        quantity: float,
        price: float,
        timestamp: int,
        passive: bool = False,
        close_position: bool = False,
        current_position_notional: float | None = None,
    ) -> TranslationReport:
        reasons: list[str] = []
        warnings: list[str] = []
        validation = validate_internal_order_intent(intent)
        reasons.extend(validation.issues)
        quantity_valid = _is_positive_finite(quantity)
        price_valid = _is_positive_finite(price)
        if not _is_finite_number(quantity):
            reasons.append("non_finite_quantity")
        elif quantity <= 0:
            reasons.append("quantity_not_positive")
        if not _is_finite_number(price):
            reasons.append("non_finite_price")
        elif price <= 0:
            reasons.append("price_not_positive")
        try:
            rules = self.rules_cache.get(intent.symbol)
        except KeyError:
            rules = None
            reasons.append("missing_exchange_rules")

        rounded_price = price if price_valid else 0.0
        rounded_quantity = quantity if quantity_valid else 0.0
        if rules is not None:
            reasons.extend(self._rule_rejections(intent, rules))
            if price_valid:
                rounded_price = _round_down_to_increment(price, rules.tick_size or 0.0)
            if quantity_valid:
                rounded_quantity = _round_down_to_increment(quantity, rules.step_size or 0.0)
            min_notional = float(rules.min_notional or 0.0)
            if rounded_quantity * rounded_price < min_notional:
                reasons.append("min_notional_violation")
            max_leverage = _max_leverage(rules)
            if max_leverage is not None and self.leverage > max_leverage:
                reasons.append("leverage_exceeds_symbol_bracket")

        if self.margin_mode not in {"cross", "isolated"}:
            reasons.append("invalid_margin_mode")
        if self.position_mode not in {"one_way", "hedge"}:
            reasons.append("invalid_position_mode")
        if intent.reduce_only_required:
            notional = rounded_quantity * rounded_price
            if current_position_notional is None or current_position_notional <= 0:
                reasons.append("reduce_only_without_position")
            elif notional > current_position_notional + 1e-9:
                reasons.append("reduce_only_exceeds_position")
        if close_position and (not intent.reduce_only_required or intent.intent_type != "close"):
            reasons.append("close_position_requires_close_reduce_only_intent")

        tif = _time_in_force(intent, passive=passive)
        if tif == "GTX" and rules is not None and "LIMIT" not in rules.order_types:
            reasons.append("limit_order_type_not_allowed")
        order_type = "LIMIT"
        position_side = _position_side(intent, self.position_mode)
        request = build_venue_order_request(
            intent,
            venue="binance_usdm",
            quantity=max(rounded_quantity, 0.0),
            order_type=order_type,
            time_in_force=tif,
            price=rounded_price,
            timestamp=timestamp,
            position_side=position_side,
        )
        order = request.to_dict()
        if close_position:
            order["closePosition"] = True
            order["reduceOnly"] = True
        if passive:
            warnings.append("post_only_mapped_to_gtx")
        return TranslationReport(
            passed=not reasons,
            raw_intent=intent.to_dict(),
            rounded_order=order,
            rule_snapshot_hash=self.rules_cache.snapshot_hash,
            rejection_reasons=sorted(set(reasons)),
            warnings=warnings,
        )

    def _rule_rejections(self, intent: InternalOrderIntent, rules: ExchangeSymbolRules) -> list[str]:
        reasons: list[str] = []
        if rules.status not in (None, "TRADING"):
            reasons.append("symbol_not_trading")
        if rules.contract_type not in (None, "PERPETUAL"):
            reasons.append("contract_type_not_perpetual")
        if rules.quote_asset not in (None, "USDT"):
            reasons.append("quote_asset_not_usdt")
        if "LIMIT" not in rules.order_types:
            reasons.append("limit_order_type_not_allowed")
        if rules.tick_size is None or rules.tick_size <= 0:
            reasons.append("missing_tick_size")
        if rules.step_size is None or rules.step_size <= 0:
            reasons.append("missing_step_size")
        if rules.min_notional is None or rules.min_notional <= 0:
            reasons.append("missing_min_notional")
        return reasons


def _time_in_force(intent: InternalOrderIntent, *, passive: bool) -> str:
    if passive:
        return "GTX"
    if intent.urgency == "urgent":
        return "IOC"
    return "GTC"


def _position_side(intent: InternalOrderIntent, position_mode: str) -> str:
    if position_mode == "one_way":
        return "BOTH"
    if intent.side == "BUY":
        return "LONG"
    return "SHORT"


def _round_down_to_increment(value: float, increment: float) -> float:
    if increment <= 0:
        return float(value)
    decimal_value = Decimal(str(value))
    decimal_increment = Decimal(str(increment))
    rounded = (decimal_value / decimal_increment).to_integral_value(rounding=ROUND_DOWN) * decimal_increment
    return float(rounded)


def _is_finite_number(value: float) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _is_positive_finite(value: float) -> bool:
    return _is_finite_number(value) and float(value) > 0.0


def _max_leverage(rules: ExchangeSymbolRules) -> int | None:
    values: list[int] = []
    for bracket in rules.leverage_brackets:
        raw = bracket.get("initialLeverage")
        if isinstance(raw, int):
            values.append(raw)
        elif isinstance(raw, str) and raw.isdigit():
            values.append(int(raw))
    return max(values) if values else None
