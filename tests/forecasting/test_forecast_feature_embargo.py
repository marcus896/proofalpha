from __future__ import annotations

import unittest

from engine.forecasting.feature_embargo import ForecastFeatureEmbargo


class ForecastFeatureEmbargoTests(unittest.TestCase):
    def test_forecast_timestamp_later_than_decision_time_is_rejected(self) -> None:
        embargo = ForecastFeatureEmbargo(
            source_timestamp="2026-05-07T00:05:00Z",
            earliest_available_at="2026-05-07T00:06:00Z",
            execution_availability=False,
            embargo_seconds=60,
            leakage_risk="future_timestamp",
        )

        result = embargo.evaluate(decision_time="2026-05-07T00:04:59Z", mode="validation")

        self.assertFalse(result.passed)
        self.assertIn("forecast_timestamp_after_decision_time", result.reasons)

    def test_embargo_blocks_early_feature_use(self) -> None:
        embargo = ForecastFeatureEmbargo(
            source_timestamp="2026-05-07T00:00:00Z",
            earliest_available_at="2026-05-07T00:05:00Z",
            execution_availability=True,
            embargo_seconds=300,
            leakage_risk="embargoed",
        )

        result = embargo.evaluate(decision_time="2026-05-07T00:04:59Z", mode="paper")

        self.assertFalse(result.passed)
        self.assertIn("forecast_feature_embargo_active", result.reasons)

    def test_embargo_rejects_unknown_leakage_risk_and_negative_seconds(self) -> None:
        embargo = ForecastFeatureEmbargo(
            source_timestamp="2026-05-07T00:00:00Z",
            earliest_available_at="2026-05-07T00:00:00Z",
            execution_availability=True,
            embargo_seconds=-1,
            leakage_risk="safe_to_trade",
        )

        result = embargo.evaluate(decision_time="2026-05-07T00:01:00Z", mode="paper")

        self.assertFalse(result.passed)
        self.assertIn("embargo_seconds_negative", result.reasons)
        self.assertIn("unknown_leakage_risk:safe_to_trade", result.reasons)


if __name__ == "__main__":
    unittest.main()
