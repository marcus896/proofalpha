from __future__ import annotations

import unittest

from engine.execution.venue_translator.binance_usdm import BinanceUsdMTranslator

from tests.execution.test_venue_order_request_schema import _intent
from tests.execution.test_tick_step_min_notional import _rules_cache


class BinanceUsdMTranslatorTests(unittest.TestCase):
    def test_translator_builds_venue_order_request_from_internal_intent(self) -> None:
        report = BinanceUsdMTranslator(_rules_cache()).translate(
            _intent(),
            quantity=0.2519,
            price=50000.129,
            timestamp=1778083200000,
        )

        self.assertTrue(report.passed, report.rejection_reasons)
        self.assertEqual(report.rounded_order["symbol"], "BTCUSDT")
        self.assertEqual(report.rounded_order["quantity"], 0.251)
        self.assertEqual(report.rounded_order["price"], 50000.1)
        self.assertEqual(report.rounded_order["timeInForce"], "GTC")


if __name__ == "__main__":
    unittest.main()
