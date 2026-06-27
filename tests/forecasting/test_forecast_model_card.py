from __future__ import annotations

import unittest

from engine.forecasting.forecast_model_card import ForecastModelCard, validate_forecast_model_card


class ForecastModelCardTests(unittest.TestCase):
    def test_forecast_model_card_records_governance_boundary(self) -> None:
        card = ForecastModelCard(
            forecast_model_id="timesfm-btc-v1",
            parent_model_id="google/timesfm-2.5-200m-pytorch",
            model_type="timesfm",
            training_window={"start": "2025-01-01", "end": "2026-01-01"},
            symbols=["BTCUSDT", "ETHUSDT"],
            horizon=2,
            quantiles=["q10", "q50", "q90"],
            calibration_metrics={"mae": 0.01},
            baseline_comparison={"edge": 0.03},
            decay_status="BASELINE_PASSED",
            allowed_modes=["research", "validation", "shadow", "paper_observation"],
            forbidden_uses=["orders", "position_size", "leverage", "stops", "execution_urgency", "artifact_promotion"],
            rollback_model_id="timesfm-btc-v0",
        )

        result = validate_forecast_model_card(card)

        self.assertTrue(result.passed, result.reasons)
        self.assertEqual(card.to_dict()["forecast_model_id"], "timesfm-btc-v1")

    def test_forecast_model_card_requires_forbidden_trade_uses(self) -> None:
        card = ForecastModelCard(
            forecast_model_id="bad-card",
            parent_model_id=None,
            model_type="timesfm",
            training_window={},
            symbols=["BTCUSDT"],
            horizon=2,
            quantiles=["q50"],
            calibration_metrics={},
            baseline_comparison={},
            decay_status="FEATURE_ALLOWED",
            allowed_modes=["research"],
            forbidden_uses=["orders"],
            rollback_model_id=None,
        )

        result = validate_forecast_model_card(card)

        self.assertFalse(result.passed)
        self.assertIn("missing_forbidden_use:leverage", result.reasons)


if __name__ == "__main__":
    unittest.main()
