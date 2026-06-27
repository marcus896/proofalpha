from __future__ import annotations

import unittest

from engine.forecasting.ttl_policy import ForecastTTLPolicy, join_forecast_feature_if_fresh


class ForecastTTLPolicyTests(unittest.TestCase):
    def test_stale_forecast_is_not_joined_into_research_rows(self) -> None:
        policy = ForecastTTLPolicy(
            horizon=2,
            max_age_seconds=300,
            stale_action="disable_feature",
            mode_scope="research",
        )
        row: dict[str, object] = {"close": 100.0}

        joined = join_forecast_feature_if_fresh(
            row,
            "forecast_q50_return",
            0.01,
            forecast_timestamp="2026-05-07T00:00:00Z",
            decision_time="2026-05-07T00:10:01Z",
            policy=policy,
            mode="research",
        )

        self.assertFalse(joined.joined)
        self.assertEqual(joined.status, "STALE")
        self.assertNotIn("forecast_q50_return", row)

    def test_warn_stale_action_keeps_feature_warning_only(self) -> None:
        policy = ForecastTTLPolicy(
            horizon=2,
            max_age_seconds=300,
            stale_action="warn",
            mode_scope="validation",
        )
        result = policy.evaluate(
            forecast_timestamp="2026-05-07T00:00:00Z",
            decision_time="2026-05-07T00:10:01Z",
            mode="validation",
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.status, "WARN_STALE")
        self.assertEqual(result.action, "warn")

    def test_invalid_stale_action_and_non_finite_ttl_fail_closed(self) -> None:
        policy = ForecastTTLPolicy(
            horizon=2,
            max_age_seconds=float("inf"),
            stale_action="trade",
            mode_scope="research",
        )

        result = policy.evaluate(
            forecast_timestamp="2026-05-07T00:00:00Z",
            decision_time="2026-05-07T00:01:00Z",
            mode="research",
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.action, "disable_feature")
        self.assertIn("invalid_stale_action:trade", result.issues)
        self.assertIn("max_age_seconds_non_finite", result.issues)


if __name__ == "__main__":
    unittest.main()
