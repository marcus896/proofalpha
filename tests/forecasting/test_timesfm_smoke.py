from __future__ import annotations

import sys
import unittest

from engine.forecasting.smoke import TimesFmSmokeConfig, run_timesfm_smoke
from engine.forecasting.timesfm_adapter import TimesFmAdapterConfig


class TimesFmSmokeTests(unittest.TestCase):
    def test_real_smoke_skips_cleanly_when_dependencies_or_weights_are_absent(self) -> None:
        result = run_timesfm_smoke(
            TimesFmSmokeConfig(symbol="BTCUSDT"),
            dependency_probe=lambda _name: False,
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["mode"], "real")
        self.assertTrue(result["research_only"])
        self.assertFalse(result["model_download_attempted"])
        self.assertIn("missing_optional_dependency:timesfm", result["skip_reasons"])
        self.assertIn("missing_optional_dependency:torch", result["skip_reasons"])
        self.assertIn("model_weights_unavailable", result["skip_reasons"])
        self.assertNotIn("order", result)
        self.assertNotIn("trade_action", result)
        self.assertNotIn("position_size", result)

    def test_fixture_smoke_builds_valid_artifact_for_allowed_symbols(self) -> None:
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            with self.subTest(symbol=symbol):
                result = run_timesfm_smoke(
                    TimesFmSmokeConfig(symbol=symbol, use_fixture=True, horizon=3),
                    dependency_probe=lambda name: self.fail(f"fixture smoke probed dependency {name}"),
                )

                self.assertEqual(result["status"], "passed")
                self.assertEqual(result["mode"], "fixture")
                self.assertTrue(result["research_only"])
                self.assertFalse(result["model_download_attempted"])
                self.assertEqual(result["artifact_validation"]["passed"], True)
                self.assertEqual(result["artifact"]["source_snapshot_id"], f"timesfm-smoke-{symbol.lower()}-fixture")

    def test_smoke_rejects_unsupported_symbol(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_smoke_symbol"):
            run_timesfm_smoke(TimesFmSmokeConfig(symbol="DOGEUSDT", use_fixture=True))

    def test_sidecar_smoke_builds_valid_artifact_without_main_dependency_probe(self) -> None:
        captured_configs: list[TimesFmAdapterConfig] = []

        def fake_sidecar_runner(payload: dict[str, object], config: TimesFmAdapterConfig) -> dict[str, object]:
            captured_configs.append(config)
            self.assertEqual(payload["model_path"], ".")
            return {
                "status": "ok",
                "point_forecast": [60016.0, 60017.0, 60018.0],
                "quantiles": {
                    "q10": [60015.5, 60016.5, 60017.5],
                    "q50": [60016.0, 60017.0, 60018.0],
                    "q90": [60016.5, 60017.5, 60018.5],
                },
                "metadata": {"sidecar_runtime": "fake"},
            }

        result = run_timesfm_smoke(
            TimesFmSmokeConfig(
                symbol="BTCUSDT",
                horizon=3,
                model_weights_path=".",
                sidecar_python_path=sys.executable,
            ),
            dependency_probe=lambda name: self.fail(f"sidecar smoke probed main dependency {name}"),
            sidecar_runner=fake_sidecar_runner,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["adapter_status"], "ok")
        self.assertEqual(result["artifact"]["source"], "timesfm_sidecar_adapter")
        self.assertEqual(result["artifact_validation"]["passed"], True)
        self.assertEqual(captured_configs[0].sidecar_python_path, sys.executable)


if __name__ == "__main__":
    unittest.main()
