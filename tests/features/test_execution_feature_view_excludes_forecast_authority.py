from __future__ import annotations

import unittest

from engine.features.contracts import FeatureContract
from engine.features.execution_feature_view import build_execution_feature_view
from engine.features.forecast_feature_contracts import validate_forecast_feature_names


class ExecutionFeatureViewForecastAuthorityTests(unittest.TestCase):
    def test_forecast_action_like_fields_are_rejected(self) -> None:
        result = validate_forecast_feature_names(["forecast_position_size", "forecast_trade_signal"])

        self.assertFalse(result.passed)
        self.assertIn("forecast_authority_field_not_allowed:forecast_position_size", result.reasons)
        self.assertIn("forecast_authority_field_not_allowed:forecast_trade_signal", result.reasons)

    def test_execution_feature_view_never_exposes_forecast_trade_authority_fields(self) -> None:
        contracts = {
            "close": FeatureContract.paper_safe("close", source="kline", max_age_seconds=900),
            "forecast_leverage": FeatureContract.paper_safe("forecast_leverage", source="forecast", max_age_seconds=900),
        }

        with self.assertRaisesRegex(ValueError, "forecast_authority_field:forecast_leverage"):
            build_execution_feature_view(
                {"close": 100.0, "forecast_leverage": 3.0},
                contracts=contracts,
                mode="paper",
                now_utc="2026-05-07T00:00:00Z",
                observed_at_by_field={
                    "close": "2026-05-07T00:00:00Z",
                    "forecast_leverage": "2026-05-07T00:00:00Z",
                },
            )

    def test_execution_feature_view_allows_observation_only_forecast_metadata(self) -> None:
        contracts = {
            "close": FeatureContract.paper_safe("close", source="kline", max_age_seconds=900),
            "forecast_observation_model_id": FeatureContract.paper_safe(
                "forecast_observation_model_id",
                source="forecast",
                max_age_seconds=900,
            ),
        }

        view = build_execution_feature_view(
            {"close": 100.0, "forecast_observation_model_id": "timesfm-btc-v1"},
            contracts=contracts,
            mode="paper",
            now_utc="2026-05-07T00:00:00Z",
            observed_at_by_field={
                "close": "2026-05-07T00:00:00Z",
                "forecast_observation_model_id": "2026-05-07T00:00:00Z",
            },
            allow_forecast_observation_metadata=True,
        )

        self.assertEqual(view["forecast_observation_model_id"], "timesfm-btc-v1")


if __name__ == "__main__":
    unittest.main()
