from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Sequence

from engine.forecasting.artifacts import REQUIRED_QUANTILES, ForecastArtifact, validate_forecast_artifact
from engine.io.artifacts import write_json_atomic


FORBIDDEN_RESEARCH_ARTIFACT_FIELDS = {"order", "trade_action", "position_size"}


@dataclass(frozen=True)
class ForecastCacheKey:
    key: str
    parts: dict[str, object]


@dataclass(frozen=True)
class ForecastArtifactMetadata:
    model_path: str
    model_sha256: str
    runtime_profile: str
    sidecar_version: str
    quantile_schema: Sequence[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "model_path": self.model_path,
            "model_sha256": self.model_sha256,
            "runtime_profile": self.runtime_profile,
            "sidecar_version": self.sidecar_version,
            "quantile_schema": list(self.quantile_schema),
        }


@dataclass(frozen=True)
class ForecastArtifactCacheRecord:
    path: Path
    payload: dict[str, object]
    cache_status: str
    metrics: dict[str, int]


def build_forecast_cache_key(
    *,
    source_snapshot_id: str,
    symbol: str,
    context_end_ts: datetime | str,
    context_length: int,
    horizon: int,
    model_id: str,
    model_sha256: str,
    config_checksum: str,
) -> ForecastCacheKey:
    parts: dict[str, object] = {
        "source_snapshot_id": source_snapshot_id,
        "symbol": symbol,
        "context_end_ts": _iso(_parse_ts(context_end_ts)),
        "context_length": int(context_length),
        "horizon": int(horizon),
        "model_id": model_id,
        "model_sha256": model_sha256,
        "config_checksum": config_checksum,
    }
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return ForecastCacheKey(key=hashlib.sha256(canonical.encode("utf-8")).hexdigest(), parts=parts)


def write_forecast_artifact(
    output_root: Path | str,
    artifact: ForecastArtifact,
    cache_key: ForecastCacheKey,
    metadata: ForecastArtifactMetadata,
) -> ForecastArtifactCacheRecord:
    validation = validate_forecast_artifact(artifact)
    if not validation.passed:
        raise ValueError(f"invalid_forecast_artifact:{validation.issues[0]}")
    _validate_metadata(metadata)

    payload: dict[str, object] = {
        "schema_version": 1,
        "research_only": True,
        "cache_key": cache_key.key,
        "cache_key_parts": dict(cache_key.parts),
        "cache_status": "miss_written",
        "artifact": artifact.to_dict(),
        "metadata": metadata.to_dict(),
        "validation": {
            "passed": validation.passed,
            "issues": list(validation.issues),
            "metrics": dict(validation.metrics),
        },
    }
    _reject_forbidden_fields(payload)

    forecast_dir = _forecast_output_dir(output_root)
    forecast_dir.mkdir(parents=True, exist_ok=True)
    path = forecast_dir / f"{cache_key.key}.json"
    write_json_atomic(path, payload)
    return ForecastArtifactCacheRecord(
        path=path,
        payload=payload,
        cache_status="miss_written",
        metrics={"cache_hits": 0, "cache_misses": 1},
    )


def load_cached_forecast_artifact(
    output_root: Path | str,
    cache_key: ForecastCacheKey,
) -> ForecastArtifactCacheRecord | None:
    path = _forecast_output_dir(output_root) / f"{cache_key.key}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("cache_key") != cache_key.key:
        return None
    _reject_forbidden_fields(payload)
    return ForecastArtifactCacheRecord(
        path=path,
        payload=payload,
        cache_status="hit",
        metrics={"cache_hits": 1, "cache_misses": 0},
    )


def get_or_create_forecast_artifact(
    output_root: Path | str,
    cache_key: ForecastCacheKey,
    metadata: ForecastArtifactMetadata,
    artifact_factory: Callable[[], ForecastArtifact],
) -> ForecastArtifactCacheRecord:
    cached = load_cached_forecast_artifact(output_root, cache_key)
    if cached is not None:
        return cached
    return write_forecast_artifact(output_root, artifact_factory(), cache_key, metadata)


def _validate_metadata(metadata: ForecastArtifactMetadata) -> None:
    values = metadata.to_dict()
    for key, value in values.items():
        if value in ("", None, []):
            raise ValueError(f"missing_forecast_artifact_metadata:{key}")
    if tuple(metadata.quantile_schema) != REQUIRED_QUANTILES:
        raise ValueError("malformed_forecast_artifact_metadata:quantile_schema")


def _reject_forbidden_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_RESEARCH_ARTIFACT_FIELDS:
                raise ValueError(f"forbidden_forecast_artifact_field:{key}")
            _reject_forbidden_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_fields(nested)


def _forecast_output_dir(output_root: Path | str) -> Path:
    root = Path(output_root)
    if root.name == "forecasts":
        return root
    return root / "forecasts"


def _parse_ts(value: datetime | str | object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
