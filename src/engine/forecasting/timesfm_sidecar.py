from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Callable, TextIO, Sequence


FORBIDDEN_WARM_BATCH_FIELDS = {"order", "trade_action", "position_size", "executor_action"}


@dataclass(frozen=True)
class TimesFmSidecarRequest:
    model_path: str
    model_id: str
    values: list[float]
    horizon: int
    max_context: int = 512
    max_horizon: int = 128
    batch_size: int = 4
    device: str = "cpu"
    allow_model_download: bool = False
    torch_compile: bool = False
    quantile_names: tuple[str, ...] = ("q10", "q50", "q90")


@dataclass(frozen=True)
class TimesFmWarmBatchItem:
    symbol: str
    values: list[float]


@dataclass(frozen=True)
class TimesFmWarmBatchRequest:
    model_path: str
    model_id: str
    series: tuple[TimesFmWarmBatchItem, ...]
    horizon: int
    max_context: int = 512
    max_horizon: int = 128
    batch_size: int = 3
    device: str = "cpu"
    allow_model_download: bool = False
    torch_compile: bool = False
    quantile_names: tuple[str, ...] = ("q10", "q50", "q90")


def parse_sidecar_request(payload: dict[str, object]) -> TimesFmSidecarRequest:
    if payload.get("allow_model_download") is True:
        raise ValueError("model_download_not_allowed")
    model_path = str(payload.get("model_path") or "")
    if not model_path:
        raise ValueError("model_path_required")
    values = _float_list(payload.get("values"))
    if not values:
        raise ValueError("values_required")
    horizon = int(payload.get("horizon") or 0)
    if horizon <= 0:
        raise ValueError("horizon_must_be_positive")
    max_horizon = int(payload.get("max_horizon") or 128)
    if horizon > max_horizon:
        raise ValueError("horizon_exceeds_max_horizon")
    max_context = int(payload.get("max_context") or 512)
    if len(values) > max_context:
        raise ValueError("context_exceeds_max_context")
    quantile_names_raw = payload.get("quantile_names")
    quantile_names = (
        tuple(str(name) for name in quantile_names_raw)
        if isinstance(quantile_names_raw, list) and quantile_names_raw
        else ("q10", "q50", "q90")
    )
    return TimesFmSidecarRequest(
        model_path=model_path,
        model_id=str(payload.get("model_id") or "google/timesfm-2.5-200m-pytorch"),
        values=values,
        horizon=horizon,
        max_context=max_context,
        max_horizon=max_horizon,
        batch_size=int(payload.get("batch_size") or 4),
        device=str(payload.get("device") or "cpu").lower(),
        allow_model_download=False,
        torch_compile=bool(payload.get("torch_compile", False)),
        quantile_names=quantile_names,
    )


def parse_warm_batch_request(payload: dict[str, object]) -> TimesFmWarmBatchRequest:
    _reject_forbidden_warm_batch_fields(payload)
    if payload.get("allow_model_download") is True:
        raise ValueError("model_download_not_allowed")
    model_path = str(payload.get("model_path") or "")
    if not model_path:
        raise ValueError("model_path_required")
    series_raw = payload.get("series")
    if not isinstance(series_raw, list) or not series_raw:
        raise ValueError("series_required")
    series: list[TimesFmWarmBatchItem] = []
    for item in series_raw:
        if not isinstance(item, dict):
            raise ValueError("series_item_not_object")
        symbol = str(item.get("symbol") or "")
        if not symbol:
            raise ValueError("series_symbol_required")
        values = _float_list(item.get("values"))
        if not values:
            raise ValueError("series_values_required")
        series.append(TimesFmWarmBatchItem(symbol=symbol, values=values))
    horizon = int(payload.get("horizon") or 0)
    if horizon <= 0:
        raise ValueError("horizon_must_be_positive")
    max_horizon = int(payload.get("max_horizon") or 128)
    if horizon > max_horizon:
        raise ValueError("horizon_exceeds_max_horizon")
    max_context = int(payload.get("max_context") or 512)
    for item in series:
        if len(item.values) > max_context:
            raise ValueError("context_exceeds_max_context")
    quantile_names_raw = payload.get("quantile_names")
    quantile_names = (
        tuple(str(name) for name in quantile_names_raw)
        if isinstance(quantile_names_raw, list) and quantile_names_raw
        else ("q10", "q50", "q90")
    )
    return TimesFmWarmBatchRequest(
        model_path=model_path,
        model_id=str(payload.get("model_id") or "google/timesfm-2.5-200m-pytorch"),
        series=tuple(series),
        horizon=horizon,
        max_context=max_context,
        max_horizon=max_horizon,
        batch_size=int(payload.get("batch_size") or len(series)),
        device=str(payload.get("device") or "cpu").lower(),
        allow_model_download=False,
        torch_compile=bool(payload.get("torch_compile", False)),
        quantile_names=quantile_names,
    )


