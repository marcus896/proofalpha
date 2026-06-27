from __future__ import annotations

import unittest

from engine.data.symbol_data_health import assess_symbol_data_health


class SymbolDataHealthTests(unittest.TestCase):
    def test_data_health_report_flags_stale_and_missing_symbol_inputs(self) -> None:
        report = assess_symbol_data_health(
            symbol="BTCUSDT",
            now_utc="2026-05-07T00:10:00Z",
            max_staleness_seconds=300,
            mark_price_ts_utc="2026-05-07T00:00:00Z",
            funding_ts_utc=None,
            open_interest_ts_utc=None,
            book_ts_utc="2026-05-07T00:09:30Z",
            book_gap_count=2,
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.symbol, "BTCUSDT")
        self.assertIn("stale_mark_price", report.issues)
        self.assertIn("missing_funding", report.issues)
        self.assertIn("missing_open_interest", report.issues)
        self.assertIn("book_gap_count=2", report.issues)
        self.assertEqual(report.to_dict()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
