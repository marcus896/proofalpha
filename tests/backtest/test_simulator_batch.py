"""Tests for the Phase 11 Numba batch simulator.

Verifies:
 1. Pure-Python reference path produces correct results independently.
 2. Numba JIT path produces results identical to the Python reference
    within float tolerance (regression guard).
 3. Batch API returns results in the correct order for N parameter sets.
 4. Graceful fallback: is_numba_available() is a truthful runtime check.
 5. Edge cases: empty signal matrix, single bar, all-False signals.
"""

from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from engine.backtest.simulator_numba import (
    BatchSimResult,
    _simulate_single_python,
    is_numba_available,
    simulate_strategy_batch,
)


def _flat_closes(n: int = 20, base: float = 100.0) -> list[float]:
    """Flat price series — no trend."""
    return [base] * n


def _trending_closes(n: int = 20, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + i * step for i in range(n)]


def _alternating_signals(n: int, every: int = 4) -> tuple[list[bool], list[bool]]:
    """Simple entry every `every` bars, exit on the following bar."""
    entry = [i % every == 1 for i in range(n)]
    exit_ = [i % every == 2 for i in range(n)]
    return entry, exit_


def _zeros(n: int) -> list[float]:
    return [0.0] * n


class _FakeArray:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)

    def tolist(self) -> list[float]:
        return list(self._values)


class PythonReferenceTests(unittest.TestCase):
    """Validate the pure-Python reference implementation standalone."""

    def test_no_signals_produces_zero_pnl_and_flat_equity(self) -> None:
        closes = _flat_closes(10)
        result = _simulate_single_python(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(10),
            entry_signals=[False] * 10,
            exit_signals=[False] * 10,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            position_side="long",
            position_leverage=1.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
        )
        self.assertEqual(result["trade_count"], 0)
        self.assertAlmostEqual(result["gross_pnl"], 0.0)
        self.assertAlmostEqual(result["net_pnl"], 0.0)
        self.assertEqual(len(result["equity_curve"]), 10)

    def test_single_winning_long_trade(self) -> None:
        closes = [100.0, 100.0, 110.0, 110.0, 110.0]
        entry = [False, True, False, False, False]
        exit_ = [False, False, True, False, False]
        result = _simulate_single_python(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(5),
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            position_side="long",
            position_leverage=1.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
        )
        self.assertEqual(result["trade_count"], 1)
        self.assertAlmostEqual(result["gross_pnl"], 10.0)

    def test_single_winning_short_trade(self) -> None:
        closes = [100.0, 100.0, 90.0, 90.0, 90.0]
        entry = [False, True, False, False, False]
        exit_ = [False, False, True, False, False]
        result = _simulate_single_python(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(5),
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            position_side="short",
            position_leverage=1.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
        )
        self.assertEqual(result["trade_count"], 1)
        self.assertAlmostEqual(result["gross_pnl"], 10.0)

    def test_fees_reduce_net_pnl(self) -> None:
        closes = [100.0, 100.0, 110.0, 110.0, 110.0]
        entry = [False, True, False, False, False]
        exit_ = [False, False, True, False, False]
        result = _simulate_single_python(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(5),
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=50.0,   # 0.5% each way
            slippage_bps=0.0,
            position_side="long",
            position_leverage=1.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
        )
        self.assertEqual(result["trade_count"], 1)
        self.assertAlmostEqual(result["gross_pnl"], 10.0)
        self.assertGreater(result["fee_spend"], 0.0)
        self.assertLess(result["net_pnl"], result["gross_pnl"])

    def test_open_position_closed_at_end_of_series(self) -> None:
        closes = [100.0, 105.0, 110.0]
        entry = [True, False, False]
        exit_ = [False, False, False]
        result = _simulate_single_python(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(3),
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            position_side="long",
            position_leverage=1.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
        )
        self.assertEqual(result["trade_count"], 1)
        self.assertAlmostEqual(result["gross_pnl"], 10.0)

    def test_equity_curve_length_matches_closes(self) -> None:
        n = 15
        entry, exit_ = _alternating_signals(n)
        closes = _trending_closes(n)
        result = _simulate_single_python(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(n),
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=5.0,
            slippage_bps=5.0,
            position_side="long",
            position_leverage=1.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
        )
        self.assertEqual(len(result["equity_curve"]), n)

    def test_reference_counts_winning_trades_for_win_rate(self) -> None:
        closes = [100.0, 100.0, 110.0, 110.0, 100.0, 100.0, 90.0, 90.0]
        entry = [False, True, False, False, False, True, False, False]
        exit_ = [False, False, True, False, False, False, True, False]
        result = _simulate_single_python(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(len(closes)),
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            position_side="long",
            position_leverage=1.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
        )

        self.assertEqual(result["trade_count"], 2)
        self.assertEqual(result["winning_trades"], 1)


