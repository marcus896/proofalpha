from __future__ import annotations

import unittest

from engine.learning.model_registry import ModelRegistry


class ModelPromotionRequiresCardTests(unittest.TestCase):
    def test_candidate_model_cannot_promote_without_card(self) -> None:
        registry = ModelRegistry()

        result = registry.approve("missing-model", mode="paper")

        self.assertFalse(result.approved)
        self.assertIn("missing_model_card", result.reasons)


if __name__ == "__main__":
    unittest.main()
