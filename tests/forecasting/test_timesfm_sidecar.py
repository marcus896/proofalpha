from __future__ import annotations

import unittest

from engine.forecasting.timesfm_sidecar import (
    ResidentTimesFmSession,
    build_sidecar_forecast_config,
    parse_sidecar_request,
    parse_warm_batch_request,
    serve_resident_jsonl,
)


class TimesFmSidecarContractTests(unittest.TestCase):
    def test_parse_sidecar_request_rejects_model_download(self) -> None:
        with self.assertRaisesRegex(ValueError, "model_download_not_allowed"):
            parse_sidecar_request(
                {
                    "model_path": ".",
                    "model_id": "google/timesfm-2.5-200m-pytorch",
                    "values": [1.0, 2.0, 3.0],
                    "horizon": 2,
                    "allow_model_download": True,
                }
            )

    def test_build_sidecar_forecast_config_uses_laptop_safe_defaults(self) -> None:
        request = parse_sidecar_request(
            {
                "model_path": ".",
                "model_id": "google/timesfm-2.5-200m-pytorch",
                "values": [1.0, 2.0, 3.0],
                "horizon": 2,
                "max_context": 512,
                "max_horizon": 16,
                "batch_size": 4,
                "device": "cuda",
                "allow_model_download": False,
            }
        )

        config = build_sidecar_forecast_config(request)

        self.assertEqual(request.device, "cuda")
        self.assertEqual(config["max_context"], 512)
        self.assertEqual(config["max_horizon"], 16)
        self.assertEqual(config["per_core_batch_size"], 4)
        self.assertTrue(config["normalize_inputs"])
        self.assertTrue(config["use_continuous_quantile_head"])
        self.assertTrue(config["force_flip_invariance"])
        self.assertTrue(config["infer_is_positive"])
        self.assertTrue(config["fix_quantile_crossing"])

    def test_parse_warm_batch_request_requires_symbol_series_without_download(self) -> None:
        request = parse_warm_batch_request(
            {
                "model_path": ".",
                "model_id": "google/timesfm-2.5-200m-pytorch",
                "mode": "warm_batch",
                "series": [
                    {"symbol": "BTCUSDT", "values": [1.0, 2.0, 3.0]},
                    {"symbol": "ETHUSDT", "values": [4.0, 5.0, 6.0]},
                    {"symbol": "SOLUSDT", "values": [7.0, 8.0, 9.0]},
                ],
                "horizon": 2,
                "max_context": 512,
                "max_horizon": 16,
                "batch_size": 3,
                "device": "cuda",
                "allow_model_download": False,
            }
        )

        self.assertEqual([item.symbol for item in request.series], ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        self.assertEqual(request.device, "cuda")
        self.assertEqual(request.batch_size, 3)

    def test_parse_warm_batch_request_rejects_executor_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden_warm_batch_field:order"):
            parse_warm_batch_request(
                {
                    "model_path": ".",
                    "mode": "warm_batch",
                    "series": [{"symbol": "BTCUSDT", "values": [1.0, 2.0, 3.0]}],
                    "horizon": 1,
                    "order": {"side": "BUY"},
                }
            )

    def test_resident_jsonl_server_handles_ping_forecast_and_shutdown(self) -> None:
        from io import StringIO

        requests = "\n".join(
            [
                json_dumps({"command": "ping"}),
                json_dumps(
                    {
                        "mode": "warm_batch",
                        "model_path": ".",
                        "series": [{"symbol": "BTCUSDT", "values": [1.0, 2.0, 3.0]}],
                        "horizon": 1,
                    }
                ),
                json_dumps({"command": "shutdown"}),
            ]
        )
        output = StringIO()

        exit_code = serve_resident_jsonl(
            StringIO(requests + "\n"),
            output,
            warm_batch_runner=lambda _request: {
                "status": "ok",
                "forecasts": {"BTCUSDT": {"point_forecast": [1.0], "quantiles": {"q50": [1.0]}}},
                "metadata": {"model_load_count": 1},
            },
        )

        self.assertEqual(exit_code, 0)
        lines = [json_loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["status"], "ok")
        self.assertEqual(lines[0]["resident_command"], "ping")
        self.assertTrue(lines[1]["metadata"]["resident_sidecar"])
        self.assertEqual(lines[1]["metadata"]["resident_request_index"], 1)
        self.assertEqual(lines[2]["resident_command"], "shutdown")

    def test_resident_session_reuses_loaded_warm_batch_model_for_matching_requests(self) -> None:
        load_calls: list[str] = []

        def load_model(request):
            load_calls.append(request.model_id)
            return {"model_id": request.model_id}

        def run_model(model, request):
            return {
                "status": "ok",
                "forecasts": {
                    request.series[0].symbol: {
                        "point_forecast": [1.0],
                        "quantiles": {"q50": [1.0]},
                    }
                },
                "metadata": {"loaded_model_id": model["model_id"]},
            }

        request = parse_warm_batch_request(
            {
                "mode": "warm_batch",
                "model_path": ".",
                "model_id": "google/timesfm-2.5-200m-pytorch",
                "series": [{"symbol": "BTCUSDT", "values": [1.0, 2.0, 3.0]}],
                "horizon": 1,
            }
        )
        session = ResidentTimesFmSession(warm_model_loader=load_model, warm_model_runner=run_model)

        first = session.run_warm_batch(request)
        second = session.run_warm_batch(request)

        self.assertEqual(load_calls, ["google/timesfm-2.5-200m-pytorch"])
        self.assertEqual(first["metadata"]["resident_model_cache_hit"], False)
        self.assertEqual(second["metadata"]["resident_model_cache_hit"], True)
        self.assertEqual(second["metadata"]["resident_model_load_count"], 1)


def json_dumps(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload, sort_keys=True)


def json_loads(payload: str) -> dict[str, object]:
    import json

    loaded = json.loads(payload)
    return loaded if isinstance(loaded, dict) else {}


if __name__ == "__main__":
    unittest.main()
