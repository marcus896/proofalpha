from __future__ import annotations

import unittest

from engine.data.validate import validate_snapshot_bundle


class SnapshotValidationTests(unittest.TestCase):
    def test_validate_snapshot_bundle_flags_missing_hours(self) -> None:
        report = validate_snapshot_bundle(
            candle_timestamps=[
                "2024-01-01T00:00:00+00:00",
                "2024-01-01T02:00:00+00:00",
            ],
            candle_opens=[100.0, 101.0],
            candle_highs=[101.0, 102.0],
            candle_lows=[99.0, 100.0],
            candle_closes=[100.5, 101.5],
            candle_volumes=[1000.0, 1001.0],
            funding_rates=[0.0, 0.0],
            open_interest=[100.0, 100.0],
            liquidation_notional=[0.0, 0.0],
            timeframe="1Hour",
        )

        self.assertIn("timestamp_gap_count=1", report["warnings"])
        self.assertFalse(report["passed"])

    def test_validate_snapshot_bundle_flags_negative_open_interest(self) -> None:
        report = validate_snapshot_bundle(
            candle_timestamps=["2024-01-01T00:00:00+00:00"],
            candle_opens=[100.0],
            candle_highs=[101.0],
            candle_lows=[99.0],
            candle_closes=[100.5],
            candle_volumes=[1000.0],
            funding_rates=[0.0],
            open_interest=[-1.0],
            liquidation_notional=[0.0],
            timeframe="1Hour",
        )

        self.assertIn("negative_open_interest_count=1", report["warnings"])
        self.assertFalse(report["passed"])

    def test_validate_snapshot_bundle_passes_clean_snapshot(self) -> None:
        report = validate_snapshot_bundle(
            candle_timestamps=[
                "2024-01-01T00:00:00+00:00",
                "2024-01-01T01:00:00+00:00",
            ],
            candle_opens=[100.0, 101.0],
            candle_highs=[102.0, 103.0],
            candle_lows=[99.0, 100.0],
            candle_closes=[101.0, 102.0],
            candle_volumes=[1000.0, 1001.0],
            funding_rates=[0.0, 0.01],
            open_interest=[100.0, 120.0],
            liquidation_notional=[0.0, 5.0],
            timeframe="1Hour",
        )

        self.assertEqual(report["warnings"], [])
        self.assertTrue(report["passed"])

    def test_validate_snapshot_bundle_flags_duplicate_timestamps(self) -> None:
        report = validate_snapshot_bundle(
            candle_timestamps=[
                "2024-01-01T00:00:00+00:00",
                "2024-01-01T00:00:00+00:00",
            ],
            candle_opens=[100.0, 101.0],
            candle_highs=[102.0, 103.0],
            candle_lows=[99.0, 100.0],
            candle_closes=[101.0, 102.0],
            candle_volumes=[1000.0, 1001.0],
            funding_rates=[0.0, 0.01],
            open_interest=[100.0, 120.0],
            liquidation_notional=[0.0, 5.0],
            timeframe="1Hour",
        )

        self.assertIn("duplicate_timestamp_count=1", report["warnings"])
        self.assertFalse(report["passed"])

    def test_validate_snapshot_bundle_flags_price_sanity_issues(self) -> None:
        report = validate_snapshot_bundle(
            candle_timestamps=["2024-01-01T00:00:00+00:00"],
            candle_opens=[100.0],
            candle_highs=[99.0],
            candle_lows=[101.0],
            candle_closes=[100.5],
            candle_volumes=[1000.0],
            funding_rates=[0.0],
            open_interest=[100.0],
            liquidation_notional=[0.0],
            timeframe="1Hour",
        )

        self.assertIn("price_sanity_count=1", report["warnings"])
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
