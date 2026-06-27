"""Numba-accelerated batch simulator for Phase 11.

Public surface
--------------
simulate_strategy_batch(snapshot, signal_matrix, params_batch, ...)
    Evaluate N parameter sets (all sharing the same signal_matrix) in one
    JIT-compiled pass.  Returns a list of BacktestResult objects in the same
    order as params_batch.

is_numba_available() -> bool
    Runtime check used by runtime.py to decide whether to use this module.

Implementation notes
--------------------
* The inner loop is kept in a separate @njit function (_simulate_single_numba)
  so that the JIT compilation happens once and is reused across all N sets.
* A pure-Python reference (_simulate_single_python) with identical semantics
  is kept beside it; CI uses both paths on the same inputs and asserts
  identical results within float tolerance.
* If numba or numpy are absent the module gracefully degrades: callers receive
  results from the pure-Python path so nothing breaks.
"""

from __future__ import annotations

import logging
import math
import time

from engine.backtest.market_impact import compute_dynamic_slippage, impact_cost_bps
from engine.backtest.simulator import (
    _apply_adverse_fill_price,
    _cascade_multiplier,
    _compute_abs_zscores,
    _compute_low_percentile_flags,
    _liquidation_ratio_for_event,
    _resolve_execution_adverse_fill_bps,
    _resolve_liquidation_step_behavior,
    _resolve_maintenance_margin_ratio,
    _resolve_tier_value,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

def is_numba_available() -> bool:
    """Return True if both numpy and numba are importable."""
    try:
        import numpy  # noqa: F401
        import numba  # noqa: F401
        return True
    except ModuleNotFoundError:
        return False


_STRESS_REGIME_MULTIPLIERS: dict[str, float] = {
    "crash": 1.50,
    "short_squeeze": 1.35,
    "liquidity_stress": 1.25,
}


class _BatchImpactCoeff:
    eta = 0.10
    alpha = 0.50
    k_latency = 0.01


_REALISTIC_BATCH_SLIPPAGE_COEFF = _BatchImpactCoeff()


def _normalize_float_series(values: list[float] | None, length: int, default: float = 0.0) -> list[float]:
    normalized = [float(value) for value in (values or [])[:length]]
    while len(normalized) < length:
        normalized.append(normalized[-1] if normalized else float(default))
    return normalized


def _normalize_stress_regimes(values: list[str] | None, length: int) -> list[str]:
    normalized = [str(value) for value in (values or [])[:length]]
    while len(normalized) < length:
        normalized.append(normalized[-1] if normalized else "")
    return normalized


def _compute_roll_vol_series(closes: list[float], window: int = 30) -> list[float]:
    result: list[float] = []
    for index in range(len(closes)):
        start = max(0, index - window)
        win = closes[start : index + 1]
        if len(win) < 2:
            result.append(0.01)
            continue
        bar_rets = [(win[j] - win[j - 1]) / max(win[j - 1], 1e-12) for j in range(1, len(win))]
        mean_r = sum(bar_rets) / len(bar_rets)
        var_r = sum((value - mean_r) ** 2 for value in bar_rets) / max(len(bar_rets) - 1, 1)
        result.append(math.sqrt(max(var_r, 0.0)))
    return result


def _percentile_threshold(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(float(value) for value in values)
    n = len(sorted_values)
    rank = (percentile / 100.0) * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    frac = rank - lower
    return sorted_values[lower] * (1.0 - frac) + sorted_values[upper] * frac


def _prepare_slippage_context(
    *,
    closes: list[float],
    funding_rates: list[float],
    open_interest: list[float] | None,
    liquidation_notional: list[float] | None,
    spread_bps: list[float] | None,
    depth_bid_1bp_usd: list[float] | None,
    depth_ask_1bp_usd: list[float] | None,
    latency_proxy_ms: list[float] | None,
    stress_regimes: list[str] | None,
) -> dict[str, list[float] | list[bool] | bool]:
    length = len(closes)
    open_interest_series = _normalize_float_series(open_interest, length, 0.0)
    funding_series = _normalize_float_series(funding_rates, length, 0.0)
    liquidation_series = _normalize_float_series(liquidation_notional, length, 0.0)
    spread_series = _normalize_float_series(spread_bps, length, 0.0)
    depth_bid_series = _normalize_float_series(depth_bid_1bp_usd, length, 0.0)
    depth_ask_series = _normalize_float_series(depth_ask_1bp_usd, length, 0.0)
    latency_series = _normalize_float_series(latency_proxy_ms, length, 0.0)
    regime_series = _normalize_stress_regimes(stress_regimes, length)
    roll_vol = _compute_roll_vol_series(closes)
    threshold = _percentile_threshold(open_interest_series, 90.0)
    oi_stressed = [value > threshold for value in open_interest_series]
    funding_z = _compute_abs_zscores(funding_series)
    liquidation_z = _compute_abs_zscores(liquidation_series)
    depth_series = [min(depth_bid_series[index], depth_ask_series[index]) for index in range(length)]
    depth_depleted = _compute_low_percentile_flags(depth_series, percentile=10.0) if any(depth_series) else [False] * length
    regime_multiplier = [_STRESS_REGIME_MULTIPLIERS.get(label, 1.0) for label in regime_series]
    microstructure_available = (
        spread_bps is not None
        and depth_bid_1bp_usd is not None
        and depth_ask_1bp_usd is not None
        and latency_proxy_ms is not None
        and len(spread_bps) > 0
        and len(depth_bid_1bp_usd) > 0
        and len(depth_ask_1bp_usd) > 0
        and len(latency_proxy_ms) > 0
    )
    return {
        "open_interest": open_interest_series,
        "roll_vol": roll_vol,
        "oi_stressed": oi_stressed,
        "funding_z": funding_z,
        "liquidation_z": liquidation_z,
        "depth_depleted": depth_depleted,
        "regime_multiplier": regime_multiplier,
        "spread_bps": spread_series,
        "depth_bid_1bp_usd": depth_bid_series,
        "depth_ask_1bp_usd": depth_ask_series,
        "latency_proxy_ms": latency_series,
        "microstructure_available": microstructure_available,
    }


def _resolve_batch_slippage_bps(
    *,
    trade_notional: float,
    bar_index: int,
    flat_slippage_bps: float,
    slippage_model: str,
    slippage_context: dict[str, list[float] | list[bool] | bool],
) -> float:
    model = str(slippage_model).strip().lower()
    if model == "flat":
        return flat_slippage_bps

    open_interest = slippage_context["open_interest"]
    roll_vol = slippage_context["roll_vol"]
    oi_stressed = slippage_context["oi_stressed"]
    regime_multiplier = slippage_context["regime_multiplier"]
    funding_z = slippage_context["funding_z"]
    liquidation_z = slippage_context["liquidation_z"]
    depth_depleted = slippage_context["depth_depleted"]
    spread_bps = slippage_context["spread_bps"]
    depth_bid = slippage_context["depth_bid_1bp_usd"]
    depth_ask = slippage_context["depth_ask_1bp_usd"]
    latency_proxy_ms = slippage_context["latency_proxy_ms"]
    microstructure_available = bool(slippage_context["microstructure_available"])

    if model == "realistic" and microstructure_available:
        available_depth = min(depth_bid[bar_index], depth_ask[bar_index])
        base_bps = impact_cost_bps(
            q_notional=trade_notional,
            available_depth_notional=available_depth,
            sigma_1h=roll_vol[bar_index],
            spread_bps=spread_bps[bar_index],
            latency_ms=latency_proxy_ms[bar_index],
            coeff=_REALISTIC_BATCH_SLIPPAGE_COEFF,
        )
        return min(
            500.0,
            base_bps
            * _cascade_multiplier(
                oi_stressed=bool(oi_stressed[bar_index]),
                funding_z=funding_z[bar_index],
                liquidation_z=liquidation_z[bar_index],
                depth_depleted=bool(depth_depleted[bar_index]),
            ),
        )

    dynamic_bps = compute_dynamic_slippage(
        trade_notional=trade_notional,
        volatility=roll_vol[bar_index],
        open_interest=open_interest[bar_index],
        oi_is_stressed=bool(oi_stressed[bar_index]),
        stress_regime="",
        flat_fallback_bps=flat_slippage_bps,
    )
    if bool(oi_stressed[bar_index]):
        return min(500.0, dynamic_bps * regime_multiplier[bar_index])
    return dynamic_bps


def _resolve_batch_execution_fill_ratio(
    *,
    trade_notional: float,
    bar_index: int,
    slippage_model: str,
    slippage_context: dict[str, list[float] | list[bool] | bool],
) -> float:
    model = str(slippage_model).strip().lower()
    if trade_notional <= 0.0 or model != "realistic":
        return 1.0

    if not bool(slippage_context["microstructure_available"]):
        return 1.0

    depth_bid = slippage_context["depth_bid_1bp_usd"]
    depth_ask = slippage_context["depth_ask_1bp_usd"]
    oi_stressed = slippage_context["oi_stressed"]
    funding_z = slippage_context["funding_z"]
    liquidation_z = slippage_context["liquidation_z"]
    depth_depleted = slippage_context["depth_depleted"]

    available_depth = min(depth_bid[bar_index], depth_ask[bar_index])
    if available_depth <= 0.0:
        return 0.0

    depth_ratio = available_depth / max(trade_notional, 1e-9)
    cascade = _cascade_multiplier(
        oi_stressed=bool(oi_stressed[bar_index]),
        funding_z=funding_z[bar_index],
        liquidation_z=liquidation_z[bar_index],
        depth_depleted=bool(depth_depleted[bar_index]),
    )
    if depth_ratio >= 2.0 and cascade <= 1.25 and not bool(depth_depleted[bar_index]):
        return 1.0

    fill_ratio = min(1.0, depth_ratio)
    if cascade > 1.0:
        fill_ratio /= cascade
    if bool(depth_depleted[bar_index]) and depth_ratio < 1.5:
        fill_ratio *= 0.85
    return max(0.05, min(1.0, fill_ratio))


def _batch_liquidation_trigger_price(
    *,
    close: float,
    high: float,
    low: float,
    is_short: bool,
    liquidation_mark_price_weight: float,
    liquidation_mark_premium_bps: float,
) -> float:
    premium_multiplier = 1.0 + (liquidation_mark_premium_bps / 10_000.0)
    if is_short:
        base_price = (high * (1.0 - liquidation_mark_price_weight)) + (
            close * liquidation_mark_price_weight
        )
        return base_price * premium_multiplier
    base_price = (low * (1.0 - liquidation_mark_price_weight)) + (
        close * liquidation_mark_price_weight
    )
    return base_price * (1.0 - (liquidation_mark_premium_bps / 10_000.0))


# ---------------------------------------------------------------------------
# Pure-Python reference implementation
# (identical semantics to the JIT version — used for regression testing)
# ---------------------------------------------------------------------------

def _simulate_single_python(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    funding_rates: list[float],
    entry_signals: list[bool],
    exit_signals: list[bool],
    taker_fee_bps: float,
    slippage_bps: float,
    position_side: str,       # "long" | "short"
    position_leverage: float,
    maintenance_margin_ratio: float,
    latency_bars: int,
    liquidation_mark_price_weight: float = 0.0,
    liquidation_mark_premium_bps: float = 0.0,
    open_interest: list[float] | None = None,
    liquidation_notional: list[float] | None = None,
    spread_bps: list[float] | None = None,
    depth_bid_1bp_usd: list[float] | None = None,
    depth_ask_1bp_usd: list[float] | None = None,
    latency_proxy_ms: list[float] | None = None,
    slippage_model: str = "flat",
    stress_regimes: list[str] | None = None,
    funding_event_counts: list[int] | None = None,
    liquidation_fee_bps: float = 0.0,
    partial_liquidation_ratio: float = 1.0,
    liquidation_cooldown_bars: int = 0,
    liquidation_step_schedule: list[float] | None = None,
    maintenance_margin_schedule: list[dict[str, float]] | None = None,
    liquidation_fee_schedule: list[dict[str, float]] | None = None,
) -> dict[str, float | int | list[float] | dict[str, float | int]]:
    """Pure-Python bar-by-bar simulation.

    Returns a dict with keys:
        trade_count, gross_pnl, fee_spend, funding_spend, net_pnl,
        equity_curve (list[float])
    """
    is_short = position_side == "short"
    event_counts = list(funding_event_counts) if funding_event_counts is not None else [1] * len(closes)
    slippage_context = _prepare_slippage_context(
        closes=closes,
        funding_rates=funding_rates,
        open_interest=open_interest,
        liquidation_notional=liquidation_notional,
        spread_bps=spread_bps,
        depth_bid_1bp_usd=depth_bid_1bp_usd,
        depth_ask_1bp_usd=depth_ask_1bp_usd,
        latency_proxy_ms=latency_proxy_ms,
        stress_regimes=stress_regimes,
    )

    position_open = False
    position_size = 0.0
    entry_price = 0.0
    entry_index = -1
    liquidation_cooldown_until = -1
    liquidation_step_index = 0
    trade_count = 0
    winning_trades = 0
    gross_pnl = 0.0
    fee_spend = 0.0
    funding_spend = 0.0
    equity_curve: list[float] = []
    fill_event_count = 0
    partial_fill_event_count = 0
    fill_ratio_sum = 0.0
    min_fill_ratio = 1.0
    adverse_fill_event_count = 0
    adverse_fill_bps_sum = 0.0
    max_adverse_fill_bps = 0.0

    n = len(closes)
    for index in range(n):
        close = closes[index]
        mark = gross_pnl - fee_spend - funding_spend

        if position_open:
            if is_short:
                unrealized = (entry_price - close) * position_size
            else:
                unrealized = (close - entry_price) * position_size
            mark = gross_pnl - fee_spend - funding_spend + unrealized

            # funding cost (applied to notional)
            direction = -1.0 if is_short else 1.0
            funding_cost = abs(close * position_size) * funding_rates[index] * direction * event_counts[index]
            funding_spend += funding_cost
            mark = gross_pnl - fee_spend - funding_spend + unrealized

            # liquidation check (simplified)
            position_notional = entry_price * position_size
            effective_maintenance_margin_ratio = _resolve_maintenance_margin_ratio(
                position_leverage,
                position_notional,
                maintenance_margin_ratio,
                maintenance_margin_schedule,
            )
            liquidation_factor = 1.0 / position_leverage - effective_maintenance_margin_ratio
            if is_short:
                liq_price = entry_price * (1.0 + liquidation_factor)
            else:
                liq_price = entry_price * (1.0 - liquidation_factor)
            liquidation_trigger_price = _batch_liquidation_trigger_price(
                close=close,
                high=highs[index],
                low=lows[index],
                is_short=is_short,
                liquidation_mark_price_weight=liquidation_mark_price_weight,
                liquidation_mark_premium_bps=liquidation_mark_premium_bps,
            )
            liquidated = (
                liquidation_trigger_price >= liq_price
                if is_short
                else liquidation_trigger_price <= liq_price
            )

            if liquidated and index > entry_index and index > liquidation_cooldown_until:
                effective_liquidation_step_schedule, effective_partial_liquidation_ratio = _resolve_liquidation_step_behavior(
                    position_leverage=position_leverage,
                    position_notional=position_notional,
                    liquidation_style="partial",
                    profile_forces_full_liquidation=False,
                    explicit_partial_liquidation_ratio=partial_liquidation_ratio != 1.0,
                    explicit_liquidation_step_schedule=liquidation_step_schedule is not None,
                    default_partial_liquidation_ratio=partial_liquidation_ratio,
                    default_liquidation_step_schedule=liquidation_step_schedule,
                    maintenance_margin_schedule=maintenance_margin_schedule,
                )
                liquidation_ratio = _liquidation_ratio_for_event(
                    effective_liquidation_step_schedule,
                    effective_partial_liquidation_ratio,
                    liquidation_step_index,
                )
                liquidation_size = position_size * liquidation_ratio
                effective_liquidation_fee_bps = _resolve_tier_value(
                    position_leverage,
                    position_notional,
                    liquidation_fee_bps,
                    liquidation_fee_schedule,
                    "liquidation_fee_bps",
                )
                liquidation_slippage_bps = _resolve_batch_slippage_bps(
                    trade_notional=liq_price * liquidation_size,
                    bar_index=index,
                    flat_slippage_bps=slippage_bps,
                    slippage_model=slippage_model,
                    slippage_context=slippage_context,
                )
                exit_cost = liq_price * liquidation_size * (
                    (taker_fee_bps + liquidation_slippage_bps + effective_liquidation_fee_bps) / 10_000.0
                )
                fee_spend += exit_cost
                if is_short:
                    trade_gross = (entry_price - liq_price) * liquidation_size
                else:
                    trade_gross = (liq_price - entry_price) * liquidation_size
                gross_pnl += trade_gross
                trade_count += 1
                position_size -= liquidation_size
                liquidation_cooldown_until = index + liquidation_cooldown_bars
                liquidation_step_index += 1
                if position_size <= 1e-9:
                    position_open = False
                    position_size = 0.0
                    entry_price = 0.0
                    entry_index = -1
                    liquidation_cooldown_until = -1
                    liquidation_step_index = 0
                    mark = gross_pnl - fee_spend - funding_spend
                else:
                    if is_short:
                        remaining_unrealized = (entry_price - close) * position_size
                    else:
                        remaining_unrealized = (close - entry_price) * position_size
                    mark = gross_pnl - fee_spend - funding_spend + remaining_unrealized
                equity_curve.append(mark)
                continue

        if not position_open and entry_signals[index]:
            fill_index = min(index + latency_bars, n - 1)
            reference_fill_price = closes[fill_index]
            requested_position_size = float(position_leverage)
            entry_fill_ratio = _resolve_batch_execution_fill_ratio(
                trade_notional=reference_fill_price * requested_position_size,
                bar_index=fill_index,
                slippage_model=slippage_model,
                slippage_context=slippage_context,
            )
            executed_position_size = requested_position_size * entry_fill_ratio
            if executed_position_size <= 1e-9:
                equity_curve.append(mark)
                continue
            fill_event_count += 1
            fill_ratio_sum += entry_fill_ratio
            min_fill_ratio = min(min_fill_ratio, entry_fill_ratio)
            if entry_fill_ratio < 1.0 - 1e-9:
                partial_fill_event_count += 1
            entry_slippage_bps = _resolve_batch_slippage_bps(
                trade_notional=reference_fill_price * executed_position_size,
                bar_index=fill_index,
                flat_slippage_bps=slippage_bps,
                slippage_model=slippage_model,
                slippage_context=slippage_context,
            )
            adverse_fill_bps = _resolve_execution_adverse_fill_bps(
                effective_slippage_bps=entry_slippage_bps,
                fill_ratio=entry_fill_ratio,
                bar_index=fill_index,
                use_realistic_slippage=str(slippage_model).strip().lower() == "realistic",
                oi_stressed=slippage_context["oi_stressed"],
                funding_z=slippage_context["funding_z"],
                liquidation_z=slippage_context["liquidation_z"],
                depth_depleted=slippage_context["depth_depleted"],
            )
            fill_price = _apply_adverse_fill_price(
                reference_fill_price,
                position_side=position_side,
                is_entry=True,
                adverse_fill_bps=adverse_fill_bps,
            )
            if adverse_fill_bps > 0.0:
                adverse_fill_event_count += 1
                adverse_fill_bps_sum += adverse_fill_bps
                max_adverse_fill_bps = max(max_adverse_fill_bps, adverse_fill_bps)
            entry_cost = fill_price * executed_position_size * ((taker_fee_bps + entry_slippage_bps) / 10_000.0)
            fee_spend += entry_cost
            position_open = True
            # PnL, fees, and funding are computed on gross notional.
            # With position_leverage=10 and 1 unit margin, notional is 10 units.
            position_size = executed_position_size
            entry_price = fill_price
            entry_index = fill_index
            liquidation_cooldown_until = -1
            liquidation_step_index = 0
            mark = gross_pnl - fee_spend - funding_spend

        elif position_open and exit_signals[index] and index >= entry_index:
            fill_index = min(index + latency_bars, n - 1)
            reference_fill_price = closes[fill_index]
            exit_fill_ratio = _resolve_batch_execution_fill_ratio(
                trade_notional=reference_fill_price * position_size,
                bar_index=fill_index,
                slippage_model=slippage_model,
                slippage_context=slippage_context,
            )
            executed_exit_size = position_size * exit_fill_ratio
            if executed_exit_size <= 1e-9:
                equity_curve.append(mark)
                continue
            fill_event_count += 1
            fill_ratio_sum += exit_fill_ratio
            min_fill_ratio = min(min_fill_ratio, exit_fill_ratio)
            if exit_fill_ratio < 1.0 - 1e-9:
                partial_fill_event_count += 1
            exit_slippage_bps = _resolve_batch_slippage_bps(
                trade_notional=reference_fill_price * executed_exit_size,
                bar_index=fill_index,
                flat_slippage_bps=slippage_bps,
                slippage_model=slippage_model,
                slippage_context=slippage_context,
            )
            adverse_fill_bps = _resolve_execution_adverse_fill_bps(
                effective_slippage_bps=exit_slippage_bps,
                fill_ratio=exit_fill_ratio,
                bar_index=fill_index,
                use_realistic_slippage=str(slippage_model).strip().lower() == "realistic",
                oi_stressed=slippage_context["oi_stressed"],
                funding_z=slippage_context["funding_z"],
                liquidation_z=slippage_context["liquidation_z"],
                depth_depleted=slippage_context["depth_depleted"],
            )
            fill_price = _apply_adverse_fill_price(
                reference_fill_price,
                position_side=position_side,
                is_entry=False,
                adverse_fill_bps=adverse_fill_bps,
            )
            if adverse_fill_bps > 0.0:
                adverse_fill_event_count += 1
                adverse_fill_bps_sum += adverse_fill_bps
                max_adverse_fill_bps = max(max_adverse_fill_bps, adverse_fill_bps)
            exit_cost = fill_price * executed_exit_size * ((taker_fee_bps + exit_slippage_bps) / 10_000.0)
            fee_spend += exit_cost
            if is_short:
                trade_gross = (entry_price - fill_price) * executed_exit_size
            else:
                trade_gross = (fill_price - entry_price) * executed_exit_size
            trade_net = trade_gross - exit_cost
            gross_pnl += trade_gross
            trade_count += 1
            if trade_net > 0.0:
                winning_trades += 1
            position_size -= executed_exit_size
            if position_size <= 1e-9:
                position_open = False
                position_size = 0.0
                entry_price = 0.0
                entry_index = -1
            mark = gross_pnl - fee_spend - funding_spend

        equity_curve.append(mark)

    # Close any open position at end of series
    if position_open:
        fill_price = closes[-1]
        exit_slippage_bps = _resolve_batch_slippage_bps(
            trade_notional=fill_price * position_size,
            bar_index=n - 1,
            flat_slippage_bps=slippage_bps,
            slippage_model=slippage_model,
            slippage_context=slippage_context,
        )
        exit_cost = fill_price * position_size * ((taker_fee_bps + exit_slippage_bps) / 10_000.0)
        fee_spend += exit_cost
        if is_short:
            trade_gross = (entry_price - fill_price) * position_size
        else:
            trade_gross = (fill_price - entry_price) * position_size
        trade_net = trade_gross - exit_cost
        gross_pnl += trade_gross
        trade_count += 1
        if trade_net > 0.0:
            winning_trades += 1
        if equity_curve:
            equity_curve[-1] = gross_pnl - fee_spend - funding_spend
        else:
            equity_curve.append(gross_pnl - fee_spend - funding_spend)

    execution_pressure_summary: dict[str, float | int] = {}
    if str(slippage_model).strip().lower() == "realistic" and fill_event_count > 0:
        execution_pressure_summary = {
            "fill_event_count": fill_event_count,
            "partial_fill_event_count": partial_fill_event_count,
            "average_fill_ratio": round(fill_ratio_sum / fill_event_count, 6),
            "min_fill_ratio": round(min_fill_ratio, 6),
        }
        if adverse_fill_event_count > 0:
            execution_pressure_summary.update(
                {
                    "adverse_fill_event_count": adverse_fill_event_count,
                    "average_adverse_fill_bps": round(adverse_fill_bps_sum / adverse_fill_event_count, 6),
                    "max_adverse_fill_bps": round(max_adverse_fill_bps, 6),
                }
            )

    return {
        "trade_count": trade_count,
        "winning_trades": winning_trades,
        "gross_pnl": gross_pnl,
        "fee_spend": fee_spend,
        "funding_spend": funding_spend,
        "net_pnl": gross_pnl - fee_spend - funding_spend,
        "equity_curve": equity_curve,
        "execution_pressure_summary": execution_pressure_summary,
    }


# ---------------------------------------------------------------------------
# Numba JIT core — compiled lazily on first call
# ---------------------------------------------------------------------------

def _build_numba_kernel():
    """Build and return the @njit compiled inner loop.

    Called once; result cached in module-level _NUMBA_KERNEL.
    Returns None if numba is unavailable.
    """
    try:
        import numpy as np
        from numba import njit
    except ModuleNotFoundError:
        return None

    @njit(cache=True)
    def _resolve_slippage_bps_numba(
        trade_notional,
        bar_index,
        flat_slippage_bps,
        slippage_model_code,
        microstructure_available,
        open_interest,
        roll_vol,
        oi_stressed,
        regime_multiplier,
        funding_z,
        liquidation_z,
        depth_depleted,
        spread_bps,
        depth_bid_1bp_usd,
        depth_ask_1bp_usd,
        latency_proxy_ms,
    ):
        if slippage_model_code == 0:
            return flat_slippage_bps

        if slippage_model_code == 2 and microstructure_available:
            available_depth = depth_bid_1bp_usd[bar_index]
            if depth_ask_1bp_usd[bar_index] < available_depth:
                available_depth = depth_ask_1bp_usd[bar_index]
            if available_depth < 1e-9:
                available_depth = 1e-9
            participation = abs(trade_notional) / available_depth
            temp_bps = 0.10 * roll_vol[bar_index] * (participation ** 0.50) * 10_000.0
            delay_bps = 0.01 * latency_proxy_ms[bar_index] * roll_vol[bar_index]
            base_bps = spread_bps[bar_index] / 2.0 + temp_bps + delay_bps
            if base_bps > 500.0:
                base_bps = 500.0
            signal_count = 0
            if oi_stressed[bar_index]:
                signal_count += 1
            if abs(funding_z[bar_index]) > 2.0:
                signal_count += 1
            if liquidation_z[bar_index] > 2.0:
                signal_count += 1
            if depth_depleted[bar_index]:
                signal_count += 1
            multiplier = 1.0
            if signal_count >= 4:
                multiplier = 1.75
            elif signal_count == 3:
                multiplier = 1.50
            elif signal_count == 2:
                multiplier = 1.25
            total_bps = base_bps * multiplier
            if total_bps > 500.0:
                total_bps = 500.0
            return total_bps

        current_open_interest = open_interest[bar_index]
        if current_open_interest <= 0.0:
            return flat_slippage_bps
        participation = abs(trade_notional) / current_open_interest
        base_bps = 0.1 * math.sqrt(max(participation, 0.0)) * roll_vol[bar_index] * 10_000.0
        total_bps = base_bps
        if oi_stressed[bar_index]:
            total_bps = base_bps * regime_multiplier[bar_index]
        if total_bps > 500.0:
            total_bps = 500.0
        if total_bps < 0.0:
            total_bps = 0.0
        return total_bps

    @njit(cache=True)
    def _resolve_execution_fill_ratio_numba(
        trade_notional,
        bar_index,
        slippage_model_code,
        microstructure_available,
        oi_stressed,
        funding_z,
        liquidation_z,
        depth_depleted,
        depth_bid_1bp_usd,
        depth_ask_1bp_usd,
    ):
        if trade_notional <= 0.0 or slippage_model_code != 2 or not microstructure_available:
            return 1.0

        available_depth = depth_bid_1bp_usd[bar_index]
        if depth_ask_1bp_usd[bar_index] < available_depth:
            available_depth = depth_ask_1bp_usd[bar_index]
        if available_depth <= 0.0:
            return 0.0

        depth_ratio = available_depth / max(trade_notional, 1e-9)
        signal_count = 0
        if oi_stressed[bar_index]:
            signal_count += 1
        if abs(funding_z[bar_index]) > 2.0:
            signal_count += 1
        if liquidation_z[bar_index] > 2.0:
            signal_count += 1
        if depth_depleted[bar_index]:
            signal_count += 1
        cascade = 1.0
        if signal_count >= 4:
            cascade = 1.75
        elif signal_count == 3:
            cascade = 1.50
        elif signal_count == 2:
            cascade = 1.25
        if depth_ratio >= 2.0 and cascade <= 1.25 and not depth_depleted[bar_index]:
            return 1.0

        fill_ratio = depth_ratio
        if fill_ratio > 1.0:
            fill_ratio = 1.0
        if cascade > 1.0:
            fill_ratio = fill_ratio / cascade
        if depth_depleted[bar_index] and depth_ratio < 1.5:
            fill_ratio = fill_ratio * 0.85
        if fill_ratio < 0.05:
            return 0.05
        if fill_ratio > 1.0:
            return 1.0
        return fill_ratio

    @njit(cache=True)
    def _resolve_adverse_fill_bps_numba(
        effective_slippage_bps,
        fill_ratio,
        bar_index,
        slippage_model_code,
        oi_stressed,
        funding_z,
        liquidation_z,
        depth_depleted,
    ):
        if slippage_model_code != 2 or effective_slippage_bps <= 0.0:
            return 0.0

        signal_count = 0
        if oi_stressed[bar_index]:
            signal_count += 1
        if abs(funding_z[bar_index]) > 2.0:
            signal_count += 1
        if liquidation_z[bar_index] > 2.0:
            signal_count += 1
        if depth_depleted[bar_index]:
            signal_count += 1

        cascade = 1.0
        if signal_count >= 4:
            cascade = 1.75
        elif signal_count == 3:
            cascade = 1.50
        elif signal_count == 2:
            cascade = 1.25

        fill_shortfall = 1.0 - fill_ratio
        if fill_shortfall < 0.0:
            fill_shortfall = 0.0
        if fill_shortfall < 1e-3 and effective_slippage_bps < 25.0:
            return 0.0
        stress_pressure = fill_shortfall
        if depth_depleted[bar_index] and stress_pressure < 0.10:
            stress_pressure = 0.10
        if oi_stressed[bar_index]:
            stress_pressure += 0.05
        if abs(funding_z[bar_index]) > 2.0:
            stress_pressure += 0.05
        if liquidation_z[bar_index] > 2.0:
            stress_pressure += 0.05
        if cascade <= 1.0 and stress_pressure < 0.10:
            return 0.0

        if stress_pressure > 0.90:
            stress_pressure = 0.90
        adverse_bps = effective_slippage_bps * (0.20 + stress_pressure)
        if cascade > 1.0:
            cascade_factor = cascade / 1.25
            if cascade_factor > 1.50:
                cascade_factor = 1.50
            adverse_bps *= cascade_factor
        if adverse_bps < 0.0:
            adverse_bps = 0.0
        if adverse_bps > 150.0:
            adverse_bps = 150.0
        return adverse_bps

    @njit(cache=True)
    def _simulate_core(
        closes,
        highs,
        lows,
        funding_rates,
        funding_event_counts,
        entry_signals,
        exit_signals,
        taker_fee_bps,
        slippage_bps,
        is_short,
        position_leverage,
        maintenance_margin_ratio,
        liquidation_fee_bps,
        liquidation_mark_price_weight,
        liquidation_mark_premium_bps,
        partial_liquidation_ratio,
        liquidation_cooldown_bars,
        explicit_liquidation_step_schedule,
        explicit_liquidation_step_schedule_len,
        maintenance_tier_max_leverage,
        maintenance_tier_max_notional,
        maintenance_tier_margin_ratio,
        maintenance_tier_partial_liquidation_ratio,
        maintenance_tier_step_schedule,
        maintenance_tier_step_schedule_len,
        liquidation_fee_tier_max_leverage,
        liquidation_fee_tier_max_notional,
        liquidation_fee_tier_bps,
        slippage_model_code,
        microstructure_available,
        open_interest,
        roll_vol,
        oi_stressed,
        regime_multiplier,
        funding_z,
        liquidation_z,
        depth_depleted,
        spread_bps,
        depth_bid_1bp_usd,
        depth_ask_1bp_usd,
        latency_proxy_ms,
        latency_bars,
    ):
        """Numba JIT inner loop — operates on pre-allocated numpy arrays.

        Returns fill metrics too for realistic-slippage pressure summaries.
        equity_curve_array has length == len(closes).
        """
        n = len(closes)
        equity_curve = np.empty(n, dtype=np.float64)

        position_open = False
        position_size = 0.0
        entry_price = 0.0
        entry_index = -1
        liquidation_cooldown_until = -1
        liquidation_step_index = 0
        trade_count = 0
        winning_trades = 0
        gross_pnl = 0.0
        fee_spend = 0.0
        funding_spend = 0.0
        fill_event_count = 0
        partial_fill_event_count = 0
        fill_ratio_sum = 0.0
        min_fill_ratio = 1.0
        adverse_fill_event_count = 0
        adverse_fill_bps_sum = 0.0
        max_adverse_fill_bps = 0.0

        for index in range(n):
            close = closes[index]
            mark = gross_pnl - fee_spend - funding_spend

            if position_open:
                if is_short:
                    unrealized = (entry_price - close) * position_size
                else:
                    unrealized = (close - entry_price) * position_size
                mark = gross_pnl - fee_spend - funding_spend + unrealized

                direction = -1.0 if is_short else 1.0
                funding_cost = abs(close * position_size) * funding_rates[index] * direction * funding_event_counts[index]
                funding_spend += funding_cost
                mark = gross_pnl - fee_spend - funding_spend + unrealized

                position_notional = entry_price * position_size
                selected_maintenance_tier = -1
                effective_maintenance_margin_ratio = maintenance_margin_ratio
                maintenance_tier_count = len(maintenance_tier_margin_ratio)
                if maintenance_tier_count > 0:
                    selected_maintenance_tier = maintenance_tier_count - 1
                    effective_maintenance_margin_ratio = maintenance_tier_margin_ratio[selected_maintenance_tier]
                    for tier_index in range(maintenance_tier_count):
                        if (
                            position_leverage <= maintenance_tier_max_leverage[tier_index]
                            and position_notional <= maintenance_tier_max_notional[tier_index]
                        ):
                            selected_maintenance_tier = tier_index
                            effective_maintenance_margin_ratio = maintenance_tier_margin_ratio[tier_index]
                            break

                liquidation_factor = 1.0 / position_leverage - effective_maintenance_margin_ratio
                if is_short:
                    liq_price = entry_price * (1.0 + liquidation_factor)
                    base_trigger_price = (highs[index] * (1.0 - liquidation_mark_price_weight)) + (
                        close * liquidation_mark_price_weight
                    )
                    liquidation_trigger_price = base_trigger_price * (
                        1.0 + (liquidation_mark_premium_bps / 10_000.0)
                    )
                    liquidated = liquidation_trigger_price >= liq_price
                else:
                    liq_price = entry_price * (1.0 - liquidation_factor)
                    base_trigger_price = (lows[index] * (1.0 - liquidation_mark_price_weight)) + (
                        close * liquidation_mark_price_weight
                    )
                    liquidation_trigger_price = base_trigger_price * (
                        1.0 - (liquidation_mark_premium_bps / 10_000.0)
                    )
                    liquidated = liquidation_trigger_price <= liq_price

                if liquidated and index > entry_index and index > liquidation_cooldown_until:
                    effective_schedule_len = explicit_liquidation_step_schedule_len
                    effective_partial_liquidation_ratio = partial_liquidation_ratio
                    if effective_schedule_len == 0 and partial_liquidation_ratio == 1.0 and liquidation_cooldown_bars == 0:
                        if selected_maintenance_tier >= 0:
                            tier_schedule_len = maintenance_tier_step_schedule_len[selected_maintenance_tier]
                            if tier_schedule_len > 0:
                                effective_schedule_len = tier_schedule_len
                            else:
                                tier_partial_ratio = maintenance_tier_partial_liquidation_ratio[selected_maintenance_tier]
                                if tier_partial_ratio > 0.0:
                                    effective_partial_liquidation_ratio = tier_partial_ratio

                    liquidation_ratio = effective_partial_liquidation_ratio
                    if effective_schedule_len > 0:
                        clamped_step_index = liquidation_step_index
                        if clamped_step_index >= effective_schedule_len:
                            clamped_step_index = effective_schedule_len - 1
                        if explicit_liquidation_step_schedule_len > 0:
                            liquidation_ratio = explicit_liquidation_step_schedule[clamped_step_index]
                        else:
                            liquidation_ratio = maintenance_tier_step_schedule[selected_maintenance_tier, clamped_step_index]

                    liquidation_size = position_size * liquidation_ratio

                    effective_liquidation_fee_bps = liquidation_fee_bps
                    liquidation_fee_tier_count = len(liquidation_fee_tier_bps)
                    if liquidation_fee_tier_count > 0:
                        effective_liquidation_fee_bps = liquidation_fee_tier_bps[liquidation_fee_tier_count - 1]
                        for tier_index in range(liquidation_fee_tier_count):
                            if (
                                position_leverage <= liquidation_fee_tier_max_leverage[tier_index]
                                and position_notional <= liquidation_fee_tier_max_notional[tier_index]
                            ):
                                effective_liquidation_fee_bps = liquidation_fee_tier_bps[tier_index]
                                break

                    exit_cost = liq_price * liquidation_size * (
                        (
                            taker_fee_bps
                            + _resolve_slippage_bps_numba(
                                liq_price * liquidation_size,
                                index,
                                slippage_bps,
                                slippage_model_code,
                                microstructure_available,
                                open_interest,
                                roll_vol,
                                oi_stressed,
                                regime_multiplier,
                                funding_z,
                                liquidation_z,
                                depth_depleted,
                                spread_bps,
                                depth_bid_1bp_usd,
                                depth_ask_1bp_usd,
                                latency_proxy_ms,
                            )
                            + effective_liquidation_fee_bps
                        ) / 10_000.0
                    )
                    fee_spend += exit_cost
                    if is_short:
                        trade_gross = (entry_price - liq_price) * liquidation_size
                    else:
                        trade_gross = (liq_price - entry_price) * liquidation_size
                    gross_pnl += trade_gross
                    trade_count += 1
                    position_size -= liquidation_size
                    liquidation_cooldown_until = index + liquidation_cooldown_bars
                    liquidation_step_index += 1
                    if position_size <= 1e-9:
                        position_open = False
                        position_size = 0.0
                        entry_price = 0.0
                        entry_index = -1
                        liquidation_cooldown_until = -1
                        liquidation_step_index = 0
                        mark = gross_pnl - fee_spend - funding_spend
                    else:
                        if is_short:
                            remaining_unrealized = (entry_price - close) * position_size
                        else:
                            remaining_unrealized = (close - entry_price) * position_size
                        mark = gross_pnl - fee_spend - funding_spend + remaining_unrealized
                    equity_curve[index] = mark
                    continue

            if not position_open and entry_signals[index]:
                fill_index = index + latency_bars
                if fill_index >= n:
                    fill_index = n - 1
                reference_fill_price = closes[fill_index]
                executed_position_size = position_leverage * _resolve_execution_fill_ratio_numba(
                    reference_fill_price * position_leverage,
                    fill_index,
                    slippage_model_code,
                    microstructure_available,
                    oi_stressed,
                    funding_z,
                    liquidation_z,
                    depth_depleted,
                    depth_bid_1bp_usd,
                    depth_ask_1bp_usd,
                )
                if executed_position_size <= 1e-9:
                    equity_curve[index] = mark
                    continue
                requested_position_size = position_leverage
                entry_fill_ratio = 0.0
                if requested_position_size > 1e-9:
                    entry_fill_ratio = executed_position_size / requested_position_size
                fill_event_count += 1
                fill_ratio_sum += entry_fill_ratio
                if entry_fill_ratio < min_fill_ratio:
                    min_fill_ratio = entry_fill_ratio
                if entry_fill_ratio < 1.0 - 1e-9:
                    partial_fill_event_count += 1
                entry_slippage_bps = _resolve_slippage_bps_numba(
                    reference_fill_price * executed_position_size,
                    fill_index,
                    slippage_bps,
                    slippage_model_code,
                    microstructure_available,
                    open_interest,
                    roll_vol,
                    oi_stressed,
                    regime_multiplier,
                    funding_z,
                    liquidation_z,
                    depth_depleted,
                    spread_bps,
                    depth_bid_1bp_usd,
                    depth_ask_1bp_usd,
                    latency_proxy_ms,
                )
                adverse_fill_bps = _resolve_adverse_fill_bps_numba(
                    entry_slippage_bps,
                    entry_fill_ratio,
                    fill_index,
                    slippage_model_code,
                    oi_stressed,
                    funding_z,
                    liquidation_z,
                    depth_depleted,
                )
                fill_price = reference_fill_price
                if adverse_fill_bps > 0.0:
                    adverse_fill_event_count += 1
                    adverse_fill_bps_sum += adverse_fill_bps
                    if adverse_fill_bps > max_adverse_fill_bps:
                        max_adverse_fill_bps = adverse_fill_bps
                    adverse_multiplier = adverse_fill_bps / 10_000.0
                    if is_short:
                        fill_price = reference_fill_price * (1.0 - adverse_multiplier)
                    else:
                        fill_price = reference_fill_price * (1.0 + adverse_multiplier)
                entry_cost = fill_price * executed_position_size * (
                    (
                        taker_fee_bps
                        + entry_slippage_bps
                    ) / 10_000.0
                )
                fee_spend += entry_cost
                position_open = True
                position_size = executed_position_size
                entry_price = fill_price
                entry_index = fill_index
                liquidation_cooldown_until = -1
                liquidation_step_index = 0
                mark = gross_pnl - fee_spend - funding_spend

            elif position_open and exit_signals[index] and index >= entry_index:
                fill_index = index + latency_bars
                if fill_index >= n:
                    fill_index = n - 1
                reference_fill_price = closes[fill_index]
                executed_exit_size = position_size * _resolve_execution_fill_ratio_numba(
                    reference_fill_price * position_size,
                    fill_index,
                    slippage_model_code,
                    microstructure_available,
                    oi_stressed,
                    funding_z,
                    liquidation_z,
                    depth_depleted,
                    depth_bid_1bp_usd,
                    depth_ask_1bp_usd,
                )
                if executed_exit_size <= 1e-9:
                    equity_curve[index] = mark
                    continue
                exit_fill_ratio = 0.0
                if position_size > 1e-9:
                    exit_fill_ratio = executed_exit_size / position_size
                fill_event_count += 1
                fill_ratio_sum += exit_fill_ratio
                if exit_fill_ratio < min_fill_ratio:
                    min_fill_ratio = exit_fill_ratio
                if exit_fill_ratio < 1.0 - 1e-9:
                    partial_fill_event_count += 1
                exit_slippage_bps = _resolve_slippage_bps_numba(
                    reference_fill_price * executed_exit_size,
                    fill_index,
                    slippage_bps,
                    slippage_model_code,
                    microstructure_available,
                    open_interest,
                    roll_vol,
                    oi_stressed,
                    regime_multiplier,
                    funding_z,
                    liquidation_z,
                    depth_depleted,
                    spread_bps,
                    depth_bid_1bp_usd,
                    depth_ask_1bp_usd,
                    latency_proxy_ms,
                )
                adverse_fill_bps = _resolve_adverse_fill_bps_numba(
                    exit_slippage_bps,
                    exit_fill_ratio,
                    fill_index,
                    slippage_model_code,
                    oi_stressed,
                    funding_z,
                    liquidation_z,
                    depth_depleted,
                )
                fill_price = reference_fill_price
                if adverse_fill_bps > 0.0:
                    adverse_fill_event_count += 1
                    adverse_fill_bps_sum += adverse_fill_bps
                    if adverse_fill_bps > max_adverse_fill_bps:
                        max_adverse_fill_bps = adverse_fill_bps
                    adverse_multiplier = adverse_fill_bps / 10_000.0
                    if is_short:
                        fill_price = reference_fill_price * (1.0 + adverse_multiplier)
                    else:
                        fill_price = reference_fill_price * (1.0 - adverse_multiplier)
                exit_cost = fill_price * executed_exit_size * (
                    (
                        taker_fee_bps
                        + exit_slippage_bps
                    ) / 10_000.0
                )
                fee_spend += exit_cost
                if is_short:
                    trade_gross = (entry_price - fill_price) * executed_exit_size
                else:
                    trade_gross = (fill_price - entry_price) * executed_exit_size
                trade_net = trade_gross - exit_cost
                gross_pnl += trade_gross
                trade_count += 1
                if trade_net > 0.0:
                    winning_trades += 1
                position_size -= executed_exit_size
                if position_size <= 1e-9:
                    position_open = False
                    position_size = 0.0
                    entry_price = 0.0
                    entry_index = -1
                mark = gross_pnl - fee_spend - funding_spend

            equity_curve[index] = mark

        # Close any open position at end
        if position_open:
            fill_price = closes[n - 1]
            exit_cost = fill_price * position_size * (
                (
                    taker_fee_bps
                    + _resolve_slippage_bps_numba(
                        fill_price * position_size,
                        n - 1,
                        slippage_bps,
                        slippage_model_code,
                        microstructure_available,
                        open_interest,
                        roll_vol,
                        oi_stressed,
                        regime_multiplier,
                        funding_z,
                        liquidation_z,
                        depth_depleted,
                        spread_bps,
                        depth_bid_1bp_usd,
                        depth_ask_1bp_usd,
                        latency_proxy_ms,
                    )
                ) / 10_000.0
            )
            fee_spend += exit_cost
            if is_short:
                trade_gross = (entry_price - fill_price) * position_size
            else:
                trade_gross = (fill_price - entry_price) * position_size
            trade_net = trade_gross - exit_cost
            gross_pnl += trade_gross
            trade_count += 1
            if trade_net > 0.0:
                winning_trades += 1
            if n > 0:
                equity_curve[n - 1] = gross_pnl - fee_spend - funding_spend

        average_fill_ratio = 0.0
        min_fill_ratio_result = 0.0
        average_adverse_fill_bps = 0.0
        if slippage_model_code == 2 and fill_event_count > 0:
            average_fill_ratio = fill_ratio_sum / fill_event_count
            min_fill_ratio_result = min_fill_ratio
        if slippage_model_code == 2 and adverse_fill_event_count > 0:
            average_adverse_fill_bps = adverse_fill_bps_sum / adverse_fill_event_count

        return (
            trade_count,
            winning_trades,
            gross_pnl,
            fee_spend,
            funding_spend,
            equity_curve,
            fill_event_count,
            partial_fill_event_count,
            average_fill_ratio,
            min_fill_ratio_result,
            adverse_fill_event_count,
            average_adverse_fill_bps,
            max_adverse_fill_bps,
        )

    return _simulate_core


_NUMBA_KERNEL = None
_NUMBA_KERNEL_BUILT = False


def _get_numba_kernel():
    global _NUMBA_KERNEL, _NUMBA_KERNEL_BUILT
    if not _NUMBA_KERNEL_BUILT:
        _NUMBA_KERNEL = _build_numba_kernel()
        _NUMBA_KERNEL_BUILT = True
    return _NUMBA_KERNEL


# ---------------------------------------------------------------------------
# Batch public API
# ---------------------------------------------------------------------------

class BatchSimResult:
    """Lightweight result container returned per parameter set."""
    __slots__ = (
        "trade_count",
        "winning_trades",
        "gross_pnl",
        "fee_spend",
        "funding_spend",
        "net_pnl",
        "equity_curve",
        "execution_pressure_summary",
    )

    def __init__(
        self,
        trade_count: int,
        gross_pnl: float,
        fee_spend: float,
        funding_spend: float,
        net_pnl: float,
        equity_curve: list[float],
        execution_pressure_summary: dict[str, float | int] | None = None,
        winning_trades: int = 0,
    ) -> None:
        self.trade_count = trade_count
        self.winning_trades = winning_trades
        self.gross_pnl = gross_pnl
        self.fee_spend = fee_spend
        self.funding_spend = funding_spend
        self.net_pnl = net_pnl
        self.equity_curve = equity_curve
        self.execution_pressure_summary = dict(execution_pressure_summary or {})

    @property
    def win_rate(self) -> float:
        return (self.winning_trades / self.trade_count) if self.trade_count else 0.0


def _sort_tier_schedule(schedule: list[dict[str, float]] | None) -> list[dict[str, float]]:
    return sorted(
        schedule or [],
        key=lambda item: (
            float(item.get("max_leverage", float("inf"))),
            float(item.get("max_notional", float("inf"))),
        ),
    )


def _max_step_schedule_width(
    explicit_schedule: list[float] | None,
    maintenance_margin_schedule: list[dict[str, float]] | None,
) -> int:
    width = len(explicit_schedule or [])
    for item in maintenance_margin_schedule or []:
        width = max(width, len(item.get("liquidation_step_schedule", [])))
    return max(width, 1)


def simulate_strategy_batch(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    funding_rates: list[float],
    signal_matrix: list[tuple[list[bool], list[bool]]],
    open_interest: list[float] | None = None,
    liquidation_notional: list[float] | None = None,
    spread_bps: list[float] | None = None,
    depth_bid_1bp_usd: list[float] | None = None,
    depth_ask_1bp_usd: list[float] | None = None,
    latency_proxy_ms: list[float] | None = None,
    stress_regimes: list[str] | None = None,
    funding_event_counts: list[int] | None = None,
    taker_fee_bps: float = 0.0,
    param_slippage_bps: list[float] | None = None,
    param_latency_bars: list[int] | None = None,
    position_side: str = "long",
    position_leverage: float = 1.0,
    maintenance_margin_ratio: float = 0.01,
    liquidation_fee_bps: float = 0.0,
    liquidation_mark_price_weight: float = 0.0,
    liquidation_mark_premium_bps: float = 0.0,
    partial_liquidation_ratio: float = 1.0,
    liquidation_cooldown_bars: int = 0,
    liquidation_step_schedule: list[float] | None = None,
    maintenance_margin_schedule: list[dict[str, float]] | None = None,
    liquidation_fee_schedule: list[dict[str, float]] | None = None,
    slippage_model: str = "flat",
    telemetry_sink: dict[str, object] | None = None,
) -> list[BatchSimResult]:
    """Evaluate N parameter sets over a shared price/funding series.

    Parameters
    ----------
    closes:
        Bar close prices, length T.
    funding_rates:
        Per-bar funding rates, length T.
    signal_matrix:
        List of N (entry_signals, exit_signals) tuples, each of length T.
    taker_fee_bps:
        Taker fee in basis points, shared across all parameter sets.
    param_slippage_bps:
        Per-set slippage override.  Defaults to 0.0 for each set.
    param_latency_bars:
        Per-set latency override.  Defaults to 0 for each set.
    position_side:
        ``"long"`` or ``"short"``, shared across all parameter sets.
    position_leverage:
        Position leverage, shared across all parameter sets.
    maintenance_margin_ratio:
        Maintenance margin ratio, shared across all parameter sets.

    Returns
    -------
    list[BatchSimResult]
        One result per element of ``signal_matrix``, in order.
    """
    n_sets = len(signal_matrix)
    if n_sets == 0:
        return []

    slippage_list = param_slippage_bps if param_slippage_bps else [0.0] * n_sets
    latency_list = param_latency_bars if param_latency_bars else [0] * n_sets
    is_short = position_side == "short"
    event_counts = list(funding_event_counts) if funding_event_counts is not None else [1] * len(closes)
    slippage_context = _prepare_slippage_context(
        closes=closes,
        funding_rates=funding_rates,
        open_interest=open_interest,
        liquidation_notional=liquidation_notional,
        spread_bps=spread_bps,
        depth_bid_1bp_usd=depth_bid_1bp_usd,
        depth_ask_1bp_usd=depth_ask_1bp_usd,
        latency_proxy_ms=latency_proxy_ms,
        stress_regimes=stress_regimes,
    )

    kernel_start = time.perf_counter()
    kernel = _get_numba_kernel()
    kernel_compile_ms = (time.perf_counter() - kernel_start) * 1000.0
    use_numba = kernel is not None
    telemetry: dict[str, object] = {
        "numba_available": use_numba,
        "numba_used": False,
        "fallback_reason": None,
        "fallback_count": 0,
        "kernel_compile_ms": round(kernel_compile_ms, 6),
        "python_fallback_ms": None,
    }

    results: list[BatchSimResult] = []

    if use_numba:
        try:
            try:
                import numpy as np
            except ModuleNotFoundError:
                np = None
            sorted_maintenance_schedule = _sort_tier_schedule(maintenance_margin_schedule)
            sorted_liquidation_fee_schedule = _sort_tier_schedule(liquidation_fee_schedule)
            max_step_width = _max_step_schedule_width(liquidation_step_schedule, sorted_maintenance_schedule)
            slippage_model_code = 2 if str(slippage_model).strip().lower() == "realistic" else (1 if str(slippage_model).strip().lower() == "dynamic" else 0)
            microstructure_available = bool(slippage_context["microstructure_available"])

            if np is None:
                maintenance_tier_max_leverage = [
                    float(item.get("max_leverage", float("inf"))) for item in sorted_maintenance_schedule
                ]
                maintenance_tier_max_notional = [
                    float(item.get("max_notional", float("inf"))) for item in sorted_maintenance_schedule
                ]
                maintenance_tier_margin_ratio = [
                    float(item["maintenance_margin_ratio"]) for item in sorted_maintenance_schedule
                ]
                maintenance_tier_partial_liquidation_ratio = [
                    float(item.get("partial_liquidation_ratio", 0.0)) for item in sorted_maintenance_schedule
                ]
                maintenance_tier_step_schedule_len = [
                    len(item.get("liquidation_step_schedule", [])) for item in sorted_maintenance_schedule
                ]
                maintenance_tier_step_schedule = [
                    ([float(value) for value in item.get("liquidation_step_schedule", [])] + ([0.0] * max_step_width))[:max_step_width]
                    for item in sorted_maintenance_schedule
                ]
                liquidation_fee_tier_max_leverage = [
                    float(item.get("max_leverage", float("inf"))) for item in sorted_liquidation_fee_schedule
                ]
                liquidation_fee_tier_max_notional = [
                    float(item.get("max_notional", float("inf"))) for item in sorted_liquidation_fee_schedule
                ]
                liquidation_fee_tier_bps = [
                    float(item["liquidation_fee_bps"]) for item in sorted_liquidation_fee_schedule
                ]
                explicit_liquidation_step_schedule_arr = [float(value) for value in liquidation_step_schedule or []]
                explicit_liquidation_step_schedule_len = len(explicit_liquidation_step_schedule_arr)

                for i, (entry_signals, exit_signals) in enumerate(signal_matrix):
                    kernel_result = kernel(
                        closes,
                        highs,
                        lows,
                        funding_rates,
                        event_counts,
                        entry_signals,
                        exit_signals,
                        taker_fee_bps,
                        slippage_list[i],
                        is_short,
                        position_leverage,
                        maintenance_margin_ratio,
                        liquidation_fee_bps,
                        liquidation_mark_price_weight,
                        liquidation_mark_premium_bps,
                        partial_liquidation_ratio,
                        liquidation_cooldown_bars,
                        explicit_liquidation_step_schedule_arr,
                        explicit_liquidation_step_schedule_len,
                        maintenance_tier_max_leverage,
                        maintenance_tier_max_notional,
                        maintenance_tier_margin_ratio,
                        maintenance_tier_partial_liquidation_ratio,
                        maintenance_tier_step_schedule,
                        maintenance_tier_step_schedule_len,
                        liquidation_fee_tier_max_leverage,
                        liquidation_fee_tier_max_notional,
                        liquidation_fee_tier_bps,
                        slippage_model_code,
                        microstructure_available,
                        slippage_context["open_interest"],
                        slippage_context["roll_vol"],
                        slippage_context["oi_stressed"],
                        slippage_context["regime_multiplier"],
                        slippage_context["funding_z"],
                        slippage_context["liquidation_z"],
                        slippage_context["depth_depleted"],
                        slippage_context["spread_bps"],
                        slippage_context["depth_bid_1bp_usd"],
                        slippage_context["depth_ask_1bp_usd"],
                        slippage_context["latency_proxy_ms"],
                        latency_list[i],
                    )
                    if len(kernel_result) == 13:
                        (
                            trade_count,
                            winning_trades,
                            gross_pnl,
                            fee_spend,
                            funding_spend,
                            eq_arr,
                            fill_event_count,
                            partial_fill_event_count,
                            average_fill_ratio,
                            min_fill_ratio,
                            adverse_fill_event_count,
                            average_adverse_fill_bps,
                            max_adverse_fill_bps,
                        ) = kernel_result
                    elif len(kernel_result) == 12:
                        (
                            trade_count,
                            gross_pnl,
                            fee_spend,
                            funding_spend,
                            eq_arr,
                            fill_event_count,
                            partial_fill_event_count,
                            average_fill_ratio,
                            min_fill_ratio,
                            adverse_fill_event_count,
                            average_adverse_fill_bps,
                            max_adverse_fill_bps,
                        ) = kernel_result
                        winning_trades = 0
                    elif len(kernel_result) == 9:
                        (
                            trade_count,
                            gross_pnl,
                            fee_spend,
                            funding_spend,
                            eq_arr,
                            fill_event_count,
                            partial_fill_event_count,
                            average_fill_ratio,
                            min_fill_ratio,
                        ) = kernel_result
                        winning_trades = 0
                        adverse_fill_event_count = 0
                        average_adverse_fill_bps = 0.0
                        max_adverse_fill_bps = 0.0
                    else:
                        trade_count, gross_pnl, fee_spend, funding_spend, eq_arr = kernel_result
                        winning_trades = 0
                        fill_event_count = 0
                        partial_fill_event_count = 0
                        average_fill_ratio = 0.0
                        min_fill_ratio = 0.0
                        adverse_fill_event_count = 0
                        average_adverse_fill_bps = 0.0
                        max_adverse_fill_bps = 0.0
                    execution_pressure_summary: dict[str, float | int] = {}
                    if slippage_model_code == 2 and int(fill_event_count) > 0:
                        execution_pressure_summary = {
                            "fill_event_count": int(fill_event_count),
                            "partial_fill_event_count": int(partial_fill_event_count),
                            "average_fill_ratio": round(float(average_fill_ratio), 6),
                            "min_fill_ratio": round(float(min_fill_ratio), 6),
                        }
                        if int(adverse_fill_event_count) > 0:
                            execution_pressure_summary.update(
                                {
                                    "adverse_fill_event_count": int(adverse_fill_event_count),
                                    "average_adverse_fill_bps": round(float(average_adverse_fill_bps), 6),
                                    "max_adverse_fill_bps": round(float(max_adverse_fill_bps), 6),
                                }
                            )
                    results.append(BatchSimResult(
                        trade_count=int(trade_count),
                        gross_pnl=float(gross_pnl),
                        fee_spend=float(fee_spend),
                        funding_spend=float(funding_spend),
                        net_pnl=float(gross_pnl - fee_spend - funding_spend),
                        equity_curve=eq_arr.tolist(),
                        execution_pressure_summary=execution_pressure_summary,
                        winning_trades=int(winning_trades),
                    ))
                telemetry["numba_used"] = True
                _update_telemetry_sink(telemetry_sink, telemetry)
                return results

            maintenance_tier_max_leverage = np.empty(len(sorted_maintenance_schedule), dtype=np.float64)
            maintenance_tier_max_notional = np.empty(len(sorted_maintenance_schedule), dtype=np.float64)
            maintenance_tier_margin_ratio = np.empty(len(sorted_maintenance_schedule), dtype=np.float64)
            maintenance_tier_partial_liquidation_ratio = np.empty(len(sorted_maintenance_schedule), dtype=np.float64)
            maintenance_tier_step_schedule_len = np.empty(len(sorted_maintenance_schedule), dtype=np.int64)
            maintenance_tier_step_schedule = np.zeros((len(sorted_maintenance_schedule), max_step_width), dtype=np.float64)

            for tier_index, item in enumerate(sorted_maintenance_schedule):
                maintenance_tier_max_leverage[tier_index] = float(item.get("max_leverage", float("inf")))
                maintenance_tier_max_notional[tier_index] = float(item.get("max_notional", float("inf")))
                maintenance_tier_margin_ratio[tier_index] = float(item["maintenance_margin_ratio"])
                maintenance_tier_partial_liquidation_ratio[tier_index] = float(item.get("partial_liquidation_ratio", 0.0))
                tier_schedule = [float(value) for value in item.get("liquidation_step_schedule", [])]
                maintenance_tier_step_schedule_len[tier_index] = len(tier_schedule)
                for step_index, value in enumerate(tier_schedule):
                    maintenance_tier_step_schedule[tier_index, step_index] = value

            liquidation_fee_tier_max_leverage = np.empty(len(sorted_liquidation_fee_schedule), dtype=np.float64)
            liquidation_fee_tier_max_notional = np.empty(len(sorted_liquidation_fee_schedule), dtype=np.float64)
            liquidation_fee_tier_bps = np.empty(len(sorted_liquidation_fee_schedule), dtype=np.float64)
            for tier_index, item in enumerate(sorted_liquidation_fee_schedule):
                liquidation_fee_tier_max_leverage[tier_index] = float(item.get("max_leverage", float("inf")))
                liquidation_fee_tier_max_notional[tier_index] = float(item.get("max_notional", float("inf")))
                liquidation_fee_tier_bps[tier_index] = float(item["liquidation_fee_bps"])

            explicit_liquidation_step_schedule_arr = np.zeros(max_step_width, dtype=np.float64)
            explicit_liquidation_step_schedule_len = len(liquidation_step_schedule or [])
            for step_index, value in enumerate(liquidation_step_schedule or []):
                explicit_liquidation_step_schedule_arr[step_index] = float(value)

            closes_arr = np.asarray(closes, dtype=np.float64)
            highs_arr = np.asarray(highs, dtype=np.float64)
            lows_arr = np.asarray(lows, dtype=np.float64)
            funding_arr = np.asarray(funding_rates, dtype=np.float64)
            funding_event_arr = np.asarray(event_counts, dtype=np.int64)
            open_interest_arr = np.asarray(slippage_context["open_interest"], dtype=np.float64)
            roll_vol_arr = np.asarray(slippage_context["roll_vol"], dtype=np.float64)
            oi_stressed_arr = np.asarray(slippage_context["oi_stressed"], dtype=np.bool_)
            regime_multiplier_arr = np.asarray(slippage_context["regime_multiplier"], dtype=np.float64)
            funding_z_arr = np.asarray(slippage_context["funding_z"], dtype=np.float64)
            liquidation_z_arr = np.asarray(slippage_context["liquidation_z"], dtype=np.float64)
            depth_depleted_arr = np.asarray(slippage_context["depth_depleted"], dtype=np.bool_)
            spread_arr = np.asarray(slippage_context["spread_bps"], dtype=np.float64)
            depth_bid_arr = np.asarray(slippage_context["depth_bid_1bp_usd"], dtype=np.float64)
            depth_ask_arr = np.asarray(slippage_context["depth_ask_1bp_usd"], dtype=np.float64)
            latency_proxy_arr = np.asarray(slippage_context["latency_proxy_ms"], dtype=np.float64)
            for i, (entry_signals, exit_signals) in enumerate(signal_matrix):
                entry_arr = np.asarray(entry_signals, dtype=np.bool_)
                exit_arr = np.asarray(exit_signals, dtype=np.bool_)
                kernel_result = kernel(
                    closes_arr,
                    highs_arr,
                    lows_arr,
                    funding_arr,
                    funding_event_arr,
                    entry_arr,
                    exit_arr,
                    taker_fee_bps,
                    slippage_list[i],
                    is_short,
                    position_leverage,
                    maintenance_margin_ratio,
                    liquidation_fee_bps,
                    liquidation_mark_price_weight,
                    liquidation_mark_premium_bps,
                    partial_liquidation_ratio,
                    liquidation_cooldown_bars,
                    explicit_liquidation_step_schedule_arr,
                    explicit_liquidation_step_schedule_len,
                    maintenance_tier_max_leverage,
                    maintenance_tier_max_notional,
                    maintenance_tier_margin_ratio,
                    maintenance_tier_partial_liquidation_ratio,
                    maintenance_tier_step_schedule,
                    maintenance_tier_step_schedule_len,
                    liquidation_fee_tier_max_leverage,
                    liquidation_fee_tier_max_notional,
                    liquidation_fee_tier_bps,
                    slippage_model_code,
                    microstructure_available,
                    open_interest_arr,
                    roll_vol_arr,
                    oi_stressed_arr,
                    regime_multiplier_arr,
                    funding_z_arr,
                    liquidation_z_arr,
                    depth_depleted_arr,
                    spread_arr,
                    depth_bid_arr,
                    depth_ask_arr,
                    latency_proxy_arr,
                    latency_list[i],
                )
                if len(kernel_result) == 13:
                    (
                        trade_count,
                        winning_trades,
                        gross_pnl,
                        fee_spend,
                        funding_spend,
                        eq_arr,
                        fill_event_count,
                        partial_fill_event_count,
                        average_fill_ratio,
                        min_fill_ratio,
                        adverse_fill_event_count,
                        average_adverse_fill_bps,
                        max_adverse_fill_bps,
                    ) = kernel_result
                elif len(kernel_result) == 12:
                    (
                        trade_count,
                        gross_pnl,
                        fee_spend,
                        funding_spend,
                        eq_arr,
                        fill_event_count,
                        partial_fill_event_count,
                        average_fill_ratio,
                        min_fill_ratio,
                        adverse_fill_event_count,
                        average_adverse_fill_bps,
                        max_adverse_fill_bps,
                    ) = kernel_result
                    winning_trades = 0
                elif len(kernel_result) == 9:
                    (
                        trade_count,
                        gross_pnl,
                        fee_spend,
                        funding_spend,
                        eq_arr,
                        fill_event_count,
                        partial_fill_event_count,
                        average_fill_ratio,
                        min_fill_ratio,
                    ) = kernel_result
                    winning_trades = 0
                else:
                    trade_count, gross_pnl, fee_spend, funding_spend, eq_arr = kernel_result
                    winning_trades = 0
                    fill_event_count = 0
                    partial_fill_event_count = 0
                    average_fill_ratio = 0.0
                    min_fill_ratio = 0.0
                    adverse_fill_event_count = 0
                    average_adverse_fill_bps = 0.0
                    max_adverse_fill_bps = 0.0
                execution_pressure_summary: dict[str, float | int] = {}
                if slippage_model_code == 2 and int(fill_event_count) > 0:
                    execution_pressure_summary = {
                        "fill_event_count": int(fill_event_count),
                        "partial_fill_event_count": int(partial_fill_event_count),
                        "average_fill_ratio": round(float(average_fill_ratio), 6),
                        "min_fill_ratio": round(float(min_fill_ratio), 6),
                    }
                    if int(adverse_fill_event_count) > 0:
                        execution_pressure_summary.update(
                            {
                                "adverse_fill_event_count": int(adverse_fill_event_count),
                                "average_adverse_fill_bps": round(float(average_adverse_fill_bps), 6),
                                "max_adverse_fill_bps": round(float(max_adverse_fill_bps), 6),
                            }
                        )
                results.append(BatchSimResult(
                    trade_count=int(trade_count),
                    gross_pnl=float(gross_pnl),
                    fee_spend=float(fee_spend),
                    funding_spend=float(funding_spend),
                    net_pnl=float(gross_pnl - fee_spend - funding_spend),
                    equity_curve=eq_arr.tolist(),
                    execution_pressure_summary=execution_pressure_summary,
                    winning_trades=int(winning_trades),
                ))
            telemetry["numba_used"] = True
            _update_telemetry_sink(telemetry_sink, telemetry)
            return results
        except Exception as exc:
            logger.warning("Numba batch sim failed (%s); falling back to pure Python", exc)
            telemetry["fallback_reason"] = str(exc)
            telemetry["fallback_count"] = 1

    # Pure-Python fallback (also used when numba unavailable)
    python_fallback_start = time.perf_counter()
    for i, (entry_signals, exit_signals) in enumerate(signal_matrix):
        raw = _simulate_single_python(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=funding_rates,
            open_interest=open_interest,
            liquidation_notional=liquidation_notional,
            spread_bps=spread_bps,
            depth_bid_1bp_usd=depth_bid_1bp_usd,
            depth_ask_1bp_usd=depth_ask_1bp_usd,
            latency_proxy_ms=latency_proxy_ms,
            funding_event_counts=event_counts,
            entry_signals=entry_signals,
            exit_signals=exit_signals,
            taker_fee_bps=taker_fee_bps,
            slippage_bps=slippage_list[i],
            position_side=position_side,
            position_leverage=position_leverage,
            maintenance_margin_ratio=maintenance_margin_ratio,
            liquidation_fee_bps=liquidation_fee_bps,
            liquidation_mark_price_weight=liquidation_mark_price_weight,
            liquidation_mark_premium_bps=liquidation_mark_premium_bps,
            slippage_model=slippage_model,
            stress_regimes=stress_regimes,
            partial_liquidation_ratio=partial_liquidation_ratio,
            liquidation_cooldown_bars=liquidation_cooldown_bars,
            liquidation_step_schedule=liquidation_step_schedule,
            latency_bars=latency_list[i],
            maintenance_margin_schedule=maintenance_margin_schedule,
            liquidation_fee_schedule=liquidation_fee_schedule,
        )
        results.append(BatchSimResult(
            trade_count=int(raw["trade_count"]),
            gross_pnl=float(raw["gross_pnl"]),
            fee_spend=float(raw["fee_spend"]),
            funding_spend=float(raw["funding_spend"]),
            net_pnl=float(raw["net_pnl"]),
            equity_curve=list(raw["equity_curve"]),
            execution_pressure_summary=dict(raw.get("execution_pressure_summary", {})),
            winning_trades=int(raw.get("winning_trades", 0)),
        ))

    telemetry["python_fallback_ms"] = round((time.perf_counter() - python_fallback_start) * 1000.0, 6)
    if not use_numba and telemetry["fallback_reason"] is None:
        telemetry["fallback_reason"] = "numba_unavailable"
    _update_telemetry_sink(telemetry_sink, telemetry)
    return results


def _update_telemetry_sink(telemetry_sink: dict[str, object] | None, telemetry: dict[str, object]) -> None:
    if telemetry_sink is not None:
        telemetry_sink.clear()
        telemetry_sink.update(telemetry)