def build_sidecar_forecast_config(request: TimesFmSidecarRequest) -> dict[str, object]:
    return {
        "max_context": request.max_context,
        "max_horizon": request.max_horizon,
        "normalize_inputs": True,
        "per_core_batch_size": request.batch_size,
        "use_continuous_quantile_head": True,
        "force_flip_invariance": True,
        "infer_is_positive": True,
        "fix_quantile_crossing": True,
    }


def build_warm_batch_forecast_config(request: TimesFmWarmBatchRequest) -> dict[str, object]:
    return {
        "max_context": request.max_context,
        "max_horizon": request.max_horizon,
        "normalize_inputs": True,
        "per_core_batch_size": request.batch_size,
        "use_continuous_quantile_head": True,
        "force_flip_invariance": True,
        "infer_is_positive": True,
        "fix_quantile_crossing": True,
    }


def run_sidecar_forecast(request: TimesFmSidecarRequest) -> dict[str, object]:
    model_path = Path(request.model_path)
    if not model_path.exists():
        return {"status": "error", "reasons": ["model_weights_unavailable"]}
    if request.device not in {"cpu", "cuda"}:
        return {"status": "error", "reasons": [f"unsupported_device:{request.device}"]}
    try:
        import numpy as np
        import timesfm
        import torch
    except Exception as exc:
        return {"status": "error", "reasons": [f"sidecar_import_failed:{type(exc).__name__}"]}

    if request.device == "cuda" and not torch.cuda.is_available():
        return {"status": "error", "reasons": ["cuda_unavailable"]}
    if request.device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
        str(model_path),
        torch_compile=request.torch_compile,
        local_files_only=True,
    )
    model.compile(timesfm.ForecastConfig(**build_sidecar_forecast_config(request)))
    point_forecast, quantile_forecast = model.forecast(
        horizon=request.horizon,
        inputs=[np.asarray(request.values, dtype=np.float32)],
    )
    quantile_map = _quantile_map(quantile_forecast[0], request.quantile_names, request.horizon)
    return {
        "status": "ok",
        "point_forecast": [float(value) for value in point_forecast[0][: request.horizon]],
        "quantiles": quantile_map,
        "metadata": {
            "sidecar_runtime": "timesfm_2p5_torch",
            "model_path": str(model_path),
            "device": request.device,
            "torch_compile": request.torch_compile,
            "memory_peak_mb": _memory_peak_mb(request.device, torch),
            "model_download_attempted": False,
        },
    }


