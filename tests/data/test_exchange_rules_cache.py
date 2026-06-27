from __future__ import annotations

import unittest

from engine.data.exchange_rules_cache import ExchangeRulesCache


class ExchangeRulesCacheTests(unittest.TestCase):
    def test_exchange_rules_are_cached_with_snapshot_hash(self) -> None:
        cache = ExchangeRulesCache.from_exchange_info(
            [
                {
                    "symbol": "BTCUSDT",
                    "filters": {
                        "PRICE_FILTER": {"tickSize": "0.10"},
                        "LOT_SIZE": {"stepSize": "0.001"},
                        "MIN_NOTIONAL": {"notional": "5"},
                    },
                    "orderTypes": ["LIMIT", "MARKET"],
                    "leverageBrackets": [{"initialLeverage": 50}],
                    "marginAsset": "USDT",
                }
            ],
            source="fixture-binance-usdm",
            created_at_utc="2026-05-07T00:00:00Z",
        )

        rules = cache.get("BTCUSDT")

        self.assertEqual(rules.tick_size, 0.1)
        self.assertEqual(rules.step_size, 0.001)
        self.assertEqual(rules.min_notional, 5.0)
        self.assertIn("LIMIT", rules.order_types)
        self.assertEqual(len(cache.snapshot_hash), 64)
        self.assertEqual(cache.to_dict()["symbols"]["BTCUSDT"]["margin_asset"], "USDT")


if __name__ == "__main__":
    unittest.main()
