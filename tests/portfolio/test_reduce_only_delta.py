from __future__ import annotations

import unittest

from engine.portfolio.delta_order_plan import build_delta_order_plan


class ReduceOnlyDeltaTests(unittest.TestCase):
    def test_reductions_and_closes_are_explicit_reduce_only_actions(self) -> None:
        plan = build_delta_order_plan(
            plan_id="target-v1",
            current_positions={"BTCUSDT": 20_000.0, "ETHUSDT": 5_000.0},
            target_positions=[],
        )

        self.assertEqual([action.symbol for action in plan.closes], ["BTCUSDT", "ETHUSDT"])
        self.assertTrue(all(action.reduce_only for action in plan.closes))
        self.assertTrue(all(intent["reduce_only"] for intent in plan.to_internal_order_intents()))


if __name__ == "__main__":
    unittest.main()
