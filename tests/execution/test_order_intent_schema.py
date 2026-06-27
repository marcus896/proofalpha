from __future__ import annotations

import unittest

from engine.execution.order_intent import InternalOrderIntent, validate_internal_order_intent


class OrderIntentSchemaTests(unittest.TestCase):
    def test_internal_order_intent_has_required_authority_and_risk_bounds(self) -> None:
        intent = InternalOrderIntent.create(
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

        validation = validate_internal_order_intent(intent)

        self.assertTrue(validation.passed, validation.issues)
        self.assertEqual(len(intent.intent_id), 48)
        self.assertEqual(intent.to_dict()["portfolio_plan_id"], "portfolio-v1")

    def test_internal_order_intent_rejects_non_finite_numeric_bounds(self) -> None:
        intent = InternalOrderIntent.create(
            artifact_id="artifact-btc",
            portfolio_plan_id="portfolio-v1",
            symbol="BTCUSDT",
            desired_position_delta=float("inf"),
            side="BUY",
            intent_type="increase",
            urgency="normal",
            reduce_only_required=False,
            max_slippage_bps=float("nan"),
            max_spread_bps=5.0,
            max_participation_rate=0.10,
            funding_guard_policy="block_if_positive_cost_gt_budget",
            liquidation_guard_policy="block_if_liquidation_buffer_breached",
            created_at="2026-05-07T00:00:00Z",
            expires_at="2026-05-07T00:15:00Z",
        )

        validation = validate_internal_order_intent(intent)

        self.assertFalse(validation.passed)
        self.assertIn("non_finite_desired_position_delta", validation.issues)
        self.assertIn("non_finite_risk_bound", validation.issues)


if __name__ == "__main__":
    unittest.main()
