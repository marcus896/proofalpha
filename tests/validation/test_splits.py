import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import DataSnapshot
from engine.data.schema import Candle
from engine.validation.splits import build_split_pack


class SplitPackTests(unittest.TestCase):
    def test_builds_chronological_60_20_20_splits(self) -> None:
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(timestamp=base_time + timedelta(hours=index), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0)
            for index in range(100)
        ]
        snapshot = DataSnapshot(
            snapshot_id="snapshot",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * 100,
            open_interest=[100.0] * 100,
            liquidation_notional=[0.0] * 100,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )

        split_pack = build_split_pack(snapshot)

        self.assertEqual(len(split_pack.in_sample.candles), 60)
        self.assertEqual(len(split_pack.selection_oos.candles), 20)
        self.assertEqual(len(split_pack.final_holdout.candles), 20)
        self.assertEqual(len(split_pack.regime_labels), 100)
        self.assertEqual(split_pack.regime_model, "deterministic")
        self.assertIn("regime_state_key", split_pack.regime_metadata)
        self.assertAlmostEqual(sum(split_pack.regime_coverage.values()), 1.0, places=6)
        self.assertLess(split_pack.in_sample.candles[-1].timestamp, split_pack.selection_oos.candles[0].timestamp)
        self.assertLess(split_pack.selection_oos.candles[-1].timestamp, split_pack.final_holdout.candles[0].timestamp)

    def test_builds_split_pack_with_hsmm_regime_model(self) -> None:
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(timestamp=base_time + timedelta(hours=index), open=100.0, high=101.0, low=99.0, close=100.0 + index, volume=1000.0)
            for index in range(40)
        ]
        snapshot = DataSnapshot(
            snapshot_id="snapshot-hsmm",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.001] * 40,
            open_interest=[100.0 + index for index in range(40)],
            liquidation_notional=[0.0] * 40,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )

        split_pack = build_split_pack(snapshot, regime_model="hsmm", regime_n_states=4)

        self.assertEqual(split_pack.regime_model, "hsmm")
        self.assertTrue(split_pack.regime_metadata["duration_aware"])
        self.assertEqual(len(split_pack.regime_labels), 40)

    def test_blocks_validation_when_feature_quality_failed(self) -> None:
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(timestamp=base_time + timedelta(hours=index), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0)
            for index in range(20)
        ]
        snapshot = DataSnapshot(
            snapshot_id="snapshot-dirty-features",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * 20,
            open_interest=[100.0] * 20,
            liquidation_notional=[0.0] * 20,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
            provenance={
                "feature_quality_status": "failed",
                "feature_quality_report": {
                    "passed": False,
                    "issues": ["future_funding_rate_last_known_row=0"],
                },
            },
        )

        with self.assertRaisesRegex(ValueError, "feature quality failed"):
            build_split_pack(snapshot)


if __name__ == "__main__":
    unittest.main()
