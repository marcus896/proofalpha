import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import BacktestResult, DataSnapshot, StressMetrics
from engine.data.schema import Candle
from engine.validation.scenarios import (
    DEFAULT_SCENARIOS,
    StressScenario,
    build_calibrated_scenario_profile,
    evaluate_scenarios,
    resolve_scenario_profile,
)


def _result(sharpe: float, drawdown: float, liquidations: list[str] | None = None) -> BacktestResult:
    return BacktestResult(
        trade_count=120,
        win_rate=0.45,
        gross_pnl=120.0,
        net_pnl=100.0,
        fee_spend=5.0,
        funding_spend=1.0,
        sharpe=sharpe,
        sortino=sharpe + 0.1,
        max_drawdown=drawdown,
        equity_curve=[0.0, 10.0, -5.0, 20.0],
        liquidation_events=liquidations or [],
    )


class ScenarioEvaluationTests(unittest.TestCase):
    def test_default_scenarios_cover_phase3_families_and_aliases_resolve_to_canonical_names(self) -> None:
        default_names = {scenario.name for scenario in DEFAULT_SCENARIOS}

        self.assertEqual(
            default_names,
            {
                "funding_basis_shock",
                "joint_crypto_dislocation",
                "liquidation_cascade",
                "liquidity_withdrawal",
                "mark_index_dislocation",
                "attention_burst",
                "short_squeeze",
                "venue_outage",
            },
        )

        venue_outage = resolve_scenario_profile(
            StressScenario("outage-shock", 0.9, "Outage shock"),
        )
        liquidity_withdrawal = resolve_scenario_profile(
            StressScenario("liquidity-withdrawal", 0.8, "Liquidity withdrawal"),
        )
        mark_index_dislocation = resolve_scenario_profile(
            StressScenario("mark-index-dislocation", 0.75, "Mark/index dislocation"),
        )
        joint_crypto_dislocation = resolve_scenario_profile(
            StressScenario("joint-crypto-dislocation", 0.92, "Joint crypto dislocation"),
        )

        self.assertEqual(venue_outage.name, "venue_outage")
        self.assertEqual(liquidity_withdrawal.name, "liquidity_withdrawal")
        self.assertEqual(mark_index_dislocation.name, "mark_index_dislocation")
        self.assertEqual(joint_crypto_dislocation.name, "joint_crypto_dislocation")

    def test_resolve_scenario_profile_can_apply_venue_specific_presets(self) -> None:
        generic = resolve_scenario_profile(
            StressScenario("outage-shock", 0.9, "Outage shock"),
            venue="generic",
        )
        binance = resolve_scenario_profile(
            StressScenario("outage-shock", 0.9, "Outage shock"),
            venue="binance",
        )

        self.assertGreaterEqual(binance.liquidity_penalty_bps, generic.liquidity_penalty_bps)
        self.assertGreaterEqual(binance.latency_delta_bars, generic.latency_delta_bars)
        self.assertGreaterEqual(binance.mark_premium_bps, generic.mark_premium_bps)
        self.assertGreaterEqual(binance.spread_multiplier, generic.spread_multiplier)
        self.assertLessEqual(binance.depth_multiplier, generic.depth_multiplier)
        self.assertGreaterEqual(binance.latency_multiplier, generic.latency_multiplier)

    def test_resolve_scenario_profile_applies_named_presets_without_overwriting_explicit_knobs(self) -> None:
        preset = resolve_scenario_profile(
            StressScenario("outage-shock", 0.9, "Outage shock"),
        )
        overridden = resolve_scenario_profile(
            StressScenario(
                "outage-shock",
                0.9,
                "Outage shock",
                liquidity_penalty_bps=10.0,
                latency_delta_bars=5,
            )
        )

        self.assertGreater(preset.liquidity_penalty_bps, 0.0)
        self.assertGreater(preset.latency_delta_bars, 0)
        self.assertEqual(overridden.liquidity_penalty_bps, 10.0)
        self.assertEqual(overridden.latency_delta_bars, 5)

    def test_resolve_scenario_profile_applies_microstructure_presets_without_overwriting_explicit_values(self) -> None:
        preset = resolve_scenario_profile(
            StressScenario("liquidity-withdrawal", 0.8, "Liquidity withdrawal"),
            venue="binance",
        )
        overridden = resolve_scenario_profile(
            StressScenario(
                "liquidity-withdrawal",
                0.8,
                "Liquidity withdrawal",
                spread_multiplier=1.4,
                depth_multiplier=0.85,
                latency_multiplier=1.2,
            ),
            venue="binance",
        )

        self.assertGreater(preset.spread_multiplier, 1.0)
        self.assertLess(preset.depth_multiplier, 1.0)
        self.assertGreater(preset.latency_multiplier, 1.0)
        self.assertEqual(overridden.spread_multiplier, 1.4)
        self.assertEqual(overridden.depth_multiplier, 0.85)
        self.assertEqual(overridden.latency_multiplier, 1.2)

    def test_resolve_scenario_profile_applies_mark_index_dislocation_presets_without_overwriting_explicit_values(self) -> None:
        preset = resolve_scenario_profile(
            StressScenario("mark-index-dislocation", 0.75, "Mark/index dislocation"),
            venue="binance",
        )
        overridden = resolve_scenario_profile(
            StressScenario(
                "mark-index-dislocation",
                0.75,
                "Mark/index dislocation",
                mark_premium_bps=90.0,
                index_basis_bps=55.0,
                premium_spike_bars=4,
            ),
            venue="binance",
        )

        self.assertGreater(preset.mark_premium_bps, 0.0)
        self.assertGreater(preset.index_basis_bps, 0.0)
        self.assertGreater(preset.premium_spike_bars, 0)
        self.assertEqual(overridden.mark_premium_bps, 90.0)
        self.assertEqual(overridden.index_basis_bps, 55.0)
        self.assertEqual(overridden.premium_spike_bars, 4)

    def test_evaluate_scenarios_marks_failures_and_counts_pass_rate(self) -> None:
        scenarios = [
            StressScenario("attention-burst", 0.6, "Attention shock"),
            StressScenario("outage-shock", 0.9, "Outage shock"),
        ]
        results = {
            "attention-burst": _result(0.70, -0.18),
            "outage-shock": _result(0.30, -0.35, liquidations=["liq"]),
        }

        report = evaluate_scenarios(scenarios, results)

        self.assertEqual(report.total_scenarios, 2)
        self.assertEqual(report.passed_scenarios, 1)
        self.assertAlmostEqual(report.pass_rate, 0.5)
        self.assertEqual(report.results[0].scenario_name, "attention-burst")
        self.assertTrue(report.results[0].passed)
        self.assertFalse(report.results[1].passed)
        self.assertIn("drawdown_kill_switch", report.results[1].failure_reasons)
        self.assertIn("liquidation_events", report.results[1].failure_reasons)

    def test_evaluate_scenarios_can_aggregate_phase3_stress_metrics(self) -> None:
        scenarios = [
            StressScenario("attention_burst", 0.6, "Attention shock"),
            StressScenario("liquidation_cascade", 0.9, "Cascade stress"),
        ]
        results = {
            "attention_burst": _result(0.70, -0.18),
            "liquidation_cascade": _result(0.30, -0.35, liquidations=["liq"]),
        }
        stress_metrics = {
            "attention_burst": StressMetrics(
                stress_slippage_quantile=0.12,
                stress_tail_slippage=0.18,
                liquidity_stress_score=0.42,
                basis_stress_score=0.25,
                cascade_liquidation_count=0,
            ),
            "liquidation_cascade": StressMetrics(
                stress_slippage_quantile=0.22,
                stress_tail_slippage=0.31,
                liquidity_stress_score=0.71,
                basis_stress_score=0.34,
                cascade_liquidation_count=3,
            ),
        }

        report = evaluate_scenarios(
            scenarios,
            results,
            stress_metrics_by_name=stress_metrics,
            regime_scenario_pass_matrix={
                "crash": {"liquidation_cascade": False},
                "sideways": {"attention_burst": True},
            },
        )

        self.assertEqual(report.stress_liquidity_metrics["stress_slippage_quantile"], 0.22)
        self.assertEqual(report.stress_liquidity_metrics["stress_tail_slippage"], 0.31)
        self.assertEqual(report.stress_liquidity_metrics["liquidity_stress_score"], 0.71)
        self.assertEqual(report.stress_liquidity_metrics["basis_stress_score"], 0.34)
        self.assertEqual(report.stress_liquidity_metrics["cascade_liquidation_count"], 3)
        self.assertEqual(report.results[0].stress_metrics.stress_slippage_quantile, 0.12)
        self.assertEqual(report.regime_scenario_pass_matrix["crash"]["liquidation_cascade"], False)

    def test_evaluate_scenarios_prefers_resolved_profile_severity(self) -> None:
        scenario = StressScenario("short_squeeze", 0.6, "Short squeeze")
        report = evaluate_scenarios(
            [scenario],
            {"short_squeeze": _result(0.4, -0.12)},
            resolved_profiles_by_name={
                "short_squeeze": {
                    "name": "short_squeeze",
                    "severity": 0.92,
                    "target_regimes": ["short_squeeze"],
                }
            },
        )

        self.assertAlmostEqual(report.results[0].severity, 0.92)

    def test_build_calibrated_scenario_profile_keeps_static_mode_unchanged(self) -> None:
        snapshot = _scenario_snapshot(clustered=False)

        profile = build_calibrated_scenario_profile(
            snapshot,
            StressScenario("liquidation_cascade", 0.9, "Cascade stress"),
            seed=7,
        )

        self.assertEqual(
            profile["resolved_scenario"].liquidation_multiplier,
            profile["calibrated_scenario"].liquidation_multiplier,
        )
        self.assertEqual(profile["stressed_path"], [candle.close for candle in snapshot.candles])

    def test_build_calibrated_scenario_profile_strengthens_cascade_under_clustered_liquidations(self) -> None:
        snapshot = _scenario_snapshot(clustered=True)

        profile = build_calibrated_scenario_profile(
            snapshot,
            StressScenario("liquidation_cascade", 0.9, "Cascade stress", calibration_mode="calibrated"),
            seed=7,
        )

        self.assertGreater(
            profile["calibrated_scenario"].liquidation_multiplier,
            profile["resolved_scenario"].liquidation_multiplier,
        )
        self.assertEqual(len(profile["stressed_path"]), len(snapshot.candles))
        self.assertIsNotNone(profile["jump_params"])
        self.assertIsNotNone(profile["hawkes_params"])

    def test_build_calibrated_joint_crypto_dislocation_strengthens_path_and_execution_knobs(self) -> None:
        snapshot = _scenario_snapshot(clustered=True)

        profile = build_calibrated_scenario_profile(
            snapshot,
            StressScenario(
                "joint_crypto_dislocation",
                0.92,
                "Joint crypto dislocation",
                calibration_mode="calibrated",
            ),
            seed=7,
        )

        resolved = profile["resolved_scenario"]
        calibrated = profile["calibrated_scenario"]
        self.assertEqual(len(profile["stressed_path"]), len(snapshot.candles))
        self.assertNotEqual(profile["stressed_path"], [candle.close for candle in snapshot.candles])
        self.assertGreater(calibrated.liquidation_multiplier, resolved.liquidation_multiplier)
        self.assertGreater(calibrated.funding_multiplier, resolved.funding_multiplier)
        self.assertGreater(calibrated.spread_multiplier, resolved.spread_multiplier)
        self.assertLess(calibrated.depth_multiplier, resolved.depth_multiplier)
        self.assertGreater(calibrated.latency_multiplier, resolved.latency_multiplier)
        self.assertGreater(calibrated.mark_premium_bps, resolved.mark_premium_bps)
        self.assertGreater(calibrated.index_basis_bps, resolved.index_basis_bps)


def _scenario_snapshot(clustered: bool) -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    closes = [100.0, 101.0, 100.5, 102.0, 89.0, 92.0, 96.0, 95.0]
    liquidation_notional = (
        [0.0, 0.0, 40.0, 55.0, 60.0, 0.0, 0.0, 0.0]
        if clustered
        else [0.0, 10.0, 0.0, 12.0, 0.0, 11.0, 0.0, 9.0]
    )
    candles = [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=close - 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=1000.0 + index,
        )
        for index, close in enumerate(closes)
    ]
    return DataSnapshot(
        snapshot_id=f"scenario-calibration-{int(clustered)}",
        symbol="SOLUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=[0.004, 0.003, 0.004, 0.006, 0.008, 0.005, 0.004, 0.003],
        open_interest=[100.0, 102.0, 105.0, 111.0, 120.0, 122.0, 123.0, 121.0],
        liquidation_notional=liquidation_notional,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        quality_flags=[],
    )


if __name__ == "__main__":
    unittest.main()
