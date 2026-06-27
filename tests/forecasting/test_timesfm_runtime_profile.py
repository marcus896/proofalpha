from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from engine.forecasting.campaign import build_forecast_validation_campaign
from engine.forecasting.runtime_profile import (
    TimesFmWarmBatchBenchmarkConfig,
    TimesFmRuntimeBenchmarkConfig,
    attach_forecast_campaign_to_runtime_profile,
    build_timesfm_runtime_matrix,
    choose_laptop_safe_timesfm_defaults,
    run_timesfm_warm_batch_benchmark,
    run_timesfm_runtime_benchmark,
    write_timesfm_runtime_profile,
)
from engine.forecasting.timesfm_adapter import ForecastResult
from engine.forecasting import runtime_profile


class TimesFmRuntimeProfileTests(unittest.TestCase):
    def _workspace_temp_path(self, name: str) -> Path:
        base = Path("outputs") / "test-temp"
        base.mkdir(parents=True, exist_ok=True)
        path = base / name
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_campaign_default_model_matches_downloaded_timesfm_checkpoint(self) -> None:
        campaign = build_forecast_validation_campaign()

        payload = campaign.to_dict()

        model_ids = {
            variant["forecast_feature_config"]["model_id"]
            for variant in payload["forecast_variants"]
        }
        self.assertEqual(model_ids, {"google/timesfm-2.5-200m-pytorch"})

    def test_runtime_matrix_builds_research_only_laptop_safe_candidates(self) -> None:
        matrix = build_timesfm_runtime_matrix(
            context_lengths=(128, 512),
            horizons=(1, 3),
            batch_sizes=(1, 3),
            torch_compile_options=(False, True),
            devices=("cpu",),
        )

        self.assertEqual(len(matrix), 16)
        first = matrix[0].to_dict()
        self.assertTrue(first["research_only"])
        self.assertEqual(first["model_id"], "google/timesfm-2.5-200m-pytorch")
        self.assertEqual(first["backend"], "pytorch")
        self.assertNotIn("order", json.dumps(first))
        self.assertNotIn("trade_action", json.dumps(first))
        self.assertNotIn("position_size", json.dumps(first))

    def test_benchmark_records_cold_warm_latency_and_selects_fastest_ok_default(self) -> None:
        calls: list[tuple[str, bool]] = []

        def runner(case, *, phase):
            calls.append((case.case_id, phase))
            return ForecastResult(
                status="ok",
                source="fixture_forecast",
                model_id=case.model_id,
                point_forecast=[1.0 for _ in range(case.horizon)],
                quantiles={"q10": [0.5], "q50": [1.0], "q90": [1.5]},
                metadata={"memory_peak_mb": 12.5},
            )

        report = run_timesfm_runtime_benchmark(
            TimesFmRuntimeBenchmarkConfig(
                matrix=build_timesfm_runtime_matrix(
                    context_lengths=(128, 512),
                    horizons=(1,),
                    batch_sizes=(1,),
                    torch_compile_options=(False,),
                    devices=("cpu",),
                ),
                use_fixture=True,
            ),
            forecast_runner=runner,
            timer=lambda: float(len(calls)),
        )

        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["research_only"])
        self.assertEqual(len(report["results"]), 2)
        self.assertIn("cold_latency_ms", report["results"][0])
        self.assertIn("warm_latency_ms", report["results"][0])
        self.assertIn("warm_throughput_points_per_second", report["results"][0])
        self.assertEqual(report["results"][0]["memory_peak_mb"], 12.5)
        self.assertEqual(report["selected_defaults"]["max_context"], 128)
        self.assertEqual(report["selected_defaults"]["batch_size"], 1)
        self.assertEqual(report["selected_defaults"]["torch_compile"], False)
        self.assertNotIn("executor_action", json.dumps(report))

    def test_defaults_select_fastest_gpu_when_only_gpu_results_succeed(self) -> None:
        defaults = choose_laptop_safe_timesfm_defaults(
            [
                {
                    "status": "ok",
                    "model_id": "google/timesfm-2.5-200m-pytorch",
                    "backend": "pytorch",
                    "device": "cuda",
                    "max_context": 512,
                    "horizon": 3,
                    "batch_size": 1,
                    "torch_compile": False,
                    "warm_latency_ms": 9000.0,
                },
                {
                    "status": "ok",
                    "model_id": "google/timesfm-2.5-200m-pytorch",
                    "backend": "pytorch",
                    "device": "cuda",
                    "max_context": 128,
                    "horizon": 1,
                    "batch_size": 1,
                    "torch_compile": True,
                    "warm_latency_ms": 15000.0,
                },
            ]
        )

        self.assertEqual(defaults["device"], "cuda")
        self.assertEqual(defaults["max_context"], 512)
        self.assertEqual(defaults["torch_compile"], False)
        self.assertEqual(defaults["selection_reason"], "fastest_successful_available_warm_latency")

    def test_missing_local_sidecar_runtime_skips_instead_of_failing(self) -> None:
        report = run_timesfm_runtime_benchmark(
            TimesFmRuntimeBenchmarkConfig(
                matrix=build_timesfm_runtime_matrix(context_lengths=(128,), horizons=(1,), batch_sizes=(1,)),
                use_fixture=False,
                model_weights_path="missing-model",
                sidecar_python_path="missing-python",
            )
        )

        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["results"][0]["status"], "skipped")
        self.assertIn("sidecar_python_unavailable", report["results"][0]["skip_reasons"])
        self.assertIn("model_weights_unavailable", report["results"][0]["skip_reasons"])

    def test_cuda_case_skips_when_cuda_runtime_is_unavailable(self) -> None:
        matrix = build_timesfm_runtime_matrix(
            context_lengths=(128,),
            horizons=(1,),
            batch_sizes=(1,),
            devices=("cuda",),
        )

        original_probe = runtime_profile._probe_sidecar_runtime
        runtime_profile._probe_sidecar_runtime = lambda _path: {
            "usable": True,
            "cuda_available": False,
            "reasons": [],
        }
        self.addCleanup(setattr, runtime_profile, "_probe_sidecar_runtime", original_probe)

        report = run_timesfm_runtime_benchmark(
            TimesFmRuntimeBenchmarkConfig(
                matrix=matrix,
                use_fixture=False,
                model_weights_path=".",
                sidecar_python_path=sys.executable,
            )
        )

        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["results"][0]["status"], "skipped")
        self.assertIn("cuda_unavailable", report["results"][0]["skip_reasons"])

    def test_unusable_sidecar_python_skips_cleanly_before_benchmark(self) -> None:
        matrix = build_timesfm_runtime_matrix(
            context_lengths=(128,),
            horizons=(1,),
            batch_sizes=(1,),
            devices=("cpu",),
        )

        original_probe = runtime_profile._probe_sidecar_runtime
        runtime_profile._probe_sidecar_runtime = lambda _path: {
            "usable": False,
            "cuda_available": False,
            "reasons": ["sidecar_python_probe_failed:101"],
        }
        self.addCleanup(setattr, runtime_profile, "_probe_sidecar_runtime", original_probe)

        report = run_timesfm_runtime_benchmark(
            TimesFmRuntimeBenchmarkConfig(
                matrix=matrix,
                use_fixture=False,
                model_weights_path=".",
                sidecar_python_path=sys.executable,
            )
        )

        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["results"][0]["status"], "skipped")
        self.assertIn("sidecar_python_unusable", report["results"][0]["skip_reasons"])

    def test_write_runtime_profile_rejects_executor_fields(self) -> None:
        report = {
            "schema_version": 1,
            "research_only": True,
            "status": "completed",
            "results": [],
            "selected_defaults": {},
            "order": {"side": "BUY"},
        }

        with self.assertRaises(ValueError):
            write_timesfm_runtime_profile(self._workspace_temp_path("unsafe-runtime.json"), report)

    def test_write_runtime_profile_round_trips_safe_report(self) -> None:
        report = run_timesfm_runtime_benchmark(
            TimesFmRuntimeBenchmarkConfig(
                matrix=build_timesfm_runtime_matrix(context_lengths=(128,), horizons=(1,), batch_sizes=(1,)),
                use_fixture=True,
            )
        )

        output = write_timesfm_runtime_profile(self._workspace_temp_path("safe-runtime.json"), report)
        payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(payload["research_only"])
        self.assertEqual(payload["schema_version"], 1)

    def test_warm_batch_benchmark_fixture_profiles_three_symbols_with_one_model_load(self) -> None:
        report = run_timesfm_warm_batch_benchmark(
            TimesFmWarmBatchBenchmarkConfig(
                symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                max_context=128,
                horizon=3,
                batch_size=3,
                device="cuda",
                use_fixture=True,
            ),
            timer=lambda: 10.0,
        )

        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["mode"], "warm_batch")
        self.assertTrue(report["research_only"])
        self.assertEqual(report["symbols"], ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        self.assertEqual(report["model_load_count"], 1)
        self.assertEqual(report["batch_size_effective"], 3)
        self.assertEqual(set(report["forecasts"]), {"BTCUSDT", "ETHUSDT", "SOLUSDT"})
        self.assertNotIn("order", json.dumps(report))
        self.assertNotIn("trade_action", json.dumps(report))
        self.assertNotIn("position_size", json.dumps(report))

    def test_warm_batch_resident_sidecar_skips_cleanly_when_runtime_is_missing(self) -> None:
        report = run_timesfm_warm_batch_benchmark(
            TimesFmWarmBatchBenchmarkConfig(
                symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                model_weights_path="missing-model",
                sidecar_python_path="missing-python",
                resident_sidecar=True,
            )
        )

        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["sidecar_mode"], "resident")
        self.assertIn("sidecar_python_unavailable", report["skipped_reasons"])
        self.assertIn("model_weights_unavailable", report["skipped_reasons"])

    def test_resident_sidecar_client_sends_warmup_and_measured_requests(self) -> None:
        captured_input: list[str] = []

        def fake_run(_args, **kwargs):
            captured_input.append(str(kwargs["input"]))
            first = {
                "status": "ok",
                "forecasts": {"BTCUSDT": {"point_forecast": [1.0], "quantiles": {"q50": [1.0]}}},
                "metadata": {"resident_request_index": 1, "resident_model_cache_hit": False},
            }
            second = {
                "status": "ok",
                "forecasts": {"BTCUSDT": {"point_forecast": [1.0], "quantiles": {"q50": [1.0]}}},
                "metadata": {"resident_request_index": 2, "resident_model_cache_hit": True},
            }
            shutdown = {"status": "ok", "resident_command": "shutdown"}
            return SimpleNamespace(
                returncode=0,
                stdout="\n".join(json.dumps(line, sort_keys=True) for line in (first, second, shutdown)),
                stderr="",
            )

        original_run = runtime_profile.subprocess.run
        runtime_profile.subprocess.run = fake_run
        self.addCleanup(setattr, runtime_profile.subprocess, "run", original_run)

        payload = runtime_profile._run_warm_batch_resident_sidecar_subprocess(
            TimesFmWarmBatchBenchmarkConfig(
                symbols=("BTCUSDT",),
                model_weights_path=".",
                sidecar_python_path=sys.executable,
                resident_sidecar=True,
            )
        )

        self.assertEqual(len(captured_input[0].splitlines()), 3)
        self.assertEqual(payload["metadata"]["resident_request_index"], 2)
        self.assertTrue(payload["metadata"]["resident_model_cache_hit"])

    def test_forecast_campaign_runtime_flow_uses_selected_profile_defaults(self) -> None:
        report = run_timesfm_runtime_benchmark(
            TimesFmRuntimeBenchmarkConfig(
                matrix=build_timesfm_runtime_matrix(
                    context_lengths=(512,),
                    horizons=(3,),
                    batch_sizes=(3,),
                    devices=("cuda",),
                ),
                use_fixture=True,
            )
        )

        payload = attach_forecast_campaign_to_runtime_profile(
            report,
            symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        )

        campaign = payload["forecast_validation_campaign"]
        self.assertTrue(payload["research_only"])
        self.assertEqual(payload["runtime_profile"]["benchmark_id"], "phase6-timesfm-runtime-profile")
        self.assertEqual(campaign["symbols"], ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        self.assertEqual(
            campaign["required_baselines"],
            ["no_forecast", "momentum", "breakout", "carry_funding"],
        )
        for variant in campaign["forecast_variants"]:
            self.assertEqual(variant["forecast_feature_config"]["model_id"], "google/timesfm-2.5-200m-pytorch")
            self.assertEqual(variant["forecast_feature_config"]["horizon"], 3)
            self.assertEqual(variant["forecast_feature_config"]["context_length"], 512)
            self.assertIsNotNone(variant["forecast_feature_config"]["config_checksum"])
        self.assertEqual(payload["campaign_runtime_config"]["device"], "cuda")
        self.assertEqual(payload["campaign_runtime_config"]["batch_size"], 3)
        self.assertNotIn("executor_action", json.dumps(payload))
        self.assertNotIn("trade_action", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
