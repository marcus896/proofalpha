from __future__ import annotations

import unittest

from engine.execution.venue_translator.binance_usdm import BinanceUsdMTranslator

from tests.execution.test_tick_step_min_notional import _rules_cache
from tests.execution.test_venue_order_request_schema import _intent


class MarginLeverageStateCheckTests(unittest.TestCase):
    def test_margin_and_leverage_state_are_checked(self) -> None:
        report = BinanceUsdMTranslator(_rules_cache(), margin_mode="portfolio", leverage=75).translate(
            _intent(), quantity=0.1, price=50_000.0, timestamp=1778083200000
        )

        self.assertFalse(report.passed)
        self.assertIn("invalid_margin_mode", report.rejection_reasons)
        self.assertIn("leverage_exceeds_symbol_bracket", report.rejection_reasons)


if __name__ == "__main__":
    unittest.main()
