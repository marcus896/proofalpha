from __future__ import annotations

import json


SCENARIO_REGIME_MAP: dict[str, set[str]] = {
    "attention-burst": {"bull", "short_squeeze"},
    "funding-basis-shock": {"bear", "liquidity_stress"},
    "liquidation-cascade": {"crash", "liquidity_stress"},
    "liquidity-withdrawal": {"liquidity_stress"},
    "short-squeeze": {"short_squeeze"},
    "venue-outage": {"liquidity_stress", "crash"},
}


def extract_layer_names(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    layer_names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            layer_name = item.get("layer_name")
            if isinstance(layer_name, str):
                layer_names.append(layer_name)
    return layer_names


def extract_scenario_names(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    scenario_names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            scenario_name = item.get("scenario_name")
            if isinstance(scenario_name, str):
                scenario_names.append(scenario_name)
    return scenario_names


def reorder_layers(values: list[str], prioritized_layers: list[str]) -> list[str]:
    priority = {layer_name: index for index, layer_name in enumerate(prioritized_layers)}
    return sorted(values, key=lambda value: (priority.get(value, len(priority) + values.index(value)), values.index(value)))


def reorder_scenarios(
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


def build_variant_promising_layers(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> list[str]:
    global_promising_layers = extract_layer_names(memory_summary.get("promising_layers"))
    if not isinstance(duplicate_baseline_history, dict):
        return global_promising_layers

    variant_promising_layers = extract_layer_names(duplicate_baseline_history.get("promising_layers"))
    merged_layers = list(variant_promising_layers)
    merged_layers.extend(layer for layer in global_promising_layers if layer not in merged_layers)
    return merged_layers


def build_variant_parameter_hints(
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


def build_variant_fragile_layers(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> set[str]:
    fragile_layers = set(extract_layer_names(memory_summary.get("fragile_layers")))
    if not isinstance(duplicate_baseline_history, dict):
        return fragile_layers

    fragile_layers.update(extract_layer_names(duplicate_baseline_history.get("fragile_layers")))
    return fragile_layers


def scenario_priority_from_regime_gaps(
    regime_coverage_gaps: object,
    scenarios: list[dict[str, object]],
) -> list[str]:
    if not isinstance(regime_coverage_gaps, list):
        return []
    gap_regimes = [
        item.get("regime_label")
        for item in regime_coverage_gaps
        if isinstance(item, dict) and isinstance(item.get("regime_label"), str)
    ]
    prioritized: list[str] = []
    for scenario in scenarios:
        scenario_name = scenario.get("name")
        if not isinstance(scenario_name, str):
            continue
        covered_regimes = SCENARIO_REGIME_MAP.get(scenario_name, set())
        if covered_regimes.intersection(gap_regimes) and scenario_name not in prioritized:
            prioritized.append(scenario_name)
    return prioritized


def build_variant_scenario_priority(
    memory_summary: dict[str, object],
    scenarios: list[dict[str, object]],
    *,
    duplicate_baseline_history: dict[str, object] | None = None,
) -> list[str]:
    global_scenarios = extract_scenario_names(memory_summary.get("scenario_profiles"))
    merged = list(global_scenarios)
    if isinstance(duplicate_baseline_history, dict):
        variant_scenarios = extract_scenario_names(duplicate_baseline_history.get("scenario_profiles"))
        merged = list(variant_scenarios)
        merged.extend(scenario_name for scenario_name in global_scenarios if scenario_name not in merged)

    regime_gap_priority = scenario_priority_from_regime_gaps(
        memory_summary.get("regime_coverage_gaps"),
        scenarios,
    )
    ordered = list(regime_gap_priority)
    ordered.extend(name for name in merged if name not in ordered)
    return ordered


def build_variant_scenario_profile_hints(
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


def build_variant_scenario_profile_avoidance(
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


def build_variant_runtime_profile_hints(
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


def apply_scenario_profile_hints(
    scenarios: list[object],
    *,
    scenario_priority: list[str],
    scenario_profile_hints: dict[str, dict[str, object]],
    scenario_profile_avoidance: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    scenario_payloads = [dict(item) for item in scenarios if isinstance(item, dict)]
    if not scenario_payloads:
        return []

    ordered = reorder_scenarios(scenario_payloads, scenario_priority)
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
            if isinstance(blocked_profile, dict) and profiles_match(profile, blocked_profile):
                resolved.append(scenario)
                continue
        merged = dict(profile)
        merged.update(scenario)
        resolved.append(merged)
    return resolved


def apply_runtime_profile_hints(
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


def profiles_match(left: dict[str, object], right: dict[str, object]) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def filter_parameter_grids(
    parameter_grids: dict[str, object],
    fragile_layers: set[str],
    approved_layers: set[str],
) -> dict[str, object]:
    return {
        layer_name: grid
        for layer_name, grid in parameter_grids.items()
        if isinstance(layer_name, str) and layer_name in approved_layers and layer_name not in fragile_layers
    }


def refine_parameter_grids(
    parameter_grids: dict[str, object],
    parameter_hints: dict[str, object],
    fragile_layers: set[str],
    approved_layers: set[str],
) -> dict[str, object]:
    refined: dict[str, object] = {}
    for layer_name, grid in parameter_grids.items():
        if not isinstance(layer_name, str) or layer_name not in approved_layers or layer_name in fragile_layers:
            continue
        if not isinstance(grid, dict):
            refined[layer_name] = grid
            continue
        layer_hints = parameter_hints.get(layer_name, {})
        if not isinstance(layer_hints, dict):
            refined[layer_name] = grid
            continue
        refined[layer_name] = {
            parameter_name: refine_parameter_spec(spec, layer_hints.get(parameter_name))
            for parameter_name, spec in grid.items()
        }
    return refined


def refine_parameter_spec(spec: object, hint: object) -> object:
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


def build_parameter_avoidance(parameter_hints: dict[str, object]) -> dict[str, dict[str, list[int | float]]]:
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


def build_variant_metadata(variant_name: str) -> dict[str, str]:
    descriptions = {
        "balanced": "Prunes fragile layers and narrows only high-confidence parameter regions.",
        "conservative": "Uses the balanced follow-up with stricter validation-oriented runtime settings.",
        "exploratory": "Keeps wider parameter grids while still applying memory-driven layer ordering and pruning.",
    }
    return {
        "name": variant_name,
        "description": descriptions.get(variant_name, "Autoresearch follow-up variant."),
    }


def apply_variant_runtime(payload: dict[str, object], variant_name: str) -> None:
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
