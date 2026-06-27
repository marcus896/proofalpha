from __future__ import annotations

import unittest

from engine.learning.model_registry import ModelRegistry
from engine.learning.rollback import build_model_rollback_plan

from tests.learning.test_model_registry import _card


class RollbackTests(unittest.TestCase):
    def test_rollback_returns_to_declared_parent_model(self) -> None:
        registry = ModelRegistry()
        registry.register_candidate(_card())
        registry.approve("slippage-v2", mode="paper")

        plan = build_model_rollback_plan(registry, model_id="slippage-v2", reason="shadow_degraded")

        self.assertTrue(plan.allowed)
        self.assertEqual(plan.rollback_model_id, "slippage-v1")
        self.assertEqual(plan.reason, "shadow_degraded")


if __name__ == "__main__":
    unittest.main()
