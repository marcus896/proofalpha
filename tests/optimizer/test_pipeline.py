import unittest
from datetime import UTC, datetime, timedelta

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
from engine.optimizer.phases import OvernightRunner
from engine.validation.protocol import ValidationProtocol, ValidationStageResult


def _snapshot() -> DataSnapshot:
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            timestamp=base_time + timedelta(hours=index),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0 + index,
            volume=1_000.0,
        )
        for index in range(300)
    ]
    return DataSnapshot(
        snapshot_id="snapshot",
        symbol="SOLUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=[0.0] * len(candles),
        open_interest=[100.0] * len(candles),
        liquidation_notional=[0.0] * len(candles),
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        quality_flags=[],
    )


def _result(sharpe: float, drawdown: float = -0.10, trades: int = 150) -> BacktestResult:
    return BacktestResult(
        trade_count=trades,
        win_rate=0.44,
        gross_pnl=130.0,
        net_pnl=110.0,
        fee_spend=5.0,
        funding_spend=1.0,
        sharpe=sharpe,
        sortino=sharpe + 0.1,
        max_drawdown=drawdown,
        equity_curve=[0.0, 5.0, -4.0, 15.0],
        liquidation_events=[],
    )


def _bootstrap(worst_dd: float = -0.10, median_profit: float = 120.0) -> BootstrapReport:
    return BootstrapReport(
        sample_count=32,
        median_net_profit=median_profit,
        median_max_drawdown=-0.08,
        worst_case_net_profit=-10.0,
        worst_case_drawdown=worst_dd,
        pass_rate=0.8,
    )


class OvernightPipelineTests(unittest.TestCase):
    def test_pipeline_aborts_when_backbone_oos_sharpe_is_too_low(self) -> None:
        evaluations = {
            "mom_squeeze": CandidateEvaluation(
                layer_name="mom_squeeze",
                decision=PromotionDecision(decision="accept", reasons=[]),
                train_result=_result(0.02),
                oos_result=_result(0.02),
                bootstrap_report=_bootstrap(),
            ),
        }
        runner = OvernightRunner(snapshot=_snapshot(), evaluator=lambda _graph, layer: evaluations[layer.name])

        report = runner.run_pipeline(
            incumbent=StrategyGraph(backbone="mom_squeeze"),
            directional_layers=[],
            known_good_filters=[],
            custom_filters=[],
            exit_layers=[],
        )

        self.assertEqual(report.status, "aborted")
        self.assertEqual(report.final_strategy.layers, [])
        self.assertEqual(report.phase_records[0].phase_name, "phase-1")
        self.assertEqual(report.phase_records[0].decision, "abort")

    def test_pipeline_builds_final_strategy_and_records_phase_history(self) -> None:
        evaluations = {
            "mom_squeeze": CandidateEvaluation("mom_squeeze", PromotionDecision("accept", []), _result(0.20), _result(0.20), _bootstrap()),
            "ema": CandidateEvaluation("ema", PromotionDecision("accept", []), _result(0.25), _result(0.25), _bootstrap()),
            "kama": CandidateEvaluation("kama", PromotionDecision("accept", []), _result(0.31), _result(0.31), _bootstrap()),
            "hull": CandidateEvaluation("hull", PromotionDecision("reject", ["oos"]), _result(0.19), _result(0.19), _bootstrap()),
            "flat9": CandidateEvaluation("flat9", PromotionDecision("accept", []), _result(0.34), _result(0.34), _bootstrap(median_profit=130.0)),
            "flat11": CandidateEvaluation("flat11", PromotionDecision("wash", ["wash"]), _result(0.35), _result(0.35), _bootstrap(median_profit=131.0)),
            "adx_weak": CandidateEvaluation("adx_weak", PromotionDecision("accept", []), _result(0.36), _result(0.36), _bootstrap(median_profit=132.0)),
            "time_stop": CandidateEvaluation("time_stop", PromotionDecision("accept", []), _result(0.40), _result(0.40), _bootstrap(median_profit=140.0)),
        }
        runner = OvernightRunner(snapshot=_snapshot(), evaluator=lambda _graph, layer: evaluations[layer.name])

        report = runner.run_pipeline(
            incumbent=StrategyGraph(backbone="mom_squeeze"),
            directional_layers=[
                LayerSpec(name="ema", family=LayerFamily.DIRECTIONAL_FILTER),
                LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER),
                LayerSpec(name="hull", family=LayerFamily.DIRECTIONAL_FILTER),
            ],
            known_good_filters=[
                LayerSpec(name="flat9", family=LayerFamily.KNOWN_GOOD_FLAT_FILTER),
                LayerSpec(name="flat11", family=LayerFamily.KNOWN_GOOD_FLAT_FILTER),
            ],
            custom_filters=[
                LayerSpec(name="adx_weak", family=LayerFamily.CUSTOM_FLAT_FILTER),
            ],
            exit_layers=[
                LayerSpec(name="time_stop", family=LayerFamily.EXIT),
            ],
        )

        self.assertEqual(report.status, "promoted")
        self.assertEqual([layer.name for layer in report.final_strategy.layers], ["kama", "flat9", "adx_weak", "time_stop"])
        self.assertEqual(report.phase_records[0].phase_name, "phase-1")
        self.assertEqual(report.phase_records[-1].layer_name, "time_stop")
        self.assertEqual(sum(1 for record in report.phase_records if record.accepted), 4)

    def test_holdout_can_block_promotion_without_changing_strategy_selection(self) -> None:
        evaluations = {
            "mom_squeeze": CandidateEvaluation("mom_squeeze", PromotionDecision("accept", []), _result(0.20), _result(0.20), _bootstrap()),
            "kama": CandidateEvaluation("kama", PromotionDecision("accept", []), _result(0.30), _result(0.30), _bootstrap(), {"aggressiveness": 2}),
        }
        runner = OvernightRunner(snapshot=_snapshot(), evaluator=lambda _graph, layer: evaluations[layer.name])

        report = runner.run_pipeline(
            incumbent=StrategyGraph(backbone="mom_squeeze"),
            directional_layers=[LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)],
            known_good_filters=[],
            custom_filters=[],
            exit_layers=[],
            validation_executor=lambda _strategy, _phase_records: ValidationProtocol(
                status="failed",
                stage_results=[
                    ValidationStageResult(
                        stage_name="final_holdout",
                        passed=False,
                        reasons=["final_holdout_sharpe"],
                        metrics={"selection_oos_sharpe": 0.30},
                    )
                ],
                probabilistic_sharpe_ratio=0.97,
                deflated_sharpe_ratio=0.40,
                in_sample_permutation_pvalue=0.004,
                walk_forward_permutation_pvalue=0.08,
                validation_trial_count=2,
                validation_gate_results={"final_holdout": False, "deflated_sharpe_ratio": False},
                promotion_decision=PromotionDecision("reject", ["final_holdout_sharpe"]),
            ),
        )

        self.assertEqual(report.status, "blocked")
        self.assertEqual([layer.name for layer in report.final_strategy.layers], ["kama"])
        self.assertEqual(report.holdout_decision.decision, "reject")
        self.assertIn("final_holdout_sharpe", report.holdout_decision.reasons)
        self.assertEqual(report.phase_records[1].selected_parameters["aggressiveness"], 2)
        self.assertIsNotNone(report.validation_protocol)
        self.assertEqual(report.validation_protocol.status, "failed")


if __name__ == "__main__":
    unittest.main()
