import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import BacktestResult, DataSnapshot, StrategyGraph
from engine.data.schema import Candle
from engine.validation.protocol import run_validation_protocol
from engine.validation.splits import build_split_pack
from engine.validation.statistics import (
    compute_deflated_sharpe_ratio,
    compute_minimum_backtest_length,
    compute_observed_sharpe_ratio,
    compute_probabilistic_sharpe_ratio,
)


class ValidationStatisticsTests(unittest.TestCase):
    def test_probabilistic_sharpe_ratio_is_high_for_consistently_positive_returns(self) -> None:
        returns = [0.012, 0.015, 0.011, 0.014, 0.016, 0.013, 0.012, 0.017, 0.014, 0.015]

        psr = compute_probabilistic_sharpe_ratio(returns, benchmark_sharpe=0.0)

        self.assertGreater(psr, 0.95)

    def test_deflated_sharpe_ratio_decreases_as_trial_count_rises(self) -> None:
        returns = [0.011, 0.013, 0.012, 0.014, 0.016, 0.012, 0.015, 0.014, 0.013, 0.017]

        dsr_one_trial = compute_deflated_sharpe_ratio(returns, trial_count=1)
        dsr_many_trials = compute_deflated_sharpe_ratio(returns, trial_count=64)

        self.assertGreater(dsr_one_trial, dsr_many_trials)

    def test_compute_minimum_backtest_length_calculates_valid_track_record(self) -> None:
        # Very high sharpe ratio -> needs few samples
        high_sr_returns = [0.05] * 10
        high_sr_returns[0] = 0.04
        high_sr_returns[1] = 0.06
        
        # Low but positive sharpe -> needs many samples
        low_sr_returns = [0.01, -0.01, 0.01, -0.009, 0.011, -0.008, 0.009, -0.01]

        high_sr_btl = compute_minimum_backtest_length(high_sr_returns, target_psr=0.95)
        low_sr_btl = compute_minimum_backtest_length(low_sr_returns, target_psr=0.95)

        self.assertGreater(high_sr_btl, 2)
        self.assertGreater(low_sr_btl, high_sr_btl)

    def test_compute_minimum_backtest_length_returns_zero_for_too_short_series(self) -> None:
        self.assertEqual(compute_minimum_backtest_length([0.01, 0.02, 0.03], target_psr=0.95), 0)

    def test_compute_minimum_backtest_length_returns_effectively_infinite_when_edge_is_non_positive(self) -> None:
        returns = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01]

        min_btl = compute_minimum_backtest_length(returns, target_sharpe=0.05, target_psr=0.95)

        self.assertEqual(min_btl, 9_999_999)

    def test_validation_protocol_marks_spa_unavailable_as_skipped(self) -> None:
        split_pack = build_split_pack(_validation_snapshot())
        strategy = StrategyGraph(backbone="mom_squeeze")

        validation = run_validation_protocol(
            split_pack=split_pack,
            strategy=strategy,
            evaluate_strategy=_evaluate_validation_strategy,
            trial_count=8,
            permutation_count=8,
            gate_min_backtest_length=True,
            seed=7,
        )

        spa_stage = next(stage for stage in validation.stage_results if stage.stage_name == "spa")
        self.assertFalse(spa_stage.metrics["available"])
        self.assertFalse(spa_stage.metrics["enforced"])

    def test_validation_protocol_uses_candidate_return_series_for_pbo(self) -> None:
        split_pack = build_split_pack(_validation_snapshot())
        strategy = StrategyGraph(backbone="mom_squeeze")

        validation = run_validation_protocol(
            split_pack=split_pack,
            strategy=strategy,
            evaluate_strategy=_evaluate_validation_strategy,
            trial_count=8,
            permutation_count=8,
            gate_min_backtest_length=True,
            candidate_return_series=[
                [0.08, 0.07, 0.09, 0.08, 0.09, 0.07, 0.08, 0.09],
                [0.05, 0.05, 0.04, 0.05, 0.04, 0.05, 0.04, 0.05],
                [-0.01, 0.00, -0.02, -0.01, 0.00, -0.01, -0.02, -0.01],
            ],
            seed=7,
        )

        pbo_stage = next(stage for stage in validation.stage_results if stage.stage_name == "pbo")
        self.assertTrue(pbo_stage.metrics["available"])
        self.assertEqual(pbo_stage.metrics["model_count"], 3)

    def test_validation_protocol_emits_strict_phase2_bundle_fields(self) -> None:
        split_pack = build_split_pack(_validation_snapshot())
        strategy = StrategyGraph(backbone="mom_squeeze")

        validation = run_validation_protocol(
            split_pack=split_pack,
            strategy=strategy,
            evaluate_strategy=_evaluate_validation_strategy,
            trial_count=8,
            permutation_count=8,
            gate_min_backtest_length=True,
            candidate_return_series=[
                [0.08, 0.07, 0.09, 0.08, 0.09, 0.07, 0.08, 0.09],
                [0.05, 0.05, 0.04, 0.05, 0.04, 0.05, 0.04, 0.05],
                [-0.01, 0.00, -0.02, -0.01, 0.00, -0.01, -0.02, -0.01],
            ],
            n_blocks=12,
            n_test_blocks=3,
            feature_lookback_bars=5,
            barrier_horizon_bars=7,
            holding_horizon_bars=4,
            embargo_bars=2,
            seed=7,
        )

        self.assertEqual(validation.cpcv_config["method"], "combinatorial_purged_cv")
        self.assertEqual(validation.n_blocks, 12)
        self.assertEqual(validation.n_test_blocks, 3)
        self.assertEqual(validation.purge_bars, 7)
        self.assertEqual(validation.embargo_bars, 2)
        self.assertEqual(validation.cpcv_config["purge_bars"], 7)
        self.assertEqual(validation.cpcv_config["embargo_bars"], 2)
        self.assertEqual(validation.in_sample_summary["trade_count"], 17)
        self.assertEqual(validation.selection_oos_summary["trade_count"], 5)
        self.assertEqual(validation.holdout_summary["trade_count"], 5)
        self.assertEqual(validation.min_trade_count, 5)
        self.assertEqual(validation.min_backtest_length, 2)


def _validation_snapshot() -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=100.0 + (index * 0.4),
            high=100.5 + (index * 0.4),
            low=99.5 + (index * 0.4),
            close=100.0 + (index * 0.4) + (0.15 if index % 2 == 0 else -0.05),
            volume=1_000.0,
        )
        for index in range(120)
    ]
    return DataSnapshot(
        snapshot_id="validation-statistics",
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


def _evaluate_validation_strategy(snapshot: DataSnapshot, _strategy: StrategyGraph) -> BacktestResult:
    closes = [float(candle.close) for candle in snapshot.candles]
    if len(closes) < 2:
        returns = [0.0]
    else:
        returns = [current - previous for previous, current in zip(closes, closes[1:])]
    sharpe = compute_observed_sharpe_ratio(returns)
    max_drawdown = min(0.0, min((equity / max(closes[0], 1.0)) - 1.0 for equity in closes))
    return BacktestResult(
        trade_count=max(1, len(returns) // 4),
        win_rate=sum(1 for value in returns if value > 0.0) / max(1, len(returns)),
        gross_pnl=closes[-1] - closes[0],
        net_pnl=(closes[-1] - closes[0]) - 1.0,
        fee_spend=0.5,
        funding_spend=0.5,
        sharpe=sharpe,
        sortino=sharpe,
        max_drawdown=max_drawdown,
        equity_curve=closes,
        liquidation_events=[],
    )

if __name__ == "__main__":
    unittest.main()