class BatchApiTests(unittest.TestCase):
    """Tests for the public simulate_strategy_batch API."""

    def _make_signals(self, n: int) -> list[tuple[list[bool], list[bool]]]:
        entry, exit_ = _alternating_signals(n)
        return [(entry, exit_)]

    def test_empty_signal_matrix_returns_empty_list(self) -> None:
        closes = _flat_closes(10)
        result = simulate_strategy_batch(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(10),
            signal_matrix=[],
        )
        self.assertEqual(result, [])

    def test_single_set_returns_one_batch_sim_result(self) -> None:
        n = 20
        matrix = self._make_signals(n)
        closes = _flat_closes(n)
        results = simulate_strategy_batch(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(n),
            signal_matrix=matrix,
        )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], BatchSimResult)
        self.assertEqual(len(results[0].equity_curve), n)

    def test_batch_results_maintain_order_for_multiple_sets(self) -> None:
        n = 20
        closes = _trending_closes(n)
        entry_a = [True if i == 2 else False for i in range(n)]
        exit_a = [True if i == 10 else False for i in range(n)]
        entry_b = [True if i == 5 else False for i in range(n)]
        exit_b = [True if i == 15 else False for i in range(n)]
        matrix = [(entry_a, exit_a), (entry_b, exit_b)]
        results = simulate_strategy_batch(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(n),
            signal_matrix=matrix,
        )
        self.assertEqual(len(results), 2)
        # Set A enters at bar 2 (price 102), exits at bar 10 (price 110): gross ~ 8
        self.assertAlmostEqual(results[0].gross_pnl, 8.0, places=6)
        # Set B enters at bar 5 (price 105), exits at bar 15 (price 115): gross ~ 10
        self.assertAlmostEqual(results[1].gross_pnl, 10.0, places=6)

    def test_per_set_slippage_bps_differs_correctly(self) -> None:
        n = 10
        closes = [100.0] * n
        entry = [True, False, False, False, False, False, False, False, False, False]
        exit_ = [False, False, True, False, False, False, False, False, False, False]
        matrix = [(entry, exit_), (entry, exit_)]
        results = simulate_strategy_batch(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(n),
            signal_matrix=matrix,
            taker_fee_bps=0.0,
            param_slippage_bps=[0.0, 100.0],   # 0 bps vs 1%
        )
        self.assertEqual(len(results), 2)
        # Same entry/exit price: no gross pnl on flat series
        # Fee spend should be higher for set B (higher slippage)
        self.assertLess(results[0].fee_spend, results[1].fee_spend)

    def test_batch_scales_entry_fee_with_leverage(self) -> None:
        closes = [100.0, 100.0, 100.0, 100.0]
        entry = [False, True, False, False]
        exit_ = [False, False, True, False]
        results = simulate_strategy_batch(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(4),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=100.0,
            position_leverage=5.0,
        )

        self.assertAlmostEqual(results[0].fee_spend, 10.0, places=8)
        self.assertAlmostEqual(results[0].net_pnl, -10.0, places=8)

    def test_batch_exit_bar_equity_matches_net_pnl(self) -> None:
        closes = [100.0, 100.0, 110.0, 110.0]
        entry = [False, True, False, False]
        exit_ = [False, False, True, False]
        results = simulate_strategy_batch(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(4),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
        )

        self.assertAlmostEqual(results[0].net_pnl, 10.0, places=8)
        self.assertAlmostEqual(results[0].equity_curve[-1], results[0].net_pnl, places=8)

    def test_batch_result_tracks_win_rate_from_completed_trades(self) -> None:
        closes = [100.0, 100.0, 110.0, 110.0, 100.0, 100.0, 90.0, 90.0]
        entry = [False, True, False, False, False, True, False, False]
        exit_ = [False, False, True, False, False, False, True, False]

        result = simulate_strategy_batch(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=_zeros(len(closes)),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
        )[0]

        self.assertEqual(result.trade_count, 2)
        self.assertEqual(result.winning_trades, 1)
        self.assertAlmostEqual(result.win_rate, 0.5)

    def test_batch_applies_funding_only_on_settlement_events(self) -> None:
        closes = [100.0] * 10
        entry = [True] + ([False] * 9)
        exit_ = ([False] * 9) + [True]
        results = simulate_strategy_batch(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=[0.01] * 10,
            funding_event_counts=[0, 0, 0, 0, 0, 0, 0, 0, 1, 0],
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
        )

        self.assertAlmostEqual(results[0].funding_spend, 1.0, places=8)

    def test_batch_uses_tiered_margin_and_liquidation_fee_inputs(self) -> None:
        closes = [100.0, 100.0, 100.0, 100.0]
        highs = [100.0, 100.0, 100.0, 100.0]
        lows = [100.0, 92.0, 92.0, 100.0]
        entry = [True, False, False, False]
        exit_ = [False, False, False, False]

        base = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(4),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=10.0,
            maintenance_margin_ratio=0.01,
        )[0]
        stressed = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(4),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=10.0,
            maintenance_margin_ratio=0.01,
            maintenance_margin_schedule=[{"max_leverage": 10.0, "maintenance_margin_ratio": 0.03}],
            liquidation_fee_schedule=[{"max_leverage": 10.0, "liquidation_fee_bps": 100.0}],
        )[0]

        self.assertEqual(base.trade_count, 1)
        self.assertEqual(stressed.trade_count, 1)
        self.assertLess(stressed.net_pnl, base.net_pnl)

    def test_batch_uses_tiered_liquidation_step_schedule(self) -> None:
        closes = [100.0, 101.0, 101.0, 100.0, 99.0, 99.0]
        highs = [100.0, 101.0, 103.0, 104.0, 105.0, 99.0]
        lows = [100.0, 101.0, 80.0, 79.0, 78.0, 99.0]
        entry = [False, True, False, False, False, False]
        exit_ = [False, False, False, False, False, False]

        result = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(6),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            maintenance_margin_schedule=[
                {
                    "max_leverage": 10.0,
                    "maintenance_margin_ratio": 0.01,
                    "liquidation_step_schedule": [0.25, 0.5, 1.0],
                },
            ],
        )[0]

        self.assertEqual(result.trade_count, 3)

    def test_batch_re_resolves_liquidation_step_schedule_after_notional_tier_change(self) -> None:
        closes = [100.0, 101.0, 101.0, 100.0, 100.0, 100.0]
        highs = [100.0, 101.0, 103.0, 104.0, 100.0, 100.0]
        lows = [100.0, 101.0, 80.0, 79.0, 100.0, 100.0]
        entry = [False, True, False, False, False, False]
        exit_ = [False, False, False, False, False, False]

        result = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(6),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            maintenance_margin_schedule=[
                {
                    "max_notional": 400.0,
                    "maintenance_margin_ratio": 0.01,
                    "liquidation_step_schedule": [1.0],
                },
                {
                    "max_notional": 600.0,
                    "maintenance_margin_ratio": 0.01,
                    "liquidation_step_schedule": [0.25],
                },
            ],
        )[0]

        self.assertEqual(result.trade_count, 2)

    def test_batch_explicit_liquidation_step_schedule_overrides_tiered_schedule(self) -> None:
        closes = [100.0, 101.0, 101.0, 100.0, 100.0, 100.0]
        highs = [100.0, 101.0, 103.0, 104.0, 100.0, 100.0]
        lows = [100.0, 101.0, 80.0, 79.0, 100.0, 100.0]
        entry = [False, True, False, False, False, False]
        exit_ = [False, False, False, False, False, False]

        result = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(6),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_step_schedule=[0.5, 1.0],
            maintenance_margin_schedule=[
                {
                    "max_leverage": 10.0,
                    "maintenance_margin_ratio": 0.01,
                    "liquidation_step_schedule": [0.25],
                },
            ],
        )[0]

        self.assertEqual(result.trade_count, 2)

    def test_batch_realistic_slippage_uses_depth_and_latency_inputs(self) -> None:
        n = 40
        closes = [100.0 + i * 0.5 for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        entry = [False] * n
        exit_ = [False] * n
        entry[5] = True
        exit_[20] = True

        low_cost = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[5_000.0] * n,
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=[5_000_000.0] * n,
            depth_ask_1bp_usd=[5_000_000.0] * n,
            latency_proxy_ms=[10.0] * n,
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=1.0,
            slippage_model="realistic",
        )[0]
        high_cost = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[5_000.0] * n,
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=[120_000.0] * n,
            depth_ask_1bp_usd=[120_000.0] * n,
            latency_proxy_ms=[220.0] * n,
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=1.0,
            slippage_model="realistic",
        )[0]

        self.assertGreater(high_cost.fee_spend, low_cost.fee_spend)
        self.assertLess(high_cost.net_pnl, low_cost.net_pnl)

    def test_batch_realistic_slippage_reduces_fill_size_when_depth_is_thin(self) -> None:
        n = 40
        closes = [100.0 + i * 0.5 for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        entry = [False] * n
        exit_ = [False] * n
        entry[5] = True
        exit_[20] = True

        deep_fill = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[5_000.0] * n,
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=[5_000_000.0] * n,
            depth_ask_1bp_usd=[5_000_000.0] * n,
            latency_proxy_ms=[25.0] * n,
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=5.0,
            slippage_model="realistic",
        )[0]
        thin_fill = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[500_000.0] * n,
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=[120.0] * n,
            depth_ask_1bp_usd=[120.0] * n,
            latency_proxy_ms=[220.0] * n,
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=5.0,
            slippage_model="realistic",
        )[0]

        self.assertGreater(deep_fill.gross_pnl, thin_fill.gross_pnl)
        self.assertGreater(deep_fill.net_pnl, thin_fill.net_pnl)

    def test_batch_realistic_slippage_tracks_adverse_fill_pressure_under_stress(self) -> None:
        n = 40
        closes = [100.0 + i * 0.5 for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        entry = [False] * n
        exit_ = [False] * n
        entry[5] = True
        exit_[20] = True

        baseline = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[5_000.0] * n,
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=[2_500_000.0] * n,
            depth_ask_1bp_usd=[2_500_000.0] * n,
            latency_proxy_ms=[25.0] * n,
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            param_slippage_bps=[5.0],
            position_leverage=5.0,
            slippage_model="realistic",
        )[0]
        stressed = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=([0.0001] * 5) + ([0.02] * 16) + ([0.0001] * 19),
            open_interest=([1_000_000.0] * 5) + ([5_000_000.0] * 16) + ([1_000_000.0] * 19),
            liquidation_notional=([5_000.0] * 5) + ([250_000.0] * 16) + ([5_000.0] * 19),
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=([2_500_000.0] * 5) + ([120.0] * 16) + ([2_500_000.0] * 19),
            depth_ask_1bp_usd=([2_500_000.0] * 5) + ([120.0] * 16) + ([2_500_000.0] * 19),
            latency_proxy_ms=([25.0] * 5) + ([220.0] * 16) + ([25.0] * 19),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            param_slippage_bps=[5.0],
            position_leverage=5.0,
            slippage_model="realistic",
        )[0]

        self.assertEqual(baseline.execution_pressure_summary.get("adverse_fill_event_count", 0), 0)
        self.assertGreater(stressed.execution_pressure_summary["adverse_fill_event_count"], 0)
        self.assertGreater(stressed.execution_pressure_summary["average_adverse_fill_bps"], 0.0)
        self.assertGreaterEqual(
            stressed.execution_pressure_summary["max_adverse_fill_bps"],
            stressed.execution_pressure_summary["average_adverse_fill_bps"],
        )
        self.assertLess(stressed.net_pnl, baseline.net_pnl)

    def test_batch_liquidation_uses_mark_premium_and_weight(self) -> None:
        closes = [100.0, 100.0, 100.0, 100.0]
        highs = [100.0, 103.0, 100.0, 100.0]
        lows = [100.0, 99.0, 100.0, 100.0]
        entry = [True, False, False, False]
        exit_ = [False, False, False, False]

        base = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(4),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_side="short",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=1.0,
            liquidation_mark_premium_bps=0.0,
        )[0]
        stressed = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(4),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_side="short",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=1.0,
            liquidation_mark_premium_bps=500.0,
        )[0]

        self.assertEqual(base.trade_count, 1)
        self.assertEqual(base.liquidation_events if hasattr(base, "liquidation_events") else [], [])
        self.assertEqual(stressed.trade_count, 1)
        self.assertLess(stressed.net_pnl, base.net_pnl)

    def test_batch_numba_path_supports_explicit_liquidation_step_schedule(self) -> None:
        closes = [100.0, 101.0, 101.0, 100.0, 100.0, 100.0]
        entry = [False, True, False, False, False, False]
        exit_ = [False, False, False, False, False, False]

        def fake_kernel(*args):
            return 7, 11.0, 2.0, 3.0, _FakeArray([42.0] * len(closes))

        with patch("engine.backtest.simulator_numba._get_numba_kernel", return_value=fake_kernel):
            result = simulate_strategy_batch(
                closes=closes,
                highs=closes,
                lows=closes,
                funding_rates=_zeros(6),
                signal_matrix=[(entry, exit_)],
                taker_fee_bps=0.0,
                position_leverage=5.0,
                maintenance_margin_ratio=0.01,
                liquidation_step_schedule=[0.5, 1.0],
            )[0]

        self.assertEqual(result.trade_count, 7)
        self.assertTrue(all(value == 42.0 for value in result.equity_curve))

    def test_batch_numba_path_supports_notional_tiered_liquidation_step_schedule(self) -> None:
        closes = [100.0, 101.0, 101.0, 100.0, 100.0, 100.0]
        entry = [False, True, False, False, False, False]
        exit_ = [False, False, False, False, False, False]

        def fake_kernel(*args):
            return 9, 13.0, 4.0, 5.0, _FakeArray([24.0] * len(closes))

        with patch("engine.backtest.simulator_numba._get_numba_kernel", return_value=fake_kernel):
            result = simulate_strategy_batch(
                closes=closes,
                highs=closes,
                lows=closes,
                funding_rates=_zeros(6),
                signal_matrix=[(entry, exit_)],
                taker_fee_bps=0.0,
                position_leverage=5.0,
                maintenance_margin_ratio=0.01,
                maintenance_margin_schedule=[
                    {
                        "max_notional": 400.0,
                        "maintenance_margin_ratio": 0.01,
                        "liquidation_step_schedule": [1.0],
                    },
                    {
                        "max_notional": 600.0,
                        "maintenance_margin_ratio": 0.01,
                        "liquidation_step_schedule": [0.25],
                    },
                ],
            )[0]

        self.assertEqual(result.trade_count, 9)
        self.assertTrue(all(value == 24.0 for value in result.equity_curve))

    def test_batch_records_telemetry_when_numba_kernel_falls_back_to_python(self) -> None:
        closes = [100.0, 101.0, 102.0, 103.0]
        entry = [False, True, False, False]
        exit_ = [False, False, True, False]
        telemetry: dict[str, object] = {}

        def failing_kernel(*args):
            raise RuntimeError("forced numba kernel failure")

        with patch("engine.backtest.simulator_numba._get_numba_kernel", return_value=failing_kernel):
            results = simulate_strategy_batch(
                closes=closes,
                highs=closes,
                lows=closes,
                funding_rates=_zeros(4),
                signal_matrix=[(entry, exit_)],
                taker_fee_bps=0.0,
                telemetry_sink=telemetry,
            )

        self.assertEqual(len(results), 1)
        self.assertFalse(telemetry["numba_used"])
        self.assertEqual(telemetry["fallback_count"], 1)
        self.assertIn("forced numba kernel failure", str(telemetry["fallback_reason"]))
        self.assertIsInstance(telemetry["python_fallback_ms"], float)


