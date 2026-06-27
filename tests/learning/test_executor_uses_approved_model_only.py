from __future__ import annotations

import unittest

from engine.learning.manager import LearningManager
from engine.learning.model_registry import ModelRegistry

from tests.learning.test_model_registry import _card


class ExecutorUsesApprovedModelOnlyTests(unittest.TestCase):
    def test_executor_can_only_resolve_approved_model_versions(self) -> None:
        registry = ModelRegistry()
        registry.register_candidate(_card())
        manager = LearningManager(registry)

        with self.assertRaisesRegex(ValueError, "model_not_approved"):
            manager.executor_model("slippage-v2", mode="paper")

        registry.approve("slippage-v2", mode="paper")
        self.assertEqual(manager.executor_model("slippage-v2", mode="paper").model_id, "slippage-v2")


if __name__ == "__main__":
    unittest.main()
