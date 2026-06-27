from __future__ import annotations

import unittest

from engine.learning.model_card import ModelCard
from engine.learning.model_registry import ModelRegistry


class ModelRegistryTests(unittest.TestCase):
    def test_registry_approves_only_carded_models_for_allowed_modes(self) -> None:
        registry = ModelRegistry()
        card = _card()

        registry.register_candidate(card)
        approved = registry.approve("slippage-v2", mode="paper")

        self.assertTrue(approved.approved)
        self.assertEqual(registry.model_for_executor("slippage-v2", mode="paper").model_id, "slippage-v2")


def _card() -> ModelCard:
    return ModelCard(
        model_id="slippage-v2",
        parent_model_id="slippage-v1",
        family="SlippageModel",
        training_window="2026-04-01/2026-05-01",
        symbols_used=["BTCUSDT"],
        features_used=["spread_bps"],
        target="slip_bps",
        validation_metric={"mae_bps": 1.2},
        shadow_result={"passed": True},
        paper_result={"passed": True},
        approved_modes=["shadow", "paper"],
        known_failures=[],
        rollback_model_id="slippage-v1",
    )


if __name__ == "__main__":
    unittest.main()
