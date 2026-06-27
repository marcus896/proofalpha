from __future__ import annotations

import json

from engine.config.models import RunCard
from engine.validation.bundle import compare_validation_bundles, normalize_validation_bundle


def compare_dashboard_payloads(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    left_phases = _index_phases(left.get("phases"))
    right_phases = _index_phases(right.get("phases"))
    left_metrics = _normalized_metrics(left, left_phases)
    right_metrics = _normalized_metrics(right, right_phases)
    left_scenario_profiles = _normalized_scenario_profiles(left.get("scenario_profiles"))
    right_scenario_profiles = _normalized_scenario_profiles(right.get("scenario_profiles"))
    left_runtime_settings = _normalized_runtime_settings(left.get("runtime_settings"))
    right_runtime_settings = _normalized_runtime_settings(right.get("runtime_settings"))
    left_snapshot_quality = _normalized_snapshot_quality(left.get("snapshot_quality"))
    right_snapshot_quality = _normalized_snapshot_quality(right.get("snapshot_quality"))
    left_snapshot_provenance = _normalized_runtime_settings(left.get("snapshot_provenance"))
    right_snapshot_provenance = _normalized_runtime_settings(right.get("snapshot_provenance"))
    left_validation_bundle = _normalized_validation_bundle(left.get("validation_protocol"))
    right_validation_bundle = _normalized_validation_bundle(right.get("validation_protocol"))

    left_accepted = {name for name, phase in left_phases.items() if bool(phase.get("accepted"))}
    right_accepted = {name for name, phase in right_phases.items() if bool(phase.get("accepted"))}

    common_layers = sorted(left_accepted & right_accepted)
    parameter_changes: dict[str, object] = {}
    for layer_name in common_layers:
        left_phase = left_phases[layer_name]
        right_phase = right_phases[layer_name]
        parameter_changes[layer_name] = {
            "selected_parameters": {
                "left": dict(_as_dict(left_phase.get("selected_parameters"))),
                "right": dict(_as_dict(right_phase.get("selected_parameters"))),
            },
            "oos_sharpe_delta": float(right_phase.get("oos_sharpe", 0.0)) - float(left_phase.get("oos_sharpe", 0.0)),
            "permutation_count_delta": int(right_phase.get("permutation_count", 1)) - int(left_phase.get("permutation_count", 1)),
        }

    metric_deltas = {
        key: float(right_metrics[key]) - float(left_metrics[key])
        for key in sorted(left_metrics.keys() & right_metrics.keys())
        if _is_number(left_metrics[key]) and _is_number(right_metrics[key])
    }

    result: dict[str, object] = {
        "left_run_id": left.get("run_id"),
        "right_run_id": right.get("run_id"),
        "decision_change": {
            "left": left.get("decision"),
            "right": right.get("decision"),
        },
        "metric_deltas": metric_deltas,
        "layer_changes": {
            "added": sorted(right_accepted - left_accepted),
            "removed": sorted(left_accepted - right_accepted),
            "retained": common_layers,
        },
        "parameter_changes": parameter_changes,
        "scenario_profile_changes": _compare_scenario_profiles(left_scenario_profiles, right_scenario_profiles),
        "runtime_settings_changes": _compare_runtime_settings(left_runtime_settings, right_runtime_settings),
    }
    if left_snapshot_quality != right_snapshot_quality:
        result["snapshot_quality_change"] = {
            "left": left_snapshot_quality,
            "right": right_snapshot_quality,
            "changed_fields": _compare_runtime_settings(left_snapshot_quality, right_snapshot_quality)["changed_fields"],
        }
    if left_snapshot_provenance != right_snapshot_provenance:
        result["snapshot_provenance_change"] = {
            "left": left_snapshot_provenance,
            "right": right_snapshot_provenance,
            "changed_fields": _compare_runtime_settings(left_snapshot_provenance, right_snapshot_provenance)["changed_fields"],
        }
    if left_validation_bundle != right_validation_bundle:
        result["validation_bundle_change"] = compare_validation_bundles(
            left.get("validation_protocol"),
            right.get("validation_protocol"),
        )
        result["validation_bundle_left"] = left_validation_bundle
        result["validation_bundle_right"] = right_validation_bundle
    left_loop = _as_dict(left.get("agent_loop_metadata"))
    right_loop = _as_dict(right.get("agent_loop_metadata"))
    if left_loop or right_loop:
        loop_changes: dict[str, object] = {}
        for key in sorted(set(left_loop) | set(right_loop)):
            if left_loop.get(key) != right_loop.get(key):
                loop_changes[key] = {"left": left_loop.get(key), "right": right_loop.get(key)}
        if loop_changes:
            result["agent_loop_changes"] = loop_changes
    left_version = left.get("research_program_version")
    right_version = right.get("research_program_version")
    if left_version != right_version and (left_version is not None or right_version is not None):
        result["research_program_version_change"] = {"left": left_version, "right": right_version}
    return result


def compare_runcards(left: RunCard, right: RunCard) -> dict[str, object]:
    metric_deltas = {
        key: float(right.metrics[key]) - float(left.metrics[key])
        for key in sorted(left.metrics.keys() & right.metrics.keys())
        if _is_number(left.metrics[key]) and _is_number(right.metrics[key])
    }
    artifact_changes = {
        key: {"left": left.artifacts.get(key), "right": right.artifacts.get(key)}
        for key in sorted(left.artifacts.keys() & right.artifacts.keys())
        if left.artifacts.get(key) != right.artifacts.get(key)
    }
    left_parameters = _load_json_object(left.artifacts.get("selected_parameters_json", "{}"))
    right_parameters = _load_json_object(right.artifacts.get("selected_parameters_json", "{}"))
    parameter_layers = sorted(set(left_parameters) | set(right_parameters))
    left_scenario_profiles = _load_json_object(left.artifacts.get("scenario_profiles_json", "{}"))
    right_scenario_profiles = _load_json_object(right.artifacts.get("scenario_profiles_json", "{}"))
    left_runtime_settings = _load_json_object(left.artifacts.get("runtime_settings_json", "{}"))
    right_runtime_settings = _load_json_object(right.artifacts.get("runtime_settings_json", "{}"))

    return {
        "left_run_id": left.run_id,
        "right_run_id": right.run_id,
        "decision_change": {
            "left": left.decision.decision,
            "right": right.decision.decision,
        },
        "metric_deltas": metric_deltas,
        "artifact_changes": artifact_changes,
        "parameter_layers": parameter_layers,
        "selected_parameters": {
            "left": left_parameters,
            "right": right_parameters,
        },
        "scenario_profile_changes": _compare_scenario_profiles(left_scenario_profiles, right_scenario_profiles),
        "runtime_settings_changes": _compare_runtime_settings(left_runtime_settings, right_runtime_settings),
    }


def compare_autoresearch_payloads(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    left_lineage = _as_dict(left.get("research_lineage"))
    right_lineage = _as_dict(right.get("research_lineage"))
    left_selected_result = _as_dict(left_lineage.get("selection_variant_result"))
    right_selected_result = _as_dict(right_lineage.get("selection_variant_result"))
    left_duplicate_history = _as_dict(left_selected_result.get("duplicate_baseline_history"))
    right_duplicate_history = _as_dict(right_selected_result.get("duplicate_baseline_history"))

    return {
        "left_run_id": left.get("run_id"),
        "right_run_id": right.get("run_id"),
        "status_change": {
            "left": left.get("status"),
            "right": right.get("status"),
        },
        "selected_variant_change": {
            "left": left_selected_result.get("variant", left_lineage.get("selected_variant")),
            "right": right_selected_result.get("variant", right_lineage.get("selected_variant")),
        },
        "duplicate_baseline_history_changes": _compare_duplicate_baseline_history(
            left_duplicate_history,
            right_duplicate_history,
        ),
    }


def compare_batch_payloads(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    left_base_run = _as_dict(left.get("base_run"))
    right_base_run = _as_dict(right.get("base_run"))
    left_preferred_variant = _as_dict(left.get("preferred_variant"))
    right_preferred_variant = _as_dict(right.get("preferred_variant"))
    left_variant_results = _index_variant_results(left.get("variant_results"))
    right_variant_results = _index_variant_results(right.get("variant_results"))
    common_variants = sorted(set(left_variant_results) | set(right_variant_results))

    variant_score_changes: dict[str, object] = {}
    variant_history_changes: dict[str, object] = {}
    for variant_name in common_variants:
        left_variant = _as_dict(left_variant_results.get(variant_name))
        right_variant = _as_dict(right_variant_results.get(variant_name))
        left_score = _to_float_or_none(left_variant.get("duplicate_baseline_score"))
        right_score = _to_float_or_none(right_variant.get("duplicate_baseline_score"))
        left_delta = _to_float_or_none(left_variant.get("duplicate_baseline_delta_vs_preferred"))
        right_delta = _to_float_or_none(right_variant.get("duplicate_baseline_delta_vs_preferred"))
        variant_score_changes[variant_name] = {
            "left_score": left_score,
            "right_score": right_score,
            "score_delta": _rounded_delta(left_score, right_score),
            "left_delta_vs_preferred": left_delta,
            "right_delta_vs_preferred": right_delta,
            "delta_vs_preferred_change": _rounded_delta(left_delta, right_delta),
        }
        history_change = _compare_duplicate_baseline_history(
            _as_dict(left_variant.get("duplicate_baseline_history")),
            _as_dict(right_variant.get("duplicate_baseline_history")),
        )
        if history_change:
            variant_history_changes[variant_name] = history_change

    return {
        "left_run_id": left_base_run.get("run_id", left.get("run_id")),
        "right_run_id": right_base_run.get("run_id", right.get("run_id")),
        "preferred_variant_change": {
            "left": left_preferred_variant.get("variant"),
            "right": right_preferred_variant.get("variant"),
        },
        "preferred_duplicate_baseline_history_changes": _compare_duplicate_baseline_history(
            _as_dict(left_preferred_variant.get("duplicate_baseline_history")),
            _as_dict(right_preferred_variant.get("duplicate_baseline_history")),
        ),
        "variant_score_changes": variant_score_changes,
        "variant_history_changes": variant_history_changes,
    }


def compare_campaign_payloads(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    left_entries = _index_named_entries(left.get("entries"))
    right_entries = _index_named_entries(right.get("entries"))
    entry_names = sorted(set(left_entries) | set(right_entries))

    entry_result_changes: dict[str, object] = {}
    for entry_name in entry_names:
        if entry_name not in left_entries or entry_name not in right_entries:
            continue
        left_entry = _as_dict(left_entries.get(entry_name))
        right_entry = _as_dict(right_entries.get(entry_name))
        changed: dict[str, object] = {}
        for field_name, key_name in (
            ("status", "status_change"),
            ("command", "command_change"),
            ("run_id", "run_id_change"),
        ):
            if left_entry.get(field_name) != right_entry.get(field_name):
                changed[key_name] = {
                    "left": left_entry.get(field_name),
                    "right": right_entry.get(field_name),
                }
        if changed:
            entry_result_changes[entry_name] = changed

    return {
        "left_run_id": left.get("campaign_id"),
        "right_run_id": right.get("campaign_id"),
        "status_change": {
            "left": left.get("status"),
            "right": right.get("status"),
        },
        "campaign_metrics": {
            "entry_count": _left_right_delta(left.get("entry_count"), right.get("entry_count")),
            "completed_entries": _left_right_delta(left.get("completed_entries"), right.get("completed_entries")),
            "failed_entries": _left_right_delta(left.get("failed_entries"), right.get("failed_entries")),
        },
        "entry_changes": {
            "added": [name for name in entry_names if name not in left_entries],
            "removed": [name for name in entry_names if name not in right_entries],
            "retained": [name for name in entry_names if name in left_entries and name in right_entries],
        },
        "entry_result_changes": entry_result_changes,
    }


def format_compare_payload(payload: dict[str, object]) -> str:
    lines: list[str] = []
    left_run_id = payload.get("left_run_id", "unknown-left")
    right_run_id = payload.get("right_run_id", "unknown-right")
    lines.append(f"Compare {left_run_id} -> {right_run_id}")

    decision_change = _as_dict(payload.get("decision_change"))
    if decision_change:
        lines.append(f"Decision: {decision_change.get('left', 'unknown')} -> {decision_change.get('right', 'unknown')}")
    status_change = _as_dict(payload.get("status_change"))
    if status_change:
        lines.append(f"Status: {status_change.get('left', 'unknown')} -> {status_change.get('right', 'unknown')}")
    selected_variant_change = _as_dict(payload.get("selected_variant_change"))
    if selected_variant_change:
        lines.append(
            f"Selected variant: {selected_variant_change.get('left', 'unknown')} -> {selected_variant_change.get('right', 'unknown')}"
        )
    preferred_variant_change = _as_dict(payload.get("preferred_variant_change"))
    if preferred_variant_change:
        lines.append(
            f"Preferred variant: {preferred_variant_change.get('left', 'unknown')} -> {preferred_variant_change.get('right', 'unknown')}"
        )

    metric_deltas = _as_dict(payload.get("metric_deltas"))
    if metric_deltas:
        lines.append("Metric deltas:")
        for key in sorted(metric_deltas):
            value = metric_deltas[key]
            if _is_number(value):
                lines.append(f"- {key}: {_format_signed(float(value))}")

    layer_changes = _as_dict(payload.get("layer_changes"))
    if layer_changes:
        lines.append(f"Added layers: {_format_list(layer_changes.get('added'))}")
        lines.append(f"Removed layers: {_format_list(layer_changes.get('removed'))}")
        lines.append(f"Retained layers: {_format_list(layer_changes.get('retained'))}")

    parameter_changes = _as_dict(payload.get("parameter_changes"))
    if parameter_changes:
        lines.append("Parameter changes:")
        for layer_name in sorted(parameter_changes):
            layer_change = _as_dict(parameter_changes[layer_name])
            lines.append(f"- {layer_name}")
            oos_sharpe_delta = layer_change.get("oos_sharpe_delta")
            if _is_number(oos_sharpe_delta):
                lines.append(f"  oos_sharpe_delta: {_format_signed(float(oos_sharpe_delta))}")
            selected_parameters = _as_dict(layer_change.get("selected_parameters"))
            if selected_parameters:
                left_params = _format_parameters(selected_parameters.get("left"))
                right_params = _format_parameters(selected_parameters.get("right"))
                lines.append(f"  selected: {left_params} -> {right_params}")

    parameter_layers = payload.get("parameter_layers")
    if isinstance(parameter_layers, list) and parameter_layers:
        lines.append(f"Parameter layers: {_format_list(parameter_layers)}")

    scenario_profile_changes = _as_dict(payload.get("scenario_profile_changes"))
    if scenario_profile_changes:
        lines.append("Scenario profile changes:")
        added_profiles = _as_dict(scenario_profile_changes.get("added"))
        for scenario_name in sorted(added_profiles):
            profile = _as_dict(added_profiles.get(scenario_name))
            lines.append(f"- added {scenario_name}: {_format_parameters(profile)}")
        removed_profiles = _as_dict(scenario_profile_changes.get("removed"))
        for scenario_name in sorted(removed_profiles):
            profile = _as_dict(removed_profiles.get(scenario_name))
            lines.append(f"- removed {scenario_name}: {_format_parameters(profile)}")
        changed_profiles = _as_dict(scenario_profile_changes.get("changed"))
        for scenario_name in sorted(changed_profiles):
            profile_change = _as_dict(changed_profiles.get(scenario_name))
            left_profile = _format_parameters(profile_change.get("left"))
            right_profile = _format_parameters(profile_change.get("right"))
            lines.append(f"- {scenario_name}: {left_profile} -> {right_profile}")
            changed_fields = _as_dict(profile_change.get("changed_fields"))
            for field_name in sorted(changed_fields):
                field_change = _as_dict(changed_fields.get(field_name))
                lines.append(
                    f"  {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}"
                )

    runtime_settings_changes = _as_dict(payload.get("runtime_settings_changes"))
    if runtime_settings_changes:
        lines.append("Runtime setting changes:")
        added_settings = _as_dict(runtime_settings_changes.get("added"))
        for setting_name in sorted(added_settings):
            lines.append(f"- added {setting_name}: {added_settings.get(setting_name)}")
        removed_settings = _as_dict(runtime_settings_changes.get("removed"))
        for setting_name in sorted(removed_settings):
            lines.append(f"- removed {setting_name}: {removed_settings.get(setting_name)}")
        changed_fields = _as_dict(runtime_settings_changes.get("changed_fields"))
        for field_name in sorted(changed_fields):
            field_change = _as_dict(changed_fields.get(field_name))
            lines.append(
                f"- {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}"
            )

    snapshot_quality_change = _as_dict(payload.get("snapshot_quality_change"))
    if snapshot_quality_change:
        lines.append("Snapshot quality:")
        changed_fields = _as_dict(snapshot_quality_change.get("changed_fields"))
        for field_name in sorted(changed_fields):
            field_change = _as_dict(changed_fields.get(field_name))
            lines.append(f"- {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}")

    snapshot_provenance_change = _as_dict(payload.get("snapshot_provenance_change"))
    if snapshot_provenance_change:
        lines.append("Snapshot provenance changes:")
        changed_fields = _as_dict(snapshot_provenance_change.get("changed_fields"))
        for field_name in sorted(changed_fields):
            field_change = _as_dict(changed_fields.get(field_name))
            lines.append(f"- {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}")

    validation_bundle_change = _as_dict(payload.get("validation_bundle_change"))
    if validation_bundle_change:
        lines.append("Validation bundle changes:")
        changed_fields = _as_dict(validation_bundle_change.get("changed_fields"))
        for field_name in sorted(changed_fields):
            field_change = _as_dict(changed_fields.get(field_name))
            if field_name == "failed_gates":
                lines.append(
                    "- failed_gates: "
                    + f"{_format_string_list(field_change.get('left'))} -> {_format_string_list(field_change.get('right'))}"
                )
                continue
            lines.append(f"- {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}")

    agent_loop_changes = _as_dict(payload.get("agent_loop_changes"))
    if agent_loop_changes:
        lines.append("Agent loop changes:")
        for key in sorted(agent_loop_changes):
            change = _as_dict(agent_loop_changes[key])
            if key == "failure_taxonomy_counts":
                lines.append(
                    f"- {key}: {_format_failure_taxonomy_counts(change.get('left'))} -> {_format_failure_taxonomy_counts(change.get('right'))}"
                )
                continue
            if key == "next_hypotheses":
                lines.append(
                    f"- {key}: {_format_string_list(change.get('left'))} -> {_format_string_list(change.get('right'))}"
                )
                continue
            lines.append(f"- {key}: {change.get('left', 'none')} -> {change.get('right', 'none')}")

    version_change = _as_dict(payload.get("research_program_version_change"))
    if version_change:
        lines.append(
            f"Program version: {version_change.get('left', 'none')} -> {version_change.get('right', 'none')}"
        )

    duplicate_baseline_history_changes = _as_dict(payload.get("duplicate_baseline_history_changes"))
    if duplicate_baseline_history_changes:
        lines.append("Duplicate baseline rationale changes:")
        changed_fields = _as_dict(duplicate_baseline_history_changes.get("changed_fields"))
        for field_name in sorted(changed_fields):
            field_change = _as_dict(changed_fields.get(field_name))
            lines.append(f"- {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}")
        net_rationale = _as_dict(duplicate_baseline_history_changes.get("net_rationale"))
        verdict = str(net_rationale.get("label", "")) if net_rationale else _selection_driver_verdict(changed_fields)
        if verdict:
            lines.append(f"Net rationale: {verdict}")
        score = net_rationale.get("score") if net_rationale else None
        if _is_number(score):
            lines.append(f"Net rationale score: {float(score):.2f}")
        selection_drivers = _build_selection_driver_lines(changed_fields)
        if selection_drivers:
            lines.append("Likely selection drivers:")
            lines.extend(selection_drivers)
        top_scenario_profile_change = _as_dict(duplicate_baseline_history_changes.get("top_scenario_profile_change"))
        if top_scenario_profile_change:
            lines.append(
                "Top scenario profile: "
                + f"{top_scenario_profile_change.get('left', 'none')} -> {top_scenario_profile_change.get('right', 'none')}"
            )
        top_fragile_profile_change = _as_dict(duplicate_baseline_history_changes.get("top_fragile_profile_change"))
        if top_fragile_profile_change:
            lines.append(
                "Top fragile profile: "
                + f"{top_fragile_profile_change.get('left', 'none')} -> {top_fragile_profile_change.get('right', 'none')}"
            )
        top_runtime_profile_change = _as_dict(duplicate_baseline_history_changes.get("top_runtime_profile_change"))
        if top_runtime_profile_change:
            lines.append(
                "Top runtime profile: "
                + f"{top_runtime_profile_change.get('left', 'none')} -> {top_runtime_profile_change.get('right', 'none')}"
            )
        _append_profile_hint_change_lines(
            lines,
            "Scenario profile hints",
            _as_dict(duplicate_baseline_history_changes.get("scenario_profile_hints")),
        )
        _append_profile_hint_change_lines(
            lines,
            "Scenario profile avoidance",
            _as_dict(duplicate_baseline_history_changes.get("scenario_profile_avoidance")),
        )
        _append_runtime_profile_hint_change_lines(
            lines,
            "Runtime profile hints",
            _as_dict(duplicate_baseline_history_changes.get("runtime_profile_hints")),
        )

    preferred_duplicate_baseline_history_changes = _as_dict(payload.get("preferred_duplicate_baseline_history_changes"))
    if preferred_duplicate_baseline_history_changes:
        lines.append("Preferred duplicate baseline rationale changes:")
        changed_fields = _as_dict(preferred_duplicate_baseline_history_changes.get("changed_fields"))
        for field_name in sorted(changed_fields):
            field_change = _as_dict(changed_fields.get(field_name))
            lines.append(f"- {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}")
        net_rationale = _as_dict(preferred_duplicate_baseline_history_changes.get("net_rationale"))
        verdict = str(net_rationale.get("label", "")) if net_rationale else _selection_driver_verdict(changed_fields)
        if verdict:
            lines.append(f"Preferred net rationale: {verdict}")
        score = net_rationale.get("score") if net_rationale else None
        if _is_number(score):
            lines.append(f"Preferred net rationale score: {float(score):.2f}")
        preferred_drivers = _build_selection_driver_lines(changed_fields)
        if preferred_drivers:
            lines.append("Likely preferred drivers:")
            lines.extend(preferred_drivers)
        top_scenario_profile_change = _as_dict(preferred_duplicate_baseline_history_changes.get("top_scenario_profile_change"))
        if top_scenario_profile_change:
            lines.append(
                "Preferred top scenario profile: "
                + f"{top_scenario_profile_change.get('left', 'none')} -> {top_scenario_profile_change.get('right', 'none')}"
            )
        top_fragile_profile_change = _as_dict(preferred_duplicate_baseline_history_changes.get("top_fragile_profile_change"))
        if top_fragile_profile_change:
            lines.append(
                "Preferred top fragile profile: "
                + f"{top_fragile_profile_change.get('left', 'none')} -> {top_fragile_profile_change.get('right', 'none')}"
            )
        top_runtime_profile_change = _as_dict(preferred_duplicate_baseline_history_changes.get("top_runtime_profile_change"))
        if top_runtime_profile_change:
            lines.append(
                "Preferred top runtime profile: "
                + f"{top_runtime_profile_change.get('left', 'none')} -> {top_runtime_profile_change.get('right', 'none')}"
            )
        _append_profile_hint_change_lines(
            lines,
            "Scenario profile hints",
            _as_dict(preferred_duplicate_baseline_history_changes.get("scenario_profile_hints")),
        )
        _append_profile_hint_change_lines(
            lines,
            "Scenario profile avoidance",
            _as_dict(preferred_duplicate_baseline_history_changes.get("scenario_profile_avoidance")),
        )
        _append_runtime_profile_hint_change_lines(
            lines,
            "Runtime profile hints",
            _as_dict(preferred_duplicate_baseline_history_changes.get("runtime_profile_hints")),
        )

    variant_score_changes = _as_dict(payload.get("variant_score_changes"))
    if variant_score_changes:
        lines.append("Variant score changes:")
        for variant_name in sorted(variant_score_changes):
            score_change = _as_dict(variant_score_changes.get(variant_name))
            lines.append(f"- {variant_name}")
            left_score = score_change.get("left_score")
            right_score = score_change.get("right_score")
            if _is_number(left_score) or _is_number(right_score):
                lines.append(f"  score: {left_score if left_score is not None else 'none'} -> {right_score if right_score is not None else 'none'}")
            score_delta = score_change.get("score_delta")
            if _is_number(score_delta):
                lines.append(f"  score_delta: {_format_signed(float(score_delta))}")
            left_delta = score_change.get("left_delta_vs_preferred")
            right_delta = score_change.get("right_delta_vs_preferred")
            if _is_number(left_delta) or _is_number(right_delta):
                lines.append(
                    "  delta_vs_preferred: "
                    + f"{left_delta if left_delta is not None else 'none'} -> {right_delta if right_delta is not None else 'none'}"
                )
            delta_change = score_change.get("delta_vs_preferred_change")
            if _is_number(delta_change):
                lines.append(f"  delta_vs_preferred_change: {_format_signed(float(delta_change))}")

    variant_history_changes = _as_dict(payload.get("variant_history_changes"))
    if variant_history_changes:
        lines.append("Variant duplicate baseline rationale changes:")
        for variant_name in sorted(variant_history_changes):
            lines.append(f"- {variant_name}")
            history_change = _as_dict(variant_history_changes.get(variant_name))
            changed_fields = _as_dict(history_change.get("changed_fields"))
            for field_name in sorted(changed_fields):
                field_change = _as_dict(changed_fields.get(field_name))
                lines.append(f"  {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}")
            net_rationale = _as_dict(history_change.get("net_rationale"))
            verdict = str(net_rationale.get("label", "")) if net_rationale else _selection_driver_verdict(changed_fields)
            if verdict:
                lines.append(f"  net_rationale: {verdict}")
            score = net_rationale.get("score") if net_rationale else None
            if _is_number(score):
                lines.append(f"  net_rationale_score: {float(score):.2f}")
            top_scenario_profile_change = _as_dict(history_change.get("top_scenario_profile_change"))
            if top_scenario_profile_change:
                lines.append(
                    "  top_scenario_profile: "
                    + f"{top_scenario_profile_change.get('left', 'none')} -> {top_scenario_profile_change.get('right', 'none')}"
                )
            top_fragile_profile_change = _as_dict(history_change.get("top_fragile_profile_change"))
            if top_fragile_profile_change:
                lines.append(
                    "  top_fragile_profile: "
                    + f"{top_fragile_profile_change.get('left', 'none')} -> {top_fragile_profile_change.get('right', 'none')}"
                )
            top_runtime_profile_change = _as_dict(history_change.get("top_runtime_profile_change"))
            if top_runtime_profile_change:
                lines.append(
                    "  top_runtime_profile: "
                    + f"{top_runtime_profile_change.get('left', 'none')} -> {top_runtime_profile_change.get('right', 'none')}"
                )
            scenario_profile_hints = _as_dict(history_change.get("scenario_profile_hints"))
            if scenario_profile_hints:
                lines.append("  Scenario profile hints:")
                _append_indented_profile_hint_change_lines(lines, scenario_profile_hints)
            scenario_profile_avoidance = _as_dict(history_change.get("scenario_profile_avoidance"))
            if scenario_profile_avoidance:
                lines.append("  Scenario profile avoidance:")
                _append_indented_profile_hint_change_lines(lines, scenario_profile_avoidance)
            runtime_profile_hints = _as_dict(history_change.get("runtime_profile_hints"))
            runtime_changed_fields = _as_dict(runtime_profile_hints.get("changed_fields"))
            if runtime_changed_fields:
                lines.append("  Runtime profile hints:")
                for field_name in sorted(runtime_changed_fields):
                    field_change = _as_dict(runtime_changed_fields.get(field_name))
                    lines.append(
                        f"  - {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}"
                    )

    campaign_metrics = _as_dict(payload.get("campaign_metrics"))
    if campaign_metrics:
        lines.append("Campaign metrics:")
        for field_name in ("entry_count", "completed_entries", "failed_entries"):
            field_change = _as_dict(campaign_metrics.get(field_name))
            if not field_change:
                continue
            line = f"- {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}"
            delta = field_change.get("delta")
            if _is_number(delta):
                line += f" ({_format_signed(float(delta))})"
            lines.append(line)

    entry_changes = _as_dict(payload.get("entry_changes"))
    if entry_changes:
        lines.append(f"Added entries: {_format_list(entry_changes.get('added'))}")
        lines.append(f"Removed entries: {_format_list(entry_changes.get('removed'))}")
        lines.append(f"Retained entries: {_format_list(entry_changes.get('retained'))}")

    entry_result_changes = _as_dict(payload.get("entry_result_changes"))
    if entry_result_changes:
        lines.append("Entry result changes:")
        for entry_name in sorted(entry_result_changes):
            lines.append(f"- {entry_name}")
            entry_change = _as_dict(entry_result_changes.get(entry_name))
            status_change = _as_dict(entry_change.get("status_change"))
            if status_change:
                lines.append(f"  status: {status_change.get('left', 'none')} -> {status_change.get('right', 'none')}")
            command_change = _as_dict(entry_change.get("command_change"))
            if command_change:
                lines.append(f"  command: {command_change.get('left', 'none')} -> {command_change.get('right', 'none')}")
            run_id_change = _as_dict(entry_change.get("run_id_change"))
            if run_id_change:
                lines.append(f"  run_id: {run_id_change.get('left', 'none')} -> {run_id_change.get('right', 'none')}")

    return "\n".join(lines)


def build_duplicate_match_compare(
    report_payload: dict[str, object],
    config_payload: dict[str, object],
    matched_row: dict[str, object],
) -> dict[str, object]:
    requested_layers = {
        "directional": _string_list(config_payload.get("directional_layers")),
        "known_good": _string_list(config_payload.get("known_good_filters")),
        "custom": _string_list(config_payload.get("custom_filters")),
        "exits": _string_list(config_payload.get("exit_layers")),
    }
    matched_layers = {
        "accepted": _string_list(matched_row.get("accepted_layers")),
        "rejected": _string_list(matched_row.get("rejected_layers")),
        "phase_layers": _string_list(matched_row.get("phase_layers")),
    }
    duplicate_match = _as_dict(report_payload.get("duplicate_match"))
    return {
        "requested_run_id": report_payload.get("run_id"),
        "matched_run_id": matched_row.get("run_id"),
        "match_type": duplicate_match.get("match_type"),
        "requested_layers": requested_layers,
        "matched_layers": matched_layers,
        "matched_metrics": {
            "selection_oos_sharpe": matched_row.get("selection_oos_sharpe"),
            "selection_oos_net_pnl": matched_row.get("selection_oos_net_pnl"),
            "selection_oos_drawdown": matched_row.get("selection_oos_drawdown"),
        },
        "matched_decision": matched_row.get("decision"),
        "matched_quality_status": matched_row.get("snapshot_quality_status"),
        "study_signature_match": (
            duplicate_match.get("study_signature") is not None
            and duplicate_match.get("study_signature") == matched_row.get("study_signature")
        ),
    }


def format_duplicate_match_compare(payload: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"Duplicate compare for {payload.get('requested_run_id', 'unknown')}")
    lines.append(f"Match: {payload.get('match_type', 'unknown')} -> {payload.get('matched_run_id', 'unknown')}")

    requested_layers = _as_dict(payload.get("requested_layers"))
    lines.append(f"Requested directional: {_format_list(requested_layers.get('directional'))}")
    lines.append(f"Requested known-good: {_format_list(requested_layers.get('known_good'))}")
    lines.append(f"Requested custom: {_format_list(requested_layers.get('custom'))}")
    lines.append(f"Requested exits: {_format_list(requested_layers.get('exits'))}")

    matched_layers = _as_dict(payload.get("matched_layers"))
    lines.append(f"Matched accepted: {_format_list(matched_layers.get('accepted'))}")
    lines.append(f"Matched rejected: {_format_list(matched_layers.get('rejected'))}")

    matched_metrics = _as_dict(payload.get("matched_metrics"))
    lines.append(
        "Matched metrics: "
        + f"sharpe={matched_metrics.get('selection_oos_sharpe', 'n/a')} | "
        + f"pnl={matched_metrics.get('selection_oos_net_pnl', 'n/a')} | "
        + f"drawdown={matched_metrics.get('selection_oos_drawdown', 'n/a')}"
    )
    lines.append(f"Matched decision: {payload.get('matched_decision', 'unknown')}")
    lines.append(f"Matched quality: {payload.get('matched_quality_status', 'unknown')}")
    lines.append(f"Study signature match: {payload.get('study_signature_match', False)}")
    return "\n".join(lines)


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _index_phases(value: object) -> dict[str, dict[str, object]]:
    phases: dict[str, dict[str, object]] = {}
    if not isinstance(value, list):
        return phases
    for item in value:
        if not isinstance(item, dict):
            continue
        layer_name = item.get("layer_name")
        if isinstance(layer_name, str):
            phases[layer_name] = item
    return phases


def _index_variant_results(value: object) -> dict[str, dict[str, object]]:
    variants: dict[str, dict[str, object]] = {}
    if not isinstance(value, list):
        return variants
    for item in value:
        if not isinstance(item, dict):
            continue
        variant_name = item.get("variant")
        if isinstance(variant_name, str):
            variants[variant_name] = item
    return variants


def _index_named_entries(value: object) -> dict[str, dict[str, object]]:
    entries: dict[str, dict[str, object]] = {}
    if not isinstance(value, list):
        return entries
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str):
            entries[name] = item
    return entries


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _to_float_or_none(value: object) -> float | None:
    if not _is_number(value):
        return None
    return float(value)


def _rounded_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(right - left, 2)


def _left_right_delta(left: object, right: object) -> dict[str, object]:
    payload = {"left": left, "right": right, "delta": None}
    if _is_number(left) and _is_number(right):
        payload["delta"] = float(right) - float(left)
    return payload


def _normalized_metrics(payload: dict[str, object], phase_index: dict[str, dict[str, object]]) -> dict[str, object]:
    metrics = dict(_as_dict(payload.get("metrics")))
    accepted_sharpes = [
        float(phase.get("oos_sharpe", 0.0))
        for phase in phase_index.values()
        if bool(phase.get("accepted")) and phase.get("oos_sharpe") is not None
    ]
    if accepted_sharpes:
        metrics["selection_oos_sharpe"] = max(accepted_sharpes)
    return metrics


def _load_json_object(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _format_signed(value: float) -> str:
    return f"{value:+.2f}"


def _format_list(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    return ", ".join(str(item) for item in value)


def _format_string_list(value: object) -> str:
    if not isinstance(value, list):
        return "none"
    items = [str(item) for item in value if isinstance(item, str) and item]
    if not items:
        return "none"
    return ", ".join(items)


def _format_failure_taxonomy_counts(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    parts: list[tuple[str, int]] = []
    for key, raw_count in value.items():
        if not isinstance(key, str) or isinstance(raw_count, bool) or not isinstance(raw_count, int | float):
            continue
        parts.append((key, int(raw_count)))
    if not parts:
        return "none"
    parts.sort(key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{label}={count}" for label, count in parts)


def _format_parameters(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _normalized_scenario_profiles(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}
    profiles: dict[str, dict[str, object]] = {}
    for scenario_name, raw_profile in value.items():
        if not isinstance(scenario_name, str) or not isinstance(raw_profile, dict):
            continue
        profiles[scenario_name] = dict(raw_profile)
    return profiles


def _normalized_runtime_settings(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _normalized_snapshot_quality(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, object] = {}
    status = value.get("status")
    if status is not None:
        normalized["status"] = status
    flag_count = value.get("flag_count")
    if flag_count is not None:
        normalized["flag_count"] = flag_count
    report = value.get("report")
    if isinstance(report, dict):
        for key in ("quality_score", "passed"):
            if key in report:
                normalized[key] = report.get(key)
    return normalized


def _normalized_validation_bundle(value: object) -> dict[str, object]:
    return normalize_validation_bundle(value)


def _compare_scenario_profiles(
    left_profiles: dict[str, dict[str, object]],
    right_profiles: dict[str, dict[str, object]],
) -> dict[str, object]:
    added = {
        scenario_name: dict(right_profiles[scenario_name])
        for scenario_name in sorted(right_profiles.keys() - left_profiles.keys())
    }
    removed = {
        scenario_name: dict(left_profiles[scenario_name])
        for scenario_name in sorted(left_profiles.keys() - right_profiles.keys())
    }
    changed = {
        scenario_name: {
            "left": dict(left_profiles[scenario_name]),
            "right": dict(right_profiles[scenario_name]),
            "changed_fields": _diff_profile_fields(left_profiles[scenario_name], right_profiles[scenario_name]),
        }
        for scenario_name in sorted(left_profiles.keys() & right_profiles.keys())
        if left_profiles[scenario_name] != right_profiles[scenario_name]
    }
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _compare_runtime_settings(
    left_settings: dict[str, object],
    right_settings: dict[str, object],
) -> dict[str, object]:
    added = {
        setting_name: right_settings[setting_name]
        for setting_name in sorted(right_settings.keys() - left_settings.keys())
    }
    removed = {
        setting_name: left_settings[setting_name]
        for setting_name in sorted(left_settings.keys() - right_settings.keys())
    }
    changed_fields = {
        field_name: {
            "left": left_settings.get(field_name),
            "right": right_settings.get(field_name),
        }
        for field_name in sorted(left_settings.keys() & right_settings.keys())
        if left_settings.get(field_name) != right_settings.get(field_name)
    }
    return {
        "added": added,
        "removed": removed,
        "changed_fields": changed_fields,
    }


def _compare_duplicate_baseline_history(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    changed_fields = {
        field_name: {
            "left": left.get(field_name),
            "right": right.get(field_name),
        }
        for field_name in sorted(set(left) | set(right))
        if field_name not in {"scenario_profile_hints", "scenario_profile_avoidance", "runtime_profile_hints"}
        and left.get(field_name) != right.get(field_name)
        and not isinstance(left.get(field_name), dict)
        and not isinstance(right.get(field_name), dict)
    }
    left_hints = _normalized_profile_hints(left.get("scenario_profile_hints"))
    right_hints = _normalized_profile_hints(right.get("scenario_profile_hints"))
    left_avoidance = _normalized_profile_hints(left.get("scenario_profile_avoidance"))
    right_avoidance = _normalized_profile_hints(right.get("scenario_profile_avoidance"))
    left_runtime_hint = _normalized_runtime_profile_hint(left.get("runtime_profile_hints"))
    right_runtime_hint = _normalized_runtime_profile_hint(right.get("runtime_profile_hints"))
    return {
        "changed_fields": changed_fields,
        "net_rationale": _selection_driver_verdict_payload(changed_fields),
        "top_scenario_profile_change": _build_top_profile_change(left_hints, right_hints),
        "top_fragile_profile_change": _build_top_profile_change(left_avoidance, right_avoidance),
        "top_runtime_profile_change": _build_top_runtime_profile_change(left_runtime_hint, right_runtime_hint),
        "scenario_profile_hints": _compare_profile_hints(left_hints, right_hints),
        "scenario_profile_avoidance": _compare_profile_hints(left_avoidance, right_avoidance),
        "runtime_profile_hints": _compare_runtime_profile_hints(left_runtime_hint, right_runtime_hint),
    }


def _diff_profile_fields(left_profile: dict[str, object], right_profile: dict[str, object]) -> dict[str, object]:
    return {
        field_name: {
            "left": left_profile.get(field_name),
            "right": right_profile.get(field_name),
        }
        for field_name in sorted(set(left_profile) | set(right_profile))
        if left_profile.get(field_name) != right_profile.get(field_name)
    }


def _normalized_profile_hints(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}
    hints: dict[str, dict[str, object]] = {}
    for scenario_name, raw_hint in value.items():
        if not isinstance(scenario_name, str) or not isinstance(raw_hint, dict):
            continue
        profile = raw_hint.get("profile")
        if not isinstance(profile, dict):
            continue
        normalized_hint: dict[str, object] = {"profile": dict(profile)}
        if _is_number(raw_hint.get("count")):
            normalized_hint["count"] = raw_hint.get("count")
        hints[scenario_name] = normalized_hint
    return hints


def _compare_profile_hints(left_hints: dict[str, dict[str, object]], right_hints: dict[str, dict[str, object]]) -> dict[str, object]:
    added = {
        scenario_name: dict(right_hints[scenario_name])
        for scenario_name in sorted(right_hints.keys() - left_hints.keys())
    }
    removed = {
        scenario_name: dict(left_hints[scenario_name])
        for scenario_name in sorted(left_hints.keys() - right_hints.keys())
    }
    changed: dict[str, object] = {}
    for scenario_name in sorted(left_hints.keys() & right_hints.keys()):
        left_hint = left_hints[scenario_name]
        right_hint = right_hints[scenario_name]
        if left_hint == right_hint:
            continue
        hint_change: dict[str, object] = {
            "left": dict(left_hint),
            "right": dict(right_hint),
            "profile_changed_fields": _diff_profile_fields(
                _as_dict(left_hint.get("profile")),
                _as_dict(right_hint.get("profile")),
            ),
        }
        if left_hint.get("count") != right_hint.get("count"):
            hint_change["count"] = {
                "left": left_hint.get("count"),
                "right": right_hint.get("count"),
            }
        changed[scenario_name] = hint_change
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _build_top_profile_change(left_hints: dict[str, dict[str, object]], right_hints: dict[str, dict[str, object]]) -> dict[str, object]:
    left_label = _format_top_profile_hint(left_hints)
    right_label = _format_top_profile_hint(right_hints)
    if left_label == "none" and right_label == "none":
        return {}
    return {
        "left": left_label,
        "right": right_label,
    }


def _normalized_runtime_profile_hint(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    profile = value.get("profile")
    if not isinstance(profile, dict) or not profile:
        return {}
    normalized_hint: dict[str, object] = {"profile": dict(profile)}
    if _is_number(value.get("count")):
        normalized_hint["count"] = value.get("count")
    return normalized_hint


def _compare_runtime_profile_hints(left_hint: dict[str, object], right_hint: dict[str, object]) -> dict[str, object]:
    left_profile = _as_dict(left_hint.get("profile"))
    right_profile = _as_dict(right_hint.get("profile"))
    changed_fields = _diff_profile_fields(left_profile, right_profile)
    count_change: dict[str, object] = {}
    if left_hint.get("count") != right_hint.get("count"):
        count_change = {
            "left": left_hint.get("count"),
            "right": right_hint.get("count"),
        }
    return {
        "left": dict(left_hint),
        "right": dict(right_hint),
        "changed_fields": changed_fields,
        "count": count_change,
    }


def _build_top_runtime_profile_change(left_hint: dict[str, object], right_hint: dict[str, object]) -> dict[str, object]:
    left_label = _format_top_runtime_profile_hint(left_hint)
    right_label = _format_top_runtime_profile_hint(right_hint)
    if left_label == "none" and right_label == "none":
        return {}
    return {
        "left": left_label,
        "right": right_label,
    }


def _format_top_profile_hint(hints: dict[str, dict[str, object]]) -> str:
    if not hints:
        return "none"
    scenario_name, hint = next(iter(hints.items()))
    profile = _as_dict(hint.get("profile"))
    if not profile:
        return "none"
    return f"{scenario_name} | {_format_parameters(profile)}"


def _format_top_runtime_profile_hint(hint: dict[str, object]) -> str:
    profile = _as_dict(hint.get("profile"))
    if not profile:
        return "none"
    return _format_parameters(profile)


def _append_profile_hint_change_lines(lines: list[str], title: str, changes: dict[str, object]) -> None:
    if not changes:
        return
    rendered_any = False
    added = _as_dict(changes.get("added"))
    removed = _as_dict(changes.get("removed"))
    changed = _as_dict(changes.get("changed"))
    if not added and not removed and not changed:
        return
    lines.append(f"{title}:")
    for scenario_name in sorted(added):
        hint = _as_dict(added.get(scenario_name))
        lines.append(f"- added {scenario_name}: {_format_parameters(_as_dict(hint.get('profile')))}")
        rendered_any = True
    for scenario_name in sorted(removed):
        hint = _as_dict(removed.get(scenario_name))
        lines.append(f"- removed {scenario_name}: {_format_parameters(_as_dict(hint.get('profile')))}")
        rendered_any = True
    for scenario_name in sorted(changed):
        hint_change = _as_dict(changed.get(scenario_name))
        lines.append(
            f"- {scenario_name}: "
            + f"{_format_parameters(_as_dict(_as_dict(hint_change.get('left')).get('profile')))}"
            + " -> "
            + f"{_format_parameters(_as_dict(_as_dict(hint_change.get('right')).get('profile')))}"
        )
        count_change = _as_dict(hint_change.get("count"))
        if count_change:
            lines.append(f"  count: {count_change.get('left', 'none')} -> {count_change.get('right', 'none')}")
        profile_changed_fields = _as_dict(hint_change.get("profile_changed_fields"))
        for field_name in sorted(profile_changed_fields):
            field_change = _as_dict(profile_changed_fields.get(field_name))
            lines.append(f"  {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}")
        rendered_any = True
    if not rendered_any:
        lines.pop()


def _append_runtime_profile_hint_change_lines(lines: list[str], title: str, changes: dict[str, object]) -> None:
    if not changes:
        return
    changed_fields = _as_dict(changes.get("changed_fields"))
    count_change = _as_dict(changes.get("count"))
    left_hint = _as_dict(changes.get("left"))
    right_hint = _as_dict(changes.get("right"))
    if not changed_fields and not count_change and not left_hint and not right_hint:
        return
    lines.append(f"{title}:")
    if left_hint or right_hint:
        lines.append(
            "- profile: "
            + f"{_format_parameters(_as_dict(left_hint.get('profile')))}"
            + " -> "
            + f"{_format_parameters(_as_dict(right_hint.get('profile')))}"
        )
    if count_change:
        lines.append(f"- count: {count_change.get('left', 'none')} -> {count_change.get('right', 'none')}")
    for field_name in sorted(changed_fields):
        field_change = _as_dict(changed_fields.get(field_name))
        lines.append(f"- {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}")


def _append_indented_profile_hint_change_lines(lines: list[str], changes: dict[str, object]) -> None:
    added = _as_dict(changes.get("added"))
    removed = _as_dict(changes.get("removed"))
    changed = _as_dict(changes.get("changed"))
    for scenario_name in sorted(added):
        hint = _as_dict(added.get(scenario_name))
        lines.append(f"  - added {scenario_name}: {_format_parameters(_as_dict(hint.get('profile')))}")
    for scenario_name in sorted(removed):
        hint = _as_dict(removed.get(scenario_name))
        lines.append(f"  - removed {scenario_name}: {_format_parameters(_as_dict(hint.get('profile')))}")
    for scenario_name in sorted(changed):
        hint_change = _as_dict(changed.get(scenario_name))
        lines.append(
            f"  - {scenario_name}: "
            + f"{_format_parameters(_as_dict(_as_dict(hint_change.get('left')).get('profile')))}"
            + " -> "
            + f"{_format_parameters(_as_dict(_as_dict(hint_change.get('right')).get('profile')))}"
        )
        count_change = _as_dict(hint_change.get("count"))
        if count_change:
            lines.append(f"    count: {count_change.get('left', 'none')} -> {count_change.get('right', 'none')}")
        profile_changed_fields = _as_dict(hint_change.get("profile_changed_fields"))
        for field_name in sorted(profile_changed_fields):
            field_change = _as_dict(profile_changed_fields.get(field_name))
            lines.append(f"    {field_name}: {field_change.get('left', 'none')} -> {field_change.get('right', 'none')}")


def _build_selection_driver_lines(changed_fields: dict[str, object]) -> list[str]:
    scored_drivers: list[tuple[float, int, str]] = []
    for field_name in ("success_rate", "average_sharpe", "promoted_count", "sample_count"):
        field_change = _as_dict(changed_fields.get(field_name))
        if not field_change:
            continue
        left_value = field_change.get("left", "none")
        right_value = field_change.get("right", "none")
        direction = _selection_driver_direction(field_name, left_value, right_value)
        score = _selection_driver_score(field_name, left_value, right_value)
        priority = _selection_driver_weight(field_name)
        strength = _selection_driver_strength(score)
        scored_drivers.append((score, priority, f"- [{strength}] {field_name} {direction}: {left_value} -> {right_value}"))
    scored_drivers.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [line for _, _, line in scored_drivers]


def _is_better_numeric_change(field_name: str, left_value: object, right_value: object) -> bool:
    if field_name not in {"success_rate", "average_sharpe", "promoted_count", "sample_count"}:
        return False
    if not _is_number(left_value) or not _is_number(right_value):
        return False
    return float(right_value) > float(left_value)


def _selection_driver_direction(field_name: str, left_value: object, right_value: object) -> str:
    if _is_better_numeric_change(field_name, left_value, right_value):
        return "improved"
    if _is_worse_numeric_change(field_name, left_value, right_value):
        return "worsened"
    return "changed"


def _selection_driver_score(field_name: str, left_value: object, right_value: object) -> float:
    weight = _selection_driver_weight(field_name)
    if not _is_number(left_value) or not _is_number(right_value):
        return float(weight)
    left_number = float(left_value)
    right_number = float(right_value)
    baseline = abs(left_number) if abs(left_number) > 1e-9 else 1.0
    relative_change = abs(right_number - left_number) / baseline
    return weight * relative_change


def _selection_driver_weight(field_name: str) -> int:
    weights = {
        "success_rate": 4,
        "average_sharpe": 3,
        "promoted_count": 2,
        "sample_count": 1,
    }
    return weights.get(field_name, 0)


def _is_worse_numeric_change(field_name: str, left_value: object, right_value: object) -> bool:
    if field_name not in {"success_rate", "average_sharpe", "promoted_count", "sample_count"}:
        return False
    if not _is_number(left_value) or not _is_number(right_value):
        return False
    return float(right_value) < float(left_value)


def _selection_driver_strength(score: float) -> str:
    if score >= 2.0:
        return "high"
    if score >= 1.0:
        return "medium"
    return "low"


def _selection_driver_verdict(changed_fields: dict[str, object]) -> str:
    payload = _selection_driver_verdict_payload(changed_fields)
    return str(payload.get("label", ""))


def _selection_driver_verdict_payload(changed_fields: dict[str, object]) -> dict[str, object]:
    net_score = 0.0
    for field_name in ("success_rate", "average_sharpe", "promoted_count", "sample_count"):
        field_change = _as_dict(changed_fields.get(field_name))
        if not field_change:
            continue
        left_value = field_change.get("left", "none")
        right_value = field_change.get("right", "none")
        score = _selection_driver_score(field_name, left_value, right_value)
        if _is_better_numeric_change(field_name, left_value, right_value):
            net_score += score
        elif _is_worse_numeric_change(field_name, left_value, right_value):
            net_score -= score
    strength = _selection_driver_strength(abs(net_score))
    if net_score > 0.05:
        direction = "improved"
    elif net_score < -0.05:
        direction = "worsened"
    else:
        direction = "mixed"
    return {
        "direction": direction,
        "strength": strength,
        "label": f"{direction} ({strength})",
        "score": round(net_score, 2),
    }
