from __future__ import annotations

from dataclasses import dataclass, field
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
from typing import Callable, Mapping, Sequence


DependencyProbe = Callable[[str], bool]


@dataclass(frozen=True)
class TimesFmAdapterConfig:
    profile_id: str = "timesfm_2p5_laptop_safe"
    model_id: str = "google/timesfm-2.5-200m-pytorch"
    backend: str = "pytorch"
    max_context: int = 512
    max_horizon: int = 128
    batch_size: int = 4
    allow_model_download: bool = False
    model_weights_path: str | None = None
    sidecar_python_path: str | None = None
    sidecar_timeout_seconds: float = 120.0
    torch_compile: bool = False
    device: str = "cpu"
    quantile_names: tuple[str, ...] = ("q10", "q50", "q90")


@dataclass(frozen=True)
class ForecastRequest:
    values: Sequence[float]
    horizon: int
    source_snapshot_id: str
    context_end_ts: str | None = None


@dataclass(frozen=True)
class TimesFmAvailability:
    available: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ForecastResult:
    status: str
    source: str
    model_id: str
    point_forecast: list[float] = field(default_factory=list)
    quantiles: dict[str, list[float]] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "source": self.source,
            "model_id": self.model_id,
            "point_forecast": list(self.point_forecast),
            "quantiles": {key: list(values) for key, values in self.quantiles.items()},
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
        }
        return payload


