from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from engine.agent.composer import AdvisoryInput, build_advisory_payload, build_advisory_variants
from engine.agent.skills import load_repo_skill_contracts
from engine.app.config import StudyConfig, build_study_signature_from_payload, load_study_config
from engine.app.runtime import build_runtime_functions
from engine.app.schema import build_study_schema
from engine.app.service import execute_research_cycle
from engine.memory.insights import (
    build_memory_summary as build_memory_summary_from_rows,
    count_excluded_dirty_rows as count_excluded_dirty_rows_from_rows,
    select_memory_rows as select_memory_rows_with_policy,
)
from engine.memory.query import query_run_memory
from engine.memory.store import ingest_artifact_directory, initialize_memory_db
from engine.io.artifacts import write_json_atomic
from engine.mcp.config import MCPProfile
from engine.mcp.discovery import get_tools_for_profile
from engine.mcp.profiles import get_profile_settings
from engine.reporting.runcards import load_runcard
from engine.strategy.catalog import catalog_by_family


@dataclass(frozen=True)
class AutoresearchExecution:
    run_id: str
    status: str
    memory_summary: dict[str, object]
    skip_reason: str | None = None
    duplicate_match: dict[str, object] | None = None
    accepted_duplicate_config_path: str | None = None
    runcard_path: str | None = None
    dashboard_path: str | None = None
    autoresearch_report_path: str | None = None
    next_study_config_path: str | None = None


@dataclass(frozen=True)
class AutoresearchBatchExecution:
    run_id: str
    status: str
    autoresearch_report_path: str | None
    accepted_duplicate_config_path: str | None
    next_study_variant_paths: dict[str, str]
    batch_report_path: str
    variant_runs: dict[str, dict[str, object]]
    preferred_variant: dict[str, object] | None = None
    base_run: dict[str, object] | None = None


def execute_autoresearch(
    study: StudyConfig,
    output_dir: Path,
    db_path: Path,
    memory_dir: Path | None = None,
    memory_limit: int = 25,
    memory_quality_policy: str = "clean-only",
    study_signature: str | None = None,
    allow_duplicate_study_signature: bool = False,
    agent_loop_metadata: dict[str, object] | None = None,
    research_program_version: str | None = None,
) -> AutoresearchExecution:
    initialize_memory_db(db_path)
    seed_dir = memory_dir or output_dir
    ingest_artifact_directory(db_path, seed_dir)
    all_rows, relevant_rows, memory_summary = _load_memory_context(
        db_path=db_path,
        snapshot_provenance=study.snapshot.provenance,
        symbol=study.snapshot.symbol,
        venue=study.snapshot.venue,
        memory_quality_policy=memory_quality_policy,
        memory_limit=memory_limit,
    )
    report_path = output_dir / f"{study.run_id}.autoresearch.json"

    duplicate_run_rows = query_run_memory(db_path, run_id=study.run_id, limit=1)
    duplicate_run_row = duplicate_run_rows[0] if duplicate_run_rows else None
    if duplicate_run_row is not None:
        duplicate_match = _build_duplicate_match(duplicate_run_row, match_type="run_id")
        report_payload = _build_autoresearch_report_payload(
            run_id=study.run_id,
            status="skipped",
            memory_summary=memory_summary,
            skip_reason="duplicate_run_id",
            duplicate_match=duplicate_match,
            runcard_path=None,
            dashboard_path=None,
            research_lineage=study.research_lineage,
        )
        _write_autoresearch_report(report_path, report_payload)
        return AutoresearchExecution(
            run_id=study.run_id,
            status="skipped",
            skip_reason="duplicate_run_id",
            duplicate_match=duplicate_match,
            memory_summary=memory_summary,
            autoresearch_report_path=str(report_path),
        )

    duplicate_signature_row = None
    if study_signature and not allow_duplicate_study_signature:
        duplicate_signature_row = next(
            (row for row in all_rows if str(row.get("study_signature")) == study_signature),
            None,
        )
    if duplicate_signature_row is not None:
        duplicate_match = _build_duplicate_match(duplicate_signature_row, match_type="study_signature")
        report_payload = _build_autoresearch_report_payload(
            run_id=study.run_id,
            status="skipped",
            memory_summary=memory_summary,
            skip_reason="duplicate_study_signature",
            duplicate_match=duplicate_match,
            runcard_path=None,
            dashboard_path=None,
            research_lineage=study.research_lineage,
        )
        _write_autoresearch_report(report_path, report_payload)
        return AutoresearchExecution(
            run_id=study.run_id,
            status="skipped",
            skip_reason="duplicate_study_signature",
            duplicate_match=duplicate_match,
            memory_summary=memory_summary,
            autoresearch_report_path=str(report_path),
        )

    evaluator, scenario_evaluator, validation_executor = build_runtime_functions(study)
    execution = execute_research_cycle(
        run_id=study.run_id,
        snapshot=study.snapshot,
        incumbent=study.incumbent,
        directional_layers=study.directional_layers,
        known_good_filters=study.known_good_filters,
        custom_filters=study.custom_filters,
        exit_layers=study.exit_layers,
        evaluator=evaluator,
        scenario_evaluator=scenario_evaluator,
        output_dir=output_dir,
        seed=study.seed,
        study_signature=study_signature,
        runtime_settings=asdict(study.runtime_settings),
        validation_executor=validation_executor,
        scenarios=study.scenarios,
        agent_loop_metadata=agent_loop_metadata,
        research_program_version=research_program_version,
    )
    ingest_artifact_directory(db_path, output_dir)
    _, _, memory_summary = _load_memory_context(
        db_path=db_path,
        snapshot_provenance=study.snapshot.provenance,
        symbol=study.snapshot.symbol,
        venue=study.snapshot.venue,
        memory_quality_policy=memory_quality_policy,
        memory_limit=memory_limit,
    )
    report_payload = _build_autoresearch_report_payload(
        run_id=study.run_id,
        status=execution.report.status,
        memory_summary=memory_summary,
        skip_reason=None,
        duplicate_match=None,
        runcard_path=execution.runcard_path,
        dashboard_path=execution.dashboard_path,
        research_lineage=study.research_lineage,
    )
    _write_autoresearch_report(report_path, report_payload)
    return AutoresearchExecution(
        run_id=study.run_id,
        status=execution.report.status,
        memory_summary=memory_summary,
        duplicate_match=None,
        runcard_path=execution.runcard_path,
        dashboard_path=execution.dashboard_path,
        autoresearch_report_path=str(report_path),
    )


