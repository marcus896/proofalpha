from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from engine.agent.regression import (
    AgentLoopPolicyVariant,
    AgentLoopRegressionResult,
    build_evolution_summary,
    build_frontier_artifact,
    run_agent_loop_regression,
)
from engine.io.artifacts import write_json_atomic


RegressionRunner = Callable[[AgentLoopPolicyVariant], AgentLoopRegressionResult]


@dataclass(frozen=True)
class Phase5RegressionArtifacts:
    regression_payload: dict[str, object]
    frontier_artifact_path: Path
    evolution_summary_artifact_path: Path
    cache_info: dict[str, object]


def write_cached_phase5_regression_artifacts(
    *,
    output_dir: Path,
    root_run_id: str,
    settings: object,
    baseline_variant: AgentLoopPolicyVariant,
    current_variant: AgentLoopPolicyVariant,
    regression_runner: RegressionRunner = run_agent_loop_regression,
) -> Phase5RegressionArtifacts:
    cache_key = phase5_regression_cache_key(
        settings=settings,
        baseline_variant=baseline_variant,
        current_variant=current_variant,
    )
    cache_path = output_dir / f"phase5-regression-cache-{cache_key}.json"
    cache_status = "hit"
    cache_payload: dict[str, object] | None = None

    if cache_path.exists():
        cache_payload = load_valid_phase5_regression_cache(cache_path, cache_key)

    if cache_payload is None:
        cache_status = "miss"
        baseline_result = regression_runner(baseline_variant)
        current_result = regression_runner(current_variant)
        frontier_payload = build_frontier_artifact([baseline_result, current_result])
        evolution_payload = build_evolution_summary([baseline_result, current_result])
        current_result_payload = {
            **current_result.to_payload(),
            "acceptable_against_incumbent": current_result.acceptable_against(baseline_result),
            "incumbent_variant_id": baseline_variant.variant_id,
        }
        cache_payload = {
            "artifact_type": "agent_loop_phase5_regression_cache",
            "cache_schema_version": 1,
            "cache_key": cache_key,
            "controller_settings": _json_safe(_dataclass_payload(settings)),
            "baseline_variant": _json_safe(asdict(baseline_variant)),
            "current_variant": _json_safe(asdict(current_variant)),
            "phase5_regression_result": current_result_payload,
            "phase5_frontier": frontier_payload,
            "phase5_evolution_summary": evolution_payload,
        }
        write_json_atomic(cache_path, cache_payload)

    frontier_artifact_path = output_dir / f"{root_run_id}.phase5-frontier.json"
    evolution_summary_artifact_path = output_dir / f"{root_run_id}.phase5-evolution-summary.json"
    frontier_payload = dict(cache_payload.get("phase5_frontier", {}))
    evolution_payload = dict(cache_payload.get("phase5_evolution_summary", {}))
    regression_payload = dict(cache_payload.get("phase5_regression_result", {}))
    write_json_atomic(frontier_artifact_path, frontier_payload)
    write_json_atomic(evolution_summary_artifact_path, evolution_payload)
    cache_info = {
        "status": cache_status,
        "cache_key": cache_key,
        "cache_path": str(cache_path),
    }
    return Phase5RegressionArtifacts(
        regression_payload=regression_payload,
        frontier_artifact_path=frontier_artifact_path,
        evolution_summary_artifact_path=evolution_summary_artifact_path,
        cache_info=cache_info,
    )


def load_valid_phase5_regression_cache(cache_path: Path, cache_key: str) -> dict[str, object] | None:
    try:
        loaded = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    if not is_valid_phase5_regression_cache_payload(loaded, cache_key):
        return None
    return loaded


def is_valid_phase5_regression_cache_payload(payload: dict[str, object], cache_key: str) -> bool:
    if payload.get("artifact_type") != "agent_loop_phase5_regression_cache":
        return False
    if payload.get("cache_schema_version") != 1:
        return False
    if payload.get("cache_key") != cache_key:
        return False
    required_dict_fields = (
        "controller_settings",
        "baseline_variant",
        "current_variant",
        "phase5_regression_result",
        "phase5_frontier",
        "phase5_evolution_summary",
    )
    if any(not isinstance(payload.get(field_name), dict) for field_name in required_dict_fields):
        return False
    regression_payload = payload["phase5_regression_result"]
    frontier_payload = payload["phase5_frontier"]
    if "variant_id" not in regression_payload:
        return False
    if not isinstance(frontier_payload.get("frontier"), list):
        return False
    return True


def phase5_regression_cache_key(
    *,
    settings: object,
    baseline_variant: AgentLoopPolicyVariant,
    current_variant: AgentLoopPolicyVariant,
) -> str:
    canonical = json.dumps(
        {
            "cache_schema_version": 1,
            "controller_settings": _json_safe(_dataclass_payload(settings)),
            "baseline_variant": _json_safe(asdict(baseline_variant)),
            "current_variant": _json_safe(asdict(current_variant)),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dataclass_payload(value: object) -> dict[str, object]:
    try:
        payload = asdict(value)
    except TypeError:
        return {}
    return {str(key): item for key, item in payload.items()}


def _json_safe(raw: object) -> object:
    if isinstance(raw, Path):
        return str(raw)
    if isinstance(raw, dict):
        return {str(key): _json_safe(value) for key, value in raw.items()}
    if isinstance(raw, list):
        return [_json_safe(value) for value in raw]
    if isinstance(raw, tuple):
        return [_json_safe(value) for value in raw]
    return raw
