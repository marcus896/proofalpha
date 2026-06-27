from __future__ import annotations

import unittest

from engine.portfolio.delta_order_plan import build_delta_order_plan
from engine.portfolio.symbol_target import SymbolTarget


class DeltaOrderPlanTests(unittest.TestCase):
    def test_current_positions_become_explicit_delta_actions_and_order_intents(self) -> None:
        plan = build_delta_order_plan(
            plan_id="target-v1",
            current_positions={"BTCUSDT": 10_000.0},
            target_positions=[
                SymbolTarget(
                    symbol="BTCUSDT",
                    artifact_id="artifact-btc",
                    role="core",
                    target_weight=0.25,
                    target_notional=25_000.0,
                    max_loss_budget=1_000.0,
                    max_slippage_bps=8.0,
                    max_funding_cost_bps=4.0,
                    rebalance_reason="drift",
                )
            ],
            fee_bps=2.0,
            slippage_bps=3.0,
            funding_cost_bps=1.0,
        )

        self.assertEqual(plan.increases[0].delta_notional, 15_000.0)
        self.assertEqual(plan.opens, ())
        intents = plan.to_internal_order_intents()
        self.assertEqual(intents[0]["symbol"], "BTCUSDT")
        self.assertEqual(intents[0]["side"], "BUY")
        self.assertFalse(intents[0]["reduce_only"])
        self.assertEqual(intents[0]["source_delta_plan_id"], plan.delta_order_plan_id)


if __name__ == "__main__":
    unittest.main()