def run_warm_batch_forecast(request: TimesFmWarmBatchRequest) -> dict[str, object]:
    model_path = Path(request.model_path)
    if not model_path.exists():
        return {"status": "error", "reasons": ["model_weights_unavailable"]}
    if request.device not in {"cpu", "cuda"}:
        return {"status": "error", "reasons": [f"unsupported_device:{request.device}"]}
    try:
        import numpy as np
        import timesfm
        import torch
    except Exception as exc:
        return {"status": "error", "reasons": [f"sidecar_import_failed:{type(exc).__name__}"]}

    if request.device == "cuda" and not torch.cuda.is_available():
        return {"status": "error", "reasons": ["cuda_unavailable"]}
    if request.device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    load_start = perf_counter()
    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
        str(model_path),
        torch_compile=request.torch_compile,
        local_files_only=True,
    )
    model.compile(timesfm.ForecastConfig(**build_warm_batch_forecast_config(request)))
    load_latency_ms = round((perf_counter() - load_start) * 1000.0, 6)
    forecast_start = perf_counter()
    point_forecast, quantile_forecast = model.forecast(
        horizon=request.horizon,
        inputs=[np.asarray(item.values, dtype=np.float32) for item in request.series],
    )
    forecast_latency_ms = round((perf_counter() - forecast_start) * 1000.0, 6)
    forecasts: dict[str, dict[str, object]] = {}
    for index, item in enumerate(request.series):
        forecasts[item.symbol] = {
            "point_forecast": [float(value) for value in point_forecast[index][: request.horizon]],
            "quantiles": _quantile_map(quantile_forecast[index], request.quantile_names, request.horizon),
        }
    return {
        "status": "ok",
        "forecasts": forecasts,
        "metadata": {
            "sidecar_runtime": "timesfm_2p5_torch_warm_batch",
            "model_path": str(model_path),
            "device": request.device,
            "torch_compile": request.torch_compile,
            "model_load_count": 1,
            "batch_size_effective": len(request.series),
            "symbols": [item.symbol for item in request.series],
            "load_latency_ms": load_latency_ms,
            "forecast_latency_ms": forecast_latency_ms,
            "memory_peak_mb": _memory_peak_mb(request.device, torch),
            "model_download_attempted": False,
        },
    }


SidecarRunner = Callable[[TimesFmSidecarRequest], dict[str, object]]
WarmBatchRunner = Callable[[TimesFmWarmBatchRequest], dict[str, object]]
WarmModelLoader = Callable[[TimesFmWarmBatchRequest], object]
WarmModelRunner = Callable[[object, TimesFmWarmBatchRequest], dict[str, object]]


@dataclass(frozen=True)
class ResidentWarmBatchModelKey:
    model_path: str
    model_id: str
    max_context: int
    max_horizon: int
    batch_size: int
    device: str
    torch_compile: bool
    quantile_names: tuple[str, ...]


@dataclass(frozen=True)
class _LoadedResidentWarmBatchModel:
    model: object
    np_module: object
    torch_module: object
    model_path: str
    device: str
    torch_compile: bool
    load_latency_ms: float


class ResidentTimesFmSession:
    def __init__(
        self,
        *,
        sidecar_runner: SidecarRunner = run_sidecar_forecast,
        warm_model_loader: WarmModelLoader | None = None,
        warm_model_runner: WarmModelRunner | None = None,
    ) -> None:
        self._sidecar_runner = sidecar_runner
        self._warm_model_loader = warm_model_loader or _load_resident_warm_batch_model
        self._warm_model_runner = warm_model_runner or _run_resident_warm_batch_model
        self._warm_model_cache: dict[ResidentWarmBatchModelKey, object] = {}
        self._warm_model_load_count = 0

    def run_sidecar(self, request: TimesFmSidecarRequest) -> dict[str, object]:
        return self._sidecar_runner(request)

    def run_warm_batch(self, request: TimesFmWarmBatchRequest) -> dict[str, object]:
        key = _resident_warm_batch_model_key(request)
        cache_hit = key in self._warm_model_cache
        if cache_hit:
            model = self._warm_model_cache[key]
        else:
            model = self._warm_model_loader(request)
            if isinstance(model, dict) and model.get("status") == "error":
                return _with_resident_model_metadata(
                    model,
                    cache_hit=False,
                    model_load_count=self._warm_model_load_count,
                    cache_size=len(self._warm_model_cache),
                )
            self._warm_model_cache[key] = model
            self._warm_model_load_count += 1
        result = self._warm_model_runner(model, request)
        return _with_resident_model_metadata(
            result,
            cache_hit=cache_hit,
            model_load_count=self._warm_model_load_count,
            cache_size=len(self._warm_model_cache),
        )


