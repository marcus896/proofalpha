from __future__ import annotations

import unittest

from engine.forecasting.artifacts import (
    ForecastCovariate,
    build_forecast_artifact,
    validate_forecast_artifact,
)
from engine.forecasting.timesfm_adapter import ForecastRequest, TimesFmAdapter, TimesFmAdapterConfig


class ForecastArtifactLeakageTests(unittest.TestCase):
    def test_fixture_forecast_builds_required_artifact_schema(self) -> None:
        result = _fixture_result()

        artifact = build_forecast_artifact(
            result,
            feature_timestamp="2026-05-01T00:15:00Z",
            created_at="2026-05-01T00:16:00Z",
            config_checksum="sha256:timesfm-laptop-safe",
            last_observed_value=102.0,
        )

        payload = artifact.to_dict()
        self.assertEqual(payload["model_id"], "google/timesfm-2.5-200m-pytorch")
        self.assertEqual(payload["point_forecast"], [103.0, 104.0])
        self.assertEqual(payload["q10"], [102.0, 103.0])
        self.assertEqual(payload["q50"], [103.0, 104.0])
        self.assertEqual(payload["q90"], [104.0, 105.0])
        self.assertEqual(payload["interval_width"], [2.0, 2.0])
        self.assertGreater(payload["direction_confidence"], 0.0)
        self.assertEqual(payload["context_length"], 3)
        self.assertEqual(payload["horizon"], 2)
        self.assertEqual(payload["config_checksum"], "sha256:timesfm-laptop-safe")
        self.assertEqual(payload["source_snapshot_id"], "snapshot-btc-1h")
        self.assertEqual(payload["context_end_ts"], "2026-05-01T00:00:00+00:00")
        self.assertEqual(payload["feature_timestamp"], "2026-05-01T00:15:00+00:00")
        self.assertEqual(payload["created_at"], "2026-05-01T00:16:00+00:00")

        report = validate_forecast_artifact(artifact)
        self.assertTrue(report.passed, report.issues)

    def test_time_travel_guard_rejects_context_after_feature_timestamp(self) -> None:
        result = _fixture_result(context_end_ts="2026-05-01T00:30:00Z")
        artifact = build_forecast_artifact(
            result,
            feature_timestamp="2026-05-01T00:15:00Z",
            created_at="2026-05-01T00:16:00Z",
            config_checksum="sha256:timesfm-laptop-safe",
        )

        report = validate_forecast_artifact(artifact)

        self.assertFalse(report.passed)
        self.assertIn("forecast_context_after_feature_timestamp", report.issues)

    def test_future_covariate_rejected_unless_known_at_decision_time(self) -> None:
        result = _fixture_result()
        artifact = build_forecast_artifact(
            result,
            feature_timestamp="2026-05-01T00:15:00Z",
            created_at="2026-05-01T00:16:00Z",
            config_checksum="sha256:timesfm-laptop-safe",
            future_covariates=[
                ForecastCovariate(
                    name="next_funding_rate",
                    value=0.0001,
                    available_at="2026-05-01T00:30:00Z",
                    known_at_decision_time=False,
                )
            ],
        )

        report = validate_forecast_artifact(artifact)

        self.assertFalse(report.passed)
        self.assertIn("future_covariate_not_known:next_funding_rate", report.issues)

        allowed = build_forecast_artifact(
            result,
            feature_timestamp="2026-05-01T00:15:00Z",
            created_at="2026-05-01T00:16:00Z",
            config_checksum="sha256:timesfm-laptop-safe",
            future_covariates=[
                ForecastCovariate(
                    name="scheduled_funding_time",
                    value="2026-05-01T08:00:00Z",
                    available_at="2026-05-01T08:00:00Z",
                    known_at_decision_time=True,
                )
            ],
        )

        self.assertTrue(validate_forecast_artifact(allowed).passed)

    def test_artifact_validation_requires_quantile_schema(self) -> None:
        adapter = TimesFmAdapter(
            TimesFmAdapterConfig(),
            fixture_forecast={"point": [103.0, 104.0], "q10": [102.0, 103.0]},
        )
        result = adapter.forecast(
            ForecastRequest(
                values=[100.0, 101.0, 102.0],
                horizon=2,
                source_snapshot_id="snapshot-btc-1h",
                context_end_ts="2026-05-01T00:00:00Z",
            )
        )
        artifact = build_forecast_artifact(
            result,
            feature_timestamp="2026-05-01T00:15:00Z",
            created_at="2026-05-01T00:16:00Z",
            config_checksum="sha256:timesfm-laptop-safe",
        )

        report = validate_forecast_artifact(artifact)

        self.assertFalse(report.passed)
        self.assertIn("missing_quantile:q50", report.issues)
        self.assertIn("missing_quantile:q90", report.issues)


def _fixture_result(context_end_ts: str = "2026-05-01T00:00:00Z"):
    adapter = TimesFmAdapter(
        TimesFmAdapterConfig(model_id="google/timesfm-2.5-200m-pytorch"),
        fixture_forecast={
            "point": [103.0, 104.0],
            "q10": [102.0, 103.0],
            "q50": [103.0, 104.0],
            "q90": [104.0, 105.0],
        },
    )
    return adapter.forecast(
        ForecastRequest(
            values=[100.0, 101.0, 102.0],
            horizon=2,
            source_snapshot_id="snapshot-btc-1h",
            context_end_ts=context_end_ts,
        )
    )


if __name__ == "__main__":
    unittest.main()
