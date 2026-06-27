from __future__ import annotations

import unittest

from engine.data.exchange_rules_cache import ExchangeRulesCache
from engine.execution.venue_translator.binance_usdm import BinanceUsdMTranslator

from tests.execution.test_venue_order_request_schema import _intent


class TickStepMinNotionalTests(unittest.TestCase):
    def test_tick_step_rounding_and_min_notional_rejection(self) -> None:
        translator = BinanceUsdMTranslator(_rules_cache())
        rounded = translator.translate(_intent(), quantity=0.2519, price=50000.129, timestamp=1778083200000)
        too_small = translator.translate(_intent(), quantity=0.0001, price=50000.0, timestamp=1778083200000)

        self.assertEqual(rounded.rounded_order["quantity"], 0.251)
        self.assertEqual(rounded.rounded_order["price"], 50000.1)
        self.assertFalse(too_small.passed)
        self.assertIn("min_notional_violation", too_small.rejection_reasons)

    def test_translator_rejects_non_finite_or_non_positive_quantity_and_price(self) -> None:
        translator = BinanceUsdMTranslator(_rules_cache())

        non_finite = translator.translate(_intent(), quantity=0.1, price=float("nan"), timestamp=1778083200000)
        negative_quantity = translator.translate(_intent(), quantity=-0.1, price=50000.0, timestamp=1778083200000)
        zero_price = translator.translate(_intent(), quantity=0.1, price=0.0, timestamp=1778083200000)

        self.assertFalse(non_finite.passed)
        self.assertIn("non_finite_price", non_finite.rejection_reasons)
        self.assertFalse(negative_quantity.passed)
        self.assertIn("quantity_not_positive", negative_quantity.rejection_reasons)
        self.assertFalse(zero_price.passed)
        self.assertIn("price_not_positive", zero_price.rejection_reasons)


def _rules_cache() -> ExchangeRulesCache:
    return ExchangeRulesCache.from_exchange_info(
        [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "contractType": "PERPETUAL",
                "quoteAsset": "USDT",
                "filters": {
                    "PRICE_FILTER": {"tickSize": "0.10"},
                    "LOT_SIZE": {"stepSize": "0.001"},
                    "MIN_NOTIONAL": {"notional": "5"},
                },
                "orderTypes": ["LIMIT", "MARKET", "STOP_MARKET"],
                "leverageBrackets": [{"initialLeverage": 50}],
                "marginAsset": "USDT",
            }
        ],
        source="fixture-binance-usdm",
        created_at_utc="2026-05-07T00:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
