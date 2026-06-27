import json
import unittest
from unittest import mock
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.config.models import (
    BacktestResult,
    BootstrapReport,
    CandidateEvaluation,
    DataSnapshot,
    LayerFamily,
    LayerSpec,
    PromotionDecision,
    StrategyGraph,
)
from engine.data.schema import Candle
from engine.app.service import execute_research_cycle
from engine.validation.scenarios import StressScenario
from engine.validation.protocol import ValidationProtocol, ValidationStageResult


def _snapshot() -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0 + index,
            volume=1_000.0,
        )
        for index in range(120)
    ]
    return DataSnapshot(
        snapshot_id="snap-2",
        symbol="SOLUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=[0.0] * 120,
        open_interest=[100.0] * 120,
        liquidation_notional=[0.0] * 120,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        quality_flags=[],
    )


def _result(sharpe: float, drawdown: float = -0.10, net_pnl: float = 100.0) -> BacktestResult:
    return BacktestResult(
        trade_count=170,
        win_rate=0.46,
        gross_pnl=120.0,
        net_pnl=net_pnl,
        fee_spend=5.0,
        funding_spend=1.0,
        sharpe=sharpe,
        sortino=sharpe + 0.1,
        max_drawdown=drawdown,
        equity_curve=[0.0, 10.0, -5.0, 20.0],
        liquidation_events=[],
    )


def _bootstrap(
    median_profit: float = 120.0,
    worst_dd: float = -0.10,
    bootstrap_method: str = "moving_block",
) -> BootstrapReport:
    return BootstrapReport(
        sample_count=32,
        median_net_profit=median_profit,
        median_max_drawdown=-0.08,
        worst_case_net_profit=-10.0,
        worst_case_drawdown=worst_dd,
        pass_rate=0.8,
        bootstrap_method=bootstrap_method,
        block_size=4,
        bootstrap_regime_summary={
            "average_regime_coverage": {"bull": 0.5, "bear": 0.2},
            "crisis_sample_frequency": {"crash": 0.25},
            "dominant_regimes": ["bull", "sideways"],
            "sample_count": 32,
        },
    )


