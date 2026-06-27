from __future__ import annotations

import json
import unittest
from unittest import mock

from engine.app.cli import main


class TimesFmSmokeCliTests(unittest.TestCase):
    def test_local_profile_fixture_cli_writes_hotspot_report(self) -> None:
        with mock.patch(
            "engine.app.cli.run_local_profiling_harness",
            return_value={
                "schema_version": 1,
                "profile_id": "optimization_phase_7_local_profile",
                "status": "completed",
                "results": [],
                "top_runtime_hotspots": [{"task_id": "batch_simulator_fixture", "elapsed_ms": 12.0}],
                "top_sql_hotspots": [{"operation": "memory.query", "elapsed_ms": 7.0}],
            },
        ) as profile_mock, mock.patch("engine.app.cli.write_local_profile_report") as write_mock, mock.patch(
            "builtins.print"
        ) as print_mock:
            write_mock.return_value = "outputs/local-profile.json"
            exit_code = main(["profile-local-harness", "--fixture", "--output", "outputs/local-profile.json"])

        self.assertEqual(exit_code, 0)
        self.assertGreaterEqual(len(profile_mock.call_args.args[0]), 5)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["profile_id"], "optimization_phase_7_local_profile")
        self.assertEqual(payload["output"], "outputs/local-profile.json")

    def test_timesfm_smoke_fixture_cli_outputs_research_only_json(self) -> None:
        with mock.patch("builtins.print") as print_mock:
            exit_code = main(["timesfm-smoke", "--fixture", "--symbol", "BTCUSDT", "--horizon", "3"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["mode"], "fixture")
        self.assertTrue(payload["research_only"])
        self.assertFalse(payload["model_download_attempted"])
        self.assertNotIn("order", payload)
        self.assertNotIn("trade_action", payload)
        self.assertNotIn("position_size", payload)

    def test_timesfm_smoke_cli_passes_sidecar_options(self) -> None:
        with mock.patch("engine.app.cli.run_timesfm_smoke", return_value={"status": "skipped"}) as smoke_mock, mock.patch(
            "builtins.print"
        ):
            exit_code = main(
                [
                    "timesfm-smoke",
                    "--symbol",
                    "BTCUSDT",
                    "--model-weights-path",
                    "models/timesfm-2.5-200m-pytorch",
                    "--sidecar-python-path",
                    ".venv-timesfm/Scripts/python.exe",
                    "--sidecar-timeout-seconds",
                    "7",
                ]
            )

        self.assertEqual(exit_code, 0)
        config = smoke_mock.call_args.args[0]
        self.assertEqual(config.model_weights_path, "models/timesfm-2.5-200m-pytorch")
        self.assertEqual(config.sidecar_python_path, ".venv-timesfm/Scripts/python.exe")
        self.assertEqual(config.sidecar_timeout_seconds, 7.0)

    def test_timesfm_benchmark_fixture_cli_writes_research_only_profile(self) -> None:
        with mock.patch(
            "engine.app.cli.run_timesfm_runtime_benchmark",
            return_value={
                "schema_version": 1,
                "research_only": True,
                "status": "completed",
                "results": [],
                "selected_defaults": {"max_context": 128},
            },
        ) as benchmark_mock, mock.patch("engine.app.cli.write_timesfm_runtime_profile") as write_mock, mock.patch(
            "builtins.print"
        ) as print_mock:
            write_mock.return_value = "outputs/timesfm-runtime.json"
            exit_code = main(
                [
                    "timesfm-benchmark",
                    "--fixture",
                    "--output",
                    "outputs/timesfm-runtime.json",
                    "--context-length",
                    "128",
                    "--horizon",
                    "1",
                    "--batch-size",
                    "1",
                ]
            )

        self.assertEqual(exit_code, 0)
        config = benchmark_mock.call_args.args[0]
        self.assertTrue(config.use_fixture)
        self.assertEqual(config.matrix[0].max_context, 128)
        self.assertEqual(config.matrix[0].horizon, 1)
        self.assertEqual(config.matrix[0].batch_size, 1)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["status"], "completed")
        self.assertTrue(payload["research_only"])
        self.assertEqual(payload["output"], "outputs/timesfm-runtime.json")

    def test_timesfm_benchmark_cli_builds_device_and_compile_matrix(self) -> None:
        with mock.patch(
            "engine.app.cli.run_timesfm_runtime_benchmark",
            return_value={
                "schema_version": 1,
                "research_only": True,
                "status": "skipped",
                "results": [],
                "selected_defaults": {},
            },
        ) as benchmark_mock, mock.patch("engine.app.cli.write_timesfm_runtime_profile") as write_mock, mock.patch(
            "builtins.print"
        ):
            write_mock.return_value = "outputs/timesfm-runtime.json"
            exit_code = main(
                [
                    "timesfm-benchmark",
                    "--output",
                    "outputs/timesfm-runtime.json",
                    "--context-length",
                    "128",
                    "--horizon",
                    "1",
                    "--batch-size",
                    "1",
                    "--device",
                    "cpu",
                    "--device",
                    "cuda",
                    "--include-torch-compile",
                ]
            )

        self.assertEqual(exit_code, 0)
        config = benchmark_mock.call_args.args[0]
        case_ids = [case.case_id for case in config.matrix]
        self.assertEqual(case_ids, [
            "pytorch-cpu-ctx128-h1-b1-tc0",
            "pytorch-cpu-ctx128-h1-b1-tc1",
            "pytorch-cuda-ctx128-h1-b1-tc0",
            "pytorch-cuda-ctx128-h1-b1-tc1",
        ])

    def test_timesfm_benchmark_cli_runs_warm_batch_profile(self) -> None:
        with mock.patch(
            "engine.app.cli.run_timesfm_warm_batch_benchmark",
            return_value={
                "schema_version": 1,
                "research_only": True,
                "status": "completed",
                "mode": "warm_batch",
                "results": [],
                "selected_defaults": {},
            },
        ) as benchmark_mock, mock.patch("engine.app.cli.write_timesfm_runtime_profile") as write_mock, mock.patch(
            "builtins.print"
        ) as print_mock:
            write_mock.return_value = "outputs/timesfm-warm-batch.json"
            exit_code = main(
                [
                    "timesfm-benchmark",
                    "--warm-batch",
                    "--fixture",
                    "--output",
                    "outputs/timesfm-warm-batch.json",
                    "--context-length",
                    "512",
                    "--horizon",
                    "3",
                    "--batch-size",
                    "3",
                    "--device",
                    "cuda",
                    "--warm-batch-symbol",
                    "BTCUSDT",
                    "--warm-batch-symbol",
                    "ETHUSDT",
                    "--warm-batch-symbol",
                    "SOLUSDT",
                ]
            )

        self.assertEqual(exit_code, 0)
        config = benchmark_mock.call_args.args[0]
        self.assertEqual(config.symbols, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        self.assertEqual(config.max_context, 512)
        self.assertEqual(config.horizon, 3)
        self.assertEqual(config.batch_size, 3)
        self.assertEqual(config.device, "cuda")
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["mode"], "warm_batch")
        self.assertEqual(payload["output"], "outputs/timesfm-warm-batch.json")

    def test_timesfm_benchmark_cli_passes_resident_sidecar_flag(self) -> None:
        with mock.patch(
            "engine.app.cli.run_timesfm_warm_batch_benchmark",
            return_value={
                "schema_version": 1,
                "research_only": True,
                "status": "skipped",
                "mode": "warm_batch",
                "sidecar_mode": "resident",
                "results": [],
                "selected_defaults": {},
            },
        ) as benchmark_mock, mock.patch("engine.app.cli.write_timesfm_runtime_profile") as write_mock, mock.patch(
            "builtins.print"
        ):
            write_mock.return_value = "outputs/timesfm-warm-batch.json"
            exit_code = main(
                [
                    "timesfm-benchmark",
                    "--warm-batch",
                    "--resident-sidecar",
                    "--output",
                    "outputs/timesfm-warm-batch.json",
                ]
            )

        self.assertEqual(exit_code, 0)
        config = benchmark_mock.call_args.args[0]
        self.assertTrue(config.resident_sidecar)

    def test_timesfm_benchmark_cli_can_attach_forecast_campaign_artifact_flow(self) -> None:
        with mock.patch(
            "engine.app.cli.run_timesfm_runtime_benchmark",
            return_value={
                "schema_version": 1,
                "research_only": True,
                "status": "completed",
                "benchmark_id": "phase6-timesfm-runtime-profile",
                "model_id": "google/timesfm-2.5-200m-pytorch",
                "backend": "pytorch",
                "results": [],
                "selected_defaults": {
                    "model_id": "google/timesfm-2.5-200m-pytorch",
                    "backend": "pytorch",
                    "device": "cuda",
                    "max_context": 512,
                    "horizon": 3,
                    "batch_size": 3,
                    "torch_compile": False,
                },
            },
        ), mock.patch("engine.app.cli.write_timesfm_runtime_profile") as write_mock, mock.patch(
            "builtins.print"
        ) as print_mock:
            write_mock.return_value = "outputs/timesfm-runtime-campaign.json"
            exit_code = main(
                [
                    "timesfm-benchmark",
                    "--fixture",
                    "--include-forecast-campaign",
                    "--forecast-campaign-symbol",
                    "BTCUSDT",
                    "--forecast-campaign-symbol",
                    "ETHUSDT",
                    "--forecast-campaign-symbol",
                    "SOLUSDT",
                    "--output",
                    "outputs/timesfm-runtime-campaign.json",
                    "--context-length",
                    "512",
                    "--horizon",
                    "3",
                    "--batch-size",
                    "3",
                    "--device",
                    "cuda",
                ]
            )

        self.assertEqual(exit_code, 0)
        written_payload = write_mock.call_args.args[1]
        self.assertEqual(written_payload["artifact_type"], "timesfm_forecast_campaign_runtime_flow")
        self.assertEqual(
            written_payload["forecast_validation_campaign"]["symbols"],
            ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        )
        self.assertEqual(written_payload["campaign_runtime_config"]["device"], "cuda")
        printed_payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(printed_payload["artifact_type"], "timesfm_forecast_campaign_runtime_flow")
        self.assertEqual(printed_payload["output"], "outputs/timesfm-runtime-campaign.json")


if __name__ == "__main__":
    unittest.main()