def serve_resident_jsonl(
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    *,
    sidecar_runner: SidecarRunner = run_sidecar_forecast,
    warm_batch_runner: WarmBatchRunner | None = None,
) -> int:
    reader = input_stream or sys.stdin
    writer = output_stream or sys.stdout
    session = ResidentTimesFmSession(sidecar_runner=sidecar_runner) if warm_batch_runner is None else None
    request_index = 0
    for raw_line in reader:
        line = raw_line.strip()
        if not line:
            continue
        shutdown_requested = False
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("request_not_object")
            command = str(payload.get("command") or "")
            if command == "ping":
                result = {
                    "status": "ok",
                    "resident_command": "ping",
                    "metadata": {"resident_sidecar": True, "resident_request_index": request_index},
                }
            elif command == "shutdown":
                shutdown_requested = True
                result = {
                    "status": "ok",
                    "resident_command": "shutdown",
                    "metadata": {"resident_sidecar": True, "resident_request_index": request_index},
                }
            elif payload.get("mode") == "warm_batch":
                request_index += 1
                request = parse_warm_batch_request(payload)
                result = warm_batch_runner(request) if warm_batch_runner is not None else session.run_warm_batch(request)  # type: ignore[union-attr]
                result = _with_resident_metadata(result, request_index)
            else:
                request_index += 1
                request = parse_sidecar_request(payload)
                result = session.run_sidecar(request) if session is not None else sidecar_runner(request)
                result = _with_resident_metadata(result, request_index)
        except Exception as exc:
            result = {
                "status": "error",
                "reasons": [f"resident_sidecar_exception:{type(exc).__name__}"],
                "metadata": {"resident_sidecar": True, "error": str(exc), "resident_request_index": request_index},
            }
        print(json.dumps(result, sort_keys=True), file=writer, flush=True)
        if shutdown_requested:
            break
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--resident" in argv:
        return serve_resident_jsonl()
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("request_not_object")
        if payload.get("mode") == "warm_batch":
            request = parse_warm_batch_request(payload)
            result = run_warm_batch_forecast(request)
        else:
            request = parse_sidecar_request(payload)
            result = run_sidecar_forecast(request)
    except Exception as exc:
        result = {"status": "error", "reasons": [f"sidecar_exception:{type(exc).__name__}"], "metadata": {"error": str(exc)}}
    print(json.dumps(result, sort_keys=True))
    return 0


def _float_list(values: object) -> list[float]:
    if not isinstance(values, list):
        return []
    return [float(value) for value in values]


def _with_resident_metadata(result: dict[str, object], request_index: int) -> dict[str, object]:
    metadata = dict(result.get("metadata")) if isinstance(result.get("metadata"), dict) else {}
    metadata["resident_sidecar"] = True
    metadata["resident_request_index"] = request_index
    return {**result, "metadata": metadata}


def _with_resident_model_metadata(
    result: dict[str, object],
    *,
    cache_hit: bool,
    model_load_count: int,
    cache_size: int,
) -> dict[str, object]:
    metadata = dict(result.get("metadata")) if isinstance(result.get("metadata"), dict) else {}
    metadata["resident_model_cache_hit"] = cache_hit
    metadata["resident_model_load_count"] = model_load_count
    metadata["resident_model_cache_size"] = cache_size
    return {**result, "metadata": metadata}


def _resident_warm_batch_model_key(request: TimesFmWarmBatchRequest) -> ResidentWarmBatchModelKey:
    return ResidentWarmBatchModelKey(
        model_path=str(Path(request.model_path)),
        model_id=request.model_id,
        max_context=request.max_context,
        max_horizon=request.max_horizon,
        batch_size=request.batch_size,
        device=request.device,
        torch_compile=request.torch_compile,
        quantile_names=request.quantile_names,
    )


