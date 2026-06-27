import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import (
    BacktestResult,
    BootstrapReport,
    CandidateEvaluation,
    DataSnapshot,
    LayerFamily,
    LayerSpec,
    ParameterRange,
    PromotionDecision,
    StrategyGraph,
)
from engine.data.schema import Candle
from engine.optimizer.phases import OvernightRunner


def _snapshot() -> DataSnapshot:
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(timestamp=base_time + timedelta(hours=index), open=100.0, high=100.0, low=100.0, close=100.0, volume=1_000.0)
        for index in range(200)
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


def _result(oos_sharpe: float, train_dd: float = -0.10, trades: int = 150) -> BacktestResult:
    return BacktestResult(
        trade_count=trades,
        win_rate=0.45,
        gross_pnl=120.0,
        net_pnl=100.0,
        fee_spend=5.0,
        funding_spend=1.0,
        sharpe=oos_sharpe,
        sortino=oos_sharpe + 0.1,
        max_drawdown=train_dd,
        equity_curve=[0.0, 10.0, -10.0, 25.0],
        liquidation_events=[],
    )


def _bootstrap(worst_dd: float = -0.10, median_profit: float = 120.0) -> BootstrapReport:
    return BootstrapReport(
        sample_count=32,
        median_net_profit=median_profit,
        median_max_drawdown=-0.08,
        worst_case_net_profit=-20.0,
        worst_case_drawdown=worst_dd,
        pass_rate=0.8,
    )


class OvernightRunnerTests(unittest.TestCase):
    def test_phase_two_keeps_single_best_directional_filter(self) -> None:
        evaluations = {
            "ema": CandidateEvaluation(
                layer_name="ema",
                decision=PromotionDecision(decision="accept", reasons=[]),
                train_result=_result(0.60, train_dd=-0.08),
                oos_result=_result(0.60),
                bootstrap_report=_bootstrap(),
            ),
            "kama": CandidateEvaluation(
                layer_name="kama",
                decision=PromotionDecision(decision="accept", reasons=[]),
                train_result=_result(0.72, train_dd=-0.09),
                oos_result=_result(0.72),
                bootstrap_report=_bootstrap(),
            ),
            "hull": CandidateEvaluation(
                layer_name="hull",
                decision=PromotionDecision(decision="reject", reasons=["oos"]),
                train_result=_result(0.50),
                oos_result=_result(0.50),
                bootstrap_report=_bootstrap(),
            ),
        }

        directional = [
            LayerSpec(name="ema", family=LayerFamily.DIRECTIONAL_FILTER, parameters={"len": ParameterRange(10, 30, 10)}),
            LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER, parameters={"len": ParameterRange(10, 30, 10)}),
            LayerSpec(name="hull", family=LayerFamily.DIRECTIONAL_FILTER, parameters={"len": ParameterRange(10, 30, 10)}),
        ]
        runner = OvernightRunner(snapshot=_snapshot(), evaluator=lambda _graph, layer: evaluations[layer.name])

        incumbent = StrategyGraph(backbone="mom_squeeze")
        promoted = runner.run_directional_phase(incumbent, directional)

        self.assertEqual(promoted.layers[-1].name, "kama")
        self.assertEqual(len([layer for layer in promoted.layers if layer.family is LayerFamily.DIRECTIONAL_FILTER]), 1)

    def test_phase_three_locks_sequential_flat_filters(self) -> None:
        evaluations = {
            "flat9": CandidateEvaluation("flat9", PromotionDecision("accept", []), _result(0.55), _result(0.55), _bootstrap(median_profit=110.0)),
            "flat11": CandidateEvaluation("flat11", PromotionDecision("wash", ["wash"]), _result(0.56), _result(0.56), _bootstrap(median_profit=111.0)),
            "flat12": CandidateEvaluation("flat12", PromotionDecision("accept", []), _result(0.60), _result(0.60), _bootstrap(median_profit=120.0)),
        }
        filters = [
            LayerSpec(name="flat9", family=LayerFamily.KNOWN_GOOD_FLAT_FILTER, parameters={}),
            LayerSpec(name="flat11", family=LayerFamily.KNOWN_GOOD_FLAT_FILTER, parameters={}),
            LayerSpec(name="flat12", family=LayerFamily.KNOWN_GOOD_FLAT_FILTER, parameters={}),
        ]
        runner = OvernightRunner(snapshot=_snapshot(), evaluator=lambda _graph, layer: evaluations[layer.name])

        promoted = runner.run_sequential_phase(StrategyGraph(backbone="mom_squeeze"), filters)

        self.assertEqual([layer.name for layer in promoted.layers], ["flat9", "flat12"])


if __name__ == "__main__":
    unittest.main()
