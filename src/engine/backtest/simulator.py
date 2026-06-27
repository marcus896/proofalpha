from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from engine.backtest.execution_costs import apply_funding, apply_trade_cost
from engine.backtest.market_impact import (
    ImpactCostCoefficients,
    compute_dynamic_slippage,
    compute_oi_stress_flag,
    impact_cost_bps,
)
from engine.backtest.risk import max_drawdown, sharpe_ratio, sortino_ratio
from engine.config.models import BacktestResult, DataSnapshot


_TIMEFRAME_BARS_PER_YEAR: dict[str, int] = {
    "1m": 365 * 24 * 60,
    "3m": 365 * 24 * 20,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,       # 8_760
    "2h": 365 * 12,
    "4h": 365 * 6,        # 2_190
    "6h": 365 * 4,
    "8h": 365 * 3,
    "12h": 365 * 2,
    "1d": 365,
    "3d": 365 // 3,
    "1w": 52,
}

_FUNDING_SETTLEMENT_HOURS_BY_VENUE: dict[str, tuple[int, ...]] = {
    "binance": (0, 8, 16),
    "bybit": (0, 8, 16),
    "okx": (0, 8, 16),
}
_UNSET = object()
_DEFAULT_MAINTENANCE_MARGIN_RATIO = 0.01
_DEFAULT_LIQUIDATION_FEE_BPS = 0.0
_DEFAULT_LIQUIDATION_MARK_PRICE_WEIGHT = 0.0
_DEFAULT_PARTIAL_LIQUIDATION_RATIO = 1.0
_DEFAULT_LIQUIDATION_COOLDOWN_BARS = 0
_DEFAULT_LIQUIDATION_MARK_PREMIUM_BPS = 0.0
_REALISTIC_SLIPPAGE_COEFF = ImpactCostCoefficients()


def _annualization_factor(timeframe: str) -> float:
    """Return sqrt(bars_per_year) for the given timeframe string.

    Crypto markets are 24/7/365 so we use 365 calendar days, not 252.
    Falls back to 1.0 (no annualisation) for unrecognised timeframe strings.
    """
    bars = _TIMEFRAME_BARS_PER_YEAR.get(str(timeframe).lower().strip())
    if bars is None or bars <= 0:
        return 1.0
    return math.sqrt(float(bars))


def _compute_funding_event_counts(candles, venue: str) -> list[int]:
    if not candles:
        return []
    settlement_hours = _FUNDING_SETTLEMENT_HOURS_BY_VENUE.get(str(venue).lower().strip())
    if not settlement_hours:
        return [1] * len(candles)

    counts: list[int] = [0] * len(candles)
    for index in range(1, len(candles)):
        counts[index] = _count_funding_events_between(
            candles[index - 1].timestamp,
            candles[index].timestamp,
            settlement_hours,
        )
    return counts


def _count_funding_events_between(
    previous_timestamp: datetime,
    current_timestamp: datetime,
    settlement_hours: tuple[int, ...],
) -> int:
    start = previous_timestamp.astimezone(UTC)
    end = current_timestamp.astimezone(UTC)
    if end <= start:
        return 0

    count = 0
    day = start.date()
    final_day = end.date()
    while day <= final_day:
        for hour in settlement_hours:
            settlement = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
            if start < settlement <= end:
                count += 1
        day += timedelta(days=1)
    return count


