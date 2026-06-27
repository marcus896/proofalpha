"""Tests for slippage and market-impact helpers (market_impact.py)."""

from __future__ import annotations

import unittest

from engine.backtest.market_impact import (
    ImpactCostCoefficients,
    compute_dynamic_slippage,
    compute_oi_stress_flag,
    impact_cost_bps,
)


class DynamicSlippageTests(unittest.TestCase):

    # ----- zero OI fallback -----------------------------------------------

    def test_zero_oi_returns_flat_fallback(self) -> None:
        result = compute_dynamic_slippage(
            trade_notional=100_000.0,
            volatility=0.02,
            open_interest=0.0,
            oi_is_stressed=False,
            stress_regime="bull",
            flat_fallback_bps=7.5,
        )
        self.assertAlmostEqual(result, 7.5)

    def test_negative_oi_returns_flat_fallback(self) -> None:
        result = compute_dynamic_slippage(
            trade_notional=100_000.0,
            volatility=0.02,
            open_interest=-1.0,
            oi_is_stressed=False,
            stress_regime="bull",
            flat_fallback_bps=10.0,
        )
        self.assertAlmostEqual(result, 10.0)

    # ----- monotonicity ---------------------------------------------------

    def test_slippage_increases_with_trade_size(self) -> None:
        kwargs = dict(volatility=0.02, open_interest=1_000_000.0, oi_is_stressed=False, stress_regime="bull")
        small = compute_dynamic_slippage(trade_notional=1_000.0, **kwargs)
        large = compute_dynamic_slippage(trade_notional=100_000.0, **kwargs)
        self.assertGreater(large, small)

    def test_slippage_increases_with_volatility(self) -> None:
        kwargs = dict(trade_notional=10_000.0, open_interest=1_000_000.0, oi_is_stressed=False, stress_regime="sideways")
        low_vol = compute_dynamic_slippage(volatility=0.005, **kwargs)
        high_vol = compute_dynamic_slippage(volatility=0.05, **kwargs)
        self.assertGreater(high_vol, low_vol)

    # ----- stress multipliers ---------------------------------------------

    def test_crash_regime_with_oi_stressed_applies_1_50_multiplier(self) -> None:
        base = compute_dynamic_slippage(
            trade_notional=10_000.0, volatility=0.02, open_interest=1_000_000.0,
            oi_is_stressed=False, stress_regime="crash",
        )
        stressed = compute_dynamic_slippage(
            trade_notional=10_000.0, volatility=0.02, open_interest=1_000_000.0,
            oi_is_stressed=True, stress_regime="crash",
        )
        self.assertAlmostEqual(stressed / base, 1.50, places=6)

    def test_short_squeeze_regime_with_oi_stressed_applies_1_35_multiplier(self) -> None:
        base = compute_dynamic_slippage(
            trade_notional=10_000.0, volatility=0.02, open_interest=1_000_000.0,
            oi_is_stressed=False, stress_regime="short_squeeze",
        )
        stressed = compute_dynamic_slippage(
            trade_notional=10_000.0, volatility=0.02, open_interest=1_000_000.0,
            oi_is_stressed=True, stress_regime="short_squeeze",
        )
        self.assertAlmostEqual(stressed / base, 1.35, places=6)

    def test_liquidity_stress_regime_with_oi_stressed_applies_1_25_multiplier(self) -> None:
        base = compute_dynamic_slippage(
            trade_notional=10_000.0, volatility=0.02, open_interest=1_000_000.0,
            oi_is_stressed=False, stress_regime="liquidity_stress",
        )
        stressed = compute_dynamic_slippage(
            trade_notional=10_000.0, volatility=0.02, open_interest=1_000_000.0,
            oi_is_stressed=True, stress_regime="liquidity_stress",
        )
        self.assertAlmostEqual(stressed / base, 1.25, places=6)

    def test_bull_regime_no_multiplier_even_when_oi_stressed(self) -> None:
        base = compute_dynamic_slippage(
            trade_notional=10_000.0, volatility=0.02, open_interest=1_000_000.0,
            oi_is_stressed=False, stress_regime="bull",
        )
        stressed = compute_dynamic_slippage(
            trade_notional=10_000.0, volatility=0.02, open_interest=1_000_000.0,
            oi_is_stressed=True, stress_regime="bull",
        )
        self.assertAlmostEqual(base, stressed)

    def test_stress_multiplier_only_armed_when_oi_stressed_true(self) -> None:
        """Even in crash regime, multiplier not applied if oi_is_stressed=False."""
        base = compute_dynamic_slippage(
            trade_notional=10_000.0, volatility=0.02, open_interest=1_000_000.0,
            oi_is_stressed=False, stress_regime="crash",
        )
        # Calling with oi_is_stressed=False should equal multiplier=1.0
        expected = 0.1 * (10_000.0 / 1_000_000.0) ** 0.5 * 0.02 * 10_000.0
        self.assertAlmostEqual(base, expected, places=4)

    # ----- clamping -------------------------------------------------------

    def test_output_clamped_to_max_500_bps(self) -> None:
        result = compute_dynamic_slippage(
            trade_notional=1e12,   # astronomically large
            volatility=10.0,      # 1000% vol
            open_interest=1.0,    # tiny OI → huge participation
            oi_is_stressed=True,
            stress_regime="crash",
        )
        self.assertLessEqual(result, 500.0)

    def test_output_always_non_negative(self) -> None:
        result = compute_dynamic_slippage(
            trade_notional=0.0,
            volatility=0.0,
            open_interest=1_000_000.0,
            oi_is_stressed=False,
            stress_regime="sideways",
        )
        self.assertGreaterEqual(result, 0.0)

    # ----- pure function --------------------------------------------------

    def test_same_inputs_produce_same_output(self) -> None:
        args = dict(
            trade_notional=50_000.0, volatility=0.015, open_interest=2_000_000.0,
            oi_is_stressed=True, stress_regime="liquidity_stress", flat_fallback_bps=5.0,
        )
        self.assertEqual(
            compute_dynamic_slippage(**args),
            compute_dynamic_slippage(**args),
        )


