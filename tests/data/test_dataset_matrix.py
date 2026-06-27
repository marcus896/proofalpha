from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path


def _write_candles(path: Path, timestamps: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "trade_count"])
        for index, timestamp in enumerate(timestamps, start=1):
            price = 100.0 + index
            writer.writerow([timestamp, price, price + 1.0, price - 1.0, price, 10.0, 1])


class DatasetMatrixTests(unittest.TestCase):
    def test_builds_year_symbol_timeframe_matrix_from_strict_inventory(self) -> None:
        from engine.data.dataset_matrix import build_dataset_matrix_from_inventory

        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            candles = tmp / "BTCUSDT-1h" / "candles.csv"
            _write_candles(
                candles,
                [
                    "2024-12-31T23:00:00+00:00",
                    "2025-01-01T00:00:00+00:00",
                    "2025-06-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ],
            )
            inventory = {
                "profile": "strict_v3",
                "archive": {
                    "bundles": [
                        {
                            "symbol": "BTCUSDT",
                            "timeframe": "1Hour",
                            "status": "collected",
                            "candles": str(candles),
                            "rows": 4,
                            "provider": "binance_public_archive",
                            "source_hash_present": True,
                            "fetch_manifest_present": True,
                            "field_confidence": {
                                "funding_rate": "observed",
                                "open_interest": "observed",
                                "liquidation_notional": "observed_public_forceorder_with_zero_buckets",
                            },
                        }
                    ]
                },
            }

            report = build_dataset_matrix_from_inventory(
                inventory,
                workspace=tmp,
                required_symbols=("BTCUSDT",),
                required_timeframes=("1Hour",),
                minimum_distinct_years=3,
                required_sidecar_fields=("funding_rate", "open_interest", "liquidation_notional"),
            )

        self.assertEqual(report["artifact_type"], "dataset_matrix")
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["robustness_ready"])
        self.assertEqual(report["symbols"], ["BTCUSDT"])
        self.assertEqual(report["timeframes"], ["1Hour"])
        self.assertEqual(report["distinct_years"], ["2024", "2025", "2026"])
        self.assertEqual(report["blockers"], [])
        coverage = report["coverage"][0]
        self.assertEqual(coverage["first_timestamp"], "2024-12-31T23:00:00+00:00")
        self.assertEqual(coverage["last_timestamp"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(coverage["year_rows"], {"2024": 1, "2025": 2, "2026": 1})

    def test_blocks_missing_bundle_and_unavailable_required_sidecar(self) -> None:
        from engine.data.dataset_matrix import build_dataset_matrix_from_inventory

        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            candles = tmp / "BTCUSDT-1h" / "candles.csv"
            _write_candles(
                candles,
                [
                    "2025-01-01T00:00:00+00:00",
                    "2025-01-01T01:00:00+00:00",
                ],
            )
            inventory = {
                "profile": "strict_v3",
                "archive": {
                    "bundles": [
                        {
                            "symbol": "BTCUSDT",
                            "timeframe": "1Hour",
                            "status": "collected",
                            "candles": str(candles),
                            "rows": 2,
                            "provider": "binance_public_archive",
                            "source_hash_present": True,
                            "fetch_manifest_present": True,
                            "field_confidence": {
                                "liquidation_notional": "unavailable_archive_sidecar_empty_do_not_treat_zero_as_truth",
                            },
                        }
                    ]
                },
            }

            report = build_dataset_matrix_from_inventory(
                inventory,
                workspace=tmp,
                required_symbols=("BTCUSDT", "ETHUSDT"),
                required_timeframes=("1Hour",),
                minimum_distinct_years=3,
                required_sidecar_fields=("liquidation_notional",),
            )

        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["robustness_ready"])
        self.assertIn("missing_bundle:ETHUSDT:1Hour", report["blockers"])
        self.assertIn("insufficient_distinct_years:BTCUSDT:1Hour", report["blockers"])
        self.assertIn("missing_required_sidecar:BTCUSDT:1Hour:liquidation_notional", report["blockers"])


if __name__ == "__main__":
    unittest.main()