def _load_memory_context(
    *,
    db_path: Path,
    snapshot_provenance: dict[str, object] | None,
    symbol: str,
    venue: str,
    memory_quality_policy: str,
    memory_limit: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    all_rows = _filter_memory_rows_for_snapshot_compatibility(
        query_run_memory(db_path, symbol=symbol, venue=venue),
        snapshot_provenance=snapshot_provenance,
    )
    relevant_rows = select_memory_rows_with_policy(
        all_rows,
        memory_quality_policy=memory_quality_policy,
        limit=memory_limit,
    )
    memory_summary = build_memory_summary_from_rows(
        relevant_rows,
        excluded_dirty_runs=count_excluded_dirty_rows_from_rows(all_rows, relevant_rows),
        memory_quality_policy=memory_quality_policy,
    )
    return all_rows, relevant_rows, memory_summary


def _filter_memory_rows_for_snapshot_compatibility(
    rows: list[dict[str, object]],
    *,
    snapshot_provenance: dict[str, object] | None,
) -> list[dict[str, object]]:
    if not isinstance(snapshot_provenance, dict) or not rows:
        return rows

    target_source_hash = snapshot_provenance.get("source_hash")
    if isinstance(target_source_hash, str) and target_source_hash:
        rows_with_source_hash = [row for row in rows if isinstance(row.get("snapshot_source_hash"), str) and row.get("snapshot_source_hash")]
        if rows_with_source_hash:
            return [row for row in rows_with_source_hash if row.get("snapshot_source_hash") == target_source_hash]

    target_build_version = snapshot_provenance.get("build_version")
    if isinstance(target_build_version, str) and target_build_version:
        rows_with_build_version = [
            row for row in rows if isinstance(row.get("snapshot_build_version"), str) and row.get("snapshot_build_version")
        ]
        if rows_with_build_version:
            return [row for row in rows_with_build_version if row.get("snapshot_build_version") == target_build_version]

    return rows






def _build_autoresearch_report_payload(
    run_id: str,
    status: str,
    memory_summary: dict[str, object],
    skip_reason: str | None,
    duplicate_match: dict[str, object] | None,
    runcard_path: str | None,
    dashboard_path: str | None,
    research_lineage: dict[str, object],
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "status": status,
        "skip_reason": skip_reason,
        "duplicate_match": duplicate_match,
        "memory_summary": memory_summary,
        "hypotheses": _build_hypotheses(memory_summary),
        "research_lineage": dict(research_lineage),
        "runcard_path": runcard_path,
        "dashboard_path": dashboard_path,
    }


def _build_duplicate_match(row: dict[str, object], *, match_type: str) -> dict[str, object]:
    return {
        "match_type": match_type,
        "run_id": row.get("run_id"),
        "decision": row.get("decision"),
        "study_signature": row.get("study_signature"),
        "selection_oos_sharpe": row.get("selection_oos_sharpe"),
        "snapshot_quality_status": row.get("snapshot_quality_status"),
    }


def _build_hypotheses(memory_summary: dict[str, object]) -> list[dict[str, object]]:
    hypotheses: list[dict[str, object]] = []
    promising_layers = memory_summary.get("promising_layers", [])
    fragile_layers = memory_summary.get("fragile_layers", [])
    top_duplicate_matches = memory_summary.get("top_duplicate_matches", [])
    scenario_profile_avoidance = memory_summary.get("scenario_profile_avoidance", {})
    if isinstance(promising_layers, list) and promising_layers:
        first = promising_layers[0]
        if isinstance(first, dict):
            hypotheses.append(
                {
                    "type": "promising_layer",
                    "layer_name": first.get("layer_name"),
                    "count": first.get("count"),
                }
            )
    if isinstance(fragile_layers, list) and fragile_layers:
        first = fragile_layers[0]
        if isinstance(first, dict):
            hypotheses.append(
                {
                    "type": "fragile_layer",
                    "layer_name": first.get("layer_name"),
                    "count": first.get("count"),
                }
            )
    if isinstance(top_duplicate_matches, list) and top_duplicate_matches:
        first = top_duplicate_matches[0]
        if isinstance(first, dict):
            hypotheses.append(
                {
                    "type": "duplicate_recovery_baseline",
                    "run_id": first.get("run_id"),
                    "count": first.get("count"),
                }
            )
    if isinstance(scenario_profile_avoidance, dict) and scenario_profile_avoidance:
        scenario_name, hint = next(iter(scenario_profile_avoidance.items()))
        if isinstance(scenario_name, str) and isinstance(hint, dict):
            hypotheses.append(
                {
                    "type": "fragile_scenario_profile",
                    "scenario_name": scenario_name,
                    "count": hint.get("count"),
                }
            )
    return hypotheses


def _write_autoresearch_report(path: Path, payload: dict[str, object]) -> None:
    write_json_atomic(path, payload)


def build_next_study_payload(
    base_payload: dict[str, object],
    memory_summary: dict[str, object],
    *,
    variant_name: str = "balanced",
    narrow_parameter_grids: bool = True,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> dict[str, object]:
    return build_advisory_payload(
        AdvisoryInput(
            base_payload=base_payload,
            memory_summary=memory_summary,
            layer_catalog=catalog_by_family(),
            study_schema=build_study_schema(),
            skill_contracts=_build_skill_contract_summaries(),
            mcp_environment=_build_mcp_environment_summary(),
            duplicate_baseline_history_by_variant=(
                {variant_name: duplicate_baseline_history}
                if isinstance(duplicate_baseline_history, dict)
                else {}
            ),
        ),
        variant_name=variant_name,
        narrow_parameter_grids=narrow_parameter_grids,
    )


def write_next_study_payload(path: Path, payload: dict[str, object]) -> None:
    write_json_atomic(path, payload)


def build_accepted_duplicate_payload(
    base_payload: dict[str, object],
    matched_row: dict[str, object],
    *,
    source_report_path: str,
) -> dict[str, object]:
    next_payload = json.loads(json.dumps(base_payload))
    base_run_id = str(next_payload.get("run_id", "study"))
    next_payload["run_id"] = f"{base_run_id}-accepted-duplicate"

    accepted_layers = _string_list(matched_row.get("accepted_layers"))
    phase_layers = set(_string_list(matched_row.get("phase_layers")))

    incumbent = next_payload.get("incumbent")
    if not isinstance(incumbent, dict):
        incumbent = {}
        next_payload["incumbent"] = incumbent
    incumbent["layers"] = accepted_layers

    layer_parameters = next_payload.get("layer_parameters")
    if not isinstance(layer_parameters, dict):
        layer_parameters = {}
        next_payload["layer_parameters"] = layer_parameters
    matched_parameters = matched_row.get("selected_parameters")
    if isinstance(matched_parameters, dict):
        for layer_name, parameters in matched_parameters.items():
            if isinstance(layer_name, str) and isinstance(parameters, dict):
                existing = layer_parameters.get(layer_name)
                if not isinstance(existing, dict):
                    existing = {}
                    layer_parameters[layer_name] = existing
                existing.update(parameters)

    for key in ("directional_layers", "known_good_filters", "custom_filters", "exit_layers"):
        values = next_payload.get(key, [])
        if isinstance(values, list):
            next_payload[key] = [value for value in values if isinstance(value, str) and value not in phase_layers]

    lineage = next_payload.get("research_lineage")
    if not isinstance(lineage, dict):
        lineage = {}
    lineage.update(
        {
            "accepted_duplicate_match_run_id": matched_row.get("run_id"),
            "accepted_duplicate_match_type": "duplicate_match",
            "accepted_duplicate_source_report": source_report_path,
        }
    )
    next_payload["research_lineage"] = lineage
    return next_payload


def build_next_study_variants(
    base_payload: dict[str, object],
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history_by_variant: dict[str, dict[str, object]] | None = None,
) -> dict[str, dict[str, object]]:
    return build_advisory_variants(
        AdvisoryInput(
            base_payload=base_payload,
            memory_summary=memory_summary,
            layer_catalog=catalog_by_family(),
            study_schema=build_study_schema(),
            skill_contracts=_build_skill_contract_summaries(),
            mcp_environment=_build_mcp_environment_summary(),
            duplicate_baseline_history_by_variant=duplicate_baseline_history_by_variant or {},
        )
    )


def materialize_next_study_variants(
    base_payload: dict[str, object],
    memory_summary: dict[str, object],
    output_dir: Path,
    base_run_id: str,
    *,
    duplicate_baseline_history_by_variant: dict[str, dict[str, object]] | None = None,
) -> dict[str, str]:
    variant_payloads = build_next_study_variants(
        base_payload,
        memory_summary,
        duplicate_baseline_history_by_variant=duplicate_baseline_history_by_variant,
    )
    variant_paths = {
        "balanced": output_dir / f"{base_run_id}.next-study.json",
        "conservative": output_dir / f"{base_run_id}.next-study.conservative.json",
        "exploratory": output_dir / f"{base_run_id}.next-study.exploratory.json",
    }
    for variant_name, path in variant_paths.items():
        write_next_study_payload(path, variant_payloads[variant_name])
    return {key: str(path) for key, path in variant_paths.items()}


def _build_skill_contract_summaries() -> list[dict[str, object]]:
    return [
        {
            "name": contract.name,
            "purpose": contract.purpose,
            "outputs": list(contract.outputs),
            "rules": list(contract.rules),
        }
        for contract in load_repo_skill_contracts()
    ]


def _build_mcp_environment_summary() -> dict[str, object]:
    profile = MCPProfile.READ_ONLY
    settings = get_profile_settings(profile)
    tools = get_tools_for_profile(profile)
    return {
        "profile": profile.value,
        "tool_categories": list(settings.default_tool_categories),
        "tool_names": [str(tool["name"]) for tool in tools if isinstance(tool.get("name"), str)],
        "launcher_enabled": settings.launcher_enabled,
    }


def _extract_layer_names(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    layer_names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            layer_name = item.get("layer_name")
            if isinstance(layer_name, str):
                layer_names.append(layer_name)
    return layer_names


def _reorder_layers(values: list[str], promising_layers: list[str]) -> list[str]:
    priority = {layer_name: index for index, layer_name in enumerate(promising_layers)}
    return sorted(values, key=lambda value: (priority.get(value, len(priority) + values.index(value)), values.index(value)))


def _reorder_scenarios(
    scenarios: list[dict[str, object]],
    scenario_priority: list[str],
) -> list[dict[str, object]]:
    priority = {scenario_name: index for index, scenario_name in enumerate(scenario_priority)}
    return sorted(
        scenarios,
        key=lambda item: (
            priority.get(str(item.get("name")), len(priority) + scenarios.index(item)),
            scenarios.index(item),
        ),
    )


def _build_variant_promising_layers(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> list[str]:
    global_promising_layers = _extract_layer_names(memory_summary.get("promising_layers"))
    if not isinstance(duplicate_baseline_history, dict):
        return global_promising_layers

    variant_promising_layers = _extract_layer_names(duplicate_baseline_history.get("promising_layers"))
    merged_layers = list(variant_promising_layers)
    merged_layers.extend(layer for layer in global_promising_layers if layer not in merged_layers)
    return merged_layers


def _build_variant_parameter_hints(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    global_parameter_hints = memory_summary.get("parameter_hints", {})
    if not isinstance(global_parameter_hints, dict):
        global_parameter_hints = {}

    merged: dict[str, dict[str, object]] = {
        layer_name: dict(layer_hints)
        for layer_name, layer_hints in global_parameter_hints.items()
        if isinstance(layer_name, str) and isinstance(layer_hints, dict)
    }
    if not isinstance(duplicate_baseline_history, dict):
        return merged

    variant_parameter_hints = duplicate_baseline_history.get("parameter_hints", {})
    if not isinstance(variant_parameter_hints, dict):
        return merged

    for layer_name, layer_hints in variant_parameter_hints.items():
        if not isinstance(layer_name, str) or not isinstance(layer_hints, dict):
            continue
        existing = merged.setdefault(layer_name, {})
        for parameter_name, hint in layer_hints.items():
            if isinstance(parameter_name, str) and isinstance(hint, dict):
                existing[parameter_name] = dict(hint)
    return merged


def _extract_scenario_names(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    scenario_names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            scenario_name = item.get("scenario_name")
            if isinstance(scenario_name, str):
                scenario_names.append(scenario_name)
    return scenario_names


def _build_variant_scenario_priority(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> list[str]:
    global_scenarios = _extract_scenario_names(memory_summary.get("scenario_profiles"))
    if not isinstance(duplicate_baseline_history, dict):
        return global_scenarios

    variant_scenarios = _extract_scenario_names(duplicate_baseline_history.get("scenario_profiles"))
    merged = list(variant_scenarios)
    merged.extend(scenario_name for scenario_name in global_scenarios if scenario_name not in merged)
    return merged


def _build_variant_scenario_profile_hints(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    global_hints = memory_summary.get("scenario_profile_hints", {})
    if not isinstance(global_hints, dict):
        global_hints = {}

    merged: dict[str, dict[str, object]] = {
        scenario_name: dict(hint)
        for scenario_name, hint in global_hints.items()
        if isinstance(scenario_name, str) and isinstance(hint, dict)
    }
    if not isinstance(duplicate_baseline_history, dict):
        return merged

    variant_hints = duplicate_baseline_history.get("scenario_profile_hints", {})
    if not isinstance(variant_hints, dict):
        return merged

    for scenario_name, hint in variant_hints.items():
        if isinstance(scenario_name, str) and isinstance(hint, dict):
            merged[scenario_name] = dict(hint)
    return merged


def _build_variant_scenario_profile_avoidance(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    global_avoidance = memory_summary.get("scenario_profile_avoidance", {})
    if not isinstance(global_avoidance, dict):
        global_avoidance = {}

    merged: dict[str, dict[str, object]] = {
        scenario_name: dict(hint)
        for scenario_name, hint in global_avoidance.items()
        if isinstance(scenario_name, str) and isinstance(hint, dict)
    }
    if not isinstance(duplicate_baseline_history, dict):
        return merged

    variant_avoidance = duplicate_baseline_history.get("scenario_profile_avoidance", {})
    if not isinstance(variant_avoidance, dict):
        return merged

    for scenario_name, hint in variant_avoidance.items():
        if isinstance(scenario_name, str) and isinstance(hint, dict):
            merged[scenario_name] = dict(hint)
    return merged


def _build_variant_runtime_profile_hints(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> dict[str, object]:
    global_hints = memory_summary.get("runtime_profile_hints", {})
    if not isinstance(global_hints, dict):
        global_hints = {}
    merged = dict(global_hints)
    if not isinstance(duplicate_baseline_history, dict):
        return merged
    variant_hints = duplicate_baseline_history.get("runtime_profile_hints", {})
    if not isinstance(variant_hints, dict):
        return merged
    merged.update(variant_hints)
    return merged


def _build_variant_fragile_layers(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> set[str]:
    fragile_layers = set(_extract_layer_names(memory_summary.get("fragile_layers")))
    if not isinstance(duplicate_baseline_history, dict):
        return fragile_layers

    fragile_layers.update(_extract_layer_names(duplicate_baseline_history.get("fragile_layers")))
    return fragile_layers


def _apply_scenario_profile_hints(
    scenarios: list[object],
    *,
    scenario_priority: list[str],
    scenario_profile_hints: dict[str, dict[str, object]],
    scenario_profile_avoidance: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    scenario_payloads = [dict(item) for item in scenarios if isinstance(item, dict)]
    if not scenario_payloads:
        return []

    ordered = _reorder_scenarios(scenario_payloads, scenario_priority)
    resolved: list[dict[str, object]] = []
    for scenario in ordered:
        scenario_name = scenario.get("name")
        hint = scenario_profile_hints.get(scenario_name) if isinstance(scenario_name, str) else None
        if not isinstance(hint, dict):
            resolved.append(scenario)
            continue
        profile = hint.get("profile")
        if not isinstance(profile, dict):
            resolved.append(scenario)
            continue
        avoidance = scenario_profile_avoidance.get(scenario_name) if isinstance(scenario_name, str) else None
        if isinstance(avoidance, dict):
            blocked_profile = avoidance.get("profile")
            if isinstance(blocked_profile, dict) and _profiles_match(profile, blocked_profile):
                resolved.append(scenario)
                continue
        merged = dict(profile)
        merged.update(scenario)
        resolved.append(merged)
    return resolved


def _apply_runtime_profile_hints(
    payload: dict[str, object],
    runtime_profile_hints: dict[str, object],
) -> None:
    if not isinstance(runtime_profile_hints, dict) or not runtime_profile_hints:
        return
    profile = runtime_profile_hints.get("profile")
    if not isinstance(profile, dict) or not profile:
        return
    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        runtime = {}
        payload["runtime"] = runtime
    for key, value in profile.items():
        runtime.setdefault(key, value)


def _profiles_match(left: dict[str, object], right: dict[str, object]) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _filter_parameter_grids(
    parameter_grids: dict[str, object],
    fragile_layers: set[str],
) -> dict[str, object]:
    return {
        layer_name: grid
        for layer_name, grid in parameter_grids.items()
        if isinstance(layer_name, str) and layer_name not in fragile_layers
    }


def _refine_parameter_grids(
    parameter_grids: dict[str, object],
    parameter_hints: dict[str, object],
    fragile_layers: set[str],
) -> dict[str, object]:
    refined: dict[str, object] = {}
    for layer_name, grid in parameter_grids.items():
        if not isinstance(layer_name, str) or layer_name in fragile_layers:
            continue
        if not isinstance(grid, dict):
            refined[layer_name] = grid
            continue
        layer_hints = parameter_hints.get(layer_name, {})
        if not isinstance(layer_hints, dict):
            refined[layer_name] = grid
            continue
        refined[layer_name] = {
            parameter_name: _refine_parameter_spec(spec, layer_hints.get(parameter_name))
            for parameter_name, spec in grid.items()
        }
    return refined


def _refine_parameter_spec(spec: object, hint: object) -> object:
    if not isinstance(spec, dict) or not isinstance(hint, dict):
        return spec
    if "minimum" not in spec or "maximum" not in spec or "step" not in spec:
        return spec
    confidence = str(hint.get("confidence", "low"))
    hint_minimum = hint.get("minimum")
    hint_maximum = hint.get("maximum")
    if not isinstance(hint_minimum, (int, float)) or not isinstance(hint_maximum, (int, float)):
        return spec
    refined = dict(spec)
    if bool(hint.get("narrowed")):
        refined["minimum"] = hint_minimum
        refined["maximum"] = hint_maximum
        return refined

    if confidence not in {"medium", "high"}:
        return spec

    blocked_values = hint.get("blocked_values", [])
    if not isinstance(blocked_values, list):
        blocked_values = []
    numeric_blocked_values = [value for value in blocked_values if isinstance(value, (int, float))]

    spec_minimum = spec.get("minimum")
    spec_maximum = spec.get("maximum")
    if isinstance(spec_minimum, (int, float)) and spec_minimum in blocked_values and hint_minimum > spec_minimum:
        refined["minimum"] = hint_minimum
    if isinstance(spec_maximum, (int, float)) and spec_maximum in blocked_values and hint_maximum < spec_maximum:
        refined["maximum"] = hint_maximum
    interior_blocked_values = sorted(
        value
        for value in numeric_blocked_values
        if value != refined.get("minimum") and value != refined.get("maximum")
        and value > float(refined.get("minimum", spec_minimum))
        and value < float(refined.get("maximum", spec_maximum))
    )
    if interior_blocked_values:
        refined["excluded_values"] = interior_blocked_values
    return refined


def _rank_counter(counter: Counter[str]) -> list[dict[str, object]]:
    return [
        {"layer_name": layer_name, "count": count}
        for layer_name, count in counter.most_common()
    ]


def _rank_named_counter(counter: Counter[str], *, key_name: str) -> list[dict[str, object]]:
    return [
        {key_name: name, "count": count}
        for name, count in counter.most_common()
    ]


def _build_scenario_profile_hints_from_counters(
    profile_counters: dict[str, Counter[str]],
    minimum_count: int = 1,
) -> dict[str, dict[str, object]]:
    hints: dict[str, dict[str, object]] = {}
    for scenario_name, profile_counter in profile_counters.items():
        if not isinstance(scenario_name, str) or not profile_counter:
            continue
        serialized_profile, count = profile_counter.most_common(1)[0]
        if count < max(1, minimum_count):
            continue
        try:
            profile = json.loads(serialized_profile)
        except json.JSONDecodeError:
            continue
        if not isinstance(profile, dict):
            continue
        hints[scenario_name] = {
            "count": count,
            "profile": profile,
        }
    return hints


def _build_runtime_profile_hint_from_counter(profile_counter: Counter[str]) -> dict[str, object]:
    if not profile_counter:
        return {}
    serialized_profile, count = profile_counter.most_common(1)[0]
    try:
        profile = json.loads(serialized_profile)
    except json.JSONDecodeError:
        return {}
    if not isinstance(profile, dict):
        return {}
    return {
        "count": count,
        "profile": profile,
    }


def _build_parameter_hint(
    promoted_values: list[int | float],
    blocked_values: list[int | float],
) -> dict[str, object]:
    unique_promoted = sorted(set(promoted_values))
    unique_blocked = sorted(set(blocked_values))
    promoted_count = len(promoted_values)
    consensus = len(unique_promoted) == 1
    blocked_overlap = any(value in unique_blocked for value in unique_promoted)

    confidence = "low"
    narrowed = False
    if promoted_count >= 2 and consensus and not blocked_overlap:
        confidence = "high"
        narrowed = True
    elif promoted_count >= 2:
        confidence = "medium"

    return {
        "minimum": min(promoted_values),
        "maximum": max(promoted_values),
        "promoted_count": promoted_count,
        "blocked_values": unique_blocked,
        "confidence": confidence,
        "narrowed": narrowed,
    }


def _build_parameter_avoidance(parameter_hints: dict[str, object]) -> dict[str, dict[str, list[int | float]]]:
    if not isinstance(parameter_hints, dict):
        return {}

    avoidance: dict[str, dict[str, list[int | float]]] = {}
    for layer_name, layer_hints in parameter_hints.items():
        if not isinstance(layer_name, str) or not isinstance(layer_hints, dict):
            continue
        blocked_for_layer: dict[str, list[int | float]] = {}
        for parameter_name, hint in layer_hints.items():
            if not isinstance(parameter_name, str) or not isinstance(hint, dict):
                continue
            if hint.get("confidence") != "high":
                continue
            blocked_values = hint.get("blocked_values", [])
            if isinstance(blocked_values, list) and blocked_values:
                blocked_for_layer[parameter_name] = list(blocked_values)
        if blocked_for_layer:
            avoidance[layer_name] = blocked_for_layer
    return avoidance


def _build_variant_metadata(variant_name: str) -> dict[str, str]:
    descriptions = {
        "balanced": "Prunes fragile layers and narrows only high-confidence parameter regions.",
        "conservative": "Uses the balanced follow-up with stricter validation-oriented runtime settings.",
        "exploratory": "Keeps wider parameter grids while still applying memory-driven layer ordering and pruning.",
    }
    return {
        "name": variant_name,
        "description": descriptions.get(variant_name, "Autoresearch follow-up variant."),
    }


def _apply_variant_runtime(payload: dict[str, object], variant_name: str) -> None:
    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        runtime = {}
        payload["runtime"] = runtime

    if variant_name == "conservative":
        runtime["bootstrap_samples"] = max(int(runtime.get("bootstrap_samples", 8)), 16)
        runtime["search_summary_limit"] = max(int(runtime.get("search_summary_limit", 3)), 5)
        runtime["holdout_sharpe_floor"] = max(float(runtime.get("holdout_sharpe_floor", 1.0)), 1.0)
    elif variant_name == "exploratory":
        runtime["max_parameter_permutations"] = max(int(runtime.get("max_parameter_permutations", 64)), 128)
        runtime["search_summary_limit"] = max(int(runtime.get("search_summary_limit", 3)), 5)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def execute_autoresearch_batch(
    study: StudyConfig,
    base_payload: dict[str, object],
    output_dir: Path,
    db_path: Path,
    memory_dir: Path | None = None,
    memory_limit: int = 25,
    memory_quality_policy: str = "clean-only",
    study_signature: str | None = None,
) -> AutoresearchBatchExecution:
    base_execution = execute_autoresearch(
        study=study,
        output_dir=output_dir,
        db_path=db_path,
        memory_dir=memory_dir,
        memory_limit=memory_limit,
        memory_quality_policy=memory_quality_policy,
        study_signature=study_signature,
    )
    accepted_duplicate_config_path = _materialize_accepted_duplicate_from_memory(
        base_payload=base_payload,
        duplicate_match=base_execution.duplicate_match,
        report_path=base_execution.autoresearch_report_path,
        db_path=db_path,
        output_dir=output_dir,
        run_id=study.run_id,
    )
    duplicate_baseline_run_id = _extract_duplicate_baseline_run_id(study.research_lineage)
    duplicate_baseline_history = _load_duplicate_baseline_variant_history(
        db_path=db_path,
        duplicate_baseline_run_id=duplicate_baseline_run_id,
        memory_quality_policy=memory_quality_policy,
        snapshot_provenance=study.snapshot.provenance,
    )
    variant_paths = materialize_next_study_variants(
        base_payload,
        base_execution.memory_summary,
        output_dir,
        study.run_id,
        duplicate_baseline_history_by_variant=duplicate_baseline_history,
    )

    base_run = _load_batch_run_summary(
        run_id=study.run_id,
        status=base_execution.status,
        runcard_path=base_execution.runcard_path,
        dashboard_path=base_execution.dashboard_path,
    )

    variant_runs: dict[str, dict[str, object]] = {}
    for variant_name in ("balanced", "conservative", "exploratory"):
        variant_path = Path(variant_paths[variant_name])
        variant_payload = json.loads(variant_path.read_text(encoding="utf-8"))
        variant_study = load_study_config(variant_path)
        variant_signature = build_study_signature_from_payload(variant_payload)
        evaluator, scenario_evaluator, validation_executor = build_runtime_functions(variant_study)
        execution = execute_research_cycle(
            run_id=variant_study.run_id,
            snapshot=variant_study.snapshot,
            incumbent=variant_study.incumbent,
            directional_layers=variant_study.directional_layers,
            known_good_filters=variant_study.known_good_filters,
            custom_filters=variant_study.custom_filters,
            exit_layers=variant_study.exit_layers,
            evaluator=evaluator,
            scenario_evaluator=scenario_evaluator,
            output_dir=output_dir,
            seed=variant_study.seed,
            study_signature=variant_signature,
            runtime_settings=asdict(variant_study.runtime_settings),
            validation_executor=validation_executor,
            scenarios=variant_study.scenarios,
        )
        ingest_artifact_directory(db_path, output_dir)
        _, _, variant_memory_summary = _load_memory_context(
            db_path=db_path,
            snapshot_provenance=variant_study.snapshot.provenance,
            symbol=variant_study.snapshot.symbol,
            venue=variant_study.snapshot.venue,
            memory_quality_policy=memory_quality_policy,
            memory_limit=memory_limit,
        )
        variant_report_path = output_dir / f"{variant_study.run_id}.autoresearch.json"
        _write_autoresearch_report(
            variant_report_path,
            _build_autoresearch_report_payload(
                run_id=variant_study.run_id,
                status=execution.report.status,
                memory_summary=variant_memory_summary,
                skip_reason=None,
                duplicate_match=None,
                runcard_path=execution.runcard_path,
                dashboard_path=execution.dashboard_path,
                research_lineage=variant_study.research_lineage,
            ),
        )
        variant_runs[variant_name] = _load_batch_run_summary(
            run_id=execution.runcard.run_id,
            status=execution.report.status,
            runcard_path=execution.runcard_path,
            dashboard_path=execution.dashboard_path,
        )

    variant_results = _rank_variant_results(variant_runs, base_run, duplicate_baseline_history)
    preferred_variant = variant_results[0] if variant_results else None
    batch_report_path = output_dir / f"{study.run_id}.variant-batch.json"
    batch_report_payload = {
        "run_id": study.run_id,
        "status": base_execution.status,
        "autoresearch_report_path": base_execution.autoresearch_report_path,
        "accepted_duplicate_config_path": accepted_duplicate_config_path,
        "next_study_variant_paths": variant_paths,
        "base_run": base_run,
        "duplicate_baseline_run_id": duplicate_baseline_run_id,
        "duplicate_baseline_history": duplicate_baseline_history,
        "preferred_variant": preferred_variant,
        "variant_results": variant_results,
    }
    write_json_atomic(batch_report_path, batch_report_payload)
    return AutoresearchBatchExecution(
        run_id=study.run_id,
        status=base_execution.status,
        autoresearch_report_path=base_execution.autoresearch_report_path,
        accepted_duplicate_config_path=accepted_duplicate_config_path,
        next_study_variant_paths=variant_paths,
        batch_report_path=str(batch_report_path),
        variant_runs=variant_runs,
        preferred_variant=preferred_variant,
        base_run=base_run,
    )


def _load_batch_run_summary(
    run_id: str,
    status: str,
    runcard_path: str | None,
    dashboard_path: str | None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "run_id": run_id,
        "status": status,
        "runcard_path": runcard_path,
        "dashboard_path": dashboard_path,
        "metrics": {},
    }
    if not runcard_path:
        return summary

    runcard = load_runcard(Path(runcard_path))
    summary["metrics"] = dict(runcard.metrics)
    for metric_name in (
        "selection_oos_sharpe",
        "selection_oos_net_pnl",
        "selection_oos_drawdown",
        "scenario_pass_rate",
        "accepted_layers",
    ):
        if metric_name in runcard.metrics:
            summary[metric_name] = runcard.metrics[metric_name]
    if dashboard_path:
        dashboard_file = Path(dashboard_path)
        if dashboard_file.exists():
            try:
                dashboard_payload = json.loads(dashboard_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                dashboard_payload = {}
            if isinstance(dashboard_payload, dict):
                agent_loop_metadata = dashboard_payload.get("agent_loop_metadata")
                if isinstance(agent_loop_metadata, dict) and agent_loop_metadata:
                    summary["agent_loop_metadata"] = dict(agent_loop_metadata)
    return summary


def _extract_duplicate_baseline_run_id(research_lineage: object) -> str | None:
    if not isinstance(research_lineage, dict):
        return None
    baseline_run_id = research_lineage.get("accepted_duplicate_match_run_id")
    if isinstance(baseline_run_id, str) and baseline_run_id:
        return baseline_run_id
    return None


def _load_duplicate_baseline_variant_history(
    *,
    db_path: Path,
    duplicate_baseline_run_id: str | None,
    memory_quality_policy: str,
    snapshot_provenance: dict[str, object] | None = None,
) -> dict[str, dict[str, float | int | str]]:
    if not duplicate_baseline_run_id:
        return {}

    rows = _filter_memory_rows_for_snapshot_compatibility(
        query_run_memory(db_path, accepted_duplicate_match_run_id=duplicate_baseline_run_id),
        snapshot_provenance=snapshot_provenance,
    )
    selected_rows = select_memory_rows_with_policy(
        rows,
        memory_quality_policy=memory_quality_policy,
        limit=None,
    )
    history: dict[str, dict[str, float | int | str]] = {}
    for row in selected_rows:
        variant_name = row.get("selected_variant")
        if not isinstance(variant_name, str) or not variant_name:
            continue
        variant_history = history.setdefault(
            variant_name,
            {
                "sample_count": 0,
                "promoted_count": 0,
                "success_rate": 0.0,
                "average_sharpe": 0.0,
                "_sharpe_total": 0.0,
                "_promoted_parameter_hints": {},
                "_blocked_parameter_hints": {},
                "_fragile_counter": Counter(),
                "_scenario_counter": Counter(),
                "_scenario_profile_counters": {},
                "_blocked_scenario_profile_counters": {},
                "_runtime_profile_counter": Counter(),
            },
        )
        variant_history["sample_count"] = int(variant_history["sample_count"]) + 1
        if row.get("decision") == "promoted":
            variant_history["promoted_count"] = int(variant_history["promoted_count"]) + 1
        variant_history["_sharpe_total"] = float(variant_history["_sharpe_total"]) + _number_or_zero(
            row.get("selection_oos_sharpe")
        )
        layer_counter = variant_history.setdefault("_layer_counter", Counter())
        if isinstance(layer_counter, Counter):
            for layer_name in _string_list(row.get("accepted_layers")):
                layer_counter[layer_name] += 1
        fragile_counter = variant_history.setdefault("_fragile_counter", Counter())
        if isinstance(fragile_counter, Counter):
            for layer_name in _string_list(row.get("rejected_layers")):
                fragile_counter[layer_name] += 1
        scenario_counter = variant_history.setdefault("_scenario_counter", Counter())
        scenario_profile_counters = variant_history.setdefault("_scenario_profile_counters", {})
        blocked_scenario_profile_counters = variant_history.setdefault("_blocked_scenario_profile_counters", {})
        scenario_profiles = row.get("scenario_profiles")
        if isinstance(scenario_counter, Counter) and isinstance(scenario_profiles, dict):
            for scenario_name, profile in scenario_profiles.items():
                if not isinstance(scenario_name, str):
                    continue
                scenario_counter[scenario_name] += 1
                if isinstance(profile, dict):
                    if row.get("decision") == "promoted" and isinstance(scenario_profile_counters, dict):
                        scenario_profile_counters.setdefault(scenario_name, Counter())[json.dumps(profile, sort_keys=True)] += 1
                    if row.get("decision") == "blocked" and isinstance(blocked_scenario_profile_counters, dict):
                        blocked_scenario_profile_counters.setdefault(scenario_name, Counter())[json.dumps(profile, sort_keys=True)] += 1
        selected_parameters = row.get("selected_parameters")
        if isinstance(selected_parameters, dict):
            target_key = "_promoted_parameter_hints" if row.get("decision") == "promoted" else "_blocked_parameter_hints"
            layer_hints = variant_history.setdefault(target_key, {})
            if isinstance(layer_hints, dict):
                for layer_name, parameters in selected_parameters.items():
                    if not isinstance(layer_name, str) or not isinstance(parameters, dict):
                        continue
                    parameter_bucket = layer_hints.setdefault(layer_name, {})
                    if not isinstance(parameter_bucket, dict):
                        continue
                    for parameter_name, value in parameters.items():
                        if isinstance(parameter_name, str) and isinstance(value, (int, float)):
                            parameter_bucket.setdefault(parameter_name, []).append(value)
        runtime_settings = row.get("runtime_settings")
        runtime_profile_counter = variant_history.setdefault("_runtime_profile_counter", Counter())
        if (
            row.get("decision") == "promoted"
            and isinstance(runtime_profile_counter, Counter)
            and isinstance(runtime_settings, dict)
            and runtime_settings
        ):
            runtime_profile_counter[json.dumps(runtime_settings, sort_keys=True)] += 1

    for variant_name, variant_history in history.items():
        sample_count = max(1, int(variant_history["sample_count"]))
        promoted_count = int(variant_history["promoted_count"])
        sharpe_total = float(variant_history.pop("_sharpe_total", 0.0))
        layer_counter = variant_history.pop("_layer_counter", Counter())
        fragile_counter = variant_history.pop("_fragile_counter", Counter())
        scenario_counter = variant_history.pop("_scenario_counter", Counter())
        scenario_profile_counters = variant_history.pop("_scenario_profile_counters", {})
        blocked_scenario_profile_counters = variant_history.pop("_blocked_scenario_profile_counters", {})
        runtime_profile_counter = variant_history.pop("_runtime_profile_counter", Counter())
        promoted_parameter_hints = variant_history.pop("_promoted_parameter_hints", {})
        blocked_parameter_hints = variant_history.pop("_blocked_parameter_hints", {})
        variant_history["success_rate"] = promoted_count / sample_count
        variant_history["average_sharpe"] = sharpe_total / sample_count
        variant_history["duplicate_baseline_run_id"] = duplicate_baseline_run_id
        variant_history["promising_layers"] = _rank_counter(layer_counter) if isinstance(layer_counter, Counter) else []
        variant_history["fragile_layers"] = _rank_counter(fragile_counter) if isinstance(fragile_counter, Counter) else []
        variant_history["scenario_profiles"] = (
            _rank_named_counter(scenario_counter, key_name="scenario_name")
            if isinstance(scenario_counter, Counter)
            else []
        )
        variant_history["scenario_profile_hints"] = (
            _build_scenario_profile_hints_from_counters(scenario_profile_counters)
            if isinstance(scenario_profile_counters, dict)
            else {}
        )
        variant_history["scenario_profile_avoidance"] = (
            _build_scenario_profile_hints_from_counters(blocked_scenario_profile_counters, minimum_count=2)
            if isinstance(blocked_scenario_profile_counters, dict)
            else {}
        )
        variant_history["runtime_profile_hints"] = (
            _build_runtime_profile_hint_from_counter(runtime_profile_counter)
            if isinstance(runtime_profile_counter, Counter)
            else {}
        )
        scenario_profile_avoidance = variant_history.get("scenario_profile_avoidance", {})
        if isinstance(scenario_profile_avoidance, dict):
            variant_history["scenario_profile_avoidance_count"] = sum(
                int(hint.get("count", 0))
                for hint in scenario_profile_avoidance.values()
                if isinstance(hint, dict)
            )
        else:
            variant_history["scenario_profile_avoidance_count"] = 0
        if isinstance(promoted_parameter_hints, dict):
            variant_history["parameter_hints"] = {
                layer_name: {
                    parameter_name: _build_parameter_hint(
                        promoted_values=parameters[parameter_name],
                        blocked_values=blocked_parameter_hints.get(layer_name, {}).get(parameter_name, [])
                        if isinstance(blocked_parameter_hints, dict)
                        and isinstance(blocked_parameter_hints.get(layer_name), dict)
                        else [],
                    )
                    for parameter_name in parameters
                    if parameters[parameter_name]
                }
                for layer_name, parameters in promoted_parameter_hints.items()
                if isinstance(layer_name, str) and isinstance(parameters, dict)
            }
    return history


def load_duplicate_baseline_variant_history_for_lineage(
    *,
    db_path: Path,
    research_lineage: object,
    memory_quality_policy: str,
    snapshot_provenance: dict[str, object] | None = None,
) -> dict[str, dict[str, float | int | str | list[dict[str, object]]]]:
    duplicate_baseline_run_id = _extract_duplicate_baseline_run_id(research_lineage)
    return _load_duplicate_baseline_variant_history(
        db_path=db_path,
        duplicate_baseline_run_id=duplicate_baseline_run_id,
        memory_quality_policy=memory_quality_policy,
        snapshot_provenance=snapshot_provenance,
    )


def _rank_variant_results(
    variant_runs: dict[str, dict[str, object]],
    base_run: dict[str, object],
    duplicate_baseline_history: dict[str, dict[str, float | int | str]] | None = None,
) -> list[dict[str, object]]:
    variant_priority = {"balanced": 0, "conservative": 1, "exploratory": 2}
    results: list[dict[str, object]] = []
    duplicate_baseline_history = duplicate_baseline_history or {}

    for variant_name, payload in variant_runs.items():
        deltas = _metric_deltas(base_run.get("metrics"), payload)
        baseline_history = duplicate_baseline_history.get(
            variant_name,
            {
                "sample_count": 0,
                "promoted_count": 0,
                "success_rate": 0.0,
                "average_sharpe": 0.0,
                "scenario_profile_avoidance_count": 0,
            },
        )
        ranking = {
            "status_rank": _status_rank(payload.get("status")),
            "duplicate_baseline_success_rate": _number_or_zero(baseline_history.get("success_rate")),
            "duplicate_baseline_scenario_avoidance_count": _number_or_zero(
                baseline_history.get("scenario_profile_avoidance_count")
            ),
            "duplicate_baseline_sample_count": _number_or_zero(baseline_history.get("sample_count")),
            "duplicate_baseline_average_sharpe": _number_or_zero(baseline_history.get("average_sharpe")),
            "scenario_pass_rate": _number_or_zero(payload.get("scenario_pass_rate")),
            "selection_oos_sharpe": _number_or_zero(payload.get("selection_oos_sharpe")),
            "selection_oos_drawdown": _number_or_zero(payload.get("selection_oos_drawdown")),
            "accepted_layers": _number_or_zero(payload.get("accepted_layers")),
            "variant_priority": -variant_priority.get(variant_name, len(variant_priority)),
        }
        duplicate_baseline_score = _compute_duplicate_baseline_score(baseline_history)
        results.append(
            {
                "variant": variant_name,
                **payload,
                "duplicate_baseline_history": baseline_history,
                "duplicate_baseline_score": duplicate_baseline_score,
                "compare_to_base": {"metric_deltas": deltas},
                "ranking": ranking,
            }
        )

    sorted_results = sorted(
        results,
        key=lambda item: (
            -_number_or_zero(item["ranking"].get("status_rank")),
            -_number_or_zero(item["ranking"].get("duplicate_baseline_success_rate")),
            -_number_or_zero(item["ranking"].get("duplicate_baseline_scenario_avoidance_count")),
            -_number_or_zero(item["ranking"].get("duplicate_baseline_sample_count")),
            -_number_or_zero(item["ranking"].get("duplicate_baseline_average_sharpe")),
            -_number_or_zero(item["ranking"].get("scenario_pass_rate")),
            -_number_or_zero(item["ranking"].get("selection_oos_sharpe")),
            -_number_or_zero(item["ranking"].get("selection_oos_drawdown")),
            -_number_or_zero(item["ranking"].get("accepted_layers")),
            -_number_or_zero(item["ranking"].get("variant_priority")),
        ),
    )
    preferred_score = sorted_results[0].get("duplicate_baseline_score") if sorted_results else None
    for item in sorted_results:
        score = item.get("duplicate_baseline_score")
        if isinstance(score, int | float) and not isinstance(score, bool) and isinstance(preferred_score, int | float) and not isinstance(preferred_score, bool):
            item["duplicate_baseline_delta_vs_preferred"] = round(float(score) - float(preferred_score), 2)
        else:
            item["duplicate_baseline_delta_vs_preferred"] = None
    return sorted_results


def _compute_duplicate_baseline_score(history: dict[str, object]) -> float | None:
    weights = {
        "success_rate": 4.0,
        "average_sharpe": 3.0,
        "promoted_count": 2.0,
        "sample_count": 1.0,
    }
    score = 0.0
    found_numeric = False
    for field_name, weight in weights.items():
        value = history.get(field_name)
        if not isinstance(value, int | float) or isinstance(value, bool):
            continue
        score += weight * float(value)
        found_numeric = True
    if not found_numeric:
        return None
    return round(score, 2)


def _metric_deltas(
    base_metrics: object,
    variant_payload: dict[str, object],
) -> dict[str, float]:
    if not isinstance(base_metrics, dict):
        return {}

    relevant_metrics = (
        "selection_oos_sharpe",
        "selection_oos_net_pnl",
        "selection_oos_drawdown",
        "scenario_pass_rate",
        "accepted_layers",
    )
    deltas: dict[str, float] = {}
    for metric_name in relevant_metrics:
        base_value = base_metrics.get(metric_name)
        variant_value = variant_payload.get(metric_name)
        if isinstance(base_value, int | float) and isinstance(variant_value, int | float):
            deltas[metric_name] = float(variant_value) - float(base_value)
    return deltas


def _status_rank(value: object) -> int:
    if value == "promoted":
        return 3
    if value == "accepted":
        return 2
    if value == "blocked":
        return 1
    return 0


def _number_or_zero(value: object) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _materialize_accepted_duplicate_from_memory(
    *,
    base_payload: dict[str, object],
    duplicate_match: dict[str, object] | None,
    report_path: str | None,
    db_path: Path,
    output_dir: Path,
    run_id: str,
) -> str | None:
    if not isinstance(duplicate_match, dict) or not isinstance(duplicate_match.get("run_id"), str):
        return None
    matched_rows = query_run_memory(db_path, run_id=str(duplicate_match["run_id"]), limit=1)
    if not matched_rows:
        return None
    accepted_payload = build_accepted_duplicate_payload(
        base_payload,
        matched_rows[0],
        source_report_path=report_path or "",
    )
    output_path = output_dir / f"{run_id}.accepted-duplicate.json"
    write_next_study_payload(output_path, accepted_payload)
    if report_path:
        report_file = Path(report_path)
        report_payload = json.loads(report_file.read_text(encoding="utf-8"))
        report_payload["accepted_duplicate_config_path"] = str(output_path)
        write_json_atomic(report_file, report_payload)
    return str(output_path)