class RealisticImpactCostTests(unittest.TestCase):

    def test_impact_cost_increases_with_latency(self) -> None:
        coeff = ImpactCostCoefficients()
        low_latency = impact_cost_bps(
            q_notional=25_000.0,
            available_depth_notional=2_000_000.0,
            sigma_1h=0.02,
            spread_bps=4.0,
            latency_ms=15.0,
            coeff=coeff,
        )
        high_latency = impact_cost_bps(
            q_notional=25_000.0,
            available_depth_notional=2_000_000.0,
            sigma_1h=0.02,
            spread_bps=4.0,
            latency_ms=180.0,
            coeff=coeff,
        )
        self.assertGreater(high_latency, low_latency)

    def test_impact_cost_decreases_with_available_depth(self) -> None:
        coeff = ImpactCostCoefficients()
        shallow = impact_cost_bps(
            q_notional=25_000.0,
            available_depth_notional=80_000.0,
            sigma_1h=0.02,
            spread_bps=4.0,
            latency_ms=40.0,
            coeff=coeff,
        )
        deep = impact_cost_bps(
            q_notional=25_000.0,
            available_depth_notional=5_000_000.0,
            sigma_1h=0.02,
            spread_bps=4.0,
            latency_ms=40.0,
            coeff=coeff,
        )
        self.assertGreater(shallow, deep)

    def test_impact_cost_keeps_half_spread_floor(self) -> None:
        coeff = ImpactCostCoefficients()
        result = impact_cost_bps(
            q_notional=0.0,
            available_depth_notional=5_000_000.0,
            sigma_1h=0.0,
            spread_bps=6.0,
            latency_ms=0.0,
            coeff=coeff,
        )
        self.assertGreaterEqual(result, 3.0)


class OiStressFlagTests(unittest.TestCase):

    def test_returns_false_for_empty_series(self) -> None:
        self.assertFalse(compute_oi_stress_flag([], 1000.0))

    def test_returns_true_for_value_above_90th_percentile(self) -> None:
        series = list(range(1, 101))  # 1..100
        # 90th pctile of 1..100 ≈ 90.1; 95 should be stressed
        self.assertTrue(compute_oi_stress_flag(series, 95.0))

    def test_returns_false_for_value_below_90th_percentile(self) -> None:
        series = list(range(1, 101))
        self.assertFalse(compute_oi_stress_flag(series, 50.0))

    def test_returns_false_for_median_value(self) -> None:
        series = [float(i) for i in range(1, 101)]
        self.assertFalse(compute_oi_stress_flag(series, 50.0))


if __name__ == "__main__":
    unittest.main()
