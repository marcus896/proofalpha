from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Callable

from engine.forecasting.artifacts import build_forecast_artifact, validate_forecast_artifact
from engine.forecasting.timesfm_adapter import ForecastRequest, TimesFmAdapter, TimesFmAdapterConfig


DependencyProbe = Callable[[str], bool]

ALLOWED_SMOKE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_CONTEXT_END_TS = "2026-05-01T00:00:00+00:00"
DEFAULT_FEATURE_TS = "2026-05-01T01:00:00+00:00"


@dataclass(frozen=True)
class TimesFmSmokeConfig:
    symbol: str = "BTCUSDT"
    horizon: int = 3
    backend: str = "pytorch"
    model_id: str = "google/timesfm-2.5-200m-pytorch"
    model_weights_path: str | None = None
    sidecar_python_path: str | None = None
    sidecar_timeout_seconds: float = 120.0
    use_fixture: bool = False
    max_context: int = 512
    max_horizon: int = 128
    batch_size: int = 4


def run_timesfm_smoke(
    config: TimesFmSmokeConfig | None = None,
    *,
    dependency_probe: DependencyProbe | None = None,
    sidecar_runner: Callable[[dict[str, object], TimesFmAdapterConfig], dict[str, object]] | None = None,
) -> dict[str, object]:
    smoke_config = config or TimesFmSmokeConfig()
    symbol = smoke_config.symbol.upper()
    if symbol not in ALLOWED_SMOKE_SYMBOLS:
        raise ValueError(f"unsupported_smoke_symbol:{smoke_config.symbol}")

    adapter_config = TimesFmAdapterConfig(
        model_id=smoke_config.model_id,
        backend=smoke_config.backend,
        max_context=smoke_config.max_context,
        max_horizon=smoke_config.max_horizon,
        batch_size=smoke_config.batch_size,
        allow_model_download=False,
        model_weights_path=smoke_config.model_weights_path,
        sidecar_python_path=smoke_config.sidecar_python_path,
        sidecar_timeout_seconds=smoke_config.sidecar_timeout_seconds,
    )
    values = _fixture_context(symbol)
    request = ForecastRequest(
        values=values,
        horizon=smoke_config.horizon,
        source_snapshot_id=_source_snapshot_id(symbol, smoke_config.use_fixture),
        context_end_ts=DEFAULT_CONTEXT_END_TS,
    )
    adapter = TimesFmAdapter(
        adapter_config,
        fixture_forecast=_fixture_forecast(values[-1]) if smoke_config.use_fixture else None,
        dependency_probe=dependency_probe,
        sidecar_runner=sidecar_runner,
    )
    result = adapter.forecast(request)

    base_payload: dict[str, object] = {
        "symbol": symbol,
        "mode": "fixture" if smoke_config.use_fixture else "real",
        "research_only": True,
        "profile_id": adapter_config.profile_id,
        "model_id": adapter_config.model_id,
        "backend": adapter_config.backend,
        "horizon": smoke_config.horizon,
        "context_length": len(values),
        "model_download_attempted": bool(result.metadata.get("model_download_attempted", False)),
        "adapter_status": result.status,
    }

    if result.status != "ok":
        base_payload.update(
            {
                "status": "skipped",
                "skip_reasons": list(result.reasons),
            }
        )
        return base_payload

    artifact = build_forecast_artifact(
        result,
        feature_timestamp=DEFAULT_FEATURE_TS,
        created_at=datetime.now(tz=UTC),
        config_checksum=_config_checksum(smoke_config),
        last_observed_value=values[-1],
    )
    validation = validate_forecast_artifact(artifact)
    base_payload.update(
        {
            "status": "passed" if validation.passed else "failed",
            "skip_reasons": [],
            "artifact": artifact.to_dict(),
            "artifact_validation": {
                "passed": validation.passed,
                "issues": list(validation.issues),
                "metrics": dict(validation.metrics),
            },
        }
    )
    return base_payload


def _source_snapshot_id(symbol: str, use_fixture: bool) -> str:
    mode = "fixture" if use_fixture else "real"
    return f"timesfm-smoke-{symbol.lower()}-{mode}"


def _fixture_context(symbol: str) -> list[float]:
    starts = {"BTCUSDT": 60000.0, "ETHUSDT": 3000.0, "SOLUSDT": 140.0}
    start = starts[symbol]
    return [start + float(index) for index in range(16)]


def _fixture_forecast(last_observed: float) -> dict[str, list[float]]:
    point = [last_observed + 1.0, last_observed + 2.0, last_observed + 3.0]
    return {
        "point": point,
        "q10": [value - 0.5 for value in point],
        "q50": list(point),
        "q90": [value + 0.5 for value in point],
    }


def _config_checksum(config: TimesFmSmokeConfig) -> str:
    payload = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
