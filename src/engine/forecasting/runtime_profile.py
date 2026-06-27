from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Callable, Iterable

from engine.forecasting.timesfm_adapter import ForecastRequest, ForecastResult, TimesFmAdapter, TimesFmAdapterConfig
from engine.io.artifacts import write_json_atomic


DEFAULT_TIMESFM_MODEL_ID = "google/timesfm-2.5-200m-pytorch"
FORBIDDEN_RUNTIME_PROFILE_FIELDS = {"order", "trade_action", "position_size", "executor_action"}


@dataclass(frozen=True)
class TimesFmRuntimeCase:
    case_id: str
    model_id: str
    backend: str
    device: str
    max_context: int
    horizon: int
    batch_size: int
    torch_compile: bool
    research_only: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TimesFmRuntimeBenchmarkConfig:
    matrix: list[TimesFmRuntimeCase]
    use_fixture: bool = False
    model_id: str = DEFAULT_TIMESFM_MODEL_ID
    backend: str = "pytorch"
    model_weights_path: str | None = None
    sidecar_python_path: str | None = None
    sidecar_timeout_seconds: float = 120.0


@dataclass(frozen=True)
class TimesFmWarmBatchBenchmarkConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    use_fixture: bool = False
    model_id: str = DEFAULT_TIMESFM_MODEL_ID
    backend: str = "pytorch"
    model_weights_path: str | None = None
    sidecar_python_path: str | None = None
    sidecar_timeout_seconds: float = 120.0
    max_context: int = 512
    horizon: int = 3
    batch_size: int = 3
    device: str = "cpu"
    torch_compile: bool = False
    resident_sidecar: bool = False


ForecastRunner = Callable[[TimesFmRuntimeCase], ForecastResult]
PhaseForecastRunner = Callable[[TimesFmRuntimeCase, str], ForecastResult]
Timer = Callable[[], float]


def build_timesfm_runtime_matrix(
    *,
    model_id: str = DEFAULT_TIMESFM_MODEL_ID,
    backend: str = "pytorch",
    context_lengths: Iterable[int] = (128, 256, 512),
    horizons: Iterable[int] = (1, 2, 3, 6),
    batch_sizes: Iterable[int] = (1, 3, 4),
    torch_compile_options: Iterable[bool] = (False, True),
    devices: Iterable[str] = ("cpu",),
) -> list[TimesFmRuntimeCase]:
    cases: list[TimesFmRuntimeCase] = []
    for device in devices:
        for context_length in context_lengths:
            for horizon in horizons:
                for batch_size in batch_sizes:
                    for torch_compile in torch_compile_options:
                        if int(context_length) <= 0 or int(horizon) <= 0 or int(batch_size) <= 0:
                            continue
                        case_id = (
                            f"{backend}-{device}-ctx{int(context_length)}"
                            f"-h{int(horizon)}-b{int(batch_size)}-tc{int(bool(torch_compile))}"
                        )
                        cases.append(
                            TimesFmRuntimeCase(
                                case_id=case_id,
                                model_id=model_id,
                                backend=backend,
                                device=str(device),
                                max_context=int(context_length),
                                horizon=int(horizon),
                                batch_size=int(batch_size),
                                torch_compile=bool(torch_compile),
                            )
                        )
    return cases