class ResearchCycleServiceTests(unittest.TestCase):
    def test_execute_research_cycle_emits_service_logging_boundaries(self) -> None:
        evaluations = {
            "mom_squeeze": CandidateEvaluation("mom_squeeze", PromotionDecision("accept", []), _result(0.20), _result(0.20), _bootstrap()),
            "kama": CandidateEvaluation("kama", PromotionDecision("accept", []), _result(0.31), _result(0.31, net_pnl=140.0), _bootstrap(median_profit=130.0)),
        }
        scenario_results = {
            "attention_burst": _result(0.40, -0.18),
        }

        output_dir = Path("test-output-service-logging")
        output_dir.mkdir(exist_ok=True)
        try:
            with self.assertLogs("engine", level="INFO") as captured_logs:
                execute_research_cycle(
                    run_id="run-4",
                    snapshot=_snapshot(),
                    incumbent=StrategyGraph(backbone="mom_squeeze"),
                    directional_layers=[LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)],
                    known_good_filters=[],
                    custom_filters=[],
                    exit_layers=[],
                    evaluator=lambda _graph, layer: evaluations[layer.name],
                    scenario_evaluator=lambda _strategy, scenario: scenario_results[scenario.name],
                    validation_executor=lambda _strategy, _phase_records: ValidationProtocol(
                        status="passed",
                        stage_results=[
                            ValidationStageResult("in_sample_excellence", True, [], {"sharpe": 0.35}),
                            ValidationStageResult("walk_forward", True, [], {"sharpe": 0.35}),
                            ValidationStageResult("final_holdout", True, [], {"sharpe": 0.20}),
                        ],
                        probabilistic_sharpe_ratio=0.98,
                        deflated_sharpe_ratio=0.96,
                        in_sample_permutation_pvalue=0.004,
                        walk_forward_permutation_pvalue=0.009,
                        validation_trial_count=3,
                        validation_gate_results={
                            "deflated_sharpe_ratio": True,
                            "in_sample_permutation": True,
                            "walk_forward_permutation": True,
                            "final_holdout": True,
                        },
                        promotion_decision=PromotionDecision("accept", []),
                    ),
                    scenarios=[StressScenario("attention_burst", 0.6, "Attention shock")],
                    output_dir=output_dir,
                    seed=77,
                    runtime_settings={
                        "bootstrap_method": "stationary_block",
                        "position_side": "short",
                        "liquidation_mark_price_weight": 0.35,
                    },
                )

            self.assertEqual(
                [record.getMessage() for record in captured_logs.records],
                [
                    "Starting research cycle 'run-4' (seed=77)",
                    "Pipeline completed for 'run-4'",
                    "Writing dashboard bundle for 'run-4'",
                    "Completed research cycle 'run-4'",
                ],
            )
        finally:
            for path in output_dir.glob("*"):
                path.unlink()
            output_dir.rmdir()

    def test_execute_research_cycle_saves_runcard_and_dashboard(self) -> None:
        evaluations = {
            "mom_squeeze": CandidateEvaluation("mom_squeeze", PromotionDecision("accept", []), _result(0.20), _result(0.20), _bootstrap()),
            "kama": CandidateEvaluation("kama", PromotionDecision("accept", []), _result(0.31), _result(0.31, net_pnl=140.0), _bootstrap(median_profit=130.0)),
            "flat9": CandidateEvaluation(
                "flat9",
                PromotionDecision("accept", []),
                _result(0.35),
                _result(0.35, net_pnl=150.0),
                _bootstrap(median_profit=135.0, bootstrap_method="stationary_block"),
            ),
        }
        scenario_results = {
            "attention_burst": _result(0.40, -0.18),
            "venue_outage": _result(0.10, -0.30),
        }

        output_dir = Path("test-output-service")
        output_dir.mkdir(exist_ok=True)
        try:
            execution = execute_research_cycle(
                run_id="run-4",
                snapshot=_snapshot(),
                incumbent=StrategyGraph(backbone="mom_squeeze"),
                directional_layers=[LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)],
                known_good_filters=[LayerSpec(name="flat9", family=LayerFamily.KNOWN_GOOD_FLAT_FILTER)],
                custom_filters=[],
                exit_layers=[],
                evaluator=lambda _graph, layer: evaluations[layer.name],
                scenario_evaluator=lambda _strategy, scenario: scenario_results[scenario.name],
                validation_executor=lambda _strategy, _phase_records: ValidationProtocol(
                    status="passed",
                    stage_results=[
                        ValidationStageResult("in_sample_excellence", True, [], {"sharpe": 0.35}),
                        ValidationStageResult("walk_forward", True, [], {"sharpe": 0.35}),
                        ValidationStageResult("final_holdout", True, [], {"sharpe": 0.20}),
                    ],
                    probabilistic_sharpe_ratio=0.98,
                    deflated_sharpe_ratio=0.96,
                    in_sample_permutation_pvalue=0.004,
                    walk_forward_permutation_pvalue=0.009,
                    validation_trial_count=3,
                    validation_gate_results={
                        "deflated_sharpe_ratio": True,
                        "in_sample_permutation": True,
                        "walk_forward_permutation": True,
                        "final_holdout": True,
                    },
                    promotion_decision=PromotionDecision("accept", []),
                ),
                scenarios=[
                    StressScenario("attention_burst", 0.6, "Attention shock"),
                    StressScenario("venue_outage", 0.9, "Outage shock"),
                ],
                output_dir=output_dir,
                seed=77,
                runtime_settings={
                    "bootstrap_method": "stationary_block",
                    "position_side": "short",
                    "liquidation_mark_price_weight": 0.35,
                },
            )

            runcard_path = output_dir / "run-4.runcard.json"
            dashboard_path = output_dir / "run-4.dashboard.json"

            self.assertEqual(execution.report.status, "promoted")
            self.assertTrue(runcard_path.exists())
            self.assertTrue(dashboard_path.exists())

            runcard_payload = json.loads(runcard_path.read_text(encoding="utf-8"))
            dashboard_payload = json.loads(dashboard_path.read_text(encoding="utf-8"))

            self.assertEqual(runcard_payload["run_id"], "run-4")
            self.assertEqual(runcard_payload["metrics"]["scenario_pass_rate"], 0.5)
            self.assertEqual(runcard_payload["metrics"]["total_trades"], 170)
            self.assertEqual(runcard_payload["metrics"]["win_rate"], 0.46)
            self.assertEqual(runcard_payload["metrics"]["sortino_ratio"], 0.44999999999999996)
            self.assertEqual(runcard_payload["metrics"]["probabilistic_sharpe_ratio"], 0.98)
            self.assertEqual(runcard_payload["metrics"]["deflated_sharpe_ratio"], 0.96)
            self.assertEqual(runcard_payload["metrics"]["in_sample_permutation_pvalue"], 0.004)
            self.assertEqual(runcard_payload["metrics"]["walk_forward_permutation_pvalue"], 0.009)
            self.assertEqual(runcard_payload["metrics"]["validation_trial_count"], 3)
            self.assertIn("stress_slippage_quantile", runcard_payload["metrics"])
            self.assertIn("stress_tail_slippage", runcard_payload["metrics"])
            self.assertIn("liquidity_stress_score", runcard_payload["metrics"])
            self.assertIn("basis_stress_score", runcard_payload["metrics"])
            self.assertIn("cascade_liquidation_count", runcard_payload["metrics"])
            self.assertIn("stress_liquidity_metrics_json", runcard_payload["artifacts"])
            self.assertIn("regime_scenario_pass_matrix_json", runcard_payload["artifacts"])
            self.assertEqual(
                runcard_payload["artifacts"]["runtime_settings_json"],
                '{"bootstrap_method": "stationary_block", "liquidation_mark_price_weight": 0.35, "position_side": "short"}',
            )
            self.assertIn('"status": "passed"', runcard_payload["artifacts"]["validation_protocol_json"])
            self.assertEqual(dashboard_payload["holdout"]["decision"], "accept")
            self.assertEqual(dashboard_payload["validation_protocol"]["status"], "passed")
            self.assertEqual(dashboard_payload["validation_protocol"]["validation_gate_results"]["deflated_sharpe_ratio"], True)
            self.assertEqual(dashboard_payload["strategy"]["layers"], ["kama", "flat9"])
            self.assertEqual(dashboard_payload["bootstrap"]["bootstrap_method"], "stationary_block")
            self.assertEqual(dashboard_payload["bootstrap"]["block_size"], 4)
            self.assertEqual(dashboard_payload["bootstrap"]["bootstrap_regime_summary"]["sample_count"], 32)
            self.assertIn("regime_coverage", dashboard_payload["regimes"])
            self.assertIn("stress_liquidity_metrics", dashboard_payload)
            self.assertIn("regime_scenario_pass_matrix", dashboard_payload)
            self.assertIn("stress_metrics", dashboard_payload["scenarios"][0])
            self.assertEqual(dashboard_payload["runtime_settings"]["position_side"], "short")
            self.assertEqual(dashboard_payload["runtime_settings"]["bootstrap_method"], "stationary_block")
            self.assertIn("execution_pressure_summary", dashboard_payload["scenarios"][0])
            self.assertEqual(len(dashboard_payload["timeseries"]), 4)
            self.assertEqual(dashboard_payload["timeseries"][0]["equity"], 0.0)
        finally:
            for path in output_dir.glob("*"):
                path.unlink()
            output_dir.rmdir()

    def test_execute_research_cycle_writes_dashboard_for_aborted_report_without_validation_protocol(self) -> None:
        evaluations = {
            "mom_squeeze": CandidateEvaluation(
                "mom_squeeze",
                PromotionDecision("reject", ["low_backbone_sharpe"]),
                _result(0.01),
                _result(0.01),
                _bootstrap(),
            ),
        }
        scenario_results = {
            "attention_burst": _result(0.05, -0.18),
        }

        output_dir = Path("test-output-service-aborted-no-validation")
        output_dir.mkdir(exist_ok=True)
        try:
            execution = execute_research_cycle(
                run_id="run-aborted",
                snapshot=_snapshot(),
                incumbent=StrategyGraph(backbone="mom_squeeze"),
                directional_layers=[LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)],
                known_good_filters=[],
                custom_filters=[],
                exit_layers=[],
                evaluator=lambda _graph, layer: evaluations[layer.name],
                scenario_evaluator=lambda _strategy, scenario: scenario_results[scenario.name],
                scenarios=[StressScenario("attention_burst", 0.6, "Attention shock")],
                output_dir=output_dir,
                seed=77,
            )

            dashboard_payload = json.loads((output_dir / "run-aborted.dashboard.json").read_text(encoding="utf-8"))
            self.assertEqual(execution.report.status, "aborted")
            self.assertEqual(dashboard_payload["validation_protocol"]["status"], "legacy_validation_missing")
            self.assertEqual(dashboard_payload["holdout"]["decision"], "accept")
        finally:
            for path in output_dir.glob("*"):
                path.unlink()
            output_dir.rmdir()

    def test_execute_research_cycle_records_active_calibrated_scenario_profile(self) -> None:
        evaluations = {
            "mom_squeeze": CandidateEvaluation("mom_squeeze", PromotionDecision("accept", []), _result(0.20), _result(0.20), _bootstrap()),
            "kama": CandidateEvaluation("kama", PromotionDecision("accept", []), _result(0.31), _result(0.31, net_pnl=140.0), _bootstrap(median_profit=130.0)),
        }
        scenario_results = {
            "short_squeeze": _result(0.40, -0.18),
        }
        calibrated = StressScenario(
            "short_squeeze",
            0.91,
            "Calibrated squeeze",
            calibration_mode="calibrated",
            funding_multiplier=2.0,
            mark_premium_bps=140.0,
            index_basis_bps=90.0,
            premium_spike_bars=3,
            liquidation_multiplier=2.5,
        )

        output_dir = Path("test-output-service-calibrated")
        output_dir.mkdir(exist_ok=True)
        try:
            calibrated_snapshot = DataSnapshot(
                snapshot_id="snap-calibrated-microstructure",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                candles=list(_snapshot().candles),
                funding_rates=list(_snapshot().funding_rates),
                open_interest=list(_snapshot().open_interest),
                liquidation_notional=list(_snapshot().liquidation_notional),
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                spread_bps=[6.0] * 120,
                depth_bid_1bp_usd=[800_000.0] * 120,
                depth_ask_1bp_usd=[750_000.0] * 120,
                latency_proxy_ms=[45.0] * 120,
                quality_flags=[],
            )
            with mock.patch(
                "engine.app.service._resolve_scenario_runtime_inputs",
                return_value=(calibrated_snapshot, calibrated),
            ):
                execution = execute_research_cycle(
                    run_id="run-calibrated",
                    snapshot=_snapshot(),
                    incumbent=StrategyGraph(backbone="mom_squeeze"),
                    directional_layers=[LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)],
                    known_good_filters=[],
                    custom_filters=[],
                    exit_layers=[],
                    evaluator=lambda _graph, layer: evaluations[layer.name],
                    scenario_evaluator=lambda _strategy, scenario: scenario_results[scenario.name],
                    validation_executor=lambda _strategy, _phase_records: ValidationProtocol(
                        status="passed",
                        stage_results=[],
                        promotion_decision=PromotionDecision("accept", []),
                    ),
                    scenarios=[StressScenario("short_squeeze", 0.6, "Original squeeze")],
                    output_dir=output_dir,
                    seed=77,
                )

            scenario_payload = execution.dashboard_payload["scenarios"][0]
            self.assertEqual(scenario_payload["scenario_name"], "short_squeeze")
            self.assertAlmostEqual(scenario_payload["severity"], 0.91)
            self.assertEqual(scenario_payload["resolved_profile"]["severity"], 0.91)
            self.assertEqual(scenario_payload["resolved_profile"]["calibration_mode"], "calibrated")
            self.assertEqual(scenario_payload["resolved_profile"]["spread_multiplier"], 1.0)
            self.assertEqual(scenario_payload["resolved_profile"]["depth_multiplier"], 1.0)
            self.assertEqual(scenario_payload["resolved_profile"]["latency_multiplier"], 1.0)
            self.assertEqual(
                scenario_payload["resolved_profile"]["dislocation_summary"],
                {
                    "mark_premium_bps": 140.0,
                    "index_basis_bps": 90.0,
                    "premium_spike_bars": 3,
                },
            )
            self.assertEqual(
                scenario_payload["resolved_profile"]["microstructure_summary"],
                {
                    "spread_bps_mean": 6.0,
                    "depth_bid_1bp_usd_mean": 800000.0,
                    "depth_ask_1bp_usd_mean": 750000.0,
                    "latency_proxy_ms_mean": 45.0,
                },
            )
        finally:
            for path in output_dir.glob("*"):
                path.unlink()
            output_dir.rmdir()

    def test_execute_research_cycle_raises_when_dashboard_write_fails(self) -> None:
        evaluations = {
            "mom_squeeze": CandidateEvaluation("mom_squeeze", PromotionDecision("accept", []), _result(0.20), _result(0.20), _bootstrap()),
            "kama": CandidateEvaluation("kama", PromotionDecision("accept", []), _result(0.31), _result(0.31, net_pnl=140.0), _bootstrap(median_profit=130.0)),
        }
        scenario_results = {
            "attention_burst": _result(0.40, -0.18),
        }

        output_dir = Path("test-output-service-write-fail")
        output_dir.mkdir(exist_ok=True)
        try:
            with mock.patch("engine.app.service.save_runcard"), mock.patch(
                "engine.io.artifacts.os.replace",
                side_effect=PermissionError("denied"),
            ):
                with self.assertRaises(PermissionError):
                    execute_research_cycle(
                        run_id="run-write-fail",
                        snapshot=_snapshot(),
                        incumbent=StrategyGraph(backbone="mom_squeeze"),
                        directional_layers=[LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)],
                        known_good_filters=[],
                        custom_filters=[],
                        exit_layers=[],
                        evaluator=lambda _graph, layer: evaluations[layer.name],
                        scenario_evaluator=lambda _strategy, scenario: scenario_results[scenario.name],
                        validation_executor=lambda _strategy, _phase_records: ValidationProtocol(
                            status="passed",
                            stage_results=[ValidationStageResult("final_holdout", True, [], {"sharpe": 0.20})],
                            probabilistic_sharpe_ratio=0.98,
                            deflated_sharpe_ratio=0.96,
                            in_sample_permutation_pvalue=0.004,
                            walk_forward_permutation_pvalue=0.009,
                            validation_trial_count=3,
                            validation_gate_results={"final_holdout": True},
                            promotion_decision=PromotionDecision("accept", []),
                        ),
                        scenarios=[StressScenario("attention_burst", 0.6, "Attention shock")],
                        output_dir=output_dir,
                        seed=77,
                    )
        finally:
            for path in output_dir.glob("*"):
                path.unlink()
            output_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