class TimesFmAdapter:
    def __init__(
        self,
        config: TimesFmAdapterConfig | None = None,
        *,
        fixture_forecast: Mapping[str, Sequence[float]] | None = None,
        dependency_probe: DependencyProbe | None = None,
        sidecar_runner: Callable[[dict[str, object], TimesFmAdapterConfig], dict[str, object]] | None = None,
    ) -> None:
        self.config = config or TimesFmAdapterConfig()
        self._fixture_forecast = fixture_forecast
        self._dependency_probe = dependency_probe or _module_available
        self._sidecar_runner = sidecar_runner or _run_sidecar_subprocess

    def availability(self) -> TimesFmAvailability:
        reasons: list[str] = []
        if self._uses_sidecar():
            sidecar_python = Path(str(self.config.sidecar_python_path))
            if not sidecar_python.is_file():
                reasons.append("sidecar_python_unavailable")
            if not self.config.model_weights_path or not Path(str(self.config.model_weights_path)).exists():
                reasons.append("model_weights_unavailable")
            if self.config.allow_model_download:
                reasons.append("model_download_not_allowed")
            return TimesFmAvailability(available=not reasons, reasons=reasons)

        for dependency in self._required_dependencies():
            if not self._dependency_probe(dependency):
                reasons.append(f"missing_optional_dependency:{dependency}")
        if not self.config.model_weights_path:
            reasons.append("model_weights_unavailable")
        return TimesFmAvailability(available=not reasons, reasons=reasons)

    def forecast(self, request: ForecastRequest) -> ForecastResult:
        self._validate_request(request)
        if self._fixture_forecast is not None:
            return self._fixture_result(request)

        availability = self.availability()
        if not availability.available:
            return ForecastResult(
                status="unavailable",
                source="timesfm_optional_adapter",
                model_id=self.config.model_id,
                reasons=availability.reasons,
                metadata=self._metadata(request),
            )

        if self._uses_sidecar():
            return self._sidecar_result(request)

        return ForecastResult(
            status="unavailable",
            source="timesfm_optional_adapter",
            model_id=self.config.model_id,
            reasons=["real_timesfm_inference_deferred_until_opt_in_smoke"],
            metadata=self._metadata(request),
        )

    def _fixture_result(self, request: ForecastRequest) -> ForecastResult:
        fixture = self._fixture_forecast or {}
        point = _slice_horizon(fixture.get("point", []), request.horizon)
        quantiles = {
            name: _slice_horizon(fixture.get(name, []), request.horizon)
            for name in self.config.quantile_names
            if name in fixture
        }
        return ForecastResult(
            status="ok",
            source="fixture_forecast",
            model_id=self.config.model_id,
            point_forecast=point,
            quantiles=quantiles,
            metadata=self._metadata(request),
        )

    def _metadata(self, request: ForecastRequest) -> dict[str, object]:
        return {
            "profile_id": self.config.profile_id,
            "backend": self.config.backend,
            "source_snapshot_id": request.source_snapshot_id,
            "context_end_ts": request.context_end_ts,
            "context_length": len(request.values),
            "horizon": request.horizon,
            "max_context": self.config.max_context,
            "max_horizon": self.config.max_horizon,
            "batch_size": self.config.batch_size,
            "device": self.config.device,
            "sidecar_python_path": self.config.sidecar_python_path,
            "model_download_attempted": False,
        }

    def _sidecar_result(self, request: ForecastRequest) -> ForecastResult:
        try:
            payload = self._sidecar_runner(self._sidecar_payload(request), self.config)
        except subprocess.TimeoutExpired:
            return ForecastResult(
                status="unavailable",
                source="timesfm_sidecar_adapter",
                model_id=self.config.model_id,
                reasons=["sidecar_timeout"],
                metadata=self._metadata(request),
            )
        except Exception as exc:
            return ForecastResult(
                status="unavailable",
                source="timesfm_sidecar_adapter",
                model_id=self.config.model_id,
                reasons=[f"sidecar_failed:{type(exc).__name__}"],
                metadata={**self._metadata(request), "sidecar_error": str(exc)},
            )

        if payload.get("status") != "ok":
            reasons = [str(reason) for reason in payload.get("reasons", []) if str(reason)]
            return ForecastResult(
                status="unavailable",
                source="timesfm_sidecar_adapter",
                model_id=self.config.model_id,
                reasons=reasons or ["sidecar_unavailable"],
                metadata={**self._metadata(request), **_dict_payload(payload.get("metadata"))},
            )

        return ForecastResult(
            status="ok",
            source="timesfm_sidecar_adapter",
            model_id=self.config.model_id,
            point_forecast=_slice_horizon(_float_list(payload.get("point_forecast", [])), request.horizon),
            quantiles={
                name: _slice_horizon(_float_list(_dict_payload(payload.get("quantiles")).get(name, [])), request.horizon)
                for name in self.config.quantile_names
                if name in _dict_payload(payload.get("quantiles"))
            },
            metadata={**self._metadata(request), **_dict_payload(payload.get("metadata"))},
        )

    def _sidecar_payload(self, request: ForecastRequest) -> dict[str, object]:
        return {
            "model_path": self.config.model_weights_path,
            "model_id": self.config.model_id,
            "values": [float(value) for value in request.values],
            "horizon": request.horizon,
            "max_context": self.config.max_context,
            "max_horizon": self.config.max_horizon,
            "batch_size": self.config.batch_size,
            "device": self.config.device,
            "allow_model_download": False,
            "torch_compile": self.config.torch_compile,
            "quantile_names": list(self.config.quantile_names),
        }

    def _uses_sidecar(self) -> bool:
        return bool(self.config.sidecar_python_path)

    def _required_dependencies(self) -> tuple[str, ...]:
        backend = self.config.backend.lower()
        if backend == "jax":
            return ("timesfm", "jax")
        return ("timesfm", "torch")

    def _validate_request(self, request: ForecastRequest) -> None:
        if request.horizon <= 0:
            raise ValueError("horizon_must_be_positive")
        if request.horizon > self.config.max_horizon:
            raise ValueError("horizon_exceeds_max_horizon")
        if not request.source_snapshot_id:
            raise ValueError("source_snapshot_id_required")
        if len(request.values) > self.config.max_context:
            raise ValueError("context_exceeds_max_context")


def _module_available(module_name: str) -> bool:
    return find_spec(module_name) is not None


def _slice_horizon(values: Sequence[float], horizon: int) -> list[float]:
    if len(values) < horizon:
        raise ValueError("fixture_forecast_shorter_than_horizon")
    return [float(value) for value in values[:horizon]]


def _run_sidecar_subprocess(payload: dict[str, object], config: TimesFmAdapterConfig) -> dict[str, object]:
    if not config.sidecar_python_path:
        raise ValueError("sidecar_python_path_required")
    env = dict(os.environ)
    src_root = Path(__file__).resolve().parents[2]
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_root) if not existing_pythonpath else str(src_root) + os.pathsep + existing_pythonpath
    completed = subprocess.run(
        [str(config.sidecar_python_path), "-m", "engine.forecasting.timesfm_sidecar"],
        input=json.dumps(payload, sort_keys=True),
        capture_output=True,
        text=True,
        timeout=max(float(config.sidecar_timeout_seconds), 0.001),
        env=env,
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


def _dict_payload(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _float_list(values: object) -> list[float]:
    if not isinstance(values, list):
        return []
    return [float(value) for value in values]
