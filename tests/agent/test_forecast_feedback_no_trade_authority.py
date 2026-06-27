from __future__ import annotations

import unittest

from engine.agent.forecast_feedback_adapter import forecast_feedback_to_study_request


class ForecastFeedbackNoTradeAuthorityTests(unittest.TestCase):
    def test_agent_can_propose_forecast_validation_studies_only(self) -> None:
        request = forecast_feedback_to_study_request(
            {
                "forecast_model_id": "timesfm-btc-v1",
                "ttl_status": "STALE",
                "baseline_comparison": {"edge": -0.01},
                "decay_status": "DISABLED",
            }
        )

        self.assertEqual(request["action"], "RequestForecastValidationStudy")
        self.assertFalse(request["trade_authority"])
        self.assertFalse(request["direct_order_change"])
        self.assertFalse(request["artifact_promotion"])
        self.assertIn("forecast_model_id", request["study"])


if __name__ == "__main__":
    unittest.main()
