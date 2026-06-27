from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import DataSnapshot
from engine.data.feature_store import (
    build_fixed_horizon_labels,
    build_meta_label_metadata,
    build_normalized_feature_rows,
    build_triple_barrier_label_metadata,
    embargo_bars_from_policy,
    purge_training_indices_for_label_intervals,
    validate_feature_store,
)
from engine.data.schema import Candle


def _snapshot(*, count: int = 16, timeframe: str = "15Min") -> DataSnapshot:
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            timestamp=base_time + timedelta(minutes=15 * index),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.5 + index,
            volume=10.0 + index,
            trade_count=100 + index,
        )
        for index in range(count)
    ]
    return DataSnapshot(
        snapshot_id="feature-snap",
        symbol="BTCUSDT",
        venue="binance",
        timeframe=timeframe,
        candles=candles,
        funding_rates=[0.0001] * count,
        open_interest=[1_000.0 + index for index in range(count)],
        liquidation_notional=[50.0 + index for index in range(count)],
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        mark_price=[candle.close + 0.1 for candle in candles],
        index_price=[candle.close for candle in candles],
        next_funding_ts=["2024-01-01T08:00:00+00:00"] * count,
        open_interest_usd=[10_000.0 + index for index in range(count)],
        liq_long_usd=[30.0 + index for index in range(count)],
        liq_short_usd=[20.0 + index for index in range(count)],
        spread_bps=[1.5] * count,
        regime_id=["calm"] * count,
        provenance={
            "field_confidence": {
                "ohlcv": "high",
                "trades_or_aggtrades_raw": "high",
                "funding_rate": "high",
                "mark_index": "high",
                "open_interest": "high",
                "live_book_or_trades": "medium_high",
                "liquidation_notional": "medium",
                "historical_l2": "unavailable",
            }
        },
    )


class FeatureStoreTests(unittest.TestCase):
    def test_normalized_rows_emit_exact_15m_contract_and_confidence(self) -> None:
        rows = build_normalized_feature_rows(_snapshot())
        payload = rows[0].contract_payload()

        self.assertEqual(rows[0].ts_close - rows[0].ts_open, timedelta(minutes=15))
        self.assertEqual(payload["source_snapshot_id"], "feature-snap")
        self.assertEqual(payload["open_interest_units"], "quote_notional")
        self.assertEqual(payload["liq_long_notional"], 30.0)
        self.assertEqual(rows[0].field_confidence["funding_rate"], "high")
        self.assertEqual(rows[0].field_confidence["historical_l2"], "unavailable")

        report = validate_feature_store(rows, expected_timeframe="15Min")

        self.assertTrue(report.passed, report.issues)
        self.assertEqual(report.status, "passed")

    def test_time_travel_guards_reject_shifted_sources(self) -> None:
        future_offsets = {
            "funding_rate_last_known": "future_funding_rate_last_known_row=0",
            "open_interest_value": "future_open_interest_value_row=0",
            "liq_long_notional": "future_liq_long_notional_row=0",
            "regime_id": "future_regime_id_row=0",
            "one_hour_signal_close": "future_one_hour_signal_close_row=0",
        }
        for field_name, expected_issue in future_offsets.items():
            with self.subTest(field_name=field_name):
                first_close = _snapshot().candles[0].timestamp + timedelta(minutes=15)
                rows = build_normalized_feature_rows(
                    _snapshot(),
                    row_source_timestamps=[{field_name: first_close + timedelta(minutes=1)}],
                )

                report = validate_feature_store(rows)

                self.assertFalse(report.passed)
                self.assertIn(expected_issue, report.issues)

    def test_labels_store_intervals_and_source_columns(self) -> None:
        rows = build_normalized_feature_rows(_snapshot(count=8))
        fixed = build_fixed_horizon_labels(rows, horizon_bars=2)
        triple = build_triple_barrier_label_metadata(rows, horizon_bars=2)
        meta = build_meta_label_metadata(rows, horizon_bars=2)

        self.assertEqual(fixed[0].t_i, rows[0].ts_close)
        self.assertEqual(fixed[0].T_i, rows[2].ts_close)
        self.assertEqual(fixed[0].horizon_bars, 2)
        self.assertEqual(fixed[0].source_columns, ["close"])
        self.assertEqual(triple[0].source_columns, ["close", "high", "low"])
        self.assertTrue(meta[0].meta_label["ready"])

    def test_purging_uses_label_intervals_and_embargo_policy(self) -> None:
        rows = build_normalized_feature_rows(_snapshot(count=12))
        labels = build_fixed_horizon_labels(rows, horizon_bars=2)

        train_indices = purge_training_indices_for_label_intervals(labels, {4}, embargo_bars=2)

        self.assertNotIn(3, train_indices)
        self.assertNotIn(4, train_indices)
        self.assertNotIn(5, train_indices)
        self.assertNotIn(6, train_indices)
        self.assertIn(1, train_indices)
        self.assertIn(8, train_indices)
        self.assertEqual(embargo_bars_from_policy(dataset_length=100, label_horizon_bars=4, embargo_fraction=0.02, horizon_multiplier=2), 8)
        with self.assertRaises(ValueError):
            embargo_bars_from_policy(dataset_length=100, label_horizon_bars=4, embargo_fraction=0.10)


if __name__ == "__main__":
    unittest.main()