def simulate_strategy(
    snapshot: DataSnapshot,
    entry_signals: list[bool],
    exit_signals: list[bool],
    slippage_bps: float = 0.0,
    latency_bars: int = 0,
    position_side: str = "long",
    position_leverage: float = 1.0,
    maintenance_margin_ratio: float | object = _UNSET,
    liquidation_fee_bps: float | object = _UNSET,
    liquidation_mark_price_weight: float | object = _UNSET,
    partial_liquidation_ratio: float | object = _UNSET,
    liquidation_cooldown_bars: int | object = _UNSET,
    liquidation_step_schedule: list[float] | None | object = _UNSET,
    liquidation_mark_premium_bps: float | object = _UNSET,
    maintenance_margin_schedule: list[dict[str, float]] | None | object = _UNSET,
    liquidation_fee_schedule: list[dict[str, float]] | None | object = _UNSET,
    slippage_model: str = "flat",
) -> BacktestResult:
    def _equity_mark(unrealized_pnl: float = 0.0) -> float:
        return gross_pnl - fee_spend - funding_spend + unrealized_pnl

    raw_partial_liquidation_ratio = partial_liquidation_ratio
    raw_liquidation_step_schedule = liquidation_step_schedule
    candles = snapshot.candles
    (
        maintenance_margin_ratio,
        liquidation_fee_bps,
        liquidation_mark_price_weight,
        partial_liquidation_ratio,
        liquidation_cooldown_bars,
        liquidation_step_schedule,
        liquidation_mark_premium_bps,
        maintenance_margin_schedule,
        liquidation_fee_schedule,
    ) = _resolve_liquidation_defaults(
        snapshot=snapshot,
        maintenance_margin_ratio=maintenance_margin_ratio,
        liquidation_fee_bps=liquidation_fee_bps,
        liquidation_mark_price_weight=liquidation_mark_price_weight,
        partial_liquidation_ratio=partial_liquidation_ratio,
        liquidation_cooldown_bars=liquidation_cooldown_bars,
        liquidation_step_schedule=liquidation_step_schedule,
        liquidation_mark_premium_bps=liquidation_mark_premium_bps,
        maintenance_margin_schedule=maintenance_margin_schedule,
        liquidation_fee_schedule=liquidation_fee_schedule,
    )
    if not (len(candles) == len(entry_signals) == len(exit_signals)):
        raise ValueError("snapshot and signals must have equal lengths")
    if latency_bars < 0:
        raise ValueError("latency_bars must be non-negative")
    if position_side not in {"long", "short"}:
        raise ValueError("position_side must be 'long' or 'short'")
    if position_leverage < 1.0:
        raise ValueError("position_leverage must be at least 1.0")
    if maintenance_margin_ratio < 0.0 or maintenance_margin_ratio >= 1.0:
        raise ValueError("maintenance_margin_ratio must be between 0.0 and 1.0")
    if liquidation_fee_bps < 0.0:
        raise ValueError("liquidation_fee_bps must be non-negative")
    if liquidation_mark_price_weight < 0.0 or liquidation_mark_price_weight > 1.0:
        raise ValueError("liquidation_mark_price_weight must be between 0.0 and 1.0")
    if partial_liquidation_ratio <= 0.0 or partial_liquidation_ratio > 1.0:
        raise ValueError("partial_liquidation_ratio must be between 0.0 and 1.0")
    if liquidation_cooldown_bars < 0:
        raise ValueError("liquidation_cooldown_bars must be non-negative")
    for value in liquidation_step_schedule or []:
        if value <= 0.0 or value > 1.0:
            raise ValueError("liquidation_step_schedule values must be between 0.0 and 1.0")
    if liquidation_mark_premium_bps < 0.0:
        raise ValueError("liquidation_mark_premium_bps must be non-negative")
    for item in maintenance_margin_schedule or []:
        if "maintenance_margin_ratio" not in item:
            raise ValueError("maintenance_margin_schedule items must include maintenance_margin_ratio")
        if "max_leverage" not in item and "max_notional" not in item:
            raise ValueError("maintenance_margin_schedule items must include max_leverage or max_notional")
        if "max_leverage" in item and float(item["max_leverage"]) <= 0.0:
            raise ValueError("maintenance_margin_schedule max_leverage must be positive")
        if "max_notional" in item and float(item["max_notional"]) <= 0.0:
            raise ValueError("maintenance_margin_schedule max_notional must be positive")
        if float(item["maintenance_margin_ratio"]) < 0.0 or float(item["maintenance_margin_ratio"]) >= 1.0:
            raise ValueError("maintenance_margin_schedule maintenance_margin_ratio must be between 0.0 and 1.0")
        for value in item.get("liquidation_step_schedule", []):
            if float(value) <= 0.0 or float(value) > 1.0:
                raise ValueError("maintenance_margin_schedule liquidation_step_schedule values must be between 0.0 and 1.0")
        if "partial_liquidation_ratio" in item:
            if float(item["partial_liquidation_ratio"]) <= 0.0 or float(item["partial_liquidation_ratio"]) > 1.0:
                raise ValueError("maintenance_margin_schedule partial_liquidation_ratio must be between 0.0 and 1.0")
    for item in liquidation_fee_schedule or []:
        if "liquidation_fee_bps" not in item:
            raise ValueError("liquidation_fee_schedule items must include liquidation_fee_bps")
        if "max_leverage" not in item and "max_notional" not in item:
            raise ValueError("liquidation_fee_schedule items must include max_leverage or max_notional")
        if "max_leverage" in item and float(item["max_leverage"]) <= 0.0:
            raise ValueError("liquidation_fee_schedule max_leverage must be positive")
        if "max_notional" in item and float(item["max_notional"]) <= 0.0:
            raise ValueError("liquidation_fee_schedule max_notional must be positive")
        if float(item["liquidation_fee_bps"]) < 0.0:
            raise ValueError("liquidation_fee_schedule liquidation_fee_bps must be non-negative")

    use_dynamic_slippage = str(slippage_model) == "dynamic"
    use_realistic_slippage = str(slippage_model) == "realistic"
    resolved_liquidation_style = _resolve_liquidation_style(
        snapshot=snapshot,
        partial_liquidation_ratio=raw_partial_liquidation_ratio,
        liquidation_step_schedule=raw_liquidation_step_schedule,
    )
    profile_forces_full_liquidation = (
        snapshot.venue_profile is not None
        and str(snapshot.venue_profile.liquidation_style).strip().lower() == "full"
        and raw_partial_liquidation_ratio is _UNSET
        and raw_liquidation_step_schedule is _UNSET
    )

    # Pre-compute dynamic slippage auxiliary arrays when needed.
    # These are cheap: O(T) stdlib arithmetic, no numpy required here.
    _regime_labels: list[str] = []
    _roll_vol: list[float] = []
    _oi_stressed: list[bool] = []
    _funding_z: list[float] = []
    _liquidation_z: list[float] = []
    _depth_depleted: list[bool] = []
    _microstructure = _load_microstructure_series(snapshot, len(candles))
    if use_dynamic_slippage or use_realistic_slippage:
        closes = [float(c.close) for c in candles]
        oi_series = list(snapshot.open_interest)
        funding_series = list(snapshot.funding_rates)
        liquidation_series = list(snapshot.liquidation_notional)
        # Pad to length if needed
        while len(oi_series) < len(candles):
            oi_series.append(oi_series[-1] if oi_series else 0.0)
        while len(funding_series) < len(candles):
            funding_series.append(funding_series[-1] if funding_series else 0.0)
        while len(liquidation_series) < len(candles):
            liquidation_series.append(liquidation_series[-1] if liquidation_series else 0.0)
        # Rolling 30-bar std of close returns
        window = 30
        for i in range(len(closes)):
            start = max(0, i - window)
            win = closes[start : i + 1]
            if len(win) < 2:
                _roll_vol.append(0.01)  # min fallback
            else:
                bar_rets = [(win[j] - win[j - 1]) / max(win[j - 1], 1e-12) for j in range(1, len(win))]
                mean_r = sum(bar_rets) / len(bar_rets)
                var_r = sum((r - mean_r) ** 2 for r in bar_rets) / max(len(bar_rets) - 1, 1)
                _roll_vol.append(math.sqrt(max(var_r, 0.0)))
            _oi_stressed.append(compute_oi_stress_flag(oi_series, oi_series[i]))
        _funding_z = _compute_abs_zscores(funding_series)
        _liquidation_z = _compute_abs_zscores(liquidation_series)
        if _microstructure:
            bid_depth = _microstructure["depth_bid_1bp_usd"]
            ask_depth = _microstructure["depth_ask_1bp_usd"]
            depth_series = [min(bid_depth[i], ask_depth[i]) for i in range(len(candles))]
            _depth_depleted = _compute_low_percentile_flags(depth_series, percentile=10.0)
        else:
            _depth_depleted = [False] * len(candles)
        # Simple regime labels via threshold (avoids hmmlearn dep in hot path)
        from engine.validation.regimes import label_snapshot_regimes
        _regime_labels = label_snapshot_regimes(snapshot)

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
    trade_results: list[float] = []
    liquidation_events: list[str] = []
    fill_event_count = 0
    partial_fill_event_count = 0
    fill_ratio_sum = 0.0
    min_fill_ratio = 1.0
    adverse_fill_event_count = 0
    adverse_fill_bps_sum = 0.0
    max_adverse_fill_bps = 0.0
    funding_event_counts = _compute_funding_event_counts(candles, snapshot.venue)

    for index, candle in enumerate(candles):
        mark_to_market = _equity_mark()

        if position_open:
            unrealized_pnl = _price_delta(candle.close, entry_price, position_side) * position_size
            mark_to_market = _equity_mark(unrealized_pnl)
            # Per-bar funding: deduct ONLY the current bar's cost (realized immediately).
            # Do NOT subtract the cumulative `funding_spend` total — that would
            # double-count every prior bar's payment. Reference: Binance docs show
            # funding as an immediate cash debit, not an accrual.
            current_bar_funding = apply_funding(
                candle.close * position_size, snapshot.funding_rates[index], position_side
            ) * funding_event_counts[index]
            funding_spend += current_bar_funding
            mark_to_market = _equity_mark(unrealized_pnl)

            effective_maintenance_margin_ratio = _resolve_maintenance_margin_ratio(
                position_leverage,
                entry_price * position_size,
                maintenance_margin_ratio,
                maintenance_margin_schedule,
            )
            liquidation_price = _liquidation_price(
                entry_price,
                position_side,
                position_leverage,
                effective_maintenance_margin_ratio,
            )
            liquidation_trigger_price = _liquidation_trigger_price(
                candle,
                position_side,
                liquidation_mark_price_weight,
                liquidation_mark_premium_bps,
            )
            liquidation_triggered = (
                liquidation_trigger_price <= liquidation_price
                if position_side == "long"
                else liquidation_trigger_price >= liquidation_price
            )
            if liquidation_triggered and index >= entry_index and index > liquidation_cooldown_until:
                effective_liquidation_step_schedule, effective_partial_liquidation_ratio = _resolve_liquidation_step_behavior(
                    position_leverage=position_leverage,
                    position_notional=entry_price * position_size,
                    liquidation_style=resolved_liquidation_style,
                    profile_forces_full_liquidation=profile_forces_full_liquidation,
                    explicit_partial_liquidation_ratio=raw_partial_liquidation_ratio is not _UNSET,
                    explicit_liquidation_step_schedule=raw_liquidation_step_schedule is not _UNSET,
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
                    entry_price * position_size,
                    liquidation_fee_bps,
                    liquidation_fee_schedule,
                    "liquidation_fee_bps",
                )
                exit_cost = apply_trade_cost(
                    liquidation_price * liquidation_size,
                    snapshot.taker_fee_bps + effective_liquidation_fee_bps,
                    _resolve_slippage_bps(
                        trade_notional=liquidation_price * liquidation_size,
                        bar_index=index,
                        flat_slippage_bps=slippage_bps,
                        use_dynamic_slippage=use_dynamic_slippage,
                        use_realistic_slippage=use_realistic_slippage,
                        open_interest_series=snapshot.open_interest,
                        roll_vol=_roll_vol,
                        oi_stressed=_oi_stressed,
                        regime_labels=_regime_labels,
                        funding_z=_funding_z,
                        liquidation_z=_liquidation_z,
                        depth_depleted=_depth_depleted,
                        microstructure=_microstructure,
                    ),
                )
                fee_spend += exit_cost
                trade_gross = _price_delta(liquidation_price, entry_price, position_side) * liquidation_size
                trade_net = trade_gross - exit_cost
                gross_pnl += trade_gross
                trade_results.append(trade_net)
                trade_count += 1
                liquidation_events.append(
                    f"{candle.timestamp.isoformat()}:liquidation@{liquidation_price:.4f}:trigger={liquidation_trigger_price:.4f}:size={liquidation_size:.4f}"
                )
                position_size -= liquidation_size
                liquidation_cooldown_until = index + liquidation_cooldown_bars
                liquidation_step_index += 1
                if position_size <= 1e-9:
                    position_open = False
                    position_size = 0.0
                    entry_price = 0.0
                    entry_index = -1
                remaining_unrealized = 0.0
                if position_open:
                    remaining_unrealized = _price_delta(candle.close, entry_price, position_side) * position_size
                mark_to_market = _equity_mark(remaining_unrealized)
                equity_curve.append(mark_to_market)
                continue

        if not position_open and entry_signals[index]:
            fill_index = min(index + latency_bars, len(candles) - 1)
            reference_fill_price = candles[fill_index].close
            requested_position_size = float(position_leverage)
            entry_fill_ratio = _resolve_execution_fill_ratio(
                trade_notional=reference_fill_price * requested_position_size,
                bar_index=fill_index,
                use_realistic_slippage=use_realistic_slippage,
                microstructure=_microstructure,
                oi_stressed=_oi_stressed,
                funding_z=_funding_z,
                liquidation_z=_liquidation_z,
                depth_depleted=_depth_depleted,
            )
            executed_position_size = requested_position_size * entry_fill_ratio
            if executed_position_size <= 1e-9:
                equity_curve.append(mark_to_market)
                continue
            fill_event_count += 1
            fill_ratio_sum += entry_fill_ratio
            min_fill_ratio = min(min_fill_ratio, entry_fill_ratio)
            if entry_fill_ratio < 1.0 - 1e-9:
                partial_fill_event_count += 1
            eff_slippage_bps = _resolve_slippage_bps(
                trade_notional=reference_fill_price * executed_position_size,
                bar_index=fill_index,
                flat_slippage_bps=slippage_bps,
                use_dynamic_slippage=use_dynamic_slippage,
                use_realistic_slippage=use_realistic_slippage,
                open_interest_series=snapshot.open_interest,
                roll_vol=_roll_vol,
                oi_stressed=_oi_stressed,
                regime_labels=_regime_labels,
                funding_z=_funding_z,
                liquidation_z=_liquidation_z,
                depth_depleted=_depth_depleted,
                microstructure=_microstructure,
            )
            adverse_fill_bps = _resolve_execution_adverse_fill_bps(
                effective_slippage_bps=eff_slippage_bps,
                fill_ratio=entry_fill_ratio,
                bar_index=fill_index,
                use_realistic_slippage=use_realistic_slippage,
                oi_stressed=_oi_stressed,
                funding_z=_funding_z,
                liquidation_z=_liquidation_z,
                depth_depleted=_depth_depleted,
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
            # When adverse_fill_bps shifted the fill price, the slippage cost
            # is already embedded in the worse price.  Only add fee-based cost
            # here to avoid double-counting slippage.
            residual_slippage_bps = 0.0 if adverse_fill_bps > 0.0 else eff_slippage_bps
            entry_cost = apply_trade_cost(fill_price * executed_position_size, snapshot.taker_fee_bps, residual_slippage_bps)
            fee_spend += entry_cost
            position_open = True
            # position_size reflects gross notional multiplier: with 10x leverage
            # a 1% price move yields 10% return on margin (Prompt 5 research confirms
            # PnL, fees, and funding are ALL computed on gross notional).
            position_size = executed_position_size
            entry_price = fill_price
            entry_index = fill_index
            liquidation_step_index = 0
            mark_to_market = _equity_mark()

        elif position_open and exit_signals[index] and index >= entry_index:
            fill_index = min(index + latency_bars, len(candles) - 1)
            reference_fill_price = candles[fill_index].close
            exit_fill_ratio = _resolve_execution_fill_ratio(
                trade_notional=reference_fill_price * position_size,
                bar_index=fill_index,
                use_realistic_slippage=use_realistic_slippage,
                microstructure=_microstructure,
                oi_stressed=_oi_stressed,
                funding_z=_funding_z,
                liquidation_z=_liquidation_z,
                depth_depleted=_depth_depleted,
            )
            executed_exit_size = position_size * exit_fill_ratio
            if executed_exit_size <= 1e-9:
                equity_curve.append(mark_to_market)
                continue
            fill_event_count += 1
            fill_ratio_sum += exit_fill_ratio
            min_fill_ratio = min(min_fill_ratio, exit_fill_ratio)
            if exit_fill_ratio < 1.0 - 1e-9:
                partial_fill_event_count += 1
            eff_slippage_bps = _resolve_slippage_bps(
                trade_notional=reference_fill_price * executed_exit_size,
                bar_index=fill_index,
                flat_slippage_bps=slippage_bps,
                use_dynamic_slippage=use_dynamic_slippage,
                use_realistic_slippage=use_realistic_slippage,
                open_interest_series=snapshot.open_interest,
                roll_vol=_roll_vol,
                oi_stressed=_oi_stressed,
                regime_labels=_regime_labels,
                funding_z=_funding_z,
                liquidation_z=_liquidation_z,
                depth_depleted=_depth_depleted,
                microstructure=_microstructure,
            )
            adverse_fill_bps = _resolve_execution_adverse_fill_bps(
                effective_slippage_bps=eff_slippage_bps,
                fill_ratio=exit_fill_ratio,
                bar_index=fill_index,
                use_realistic_slippage=use_realistic_slippage,
                oi_stressed=_oi_stressed,
                funding_z=_funding_z,
                liquidation_z=_liquidation_z,
                depth_depleted=_depth_depleted,
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
            # Same double-count guard as entry: when the fill price was already
            # adversely shifted, do not add slippage again via the fee path.
            residual_slippage_bps = 0.0 if adverse_fill_bps > 0.0 else eff_slippage_bps
            exit_cost = apply_trade_cost(fill_price * executed_exit_size, snapshot.taker_fee_bps, residual_slippage_bps)
            fee_spend += exit_cost
            trade_gross = _price_delta(fill_price, entry_price, position_side) * executed_exit_size
            trade_net = trade_gross - exit_cost
            gross_pnl += trade_gross
            trade_results.append(trade_net)
            if trade_net > 0:
                winning_trades += 1
            trade_count += 1
            position_size -= executed_exit_size
            if position_size <= 1e-9:
                position_open = False
                position_size = 0.0
                entry_price = 0.0
                entry_index = -1
            mark_to_market = _equity_mark()

        equity_curve.append(mark_to_market)

    if position_open:
        fill_price = candles[-1].close
        last_idx = len(candles) - 1
        eff_slippage_bps = _resolve_slippage_bps(
            trade_notional=fill_price * position_size,
            bar_index=last_idx,
            flat_slippage_bps=slippage_bps,
            use_dynamic_slippage=use_dynamic_slippage,
            use_realistic_slippage=use_realistic_slippage,
            open_interest_series=snapshot.open_interest,
            roll_vol=_roll_vol,
            oi_stressed=_oi_stressed,
            regime_labels=_regime_labels,
            funding_z=_funding_z,
            liquidation_z=_liquidation_z,
            depth_depleted=_depth_depleted,
            microstructure=_microstructure,
        )
        exit_cost = apply_trade_cost(fill_price * position_size, snapshot.taker_fee_bps, eff_slippage_bps)
        fee_spend += exit_cost
        trade_gross = _price_delta(fill_price, entry_price, position_side) * position_size
        trade_net = trade_gross - exit_cost
        gross_pnl += trade_gross
        trade_results.append(trade_net)
        if trade_net > 0:
            winning_trades += 1
        trade_count += 1
        equity_curve[-1] = _equity_mark()

    net_pnl = gross_pnl - fee_spend - funding_spend
    execution_pressure_summary: dict[str, float | int] = {}
    if use_realistic_slippage and fill_event_count > 0:
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
    returns = [
        equity_curve[index] - equity_curve[index - 1]
        for index in range(1, len(equity_curve))
    ]
    ann = _annualization_factor(snapshot.timeframe)
    return BacktestResult(
        trade_count=trade_count,
        win_rate=(winning_trades / trade_count) if trade_count else 0.0,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        fee_spend=fee_spend,
        funding_spend=funding_spend,
        sharpe=sharpe_ratio(returns, annualization_factor=ann),
        sortino=sortino_ratio(returns, annualization_factor=ann),
        max_drawdown=max_drawdown(equity_curve),
        equity_curve=equity_curve,
        liquidation_events=liquidation_events,
        execution_pressure_summary=execution_pressure_summary,
    )


def _liquidation_price(
    entry_price: float,
    position_side: str,
    position_leverage: float,
    maintenance_margin_ratio: float,
) -> float:
    if position_side == "short":
        return entry_price * (1.0 + (1.0 / position_leverage) - maintenance_margin_ratio)
    return entry_price * (1.0 - (1.0 / position_leverage) + maintenance_margin_ratio)


def _liquidation_trigger_price(
    candle,
    position_side: str,
    liquidation_mark_price_weight: float,
    liquidation_mark_premium_bps: float,
) -> float:
    if position_side == "short":
        base_price = (candle.high * (1.0 - liquidation_mark_price_weight)) + (
            candle.close * liquidation_mark_price_weight
        )
        return base_price * (1.0 + (liquidation_mark_premium_bps / 10_000.0))
    base_price = (candle.low * (1.0 - liquidation_mark_price_weight)) + (
        candle.close * liquidation_mark_price_weight
    )
    return base_price * (1.0 - (liquidation_mark_premium_bps / 10_000.0))


def _price_delta(current_price: float, entry_price: float, position_side: str) -> float:
    if position_side == "short":
        return entry_price - current_price
    return current_price - entry_price


def _liquidation_ratio_for_event(
    liquidation_step_schedule: list[float] | None,
    partial_liquidation_ratio: float,
    liquidation_step_index: int,
) -> float:
    if liquidation_step_schedule:
        clamped_index = min(liquidation_step_index, len(liquidation_step_schedule) - 1)
        return liquidation_step_schedule[clamped_index]
    return partial_liquidation_ratio


def _resolve_liquidation_step_behavior(
    *,
    position_leverage: float,
    position_notional: float,
    liquidation_style: str,
    profile_forces_full_liquidation: bool,
    explicit_partial_liquidation_ratio: bool,
    explicit_liquidation_step_schedule: bool,
    default_partial_liquidation_ratio: float,
    default_liquidation_step_schedule: list[float] | None,
    maintenance_margin_schedule: list[dict[str, float]] | None,
) -> tuple[list[float] | None, float]:
    if profile_forces_full_liquidation:
        return None, 1.0
    if explicit_liquidation_step_schedule or explicit_partial_liquidation_ratio:
        return default_liquidation_step_schedule, default_partial_liquidation_ratio
    tier = _resolve_tier_entry(position_leverage, position_notional, maintenance_margin_schedule)
    if tier is None:
        return default_liquidation_step_schedule, default_partial_liquidation_ratio
    tier_schedule = tier.get("liquidation_step_schedule")
    if isinstance(tier_schedule, list) and tier_schedule:
        return [float(value) for value in tier_schedule], default_partial_liquidation_ratio
    tier_ratio = tier.get("partial_liquidation_ratio")
    if isinstance(tier_ratio, (int, float)):
        return default_liquidation_step_schedule, float(tier_ratio)
    return default_liquidation_step_schedule, default_partial_liquidation_ratio


def _resolve_slippage_bps(
    *,
    trade_notional: float,
    bar_index: int,
    flat_slippage_bps: float,
    use_dynamic_slippage: bool,
    use_realistic_slippage: bool,
    open_interest_series: list[float],
    roll_vol: list[float],
    oi_stressed: list[bool],
    regime_labels: list[str],
    funding_z: list[float],
    liquidation_z: list[float],
    depth_depleted: list[bool],
    microstructure: dict[str, list[float]] | None,
) -> float:
    if use_realistic_slippage and microstructure is not None:
        available_depth = min(
            microstructure["depth_bid_1bp_usd"][bar_index],
            microstructure["depth_ask_1bp_usd"][bar_index],
        )
        base_bps = impact_cost_bps(
            q_notional=trade_notional,
            available_depth_notional=available_depth,
            sigma_1h=roll_vol[bar_index],
            spread_bps=microstructure["spread_bps"][bar_index],
            latency_ms=microstructure["latency_proxy_ms"][bar_index],
            coeff=_REALISTIC_SLIPPAGE_COEFF,
        )
        return min(
            500.0,
            base_bps * _cascade_multiplier(
                oi_stressed=oi_stressed[bar_index],
                funding_z=funding_z[bar_index],
                liquidation_z=liquidation_z[bar_index],
                depth_depleted=depth_depleted[bar_index],
            ),
        )

    if use_dynamic_slippage or use_realistic_slippage:
        return compute_dynamic_slippage(
            trade_notional=trade_notional,
            volatility=roll_vol[bar_index],
            open_interest=open_interest_series[bar_index] if bar_index < len(open_interest_series) else 0.0,
            oi_is_stressed=oi_stressed[bar_index],
            stress_regime=regime_labels[bar_index] if bar_index < len(regime_labels) else "",
            flat_fallback_bps=flat_slippage_bps,
        )
    return flat_slippage_bps


def _resolve_execution_fill_ratio(
    *,
    trade_notional: float,
    bar_index: int,
    use_realistic_slippage: bool,
    microstructure: dict[str, list[float]] | None,
    oi_stressed: list[bool],
    funding_z: list[float],
    liquidation_z: list[float],
    depth_depleted: list[bool],
) -> float:
    if trade_notional <= 0.0 or not use_realistic_slippage or microstructure is None:
        return 1.0

    available_depth = min(
        microstructure["depth_bid_1bp_usd"][bar_index],
        microstructure["depth_ask_1bp_usd"][bar_index],
    )
    if available_depth <= 0.0:
        return 0.0

    depth_ratio = available_depth / max(trade_notional, 1e-9)
    cascade = _cascade_multiplier(
        oi_stressed=oi_stressed[bar_index],
        funding_z=funding_z[bar_index],
        liquidation_z=liquidation_z[bar_index],
        depth_depleted=depth_depleted[bar_index],
    )
    if depth_ratio >= 2.0 and cascade <= 1.25 and not depth_depleted[bar_index]:
        return 1.0

    fill_ratio = min(1.0, depth_ratio)
    if cascade > 1.0:
        fill_ratio /= cascade
    if depth_depleted[bar_index] and depth_ratio < 1.5:
        fill_ratio *= 0.85
    return max(0.05, min(1.0, fill_ratio))


def _resolve_execution_adverse_fill_bps(
    *,
    effective_slippage_bps: float,
    fill_ratio: float,
    bar_index: int,
    use_realistic_slippage: bool,
    oi_stressed: list[bool],
    funding_z: list[float],
    liquidation_z: list[float],
    depth_depleted: list[bool],
) -> float:
    if not use_realistic_slippage or effective_slippage_bps <= 0.0:
        return 0.0

    cascade = _cascade_multiplier(
        oi_stressed=oi_stressed[bar_index],
        funding_z=funding_z[bar_index],
        liquidation_z=liquidation_z[bar_index],
        depth_depleted=depth_depleted[bar_index],
    )
    fill_shortfall = max(0.0, 1.0 - fill_ratio)
    if fill_shortfall < 1e-3 and effective_slippage_bps < 25.0:
        return 0.0
    stress_pressure = fill_shortfall
    if depth_depleted[bar_index]:
        stress_pressure = max(stress_pressure, 0.10)
    if oi_stressed[bar_index]:
        stress_pressure += 0.05
    if abs(funding_z[bar_index]) > 2.0:
        stress_pressure += 0.05
    if liquidation_z[bar_index] > 2.0:
        stress_pressure += 0.05
    if cascade <= 1.0 and stress_pressure < 0.10:
        return 0.0

    adverse_bps = effective_slippage_bps * (0.20 + min(0.90, stress_pressure))
    if cascade > 1.0:
        adverse_bps *= min(1.50, cascade / 1.25)
    return min(150.0, max(0.0, adverse_bps))


def _apply_adverse_fill_price(
    fill_price: float,
    *,
    position_side: str,
    is_entry: bool,
    adverse_fill_bps: float,
) -> float:
    if adverse_fill_bps <= 0.0:
        return fill_price
    multiplier = adverse_fill_bps / 10_000.0
    if position_side == "long":
        return fill_price * (1.0 + multiplier) if is_entry else fill_price * (1.0 - multiplier)
    return fill_price * (1.0 - multiplier) if is_entry else fill_price * (1.0 + multiplier)


def _cascade_multiplier(
    *,
    oi_stressed: bool,
    funding_z: float,
    liquidation_z: float,
    depth_depleted: bool,
) -> float:
    signal_count = 0
    if oi_stressed:
        signal_count += 1
    if abs(funding_z) > 2.0:
        signal_count += 1
    if liquidation_z > 2.0:
        signal_count += 1
    if depth_depleted:
        signal_count += 1
    if signal_count >= 4:
        return 1.75
    if signal_count == 3:
        return 1.50
    if signal_count == 2:
        return 1.25
    return 1.0


def _load_microstructure_series(snapshot: DataSnapshot, length: int) -> dict[str, list[float]] | None:
    typed = _load_typed_microstructure_series(snapshot, length)
    if typed is not None:
        return typed

    micro = snapshot.provenance.get("microstructure")
    if not isinstance(micro, dict):
        return None

    required_keys = (
        "spread_bps",
        "depth_bid_1bp_usd",
        "depth_ask_1bp_usd",
        "latency_proxy_ms",
    )
    result: dict[str, list[float]] = {}
    for key in required_keys:
        values = micro.get(key)
        if not isinstance(values, list) or not values:
            return None
        result[key] = _normalize_numeric_series(values, length)
    return result


def _load_typed_microstructure_series(snapshot: DataSnapshot, length: int) -> dict[str, list[float]] | None:
    spread = getattr(snapshot, "spread_bps", [])
    depth_bid = getattr(snapshot, "depth_bid_1bp_usd", [])
    depth_ask = getattr(snapshot, "depth_ask_1bp_usd", [])
    latency = getattr(snapshot, "latency_proxy_ms", [])
    if not spread or not depth_bid or not depth_ask or not latency:
        return None
    return {
        "spread_bps": _normalize_numeric_series(spread, length),
        "depth_bid_1bp_usd": _normalize_numeric_series(depth_bid, length),
        "depth_ask_1bp_usd": _normalize_numeric_series(depth_ask, length),
        "latency_proxy_ms": _normalize_numeric_series(latency, length),
    }


def _normalize_numeric_series(values: list[Any], length: int) -> list[float]:
    normalized = [float(value) for value in values[:length]]
    while len(normalized) < length:
        normalized.append(normalized[-1] if normalized else 0.0)
    return normalized


def _compute_abs_zscores(values: list[float]) -> list[float]:
    """Expanding-window absolute z-scores — no look-ahead bias.

    Each bar's z-score uses only the mean and std of values seen up to that
    bar, so the simulator never uses future information to set current-bar
    slippage multipliers.
    """
    if not values:
        return []
    result: list[float] = []
    running_sum = 0.0
    running_sq_sum = 0.0
    for i, raw in enumerate(values):
        v = float(raw)
        running_sum += v
        running_sq_sum += v * v
        n = i + 1
        mean_val = running_sum / n
        if n < 2:
            result.append(0.0)
            continue
        variance = (running_sq_sum / n) - (mean_val * mean_val)
        std = math.sqrt(max(variance, 0.0))
        if std <= 1e-12:
            result.append(0.0)
        else:
            result.append(abs((v - mean_val) / std))
    return result


def _compute_low_percentile_flags(values: list[float], percentile: float) -> list[bool]:
    if not values:
        return []
    sorted_values = sorted(float(value) for value in values)
    n = len(sorted_values)
    rank = (percentile / 100.0) * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    frac = rank - lower
    threshold = sorted_values[lower] * (1.0 - frac) + sorted_values[upper] * frac
    return [float(value) <= threshold for value in values]


def _resolve_liquidation_defaults(
    *,
    snapshot: DataSnapshot,
    maintenance_margin_ratio: float | object,
    liquidation_fee_bps: float | object,
    liquidation_mark_price_weight: float | object,
    partial_liquidation_ratio: float | object,
    liquidation_cooldown_bars: int | object,
    liquidation_step_schedule: list[float] | None | object,
    liquidation_mark_premium_bps: float | object,
    maintenance_margin_schedule: list[dict[str, float]] | None | object,
    liquidation_fee_schedule: list[dict[str, float]] | None | object,
) -> tuple[
    float,
    float,
    float,
    float,
    int,
    list[float] | None,
    float,
    list[dict[str, float]] | None,
    list[dict[str, float]] | None,
]:
    profile = snapshot.venue_profile
    resolved_liquidation_style = _resolve_liquidation_style(
        snapshot=snapshot,
        partial_liquidation_ratio=partial_liquidation_ratio,
        liquidation_step_schedule=liquidation_step_schedule,
    )

    resolved_maintenance_margin_ratio = float(
        _DEFAULT_MAINTENANCE_MARGIN_RATIO
        if maintenance_margin_ratio is _UNSET
        else maintenance_margin_ratio
    )
    resolved_liquidation_fee_bps = float(
        _DEFAULT_LIQUIDATION_FEE_BPS
        if liquidation_fee_bps is _UNSET
        else liquidation_fee_bps
    )
    resolved_liquidation_mark_price_weight = float(
        profile.liquidation_mark_price_weight
        if liquidation_mark_price_weight is _UNSET and profile is not None
        else _DEFAULT_LIQUIDATION_MARK_PRICE_WEIGHT
        if liquidation_mark_price_weight is _UNSET
        else liquidation_mark_price_weight
    )
    resolved_partial_liquidation_ratio = float(
        profile.partial_liquidation_ratio
        if partial_liquidation_ratio is _UNSET and profile is not None
        else _DEFAULT_PARTIAL_LIQUIDATION_RATIO
        if partial_liquidation_ratio is _UNSET
        else partial_liquidation_ratio
    )
    resolved_liquidation_cooldown_bars = int(
        profile.liquidation_cooldown_bars
        if liquidation_cooldown_bars is _UNSET and profile is not None
        else _DEFAULT_LIQUIDATION_COOLDOWN_BARS
        if liquidation_cooldown_bars is _UNSET
        else liquidation_cooldown_bars
    )
    resolved_liquidation_step_schedule = (
        None
        if liquidation_step_schedule is _UNSET
        else liquidation_step_schedule
    )
    if resolved_liquidation_style == "full":
        resolved_partial_liquidation_ratio = 1.0
        resolved_liquidation_step_schedule = None
    resolved_liquidation_mark_premium_bps = float(
        profile.liquidation_mark_premium_bps
        if liquidation_mark_premium_bps is _UNSET and profile is not None
        else _DEFAULT_LIQUIDATION_MARK_PREMIUM_BPS
        if liquidation_mark_premium_bps is _UNSET
        else liquidation_mark_premium_bps
    )
    resolved_maintenance_margin_schedule = (
        list(profile.maintenance_margin_schedule)
        if maintenance_margin_schedule is _UNSET and profile is not None and profile.maintenance_margin_schedule
        else None
        if maintenance_margin_schedule is _UNSET
        else maintenance_margin_schedule
    )
    resolved_liquidation_fee_schedule = (
        list(profile.liquidation_fee_schedule)
        if liquidation_fee_schedule is _UNSET and profile is not None and profile.liquidation_fee_schedule
        else None
        if liquidation_fee_schedule is _UNSET
        else liquidation_fee_schedule
    )

    return (
        resolved_maintenance_margin_ratio,
        resolved_liquidation_fee_bps,
        resolved_liquidation_mark_price_weight,
        resolved_partial_liquidation_ratio,
        resolved_liquidation_cooldown_bars,
        resolved_liquidation_step_schedule,
        resolved_liquidation_mark_premium_bps,
        resolved_maintenance_margin_schedule,
        resolved_liquidation_fee_schedule,
    )


def _resolve_liquidation_style(
    *,
    snapshot: DataSnapshot,
    partial_liquidation_ratio: float | object,
    liquidation_step_schedule: list[float] | None | object,
) -> str:
    profile = snapshot.venue_profile
    profile_style = "full"
    if profile is not None:
        candidate = str(profile.liquidation_style).strip().lower()
        if candidate in {"full", "partial"}:
            profile_style = candidate

    explicit_partial_ratio = (
        partial_liquidation_ratio is not _UNSET
        and float(partial_liquidation_ratio) < 1.0
    )
    explicit_partial_schedule = (
        liquidation_step_schedule is not _UNSET
        and liquidation_step_schedule is not None
        and any(float(value) < 1.0 for value in liquidation_step_schedule)
    )
    if explicit_partial_ratio or explicit_partial_schedule:
        return "partial"
    return profile_style


def _resolve_maintenance_margin_ratio(
    position_leverage: float,
    position_notional: float,
    maintenance_margin_ratio: float,
    maintenance_margin_schedule: list[dict[str, float]] | None,
) -> float:
    return _resolve_tier_value(
        position_leverage,
        position_notional,
        maintenance_margin_ratio,
        maintenance_margin_schedule,
        "maintenance_margin_ratio",
    )


def _resolve_tier_value(
    position_leverage: float,
    position_notional: float,
    default_value: float,
    schedule: list[dict[str, float]] | None,
    value_key: str,
) -> float:
    tier = _resolve_tier_entry(position_leverage, position_notional, schedule)
    if tier is None:
        return default_value
    return float(tier[value_key])


def _resolve_tier_entry(
    position_leverage: float,
    position_notional: float,
    schedule: list[dict[str, float]] | None,
) -> dict[str, float] | None:
    if not schedule:
        return None
    tiers = sorted(
        schedule,
        key=lambda item: (
            float(item.get("max_leverage", float("inf"))),
            float(item.get("max_notional", float("inf"))),
        ),
    )
    for tier in tiers:
        max_leverage = float(tier["max_leverage"]) if "max_leverage" in tier else float("inf")
        max_notional = float(tier["max_notional"]) if "max_notional" in tier else float("inf")
        if position_leverage <= max_leverage and position_notional <= max_notional:
            return tier
    return tiers[-1]
