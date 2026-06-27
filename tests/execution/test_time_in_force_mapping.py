from __future__ import annotations

import unittest

from engine.execution.order_intent import InternalOrderIntent
from engine.execution.venue_translator.binance_usdm import BinanceUsdMTranslator

from tests.execution.test_tick_step_min_notional import _rules_cache
from tests.execution.test_venue_order_request_schema import _intent


class TimeInForceMappingTests(unittest.TestCase):
    def test_passive_maps_to_gtx_and_urgent_maps_to_ioc(self) -> None:
        translator = BinanceUsdMTranslator(_rules_cache())
        passive = translator.translate(_intent(), quantity=0.1, price=50_000.0, passive=True, timestamp=1778083200000)
        urgent_intent = InternalOrderIntent.create(
            artifact_id="artifact-btc",
            portfolio_plan_id="portfolio-v1",
            symbol="BTCUSDT",
            desired_position_delta=12_500.0,
            side="BUY",
            intent_type="increase",
            urgency="urgent",
            reduce_only_required=False,
            max_slippage_bps=8.0,
            max_spread_bps=5.0,
            max_participation_rate=0.10,
            funding_guard_policy="block_if_positive_cost_gt_budget",
            liquidation_guard_policy="block_if_liquidation_buffer_breached",
            created_at="2026-05-07T00:00:00Z",
            expires_at="2026-05-07T00:15:00Z",
        )
        urgent = translator.translate(urgent_intent, quantity=0.1, price=50_000.0, timestamp=1778083200000)

        self.assertEqual(passive.rounded_order["timeInForce"], "GTX")
        self.assertEqual(urgent.rounded_order["timeInForce"], "IOC")


if __name__ == "__main__":
    unittest.main()
