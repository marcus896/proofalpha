from __future__ import annotations

import unittest

from engine.execution.venue_translator.binance_usdm import BinanceUsdMTranslator

from tests.execution.test_tick_step_min_notional import _rules_cache
from tests.execution.test_venue_order_request_schema import _intent


class TranslationReportTests(unittest.TestCase):
    def test_translation_report_contains_raw_intent_order_rules_and_rejections(self) -> None:
        report = BinanceUsdMTranslator(_rules_cache()).translate(
            _intent(), quantity=0.0001, price=50_000.0, timestamp=1778083200000
        )

        payload = report.to_dict()
        self.assertFalse(report.passed)
        self.assertEqual(payload["raw_intent"]["symbol"], "BTCUSDT")
        self.assertEqual(len(payload["rule_snapshot_hash"]), 64)
        self.assertIn("min_notional_violation", payload["rejection_reasons"])
        self.assertIn("rounded_order", payload)


if __name__ == "__main__":
    unittest.main()
