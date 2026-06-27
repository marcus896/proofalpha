from __future__ import annotations

import sys
import unittest

from engine.forecasting.timesfm_adapter import (
    ForecastRequest,
    TimesFmAdapter,
    TimesFmAdapterConfig,
)


class TimesFmAdapterBoundaryTests(unittest.TestCase):
    def test_adapter_does_not_probe_optional_dependencies_until_needed(self) -> None:
        probed: list[str] = []

        adapter = TimesFmAdapter(
            TimesFmAdapterConfig(),
            dependency_probe=lambda name: probed.append(name) or False,
        )

        self.assertEqual(probed, [])

        availability = adapter.availability()

        self.assertFalse(availability.available)
        self.assertIn("missing_optional_dependency:timesfm", availability.reasons)
        self.assertIn("missing_optional_dependency:torch", availability.reasons)
        self.assertIn("model_weights_unavailable", availability.reasons)
        self.assertEqual(probed, ["timesfm", "torch"])

    def test_missing_dependency_forecast_returns_unavailable_without_order_fields(self) -> None:
        adapter = TimesFmAdapter(
            TimesFmAdapterConfig(model_id="google/timesfm-2.5-200m-pytorch"),
            dependency_probe=lambda _name: False,
        )

        result = adapter.forecast(
            ForecastRequest(
                values=[100.0, 101.0, 102.0],
                horizon=2,
                source_snapshot_id="snapshot-btc-1h",
            )
        )

        payload = result.to_dict()
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["source"], "timesfm_optional_adapter")
        self.assertEqual(payload["model_id"], "google/timesfm-2.5-200m-pytorch")
        self.assertIn("missing_optional_dependency:timesfm", payload["reasons"])
        self.assertNotIn("order", payload)
        self.assertNotIn("trade_action", payload)
        self.assertNotIn("position_size", payload)

    def test_fixture_forecast_runs_without_optional_dependencies_or_download(self) -> None:
        adapter = TimesFmAdapter(
            TimesFmAdapterConfig(model_id="google/timesfm-2.5-200m-pytorch"),
            fixture_forecast={
                "point": [103.0, 104.0, 105.0],
                "q10": [102.0, 103.0, 104.0],
                "q50": [103.0, 104.0, 105.0],
                "q90": [104.0, 105.0, 106.0],
            },
            dependency_probe=lambda name: self.fail(f"fixture path probed dependency {name}"),
        )

        result = adapter.forecast(
            ForecastRequest(
                values=[100.0, 101.0, 102.0],
                horizon=2,
                source_snapshot_id="snapshot-btc-1h",
                context_end_ts="2026-05-01T00:00:00Z",
            )
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.source, "fixture_forecast")
        self.assertEqual(result.point_forecast, [103.0, 104.0])
        self.assertEqual(result.quantiles["q10"], [102.0, 103.0])
        self.assertEqual(result.quantiles["q50"], [103.0, 104.0])
        self.assertEqual(result.quantiles["q90"], [104.0, 105.0])
        self.assertEqual(result.metadata["source_snapshot_id"], "snapshot-btc-1h")
        self.assertEqual(result.metadata["context_end_ts"], "2026-05-01T00:00:00Z")
        self.assertFalse(result.metadata["model_download_attempted"])

    def test_adapter_rejects_horizon_above_laptop_safe_cap(self) -> None:
        adapter = TimesFmAdapter(TimesFmAdapterConfig(max_horizon=2), fixture_forecast={"point": [1.0, 2.0, 3.0]})

        with self.assertRaisesRegex(ValueError, "horizon_exceeds_max_horizon"):
            adapter.forecast(ForecastRequest(values=[1.0, 2.0], horizon=3, source_snapshot_id="snapshot"))

    def test_jax_backend_checks_jax_without_crashing(self) -> None:
        probed: list[str] = []
        adapter = TimesFmAdapter(
            TimesFmAdapterConfig(backend="jax"),
            dependency_probe=lambda name: probed.append(name) or False,
        )

        availability = adapter.availability()

        self.assertFalse(availability.available)
        self.assertIn("missing_optional_dependency:jax", availability.reasons)
        self.assertEqual(probed, ["timesfm", "jax"])

    def test_sidecar_availability_does_not_probe_main_python_dependencies(self) -> None:
        probed: list[str] = []
        adapter = TimesFmAdapter(
            TimesFmAdapterConfig(
                sidecar_python_path="missing-sidecar-python.exe",
                model_weights_path="missing-model-dir",
            ),
            dependency_probe=lambda name: probed.append(name) or False,
        )

        availability = adapter.availability()

        self.assertFalse(availability.available)
        self.assertIn("sidecar_python_unavailable", availability.reasons)
        self.assertIn("model_weights_unavailable", availability.reasons)
        self.assertEqual(probed, [])

    def test_sidecar_runner_result_maps_to_forecast_result_without_order_fields(self) -> None:
        captured_payloads: list[dict[str, object]] = []

        def fake_sidecar_runner(payload: dict[str, object], _config: TimesFmAdapterConfig) -> dict[str, object]:
            captured_payloads.append(payload)
            return {
                "status": "ok",
                "point_forecast": [103.0, 104.0],
                "quantiles": {
                    "q10": [102.0, 103.0],
                    "q50": [103.0, 104.0],
                    "q90": [104.0, 105.0],
                },
                "metadata": {"sidecar_runtime": "fake"},
            }

        adapter = TimesFmAdapter(
            TimesFmAdapterConfig(
                sidecar_python_path=sys.executable,
                model_weights_path=".",
                max_context=512,
                max_horizon=16,
                batch_size=4,
                device="cuda",
            ),
            sidecar_runner=fake_sidecar_runner,
        )

        result = adapter.forecast(
            ForecastRequest(
                values=[100.0, 101.0, 102.0],
                horizon=2,
                source_snapshot_id="snapshot-btc-1h",
                context_end_ts="2026-05-01T00:00:00Z",
            )
        )

        payload = result.to_dict()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["source"], "timesfm_sidecar_adapter")
        self.assertEqual(payload["point_forecast"], [103.0, 104.0])
        self.assertEqual(payload["quantiles"]["q50"], [103.0, 104.0])
        self.assertEqual(payload["metadata"]["sidecar_runtime"], "fake")
        self.assertEqual(captured_payloads[0]["values"], [100.0, 101.0, 102.0])
        self.assertEqual(captured_payloads[0]["horizon"], 2)
        self.assertEqual(captured_payloads[0]["device"], "cuda")
        self.assertFalse(captured_payloads[0]["allow_model_download"])
        self.assertNotIn("order", payload)
        self.assertNotIn("trade_action", payload)
        self.assertNotIn("position_size", payload)

    def test_sidecar_failure_returns_unavailable_reason(self) -> None:
        adapter = TimesFmAdapter(
            TimesFmAdapterConfig(
                sidecar_python_path=sys.executable,
                model_weights_path=".",
            ),
            sidecar_runner=lambda _payload, _config: {"status": "error", "reasons": ["sidecar_import_failed:timesfm"]},
        )

        result = adapter.forecast(
            ForecastRequest(values=[1.0, 2.0, 3.0], horizon=2, source_snapshot_id="snapshot")
        )

        self.assertEqual(result.status, "unavailable")
        self.assertIn("sidecar_import_failed:timesfm", result.reasons)


if __name__ == "__main__":
    unittest.main()
