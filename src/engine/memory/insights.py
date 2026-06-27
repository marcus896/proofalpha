from __future__ import annotations

from collections import Counter
import json


KNOWN_REGIMES = ("bull", "bear", "sideways", "crash", "liquidity_stress", "short_squeeze")


def select_memory_rows(
    rows: list[dict[str, object]],
    *,
    memory_quality_policy: str,
    limit: int | None = None,
) -> list[dict[str, object]]:
    limited = list(rows)
    if memory_quality_policy != "all":
        limited = [row for row in rows if row.get("snapshot_quality_status") != "dirty"]
    if limit is None:
        return limited
    return limited[: max(0, limit)]


def count_excluded_dirty_rows(all_rows: list[dict[str, object]], selected_rows: list[dict[str, object]]) -> int:
    selected_ids = {str(row.get("run_id")) for row in selected_rows}
    return sum(
        1
        for row in all_rows
        if row.get("snapshot_quality_status") == "dirty" and str(row.get("run_id")) not in selected_ids
    )


def build_memory_summary(
    rows: list[dict[str, object]],
    excluded_dirty_runs: int = 0,
    memory_quality_policy: str = "clean-only",
) -> dict[str, object]:
    promoted_runs = [row for row in rows if row.get("decision") == "promoted"]
    blocked_runs = [row for row in rows if row.get("decision") == "blocked"]
    promising_counter: Counter[str] = Counter()
    fragile_counter: Counter[str] = Counter()
    duplicate_match_counter: Counter[str] = Counter()
    scenario_profile_counter: Counter[str] = Counter()
    scenario_profile_variants: dict[str, Counter[str]] = {}
    blocked_scenario_profile_variants: dict[str, Counter[str]] = {}
    runtime_profile_variants: Counter[str] = Counter()
    snapshot_build_variants: Counter[str] = Counter()
    snapshot_source_hashes: set[str] = set()
    loop_failure_taxonomy_counter: Counter[str] = Counter()
    next_action_counter: Counter[str] = Counter()
    validation_failure_counter: Counter[str] = Counter()
    regime_coverage_totals: dict[str, float] = {regime: 0.0 for regime in KNOWN_REGIMES}
    regime_summary_rows = 0
    promoted_parameter_hints: dict[str, dict[str, list[int | float]]] = {}
    blocked_parameter_hints: dict[str, dict[str, list[int | float]]] = {}
    promoted_regime_parameter_hints: dict[str, dict[str, dict[str, list[int | float]]]] = {}
    blocked_regime_parameter_hints: dict[str, dict[str, dict[str, list[int | float]]]] = {}

    for row in promoted_runs:
        for layer in row.get("accepted_layers", []):
            if isinstance(layer, str):
                promising_counter[layer] += 1
        duplicate_match_run_id = row.get("accepted_duplicate_match_run_id")
        if isinstance(duplicate_match_run_id, str) and duplicate_match_run_id:
            duplicate_match_counter[duplicate_match_run_id] += 1
        scenario_profiles = row.get("scenario_profiles")
        if isinstance(scenario_profiles, dict):
            for scenario_name, profile in scenario_profiles.items():
                if isinstance(scenario_name, str):
                    scenario_profile_counter[scenario_name] += 1
                    if isinstance(profile, dict):
                        scenario_profile_variants.setdefault(scenario_name, Counter())[json.dumps(profile, sort_keys=True)] += 1
        runtime_settings = row.get("runtime_settings")
        if isinstance(runtime_settings, dict) and runtime_settings:
            runtime_profile_variants[json.dumps(runtime_settings, sort_keys=True)] += 1
        snapshot_build_version = row.get("snapshot_build_version")
        if isinstance(snapshot_build_version, str) and snapshot_build_version:
            snapshot_build_variants[snapshot_build_version] += 1
        snapshot_source_hash = row.get("snapshot_source_hash")
        if isinstance(snapshot_source_hash, str) and snapshot_source_hash:
            snapshot_source_hashes.add(snapshot_source_hash)
        agent_loop_metadata = row.get("agent_loop_metadata")
        if isinstance(agent_loop_metadata, dict):
            _collect_loop_failure_taxonomy(loop_failure_taxonomy_counter, agent_loop_metadata.get("failure_taxonomy_counts"))
            _collect_next_actions(next_action_counter, agent_loop_metadata.get("next_hypotheses"))
        _collect_parameter_values(promoted_parameter_hints, row.get("selected_parameters"))
        _collect_regime_parameter_values(
            promoted_regime_parameter_hints,
            row.get("regime_summary"),
            row.get("selected_parameters"),
        )
        regime_summary_rows += _accumulate_regime_coverage(regime_coverage_totals, row.get("regime_summary"))
        _collect_validation_failures(validation_failure_counter, row.get("validation_gate_results"))

    for row in blocked_runs:
        for layer in row.get("rejected_layers", []):
            if isinstance(layer, str):
                fragile_counter[layer] += 1
        scenario_profiles = row.get("scenario_profiles")
        if isinstance(scenario_profiles, dict):
            for scenario_name, profile in scenario_profiles.items():
                if isinstance(scenario_name, str) and isinstance(profile, dict):
                    blocked_scenario_profile_variants.setdefault(scenario_name, Counter())[json.dumps(profile, sort_keys=True)] += 1
        _collect_parameter_values(blocked_parameter_hints, row.get("selected_parameters"))
        _collect_regime_parameter_values(
            blocked_regime_parameter_hints,
            row.get("regime_summary"),
            row.get("selected_parameters"),
        )
        regime_summary_rows += _accumulate_regime_coverage(regime_coverage_totals, row.get("regime_summary"))
        _collect_validation_failures(validation_failure_counter, row.get("validation_gate_results"))

    parameter_hints = {
        layer_name: {
            parameter_name: _build_parameter_hint(
                promoted_values=parameters[parameter_name],
                blocked_values=blocked_parameter_hints.get(layer_name, {}).get(parameter_name, []),
            )
            for parameter_name in parameters
            if parameters[parameter_name]
        }
        for layer_name, parameters in promoted_parameter_hints.items()
    }

    return {
        "prior_runs": len(rows),
        "promoted_runs": len(promoted_runs),
        "blocked_runs": len(blocked_runs),
        "excluded_dirty_runs": excluded_dirty_runs,
        "memory_quality_policy": memory_quality_policy,
        "recovered_duplicate_runs": sum(duplicate_match_counter.values()),
        "top_duplicate_matches": _rank_counter(duplicate_match_counter, key_name="run_id"),
        "scenario_profiles": _rank_counter(scenario_profile_counter, key_name="scenario_name"),
        "scenario_profile_hints": _build_scenario_profile_hints(scenario_profile_variants),
        "scenario_profile_avoidance": _build_scenario_profile_hints(blocked_scenario_profile_variants, minimum_count=2),
        "runtime_profile_hints": _build_runtime_profile_hints(runtime_profile_variants),
        "snapshot_build_versions": _rank_counter(snapshot_build_variants, key_name="build_version"),
        "snapshot_source_hash_distinct_count": len(snapshot_source_hashes),
        "loop_failure_taxonomy_counts": _rank_counter(loop_failure_taxonomy_counter, key_name="taxonomy_label"),
        "next_actions": _rank_counter(next_action_counter, key_name="action"),
        "validation_failures": _rank_counter(validation_failure_counter, key_name="gate_name"),
        "regime_coverage_gaps": _build_regime_coverage_gaps(regime_coverage_totals, regime_summary_rows),
        "regime_parameter_hints": _build_regime_parameter_hints(
            promoted_regime_parameter_hints,
            blocked_regime_parameter_hints,
        ),
        "promising_layers": _rank_counter(promising_counter),
        "fragile_layers": _rank_counter(fragile_counter),
        "parameter_hints": parameter_hints,
    }