def run_timesfm_runtime_benchmark(
    config: TimesFmRuntimeBenchmarkConfig,
    *,
    forecast_runner: PhaseForecastRunner | None = None,
    timer: Timer = perf_counter,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    for case in config.matrix:
        runner = forecast_runner or _default_runner(config)
        results.append(_benchmark_case(case, runner=runner, timer=timer))

    selected_defaults = choose_laptop_safe_timesfm_defaults(results)
    status = "completed" if any(result["status"] == "ok" for result in results) else "skipped"
    report = {
        "schema_version": 1,
        "benchmark_id": "phase6-timesfm-runtime-profile",
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "research_only": True,
        "status": status,
        "model_id": config.model_id,
        "backend": config.backend,
        "results": results,
        "selected_defaults": selected_defaults,
        "skipped_reasons": _unique(
            reason
            for result in results
            for reason in result.get("skip_reasons", [])
            if isinstance(reason, str)
        ),
    }
    _reject_forbidden_fields(report)
    return report


def run_timesfm_warm_batch_benchmark(
    config: TimesFmWarmBatchBenchmarkConfig,
    *,
    timer: Timer = perf_counter,
) -> dict[str, object]:
    start = timer()
    if config.use_fixture:
        payload = _fixture_warm_batch_payload(config)
    else:
        skip_reasons = _warm_batch_skip_reasons(config)
        if skip_reasons:
            payload = {"status": "error", "reasons": skip_reasons, "metadata": {}}
        elif config.resident_sidecar:
            payload = _run_warm_batch_resident_sidecar_subprocess(config)
        else:
            payload = _run_warm_batch_sidecar_subprocess(config)
    elapsed = max(0.0, timer() - start)
    metadata = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    status = "completed" if payload.get("status") == "ok" else "skipped"
    forecasts = _forecast_payloads(payload.get("forecasts"))
    symbols = list(config.symbols)
    report = {
        "schema_version": 1,
        "benchmark_id": "phase6-timesfm-warm-batch-profile",
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "research_only": True,
        "mode": "warm_batch",
        "sidecar_mode": _warm_batch_sidecar_mode(config),
        "status": status,
        "model_id": config.model_id,
        "backend": config.backend,
        "symbols": symbols,
        "device": config.device,
        "max_context": config.max_context,
        "horizon": config.horizon,
        "batch_size": config.batch_size,
        "torch_compile": config.torch_compile,
        "subprocess_latency_ms": round(elapsed * 1000.0, 6),
        "load_latency_ms": _metadata_float(metadata, "load_latency_ms"),
        "forecast_latency_ms": _metadata_float(metadata, "forecast_latency_ms"),
        "memory_peak_mb": _metadata_float(metadata, "memory_peak_mb"),
        "model_load_count": int(metadata.get("model_load_count", 1 if config.use_fixture else 0) or 0),
        "batch_size_effective": int(metadata.get("batch_size_effective", len(forecasts)) or 0),
        "forecasts": forecasts,
        "results": [
            {
                "status": "ok" if status == "completed" else "skipped",
                "mode": "warm_batch",
                "symbols": symbols,
                "device": config.device,
                "max_context": config.max_context,
                "horizon": config.horizon,
                "batch_size": config.batch_size,
                "torch_compile": config.torch_compile,
                "subprocess_latency_ms": round(elapsed * 1000.0, 6),
                "load_latency_ms": _metadata_float(metadata, "load_latency_ms"),
                "forecast_latency_ms": _metadata_float(metadata, "forecast_latency_ms"),
                "memory_peak_mb": _metadata_float(metadata, "memory_peak_mb"),
                "skip_reasons": _string_list(payload.get("reasons")) if status == "skipped" else [],
            }
        ],
        "selected_defaults": {
            "profile_id": "timesfm_2p5_warm_batch",
            "model_id": config.model_id,
            "backend": config.backend,
            "device": config.device,
            "max_context": config.max_context,
            "horizon": config.horizon,
            "batch_size": config.batch_size,
            "torch_compile": config.torch_compile,
            "selection_reason": "warm_batch_profile_configuration" if status == "completed" else "warm_batch_skipped",
        },
        "skipped_reasons": _string_list(payload.get("reasons")) if status == "skipped" else [],
    }
    _reject_forbidden_fields(report)
    return report


def attach_forecast_campaign_to_runtime_profile(
    report: dict[str, object],
    *,
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    config_checksum: str | None = None,
) -> dict[str, object]:
    _reject_forbidden_fields(report)
    runtime_profile = _json_safe_copy(report)
    selected_defaults = _object_dict(runtime_profile.get("selected_defaults"))
    runtime_config = _campaign_runtime_config(runtime_profile, selected_defaults)
    checksum = config_checksum or _runtime_config_checksum(runtime_config)

    from engine.forecasting.campaign import build_forecast_validation_campaign

    campaign = build_forecast_validation_campaign(
        symbols=tuple(symbols),
        model_id=str(runtime_config["model_id"]),
        config_checksum=checksum,
        horizon=int(runtime_config["horizon"]),
        context_length=int(runtime_config["max_context"]),
    )
    payload = {
        "schema_version": 1,
        "artifact_type": "timesfm_forecast_campaign_runtime_flow",
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "research_only": True,
        "status": str(runtime_profile.get("status", "unknown")),
        "runtime_profile": runtime_profile,
        "campaign_runtime_config": {**runtime_config, "config_checksum": checksum},
        "forecast_validation_campaign": campaign.to_dict(),
        "skipped_reasons": _string_list(runtime_profile.get("skipped_reasons")),
    }
    _reject_forbidden_fields(payload)
    return payload


def choose_laptop_safe_timesfm_defaults(results: list[dict[str, object]]) -> dict[str, object]:
    successful_results = [
        result
        for result in results
        if result.get("status") == "ok"
        and int(result.get("max_context", 0)) <= 512
    ]
    cpu_results = [
        result
        for result in successful_results
        if str(result.get("device", "cpu")).lower() == "cpu"
    ]
    ok_results = cpu_results or successful_results
    if not ok_results:
        return {
            "profile_id": "timesfm_2p5_laptop_safe",
            "model_id": DEFAULT_TIMESFM_MODEL_ID,
            "backend": "pytorch",
            "device": "cpu",
            "max_context": 512,
            "horizon": 3,
            "batch_size": 1,
            "torch_compile": False,
            "selection_reason": "fallback_no_successful_benchmark",
        }
    chosen = min(
        ok_results,
        key=lambda result: (
            float(result.get("warm_latency_ms", result.get("cold_latency_ms", 1e18))),
            int(result.get("max_context", 0)),
            int(result.get("batch_size", 0)),
            bool(result.get("torch_compile", False)),
        ),
    )
    return {
        "profile_id": "timesfm_2p5_laptop_safe",
        "model_id": str(chosen["model_id"]),
        "backend": str(chosen["backend"]),
        "device": str(chosen["device"]),
        "max_context": int(chosen["max_context"]),
        "horizon": int(chosen["horizon"]),
        "batch_size": int(chosen["batch_size"]),
        "torch_compile": bool(chosen["torch_compile"]),
        "selection_reason": (
            "fastest_successful_laptop_safe_warm_latency"
            if cpu_results
            else "fastest_successful_available_warm_latency"
        ),
    }


def write_timesfm_runtime_profile(path: Path | str, report: dict[str, object]) -> Path:
    _reject_forbidden_fields(report)
    output = Path(path)
    return write_json_atomic(output, report)


def _benchmark_case(
    case: TimesFmRuntimeCase,
    *,
    runner: PhaseForecastRunner,
    timer: Timer,
) -> dict[str, object]:
    base = case.to_dict()
    cold_start = timer()
    cold_result = runner(case, phase="cold")
    cold_elapsed = max(0.0, timer() - cold_start)
    if cold_result.status != "ok":
        return {
            **base,
            "status": "skipped",
            "cold_latency_ms": round(cold_elapsed * 1000.0, 6),
            "warm_latency_ms": None,
            "cold_throughput_points_per_second": _throughput(case.horizon, cold_elapsed),
            "warm_throughput_points_per_second": None,
            "memory_peak_mb": _metadata_float(cold_result.metadata, "memory_peak_mb"),
            "skip_reasons": list(cold_result.reasons) or ["forecast_unavailable"],
            "source": cold_result.source,
        }

    warm_start = timer()
    warm_result = runner(case, phase="warm")
    warm_elapsed = max(0.0, timer() - warm_start)
    status = "ok" if warm_result.status == "ok" else "skipped"
    return {
        **base,
        "status": status,
        "cold_latency_ms": round(cold_elapsed * 1000.0, 6),
        "warm_latency_ms": round(warm_elapsed * 1000.0, 6) if status == "ok" else None,
        "cold_throughput_points_per_second": _throughput(case.horizon, cold_elapsed),
        "warm_throughput_points_per_second": _throughput(case.horizon, warm_elapsed) if status == "ok" else None,
        "memory_peak_mb": _metadata_float(warm_result.metadata, "memory_peak_mb"),
        "skip_reasons": [] if status == "ok" else list(warm_result.reasons),
        "source": warm_result.source,
        "point_count": len(warm_result.point_forecast),
        "quantile_schema": sorted(warm_result.quantiles),
    }


def _default_runner(config: TimesFmRuntimeBenchmarkConfig) -> PhaseForecastRunner:
    sidecar_probe_cache: dict[str, dict[str, object]] = {}

    def run(case: TimesFmRuntimeCase, phase: str) -> ForecastResult:
        device_skip_reasons = _device_skip_reasons(case, config=config, sidecar_probe_cache=sidecar_probe_cache)
        if device_skip_reasons and not config.use_fixture:
            return ForecastResult(
                status="unavailable",
                source="timesfm_runtime_benchmark",
                model_id=case.model_id,
                reasons=device_skip_reasons,
                metadata={"phase": phase},
            )
        if config.use_fixture:
            adapter = TimesFmAdapter(
                TimesFmAdapterConfig(
                    model_id=case.model_id,
                    backend=case.backend,
                    max_context=case.max_context,
                    max_horizon=max(case.horizon, 1),
                    batch_size=case.batch_size,
                    torch_compile=case.torch_compile,
                    device=case.device,
                ),
                fixture_forecast=_fixture_forecast(case.horizon),
            )
        else:
            adapter_config = TimesFmAdapterConfig(
                model_id=case.model_id,
                backend=case.backend,
                max_context=case.max_context,
                max_horizon=max(case.horizon, 1),
                batch_size=case.batch_size,
                allow_model_download=False,
                model_weights_path=config.model_weights_path,
                sidecar_python_path=config.sidecar_python_path,
                sidecar_timeout_seconds=config.sidecar_timeout_seconds,
                torch_compile=case.torch_compile,
                device=case.device,
            )
            adapter = TimesFmAdapter(adapter_config)
            availability = adapter.availability()
            if not availability.available:
                return ForecastResult(
                    status="unavailable",
                    source="timesfm_runtime_benchmark",
                    model_id=case.model_id,
                    reasons=availability.reasons,
                    metadata={"phase": phase},
                )
        return adapter.forecast(
            ForecastRequest(
                values=[float(index) for index in range(case.max_context)],
                horizon=case.horizon,
                source_snapshot_id=f"phase6-runtime-{case.case_id}",
                context_end_ts="2026-05-01T00:00:00+00:00",
            )
        )

    return run


def _fixture_forecast(horizon: int) -> dict[str, list[float]]:
    point = [float(index + 1) for index in range(horizon)]
    return {
        "point": point,
        "q10": [value - 0.25 for value in point],
        "q50": point,
        "q90": [value + 0.25 for value in point],
    }


def _fixture_warm_batch_payload(config: TimesFmWarmBatchBenchmarkConfig) -> dict[str, object]:
    point = [float(index + 1) for index in range(config.horizon)]
    forecasts = {
        symbol: {
            "point_forecast": point,
            "quantiles": {
                "q10": [value - 0.25 for value in point],
                "q50": point,
                "q90": [value + 0.25 for value in point],
            },
        }
        for symbol in config.symbols
    }
    return {
        "status": "ok",
        "forecasts": forecasts,
        "metadata": {
            "sidecar_runtime": "fixture_warm_batch",
            "model_load_count": 1,
            "batch_size_effective": len(config.symbols),
            "symbols": list(config.symbols),
            "load_latency_ms": 0.0,
            "forecast_latency_ms": 0.0,
            "memory_peak_mb": None,
            "model_download_attempted": False,
        },
    }


def _warm_batch_skip_reasons(config: TimesFmWarmBatchBenchmarkConfig) -> list[str]:
    reasons: list[str] = []
    if not config.sidecar_python_path or not Path(str(config.sidecar_python_path)).is_file():
        reasons.append("sidecar_python_unavailable")
    if not config.model_weights_path or not Path(str(config.model_weights_path)).exists():
        reasons.append("model_weights_unavailable")
    if reasons:
        return reasons
    probe = _probe_sidecar_runtime(str(config.sidecar_python_path))
    if not probe.get("usable"):
        return ["sidecar_python_unusable", *_string_list(probe.get("reasons"))]
    if config.device.lower() == "cuda" and not probe.get("cuda_available"):
        return ["cuda_unavailable"]
    if config.device.lower() not in {"cpu", "cuda"}:
        return [f"unsupported_device:{config.device}"]
    return []


def _run_warm_batch_sidecar_subprocess(config: TimesFmWarmBatchBenchmarkConfig) -> dict[str, object]:
    if not config.sidecar_python_path:
        return {"status": "error", "reasons": ["sidecar_python_unavailable"]}
    payload = _warm_batch_sidecar_payload(config)
    completed = subprocess.run(
        [str(config.sidecar_python_path), "-m", "engine.forecasting.timesfm_sidecar"],
        input=json.dumps(payload, sort_keys=True),
        capture_output=True,
        text=True,
        timeout=max(float(config.sidecar_timeout_seconds), 0.001),
        env=_sidecar_env(),
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "unknown"
        return {"status": "error", "reasons": [f"sidecar_process_failed:{completed.returncode}", stderr]}
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {"status": "error", "reasons": ["sidecar_invalid_json"], "metadata": {"error": str(exc)}}
    return parsed if isinstance(parsed, dict) else {"status": "error", "reasons": ["sidecar_payload_not_object"]}


def _run_warm_batch_resident_sidecar_subprocess(config: TimesFmWarmBatchBenchmarkConfig) -> dict[str, object]:
    if not config.sidecar_python_path:
        return {"status": "error", "reasons": ["sidecar_python_unavailable"]}
    request_payload = json.dumps(_warm_batch_sidecar_payload(config), sort_keys=True)
    shutdown_payload = json.dumps({"command": "shutdown"}, sort_keys=True)
    completed = subprocess.run(
        [str(config.sidecar_python_path), "-m", "engine.forecasting.timesfm_sidecar", "--resident"],
        input=request_payload + "\n" + request_payload + "\n" + shutdown_payload + "\n",
        capture_output=True,
        text=True,
        timeout=max(float(config.sidecar_timeout_seconds), 0.001),
        env=_sidecar_env(),
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "unknown"
        return {"status": "error", "reasons": [f"resident_sidecar_process_failed:{completed.returncode}", stderr]}
    forecast_payload: dict[str, object] | None = None
    for line in completed.stdout.splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("resident_command") != "shutdown":
            forecast_payload = parsed
    if forecast_payload is None:
        return {"status": "error", "reasons": ["resident_sidecar_no_forecast_payload"]}
    metadata = dict(forecast_payload.get("metadata")) if isinstance(forecast_payload.get("metadata"), dict) else {}
    metadata["resident_client_request_count"] = 2
    return {**forecast_payload, "metadata": metadata}


def _warm_batch_sidecar_payload(config: TimesFmWarmBatchBenchmarkConfig) -> dict[str, object]:
    return {
        "mode": "warm_batch",
        "model_path": config.model_weights_path,
        "model_id": config.model_id,
        "series": [
            {
                "symbol": symbol,
                "values": [float(index) for index in range(config.max_context)],
            }
            for symbol in config.symbols
        ],
        "horizon": config.horizon,
        "max_context": config.max_context,
        "max_horizon": max(config.horizon, 1),
        "batch_size": config.batch_size,
        "device": config.device,
        "allow_model_download": False,
        "torch_compile": config.torch_compile,
        "quantile_names": ["q10", "q50", "q90"],
    }


def _sidecar_env() -> dict[str, str]:
    env = dict(os.environ)
    src_root = Path(__file__).resolve().parents[2]
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_root) if not existing_pythonpath else str(src_root) + os.pathsep + existing_pythonpath
    return env


def _warm_batch_sidecar_mode(config: TimesFmWarmBatchBenchmarkConfig) -> str:
    if config.use_fixture:
        return "fixture"
    return "resident" if config.resident_sidecar else "subprocess"


def _forecast_payloads(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): nested for key, nested in value.items() if isinstance(nested, dict)}


def _campaign_runtime_config(
    report: dict[str, object],
    selected_defaults: dict[str, object],
) -> dict[str, object]:
    return {
        "model_id": str(_first_present(selected_defaults, report, "model_id", DEFAULT_TIMESFM_MODEL_ID)),
        "backend": str(_first_present(selected_defaults, report, "backend", "pytorch")),
        "device": str(_first_present(selected_defaults, report, "device", "cpu")),
        "max_context": int(_first_present(selected_defaults, report, "max_context", 512) or 512),
        "horizon": int(_first_present(selected_defaults, report, "horizon", 3) or 3),
        "batch_size": int(_first_present(selected_defaults, report, "batch_size", 1) or 1),
        "torch_compile": bool(_first_present(selected_defaults, report, "torch_compile", False)),
    }


def _runtime_config_checksum(config: dict[str, object]) -> str:
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _first_present(primary: dict[str, object], secondary: dict[str, object], key: str, fallback: object) -> object:
    value = primary.get(key)
    if value not in {None, ""}:
        return value
    value = secondary.get(key)
    if value not in {None, ""}:
        return value
    return fallback


def _object_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _json_safe_copy(value: dict[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(value, sort_keys=True))


def _reject_forbidden_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_RUNTIME_PROFILE_FIELDS:
                raise ValueError(f"forbidden_timesfm_runtime_profile_field:{key}")
            _reject_forbidden_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_fields(nested)


def _device_skip_reasons(
    case: TimesFmRuntimeCase,
    *,
    config: TimesFmRuntimeBenchmarkConfig,
    sidecar_probe_cache: dict[str, dict[str, object]],
) -> list[str]:
    device = case.device.lower()
    if device == "cpu":
        if config.sidecar_python_path and Path(str(config.sidecar_python_path)).is_file():
            probe = _cached_sidecar_probe(str(config.sidecar_python_path), sidecar_probe_cache)
            if not probe.get("usable"):
                return ["sidecar_python_unusable", *_string_list(probe.get("reasons"))]
        return []
    if device != "cuda":
        return [f"unsupported_device:{case.device}"]
    if config.sidecar_python_path and Path(str(config.sidecar_python_path)).is_file():
        probe = _cached_sidecar_probe(str(config.sidecar_python_path), sidecar_probe_cache)
        if not probe.get("usable"):
            return ["sidecar_python_unusable", *_string_list(probe.get("reasons"))]
        return [] if probe.get("cuda_available") else ["cuda_unavailable"]
    return [] if _cuda_available() else ["cuda_unavailable"]


def _cached_sidecar_probe(path: str, cache: dict[str, dict[str, object]]) -> dict[str, object]:
    if path not in cache:
        cache[path] = _probe_sidecar_runtime(path)
    return cache[path]


def _probe_sidecar_runtime(path: str) -> dict[str, object]:
    sidecar_python = Path(path)
    if not sidecar_python.is_file():
        return {"usable": False, "cuda_available": False, "reasons": ["sidecar_python_unavailable"]}
    probe_code = (
        "import json, sys\n"
        "payload={'usable': True, 'python': sys.executable, 'torch_available': False, 'cuda_available': False, 'reasons': []}\n"
        "try:\n"
        " import torch\n"
        " payload['torch_available']=True\n"
        " payload['cuda_available']=bool(torch.cuda.is_available())\n"
        "except Exception as exc:\n"
        " payload['reasons'].append('torch_probe_failed:'+type(exc).__name__)\n"
        "print(json.dumps(payload, sort_keys=True))\n"
    )
    try:
        completed = subprocess.run(
            [str(sidecar_python), "-c", probe_code],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return {
            "usable": False,
            "cuda_available": False,
            "reasons": [f"sidecar_python_probe_exception:{type(exc).__name__}"],
        }
    if completed.returncode != 0:
        return {
            "usable": False,
            "cuda_available": False,
            "reasons": [f"sidecar_python_probe_failed:{completed.returncode}"],
        }
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"usable": False, "cuda_available": False, "reasons": ["sidecar_python_probe_invalid_json"]}
    return parsed if isinstance(parsed, dict) else {"usable": False, "cuda_available": False, "reasons": ["sidecar_python_probe_not_object"]}


def _cuda_available() -> bool:
    if find_spec("torch") is None:
        return False
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _throughput(horizon: int, elapsed_seconds: float) -> float | None:
    if elapsed_seconds <= 0:
        return None
    return round(float(horizon) / elapsed_seconds, 6)


def _metadata_float(metadata: dict[str, object], key: str) -> float | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
