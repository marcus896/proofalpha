import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import BacktestResult, DataSnapshot, SnapshotQualityReport, StrategyGraph, VenueProfile
from engine.data.schema import Candle
from engine.validation.permutation import permute_snapshot_path, run_in_sample_permutation_test


def _snapshot() -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    closes = [
        100.0,
        102.0,
        104.0,
        106.0,
        108.0,
        110.0,
        108.0,
        106.0,
        104.0,
        102.0,
        100.0,
        98.0,
    ]
    candles = [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=close - 0.5,
            high=close + 0.5,
            low=close - 1.0,
            close=close,
            volume=1_000.0 + index,
        )
        for index, close in enumerate(closes)
    ]
    return DataSnapshot(
        snapshot_id="permutation-snapshot",
        symbol="SOLUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=[0.001 * ((index % 3) - 1) for index in range(len(candles))],
        open_interest=[100.0 + index for index in range(len(candles))],
        liquidation_notional=[5.0 * index for index in range(len(candles))],
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        quality_flags=[],
        venue_profile=VenueProfile(
            venue="binance",
            funding_interval_h=8,
            maintenance_margin_schedule=[{"max_leverage": 20.0, "maintenance_margin_ratio": 0.025}],
            liquidation_fee_schedule=[{"max_leverage": 20.0, "liquidation_fee_bps": 40.0}],
            liquidation_style="partial",
        ),
        quality_report=SnapshotQualityReport(
            report_id="permutation-quality",
            snapshot_id="permutation-snapshot",
            quality_score=0.95,
            passed=True,
            issues=[],
            metrics={"row_count": len(candles)},
            source_checks={"provider": "fixture"},
        ),
        provenance={"provider": "fixture", "build_mode": "test"},
    )


def _autocorrelation_evaluator(snapshot: DataSnapshot, _strategy: StrategyGraph) -> BacktestResult:
    closes = [candle.close for candle in snapshot.candles]
    deltas = [right - left for left, right in zip(closes, closes[1:])]
    autocorrelation = sum(left * right for left, right in zip(deltas, deltas[1:])) / max(1, len(deltas) - 1)
    equity_curve: list[float] = []
    running = 0.0
    for delta in deltas:
        running += delta
        equity_curve.append(running)
    return BacktestResult(
        trade_count=max(1, len(deltas)),
        win_rate=0.5,
        gross_pnl=running,
        net_pnl=running,
        fee_spend=0.0,
        funding_spend=0.0,
        sharpe=autocorrelation,
        sortino=autocorrelation,
        max_drawdown=-0.1,
        equity_curve=equity_curve,
        liquidation_events=[],
    )


class PermutationValidationTests(unittest.TestCase):
    def test_permute_snapshot_path_keeps_series_aligned(self) -> None:
        snapshot = _snapshot()

        permuted = permute_snapshot_path(snapshot, seed=7)

        self.assertEqual(permuted.snapshot_id, "permutation-snapshot:permuted:7")
        self.assertEqual(len(permuted.candles), len(snapshot.candles))
        self.assertEqual(len(permuted.funding_rates), len(snapshot.funding_rates))
        self.assertEqual(len(permuted.open_interest), len(snapshot.open_interest))
        self.assertEqual(len(permuted.liquidation_notional), len(snapshot.liquidation_notional))
        self.assertEqual(permuted.candles[0].timestamp, snapshot.candles[0].timestamp)
        self.assertNotEqual(
            [candle.close for candle in permuted.candles],
            [candle.close for candle in snapshot.candles],
        )
        self.assertIsNotNone(permuted.venue_profile)
        self.assertEqual(permuted.venue_profile.funding_interval_h, 8)
        self.assertIsNotNone(permuted.quality_report)
        self.assertEqual(permuted.quality_report.snapshot_id, permuted.snapshot_id)
        self.assertEqual(permuted.provenance["derived_from_snapshot_id"], snapshot.snapshot_id)
        self.assertEqual(permuted.provenance["transformation"], "permutation")
        self.assertEqual(permuted.provenance["seed"], 7)
        self.assertEqual(
            permuted.quality_report.source_checks["derived_from_snapshot_id"],
            snapshot.snapshot_id,
        )

    def test_in_sample_permutation_test_is_seeded_and_penalizes_order_dependent_edge(self) -> None:
        snapshot = _snapshot()
        strategy = StrategyGraph(backbone="mom_squeeze")

        first = run_in_sample_permutation_test(
            snapshot=snapshot,
            strategy=strategy,
            evaluate_strategy=_autocorrelation_evaluator,
            permutation_count=64,
            seed=11,
        )
        second = run_in_sample_permutation_test(
            snapshot=snapshot,
            strategy=strategy,
            evaluate_strategy=_autocorrelation_evaluator,
            permutation_count=64,
            seed=11,
        )

        self.assertEqual(first.pvalue, second.pvalue)
        self.assertGreater(first.observed_metric, 0.0)
        self.assertLess(first.pvalue, 0.10)


if __name__ == "__main__":
    unittest.main()