def render_memory_summary(summary: dict[str, object], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(summary, sort_keys=True)

    lines = ["Research memory summary"]
    lines.append(f"Memory quality policy: {summary.get('memory_quality_policy', 'unknown')}")
    lines.append(f"Prior runs: {summary.get('prior_runs', 0)}")
    lines.append(f"Promoted runs: {summary.get('promoted_runs', 0)}")
    lines.append(f"Blocked runs: {summary.get('blocked_runs', 0)}")
    lines.append(f"Excluded dirty runs: {summary.get('excluded_dirty_runs', 0)}")
    lines.append(f"Recovered duplicate runs: {summary.get('recovered_duplicate_runs', 0)}")
    lines.append(f"Top duplicate matches: {_format_ranked_counts(summary.get('top_duplicate_matches'), key_name='run_id')}")
    lines.append(f"Scenario profiles: {_format_ranked_counts(summary.get('scenario_profiles'), key_name='scenario_name')}")
    top_scenario_profile = _format_top_scenario_profile(summary.get("scenario_profile_hints"))
    if top_scenario_profile != "none":
        lines.append(f"Top scenario profile: {top_scenario_profile}")
    top_runtime_profile = _format_top_runtime_profile(summary.get("runtime_profile_hints"))
    if top_runtime_profile != "none":
        lines.append(f"Top runtime profile: {top_runtime_profile}")
    top_snapshot_builds = _format_ranked_counts(summary.get("snapshot_build_versions"), key_name="build_version")
    if top_snapshot_builds != "none":
        lines.append(f"Top snapshot builds: {top_snapshot_builds}")
    source_hash_count = summary.get("snapshot_source_hash_distinct_count", 0)
    lines.append(f"Snapshot source hashes: {source_hash_count} distinct")
    top_loop_pressure = _format_ranked_counts(summary.get("loop_failure_taxonomy_counts"), key_name="taxonomy_label")
    if top_loop_pressure != "none":
        lines.append(f"Loop pressure: {top_loop_pressure}")
    top_next_actions = _format_ranked_counts(summary.get("next_actions"), key_name="action")
    if top_next_actions != "none":
        lines.append(f"Top next actions: {top_next_actions}")
    top_validation_failure = _format_ranked_counts(summary.get("validation_failures"), key_name="gate_name")
    if top_validation_failure != "none":
        lines.append(f"Validation failures: {top_validation_failure}")
    top_regime_gaps = _format_ranked_regime_gaps(summary.get("regime_coverage_gaps"))
    if top_regime_gaps != "none":
        lines.append(f"Regime coverage gaps: {top_regime_gaps}")
    lines.append(
        f"Fragile scenario profiles: {_format_scenario_profile_hints(summary.get('scenario_profile_avoidance'))}"
    )
    top_fragile_profile = _format_top_scenario_profile(summary.get("scenario_profile_avoidance"))
    if top_fragile_profile != "none":
        lines.append(f"Top fragile profile: {top_fragile_profile}")
    lines.append(f"Promising layers: {_format_layer_counts(summary.get('promising_layers'))}")
    lines.append(f"Fragile layers: {_format_layer_counts(summary.get('fragile_layers'))}")
    return "\n".join(lines)


def _collect_parameter_values(
    target: dict[str, dict[str, list[int | float]]],
    selected_parameters: object,
) -> None:
    if not isinstance(selected_parameters, dict):
        return
    for layer_name, parameters in selected_parameters.items():
        if not isinstance(layer_name, str) or not isinstance(parameters, dict):
            continue
        layer_hints = target.setdefault(layer_name, {})
        for parameter_name, value in parameters.items():
            if isinstance(parameter_name, str) and isinstance(value, (int, float)):
                layer_hints.setdefault(parameter_name, []).append(value)


def _collect_regime_parameter_values(
    target: dict[str, dict[str, dict[str, list[int | float]]]],
    regime_summary: object,
    selected_parameters: object,
) -> None:
    state_key = _regime_state_key_from_summary(regime_summary)
    if state_key is None:
        return
    bucket = target.setdefault(state_key, {})
    _collect_parameter_values(bucket, selected_parameters)


def _rank_counter(counter: Counter[str], key_name: str = "layer_name") -> list[dict[str, object]]:
    return [
        {key_name: name, "count": count}
        for name, count in counter.most_common()
    ]


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


def _build_regime_parameter_hints(
    promoted: dict[str, dict[str, dict[str, list[int | float]]]],
    blocked: dict[str, dict[str, dict[str, list[int | float]]]],
) -> dict[str, dict[str, object]]:
    hints: dict[str, dict[str, object]] = {}
    for state_key, promoted_layers in promoted.items():
        if not isinstance(state_key, str) or not isinstance(promoted_layers, dict):
            continue
        state_hints = {
            layer_name: {
                parameter_name: _build_parameter_hint(
                    promoted_values=parameters[parameter_name],
                    blocked_values=blocked.get(state_key, {}).get(layer_name, {}).get(parameter_name, []),
                )
                for parameter_name in parameters
                if parameters[parameter_name]
            }
            for layer_name, parameters in promoted_layers.items()
            if isinstance(layer_name, str) and isinstance(parameters, dict)
        }
        if state_hints:
            hints[state_key] = {
                "state_key": state_key,
                "parameter_hints": state_hints,
            }
    return hints


def _regime_state_key_from_summary(regime_summary: object) -> str | None:
    if not isinstance(regime_summary, dict):
        return None
    metadata = regime_summary.get("regime_metadata")
    if isinstance(metadata, dict):
        key = metadata.get("regime_state_key")
        if isinstance(key, str) and key:
            return key
    state = regime_summary.get("regime_state")
    if isinstance(state, dict):
        key = state.get("regime_state_key")
        if isinstance(key, str) and key:
            return key
    coverage = regime_summary.get("regime_coverage")
    if isinstance(coverage, dict) and coverage:
        dominant = max(
            ((str(label), float(value)) for label, value in coverage.items() if isinstance(value, int | float)),
            key=lambda item: item[1],
            default=("unknown", 0.0),
        )[0]
        return f"{dominant}|unknown|unknown|unknown"
    return None


def _build_scenario_profile_hints(
    profile_variants: dict[str, Counter[str]],
    minimum_count: int = 1,
) -> dict[str, dict[str, object]]:
    hints: dict[str, dict[str, object]] = {}
    for scenario_name, variants in profile_variants.items():
        if not isinstance(scenario_name, str) or not variants:
            continue
        serialized_profile, count = variants.most_common(1)[0]
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


def _build_runtime_profile_hints(profile_variants: Counter[str]) -> dict[str, object]:
    if not profile_variants:
        return {}
    serialized_profile, count = profile_variants.most_common(1)[0]
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


def _collect_validation_failures(counter: Counter[str], validation_gate_results: object) -> None:
    if not isinstance(validation_gate_results, dict):
        return
    for gate_name, passed in validation_gate_results.items():
        if isinstance(gate_name, str) and passed is False:
            counter[gate_name] += 1


def _collect_loop_failure_taxonomy(counter: Counter[str], failure_taxonomy_counts: object) -> None:
    if not isinstance(failure_taxonomy_counts, dict):
        return
    for label, count in failure_taxonomy_counts.items():
        if isinstance(label, str) and isinstance(count, int | float) and not isinstance(count, bool):
            counter[label] += int(count)


def _collect_next_actions(counter: Counter[str], next_hypotheses: object) -> None:
    if not isinstance(next_hypotheses, list):
        return
    for item in next_hypotheses:
        if isinstance(item, str) and item:
            counter[item] += 1


def _accumulate_regime_coverage(
    regime_coverage_totals: dict[str, float],
    regime_summary: object,
) -> int:
    if not isinstance(regime_summary, dict):
        return 0
    coverage = regime_summary.get("regime_coverage")
    if not isinstance(coverage, dict):
        return 0
    for regime in KNOWN_REGIMES:
        value = coverage.get(regime, 0.0)
        if isinstance(value, int | float) and not isinstance(value, bool):
            regime_coverage_totals[regime] += float(value)
    return 1


def _build_regime_coverage_gaps(
    regime_coverage_totals: dict[str, float],
    regime_summary_rows: int,
) -> list[dict[str, object]]:
    if regime_summary_rows <= 0:
        return []
    gaps: list[dict[str, object]] = []
    for regime in KNOWN_REGIMES:
        average_coverage = regime_coverage_totals.get(regime, 0.0) / regime_summary_rows
        if average_coverage < 0.15 and regime_coverage_totals.get(regime, 0.0) > 0.0:
            gaps.append(
                {
                    "regime_label": regime,
                    "average_coverage": round(average_coverage, 6),
                    "count": regime_summary_rows,
                }
            )
    return sorted(gaps, key=lambda item: (float(item["average_coverage"]), str(item["regime_label"])))


def _format_layer_counts(raw: object) -> str:
    return _format_ranked_counts(raw, key_name="layer_name")


def _format_ranked_counts(raw: object, key_name: str) -> str:
    if not isinstance(raw, list) or not raw:
        return "none"
    parts: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get(key_name)
        count = item.get("count")
        if isinstance(name, str):
            parts.append(f"{name}({count})")
    return ", ".join(parts) if parts else "none"


def _format_ranked_regime_gaps(raw: object) -> str:
    if not isinstance(raw, list) or not raw:
        return "none"
    parts: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        regime = item.get("regime_label")
        coverage = item.get("average_coverage")
        if isinstance(regime, str):
            parts.append(f"{regime}({coverage})")
    return ", ".join(parts) if parts else "none"


def _format_scenario_profile_hints(raw: object) -> str:
    if not isinstance(raw, dict) or not raw:
        return "none"
    parts: list[str] = []
    for scenario_name, hint in raw.items():
        if not isinstance(scenario_name, str) or not isinstance(hint, dict):
            continue
        parts.append(f"{scenario_name}({hint.get('count', 0)})")
    return ", ".join(parts) if parts else "none"


def _format_top_scenario_profile(raw: object) -> str:
    if not isinstance(raw, dict) or not raw:
        return "none"
    scenario_name, hint = next(iter(raw.items()))
    if not isinstance(scenario_name, str) or not isinstance(hint, dict):
        return "none"
    profile = hint.get("profile")
    if not isinstance(profile, dict) or not profile:
        return "none"
    parts = [f"{key}={profile[key]}" for key in sorted(profile)]
    return f"{scenario_name} | " + ", ".join(parts)


def _format_top_runtime_profile(raw: object) -> str:
    if not isinstance(raw, dict) or not raw:
        return "none"
    profile = raw.get("profile")
    if not isinstance(profile, dict) or not profile:
        return "none"
    parts = [f"{key}={profile[key]}" for key in sorted(profile)]
    return ", ".join(parts)
