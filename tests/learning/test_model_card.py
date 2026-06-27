from __future__ import annotations

import unittest

from engine.learning.model_card import ModelCard, validate_model_card


class ModelCardTests(unittest.TestCase):
    def test_model_card_records_training_validation_shadow_paper_and_rollback(self) -> None:
        card = ModelCard(
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

        self.assertTrue(validate_model_card(card).passed)
        self.assertEqual(card.to_dict()["rollback_model_id"], "slippage-v1")


if __name__ == "__main__":
    unittest.main()