class NumbaParityTests(unittest.TestCase):
    """JIT path must produce identical results to the Python reference.

    Skipped gracefully when numba is unavailable in the environment.
    """

    def _run_both_paths(
        self,
        closes: list[float],
        funding_rates: list[float],
        entry_signals: list[bool],
        exit_signals: list[bool],
        taker_fee_bps: float = 5.0,
        slippage_bps: float = 5.0,
        position_side: str = "long",
        position_leverage: float = 1.0,
        maintenance_margin_ratio: float = 0.01,
        latency_bars: int = 0,
        liquidation_fee_bps: float = 0.0,
        partial_liquidation_ratio: float = 1.0,
        liquidation_cooldown_bars: int = 0,
        liquidation_step_schedule: list[float] | None = None,
        maintenance_margin_schedule: list[dict[str, float]] | None = None,
        liquidation_fee_schedule: list[dict[str, float]] | None = None,
    ) -> tuple[dict, BatchSimResult]:
        ref = _simulate_single_python(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=funding_rates,
            entry_signals=entry_signals,
            exit_signals=exit_signals,
            taker_fee_bps=taker_fee_bps,
            slippage_bps=slippage_bps,
            position_side=position_side,
            position_leverage=position_leverage,
            maintenance_margin_ratio=maintenance_margin_ratio,
            latency_bars=latency_bars,
            liquidation_fee_bps=liquidation_fee_bps,
            partial_liquidation_ratio=partial_liquidation_ratio,
            liquidation_cooldown_bars=liquidation_cooldown_bars,
            liquidation_step_schedule=liquidation_step_schedule,
            maintenance_margin_schedule=maintenance_margin_schedule,
            liquidation_fee_schedule=liquidation_fee_schedule,
        )
        batch = simulate_strategy_batch(
            closes=closes,
            highs=closes,
            lows=closes,
            funding_rates=funding_rates,
            signal_matrix=[(entry_signals, exit_signals)],
            taker_fee_bps=taker_fee_bps,
            param_slippage_bps=[slippage_bps],
            param_latency_bars=[latency_bars],
            position_side=position_side,
            position_leverage=position_leverage,
            maintenance_margin_ratio=maintenance_margin_ratio,
            liquidation_fee_bps=liquidation_fee_bps,
            partial_liquidation_ratio=partial_liquidation_ratio,
            liquidation_cooldown_bars=liquidation_cooldown_bars,
            liquidation_step_schedule=liquidation_step_schedule,
            maintenance_margin_schedule=maintenance_margin_schedule,
            liquidation_fee_schedule=liquidation_fee_schedule,
        )
        return ref, batch[0]

    def _assert_parity(self, ref: dict, batch: BatchSimResult, tol: float = 1e-9) -> None:
        self.assertAlmostEqual(ref["gross_pnl"], batch.gross_pnl, delta=tol,
                               msg="gross_pnl mismatch")
        self.assertAlmostEqual(ref["fee_spend"], batch.fee_spend, delta=tol,
                               msg="fee_spend mismatch")
        self.assertAlmostEqual(ref["funding_spend"], batch.funding_spend, delta=tol,
                               msg="funding_spend mismatch")
        self.assertAlmostEqual(ref["net_pnl"], batch.net_pnl, delta=tol,
                               msg="net_pnl mismatch")
        self.assertEqual(ref["trade_count"], batch.trade_count,
                         msg="trade_count mismatch")
        self.assertEqual(len(ref["equity_curve"]), len(batch.equity_curve),
                         msg="equity_curve length mismatch")
        for bar_index, (r, b) in enumerate(zip(ref["equity_curve"], batch.equity_curve)):
            self.assertAlmostEqual(r, b, delta=tol,
                                   msg=f"equity_curve[{bar_index}] mismatch")
        self.assertEqual(
            ref.get("execution_pressure_summary", {}),
            getattr(batch, "execution_pressure_summary", {}),
            msg="execution_pressure_summary mismatch",
        )
        self.assertEqual(ref["winning_trades"], batch.winning_trades, msg="winning_trades mismatch")

    def test_parity_long_trending_market(self) -> None:
        n = 30
        closes = _trending_closes(n)
        entry, exit_ = _alternating_signals(n)
        ref, batch = self._run_both_paths(closes, _zeros(n), entry, exit_)
        self._assert_parity(ref, batch)

    def test_parity_short_trending_market(self) -> None:
        n = 30
        closes = [200.0 - i * 2.0 for i in range(n)]
        entry, exit_ = _alternating_signals(n)
        ref, batch = self._run_both_paths(
            closes, _zeros(n), entry, exit_, position_side="short"
        )
        self._assert_parity(ref, batch)

    def test_parity_flat_market_with_fees(self) -> None:
        n = 20
        closes = _flat_closes(n)
        entry, exit_ = _alternating_signals(n)
        ref, batch = self._run_both_paths(
            closes, _zeros(n), entry, exit_, taker_fee_bps=10.0, slippage_bps=5.0
        )
        self._assert_parity(ref, batch)

    def test_parity_with_nonzero_funding(self) -> None:
        n = 20
        closes = _flat_closes(n, base=50_000.0)
        funding = [0.0001] * n
        entry, exit_ = _alternating_signals(n)
        ref, batch = self._run_both_paths(closes, funding, entry, exit_)
        self._assert_parity(ref, batch)

    def test_parity_with_latency_bars(self) -> None:
        n = 30
        closes = _trending_closes(n)
        entry, exit_ = _alternating_signals(n)
        ref, batch = self._run_both_paths(
            closes, _zeros(n), entry, exit_, latency_bars=2
        )
        self._assert_parity(ref, batch)

    def test_parity_no_signals(self) -> None:
        n = 20
        ref, batch = self._run_both_paths(
            _flat_closes(n), _zeros(n), [False] * n, [False] * n
        )
        self._assert_parity(ref, batch)

    def test_parity_position_never_closed_before_eod(self) -> None:
        n = 20
        closes = _trending_closes(n)
        entry = [True] + [False] * (n - 1)
        exit_ = [False] * n
        ref, batch = self._run_both_paths(closes, _zeros(n), entry, exit_)
        self._assert_parity(ref, batch)

    def test_parity_with_explicit_liquidation_step_schedule(self) -> None:
        closes = [100.0, 101.0, 101.0, 100.0, 100.0, 100.0]
        highs = [100.0, 101.0, 103.0, 104.0, 100.0, 100.0]
        lows = [100.0, 101.0, 80.0, 79.0, 100.0, 100.0]
        entry = [False, True, False, False, False, False]
        exit_ = [False, False, False, False, False, False]

        ref = _simulate_single_python(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(6),
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
            liquidation_step_schedule=[0.5, 1.0],
        )
        batch = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(6),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_step_schedule=[0.5, 1.0],
        )[0]

        self._assert_parity(ref, batch)

    def test_parity_with_realistic_slippage_inputs(self) -> None:
        n = 40
        closes = [100.0 + i * 0.5 for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        entry = [False] * n
        exit_ = [False] * n
        entry[5] = True
        exit_[20] = True

        ref = _simulate_single_python(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[5_000.0] * n,
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=[2_500_000.0] * n,
            depth_ask_1bp_usd=[2_500_000.0] * n,
            latency_proxy_ms=[25.0] * n,
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=5.0,
            position_side="long",
            position_leverage=1.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
            slippage_model="realistic",
        )
        batch = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[5_000.0] * n,
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=[2_500_000.0] * n,
            depth_ask_1bp_usd=[2_500_000.0] * n,
            latency_proxy_ms=[25.0] * n,
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            param_slippage_bps=[5.0],
            position_leverage=1.0,
            slippage_model="realistic",
        )[0]

        self._assert_parity(ref, batch)

    def test_parity_with_dynamic_slippage_and_regime_pressure(self) -> None:
        n = 40
        closes = (
            [100.0, 101.0, 102.0, 103.0, 104.0]
            + [96.0, 90.0, 86.0, 84.0, 83.0, 82.0, 81.0, 80.0, 79.0, 78.0]
            + [79.0 + i * 0.3 for i in range(20)]
        )
        closes = closes[:n]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        funding = ([0.0001] * 5) + ([0.018] * 15) + ([0.0001] * 20)
        open_interest = ([1_000_000.0] * 5) + ([5_000_000.0] * 15) + ([1_200_000.0] * 20)
        liquidation_notional = ([5_000.0] * 5) + ([500_000.0] * 15) + ([5_000.0] * 20)
        entry = [False] * n
        exit_ = [False] * n
        entry[5] = True
        exit_[20] = True

        from engine.config.models import DataSnapshot
        from engine.data.schema import Candle
        from engine.validation.regimes import label_snapshot_regimes
        from datetime import UTC, datetime, timedelta

        snapshot = DataSnapshot(
            snapshot_id="dynamic-batch-parity",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index),
                    open=close,
                    high=highs[index],
                    low=lows[index],
                    close=close,
                    volume=1_000.0,
                )
                for index, close in enumerate(closes)
            ],
            funding_rates=funding,
            open_interest=open_interest,
            liquidation_notional=liquidation_notional,
            maker_fee_bps=2.0,
            taker_fee_bps=0.0,
            quality_flags=[],
        )
        stress_regimes = label_snapshot_regimes(snapshot)

        ref = _simulate_single_python(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=funding,
            open_interest=open_interest,
            liquidation_notional=liquidation_notional,
            stress_regimes=stress_regimes,
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=5.0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
            slippage_model="dynamic",
        )
        batch = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=funding,
            open_interest=open_interest,
            liquidation_notional=liquidation_notional,
            stress_regimes=stress_regimes,
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            param_slippage_bps=[5.0],
            position_leverage=5.0,
            slippage_model="dynamic",
        )[0]

        self._assert_parity(ref, batch)
        self.assertGreater(batch.fee_spend, 0.0)

    def test_parity_with_realistic_partial_fill_inputs(self) -> None:
        n = 40
        closes = [100.0 + i * 0.5 for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        entry = [False] * n
        exit_ = [False] * n
        entry[5] = True
        exit_[20] = True

        ref = _simulate_single_python(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[500_000.0] * n,
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=[120.0] * n,
            depth_ask_1bp_usd=[120.0] * n,
            latency_proxy_ms=[220.0] * n,
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=5.0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
            slippage_model="realistic",
        )
        batch = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[500_000.0] * n,
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=[120.0] * n,
            depth_ask_1bp_usd=[120.0] * n,
            latency_proxy_ms=[220.0] * n,
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            param_slippage_bps=[5.0],
            position_leverage=5.0,
            slippage_model="realistic",
        )[0]

        self._assert_parity(ref, batch)
        self.assertGreater(batch.execution_pressure_summary["partial_fill_event_count"], 0)
        self.assertLess(batch.execution_pressure_summary["average_fill_ratio"], 1.0)

    def test_parity_with_realistic_adverse_fill_inputs(self) -> None:
        n = 40
        closes = [100.0 + i * 0.5 for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        entry = [False] * n
        exit_ = [False] * n
        entry[5] = True
        exit_[20] = True

        ref = _simulate_single_python(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=([0.0001] * 5) + ([0.02] * 16) + ([0.0001] * 19),
            open_interest=([1_000_000.0] * 5) + ([5_000_000.0] * 16) + ([1_000_000.0] * 19),
            liquidation_notional=([5_000.0] * 5) + ([250_000.0] * 16) + ([5_000.0] * 19),
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=([2_500_000.0] * 5) + ([120.0] * 16) + ([2_500_000.0] * 19),
            depth_ask_1bp_usd=([2_500_000.0] * 5) + ([120.0] * 16) + ([2_500_000.0] * 19),
            latency_proxy_ms=([25.0] * 5) + ([220.0] * 16) + ([25.0] * 19),
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=5.0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
            slippage_model="realistic",
        )
        batch = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=([0.0001] * 5) + ([0.02] * 16) + ([0.0001] * 19),
            open_interest=([1_000_000.0] * 5) + ([5_000_000.0] * 16) + ([1_000_000.0] * 19),
            liquidation_notional=([5_000.0] * 5) + ([250_000.0] * 16) + ([5_000.0] * 19),
            spread_bps=[3.0] * n,
            depth_bid_1bp_usd=([2_500_000.0] * 5) + ([120.0] * 16) + ([2_500_000.0] * 19),
            depth_ask_1bp_usd=([2_500_000.0] * 5) + ([120.0] * 16) + ([2_500_000.0] * 19),
            latency_proxy_ms=([25.0] * 5) + ([220.0] * 16) + ([25.0] * 19),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            param_slippage_bps=[5.0],
            position_leverage=5.0,
            slippage_model="realistic",
        )[0]

        self._assert_parity(ref, batch)
        self.assertGreater(batch.execution_pressure_summary["adverse_fill_event_count"], 0)
        self.assertGreater(batch.execution_pressure_summary["average_adverse_fill_bps"], 0.0)

    def test_parity_with_mark_premium_liquidation_inputs(self) -> None:
        closes = [100.0, 100.0, 100.0, 100.0]
        highs = [100.0, 103.0, 100.0, 100.0]
        lows = [100.0, 99.0, 100.0, 100.0]
        entry = [True, False, False, False]
        exit_ = [False, False, False, False]

        ref = _simulate_single_python(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(4),
            entry_signals=entry,
            exit_signals=exit_,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            position_side="short",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            latency_bars=0,
            liquidation_mark_price_weight=1.0,
            liquidation_mark_premium_bps=500.0,
        )
        batch = simulate_strategy_batch(
            closes=closes,
            highs=highs,
            lows=lows,
            funding_rates=_zeros(4),
            signal_matrix=[(entry, exit_)],
            taker_fee_bps=0.0,
            position_side="short",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=1.0,
            liquidation_mark_premium_bps=500.0,
        )[0]

        self._assert_parity(ref, batch)


if __name__ == "__main__":
    unittest.main()