def _load_resident_warm_batch_model(request: TimesFmWarmBatchRequest) -> object:
    model_path = Path(request.model_path)
    if not model_path.exists():
        return {"status": "error", "reasons": ["model_weights_unavailable"]}
    if request.device not in {"cpu", "cuda"}:
        return {"status": "error", "reasons": [f"unsupported_device:{request.device}"]}
    try:
        import numpy as np
        import timesfm
        import torch
    except Exception as exc:
        return {"status": "error", "reasons": [f"sidecar_import_failed:{type(exc).__name__}"]}

    if request.device == "cuda" and not torch.cuda.is_available():
        return {"status": "error", "reasons": ["cuda_unavailable"]}
    if request.device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    load_start = perf_counter()
    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
        str(model_path),
        torch_compile=request.torch_compile,
        local_files_only=True,
    )
    model.compile(timesfm.ForecastConfig(**build_warm_batch_forecast_config(request)))
    return _LoadedResidentWarmBatchModel(
        model=model,
        np_module=np,
        torch_module=torch,
        model_path=str(model_path),
        device=request.device,
        torch_compile=request.torch_compile,
        load_latency_ms=round((perf_counter() - load_start) * 1000.0, 6),
    )


def _run_resident_warm_batch_model(model_handle: object, request: TimesFmWarmBatchRequest) -> dict[str, object]:
    if isinstance(model_handle, dict) and model_handle.get("status") == "error":
        return model_handle
    if not isinstance(model_handle, _LoadedResidentWarmBatchModel):
        return {"status": "error", "reasons": ["resident_model_handle_invalid"]}
    forecast_start = perf_counter()
    point_forecast, quantile_forecast = model_handle.model.forecast(
        horizon=request.horizon,
        inputs=[model_handle.np_module.asarray(item.values, dtype=model_handle.np_module.float32) for item in request.series],
    )
    forecast_latency_ms = round((perf_counter() - forecast_start) * 1000.0, 6)
    forecasts: dict[str, dict[str, object]] = {}
    for index, item in enumerate(request.series):
        forecasts[item.symbol] = {
            "point_forecast": [float(value) for value in point_forecast[index][: request.horizon]],
            "quantiles": _quantile_map(quantile_forecast[index], request.quantile_names, request.horizon),
        }
    return {
        "status": "ok",
        "forecasts": forecasts,
        "metadata": {
            "sidecar_runtime": "timesfm_2p5_torch_resident_warm_batch",
            "model_path": model_handle.model_path,
            "device": request.device,
            "torch_compile": request.torch_compile,
            "batch_size_effective": len(request.series),
            "symbols": [item.symbol for item in request.series],
            "load_latency_ms": model_handle.load_latency_ms,
            "forecast_latency_ms": forecast_latency_ms,
            "memory_peak_mb": _memory_peak_mb(request.device, model_handle.torch_module),
            "model_download_attempted": False,
        },
    }


def _reject_forbidden_warm_batch_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_WARM_BATCH_FIELDS:
                raise ValueError(f"forbidden_warm_batch_field:{key}")
            _reject_forbidden_warm_batch_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_warm_batch_fields(nested)


def _quantile_map(raw_quantiles: object, names: Sequence[str], horizon: int) -> dict[str, list[float]]:
    rows = raw_quantiles.tolist()
    quantile_indexes = {"q10": 1, "q50": 5, "q90": 9}
    mapped: dict[str, list[float]] = {}
    for name in names:
        index = quantile_indexes.get(name)
        if index is None:
            continue
        mapped[name] = [float(row[index]) for row in rows[:horizon]]
    return mapped


def _memory_peak_mb(device: str, torch_module: object) -> float | None:
    if device != "cuda":
        return None
    try:
        return round(float(torch_module.cuda.max_memory_allocated()) / (1024.0 * 1024.0), 6)
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
