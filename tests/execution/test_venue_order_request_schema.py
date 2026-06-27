from __future__ import annotations

import unittest

from engine.execution.idempotency import deterministic_client_order_id
from engine.execution.order_intent import InternalOrderIntent
from engine.execution.venue_order_request import build_venue_order_request, validate_venue_order_request


class VenueOrderRequestSchemaTests(unittest.TestCase):
    def test_venue_order_request_uses_deterministic_client_order_id_and_metadata_hash(self) -> None:
        intent = _intent()
        client_id = deterministic_client_order_id(intent, venue="binance_usdm")
        request = build_venue_order_request(
            intent,
            venue="binance_usdm",
            quantity=0.25,
            order_type="LIMIT",
            time_in_force="GTX",
            price=50_000.0,
            timestamp=1778083200000,
        )

        self.assertEqual(request.newClientOrderId, client_id)
        self.assertEqual(request.reduceOnly, intent.reduce_only_required)
        self.assertEqual(len(request.metadata_hash), 64)
        self.assertTrue(validate_venue_order_request(request).passed)


def _intent() -> InternalOrderIntent:
    return InternalOrderIntent.create(
        artifact_id="artifact-btc",
        portfolio_plan_id="portfolio-v1",
        symbol="BTCUSDT",
        desired_position_delta=12_500.0,
        side="BUY",
        intent_type="increase",
        urgency="normal",
        reduce_only_required=False,
        max_slippage_bps=8.0,
        max_spread_bps=5.0,
        max_participation_rate=0.10,
        funding_guard_policy="block_if_positive_cost_gt_budget",
        liquidation_guard_policy="block_if_liquidation_buffer_breached",
        created_at="2026-05-07T00:00:00Z",
        expires_at="2026-05-07T00:15:00Z",
    )


if __name__ == "__main__":
    unittest.main()
