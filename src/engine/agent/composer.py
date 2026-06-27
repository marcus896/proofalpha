from __future__ import annotations

from dataclasses import dataclass, field
import json

from engine.agent.heuristics import (
    apply_runtime_profile_hints,
    apply_scenario_profile_hints,
    apply_variant_runtime,
    build_parameter_avoidance,
    build_variant_fragile_layers,
    build_variant_metadata,
    build_variant_parameter_hints,
    build_variant_promising_layers,
    build_variant_runtime_profile_hints,
    build_variant_scenario_priority,
    build_variant_scenario_profile_avoidance,
    build_variant_scenario_profile_hints,
    filter_parameter_grids,
    refine_parameter_grids,
    reorder_layers,
)


@dataclass(frozen=True)
class AdvisoryInput:
    base_payload: dict[str, object]
    memory_summary: dict[str, object]
    layer_catalog: dict[str, list[str]]
    study_schema: dict[str, object]
    duplicate_baseline_history_by_variant: dict[str, dict[str, object]] = field(default_factory=dict)
    skill_contracts: list[dict[str, object]] = field(default_factory=list)
    mcp_environment: dict[str, object] = field(default_factory=dict)
    loop_policy: dict[str, object] = field(default_factory=dict)


def build_advisory_payload(
    advisory_input: AdvisoryInput,
    *,
    variant_name: str,
    narrow_parameter_grids: bool,
) -> dict[str, object]:
    next_payload = json.loads(json.dumps(advisory_input.base_payload))
    base_run_id = str(next_payload.get("run_id", "study"))
    next_payload["run_id"] = f"{base_run_id}-next" if variant_name == "balanced" else f"{base_run_id}-next-{variant_name}"

    duplicate_baseline_history = advisory_input.duplicate_baseline_history_by_variant.get(variant_name, {})
    if not isinstance(duplicate_baseline_history, dict):
        duplicate_baseline_history = {}

    approved_catalog = {
        key: [name for name in values if isinstance(name, str)]
        for key, values in advisory_input.layer_catalog.items()
        if isinstance(key, str) and isinstance(values, list)
    }
    approved_layer_names = {
        name
        for values in approved_catalog.values()
        for name in values
        if isinstance(name, str)
    }

    promising_layers = build_variant_promising_layers(
        advisory_input.memory_summary,
        duplicate_baseline_history=duplicate_baseline_history,
    )
    parameter_hints = build_variant_parameter_hints(
        advisory_input.memory_summary,
        duplicate_baseline_history=duplicate_baseline_history,
    )
    target_regime_state = _derive_payload_regime_state(next_payload.get("snapshot"))
    parameter_hints = _merge_matching_regime_parameter_hints(
        parameter_hints,
        advisory_input.memory_summary,
        target_regime_state,
    )
    fragile_layers = build_variant_fragile_layers(
        advisory_input.memory_summary,
        duplicate_baseline_history=duplicate_baseline_history,
    )
    scenario_profile_hints = build_variant_scenario_profile_hints(
        advisory_input.memory_summary,
        duplicate_baseline_history=duplicate_baseline_history,
    )
    scenario_profile_avoidance = build_variant_scenario_profile_avoidance(
        advisory_input.memory_summary,
        duplicate_baseline_history=duplicate_baseline_history,
    )
    runtime_profile_hints = build_variant_runtime_profile_hints(
        advisory_input.memory_summary,
        duplicate_baseline_history=duplicate_baseline_history,
    )

    for key in ("directional_layers", "known_good_filters", "custom_filters", "exit_layers"):
        values = next_payload.get(key, [])
        allowed = set(approved_catalog.get(key, []))
        if not isinstance(values, list):
            continue
        filtered = [
            value
            for value in values
            if isinstance(value, str) and value in allowed and value not in fragile_layers
        ]
        next_payload[key] = reorder_layers(filtered, promising_layers)

    scenarios = next_payload.get("scenarios")
    if isinstance(scenarios, list):
        normalized_scenarios = [dict(item) for item in scenarios if isinstance(item, dict)]
        scenario_priority = build_variant_scenario_priority(
            advisory_input.memory_summary,
            normalized_scenarios,
            duplicate_baseline_history=duplicate_baseline_history,
        )
        next_payload["scenarios"] = apply_scenario_profile_hints(
            normalized_scenarios,
            scenario_priority=scenario_priority,
            scenario_profile_hints=scenario_profile_hints,
            scenario_profile_avoidance=scenario_profile_avoidance,
        )

    parameter_grids = next_payload.get("parameter_grids")
    if isinstance(parameter_grids, dict):
        if narrow_parameter_grids:
            next_payload["parameter_grids"] = refine_parameter_grids(
                parameter_grids,
                parameter_hints,
                fragile_layers,
                approved_layer_names,
            )
        else:
            next_payload["parameter_grids"] = filter_parameter_grids(
                parameter_grids,
                fragile_layers,
                approved_layer_names,
            )

    apply_runtime_profile_hints(next_payload, runtime_profile_hints)

    regime_coverage_gaps = list(advisory_input.memory_summary.get("regime_coverage_gaps", []))
    validation_failures = list(advisory_input.memory_summary.get("validation_failures", []))
    failure_taxonomy_counts = _coerce_count_mapping(advisory_input.memory_summary.get("failure_taxonomy_counts"))
    next_hypotheses = _coerce_str_list(advisory_input.memory_summary.get("next_hypotheses"))
    stop_reason = advisory_input.memory_summary.get("stop_reason")
    if not isinstance(stop_reason, str) or not stop_reason:
        stop_reason = None
    duplicate_baseline_run_id = _resolve_duplicate_baseline_run_id(
        advisory_input.memory_summary,
        duplicate_baseline_history,
    )
    next_payload["research_hypotheses"] = {
        "promising_layers": list(advisory_input.memory_summary.get("promising_layers", [])),
        "fragile_layers": list(advisory_input.memory_summary.get("fragile_layers", [])),
        "top_duplicate_matches": list(advisory_input.memory_summary.get("top_duplicate_matches", [])),
        "scenario_profiles": list(advisory_input.memory_summary.get("scenario_profiles", [])),
        "scenario_profile_hints": scenario_profile_hints,
        "scenario_profile_avoidance": scenario_profile_avoidance,
        "runtime_profile_hints": runtime_profile_hints,
        "parameter_hints": parameter_hints,
        "regime_conditioning": {
            "target_state": target_regime_state,
            "matched_state_key": target_regime_state.get("regime_state_key"),
            "used_regime_parameter_hints": bool(
                target_regime_state.get("regime_state_key")
                in advisory_input.memory_summary.get("regime_parameter_hints", {})
                if isinstance(advisory_input.memory_summary.get("regime_parameter_hints"), dict)
                else False
            ),
        },
        "validation_failures": validation_failures,
        "failure_taxonomy_counts": failure_taxonomy_counts,
        "next_hypotheses": next_hypotheses,
        "stop_reason": stop_reason,
        "regime_coverage_gaps": regime_coverage_gaps,
        "duplicate_baseline_history": dict(duplicate_baseline_history),
    }
    next_payload["scenario_profile_avoidance"] = scenario_profile_avoidance
    next_payload["parameter_avoidance"] = build_parameter_avoidance(parameter_hints)

    lineage = next_payload.get("research_lineage")
    if not isinstance(lineage, dict):
        lineage = {}
    lineage["selected_variant"] = variant_name
    next_payload["research_lineage"] = lineage
    next_payload["research_variant"] = build_variant_metadata(variant_name)
    apply_variant_runtime(next_payload, variant_name)
    next_payload["advisory_context"] = {
        "study_schema_title": str(advisory_input.study_schema.get("title", "unknown")),
        "layer_catalog": approved_catalog,
        "duplicate_baseline_run_id": duplicate_baseline_run_id,
        "agent_environment": {
            "skills": [dict(item) for item in advisory_input.skill_contracts if isinstance(item, dict)],
            "mcp": dict(advisory_input.mcp_environment),
            "loop_policy": _build_loop_policy_summary(advisory_input.loop_policy),
            "upstream_adaptation": _build_upstream_adaptation_context(advisory_input.memory_summary),
        },
    }
    next_payload["advisory_rationale"] = {
        "variant": variant_name,
        "summary": _build_advisory_summary(
            variant_name=variant_name,
            promising_layers=promising_layers,
            validation_failures=validation_failures,
            failure_taxonomy_counts=failure_taxonomy_counts,
            next_hypotheses=next_hypotheses,
            stop_reason=stop_reason,
            regime_coverage_gaps=regime_coverage_gaps,
        ),
        "constraints": [
            "approved layer catalog only",
            "no arbitrary indicator invention",
            "no runtime widening of approved parameter bounds",
            "promotion rules unchanged",
        ],
        "evidence": _build_advisory_evidence(
            advisory_input.memory_summary,
            duplicate_baseline_run_id=duplicate_baseline_run_id,
        ),
    }
    return next_payload


def build_advisory_variants(advisory_input: AdvisoryInput) -> dict[str, dict[str, object]]:
    return {
        "balanced": build_advisory_payload(
            advisory_input,
            variant_name="balanced",
            narrow_parameter_grids=True,
        ),
        "conservative": build_advisory_payload(
            advisory_input,
            variant_name="conservative",
            narrow_parameter_grids=True,
        ),
        "exploratory": build_advisory_payload(
            advisory_input,
            variant_name="exploratory",
            narrow_parameter_grids=False,
        ),
    }


def _merge_matching_regime_parameter_hints(
    parameter_hints: dict[str, dict[str, object]],
    memory_summary: dict[str, object],
    target_regime_state: dict[str, object],
) -> dict[str, dict[str, object]]:
    state_key = target_regime_state.get("regime_state_key")
    regime_parameter_hints = memory_summary.get("regime_parameter_hints", {})
    if not isinstance(state_key, str) or not isinstance(regime_parameter_hints, dict):
        return parameter_hints
    matched = regime_parameter_hints.get(state_key)
    if not isinstance(matched, dict):
        return parameter_hints
    matched_hints = matched.get("parameter_hints")
    if not isinstance(matched_hints, dict):
        return parameter_hints
    merged = {
        layer_name: dict(layer_hints)
        for layer_name, layer_hints in parameter_hints.items()
        if isinstance(layer_name, str) and isinstance(layer_hints, dict)
    }
    for layer_name, layer_hints in matched_hints.items():
        if not isinstance(layer_name, str) or not isinstance(layer_hints, dict):
            continue
        existing = merged.setdefault(layer_name, {})
        for parameter_name, hint in layer_hints.items():
            if isinstance(parameter_name, str) and isinstance(hint, dict):
                current_hint = existing.get(parameter_name)
                if isinstance(current_hint, dict) and not _is_regime_hint_stronger(hint, current_hint):
                    continue
                regime_hint = dict(hint)
                regime_hint["regime_conditioned"] = True
                existing[parameter_name] = regime_hint
    return merged


def _is_regime_hint_stronger(
    regime_hint: dict[str, object],
    current_hint: dict[str, object],
) -> bool:
    confidence_rank = {"low": 1, "medium": 2, "high": 3}
    regime_confidence = confidence_rank.get(str(regime_hint.get("confidence")), 0)
    current_confidence = confidence_rank.get(str(current_hint.get("confidence")), 0)
    regime_count = regime_hint.get("promoted_count", 0)
    current_count = current_hint.get("promoted_count", 0)
    if not isinstance(regime_count, int | float) or isinstance(regime_count, bool):
        regime_count = 0
    if not isinstance(current_count, int | float) or isinstance(current_count, bool):
        current_count = 0
    return (regime_confidence, float(regime_count)) >= (current_confidence, float(current_count))


def _derive_payload_regime_state(snapshot_payload: object) -> dict[str, object]:
    if not isinstance(snapshot_payload, dict):
        return {
            "dominant_regime": "unknown",
            "funding_bucket": "flat",
            "volatility_bucket": "low",
            "open_interest_bucket": "flat",
            "regime_state_key": "unknown|flat|low|flat",
        }
    candles = snapshot_payload.get("candles", [])
    closes: list[float] = []
    if isinstance(candles, list):
        for candle in candles:
            if not isinstance(candle, dict):
                continue
            close = candle.get("close")
            if isinstance(close, int | float) and not isinstance(close, bool):
                closes.append(float(close))
    funding_values = _coerce_float_list(snapshot_payload.get("funding_rates"))
    open_interest = _coerce_float_list(snapshot_payload.get("open_interest"))
    avg_funding = sum(funding_values) / len(funding_values) if funding_values else 0.0
    returns = [
        (closes[index] / closes[index - 1]) - 1.0
        for index in range(1, len(closes))
        if closes[index - 1] != 0.0
    ]
    realized_vol = _stddev(returns)
    oi_change = 0.0
    if len(open_interest) >= 2 and open_interest[0] != 0.0:
        oi_change = (open_interest[-1] / open_interest[0]) - 1.0
    dominant_regime = _dominant_payload_regime(snapshot_payload, realized_vol, avg_funding, oi_change)
    funding_bucket = _bucket_funding(avg_funding)
    volatility_bucket = _bucket_volatility(realized_vol)
    open_interest_bucket = _bucket_open_interest(oi_change)
    return {
        "dominant_regime": dominant_regime,
        "funding_bucket": funding_bucket,
        "volatility_bucket": volatility_bucket,
        "open_interest_bucket": open_interest_bucket,
        "average_funding_rate": round(avg_funding, 10),
        "realized_volatility": round(realized_vol, 10),
        "open_interest_change": round(oi_change, 10),
        "regime_state_key": f"{dominant_regime}|{funding_bucket}|{volatility_bucket}|{open_interest_bucket}",
    }


def _dominant_payload_regime(
    snapshot_payload: dict[str, object],
    realized_vol: float,
    avg_funding: float,
    oi_change: float,
) -> str:
    regime_ids = snapshot_payload.get("regime_id")
    if isinstance(regime_ids, list) and regime_ids:
        counts: dict[str, int] = {}
        for item in regime_ids:
            if isinstance(item, str) and item:
                counts[item] = counts.get(item, 0) + 1
        if counts:
            return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    if realized_vol >= 0.04 and avg_funding < 0:
        return "crash"
    if oi_change >= 0.10 and avg_funding > 0:
        return "short_squeeze"
    if abs(avg_funding) >= 0.01 or abs(oi_change) >= 0.15:
        return "liquidity_stress"
    return "sideways"


def _coerce_float_list(raw: object) -> list[float]:
    if not isinstance(raw, list):
        return []
    values: list[float] = []
    for item in raw:
        if isinstance(item, int | float) and not isinstance(item, bool):
            values.append(float(item))
    return values


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / len(values)
    return (sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def _bucket_funding(value: float) -> str:
    if value >= 0.01:
        return "positive_extreme"
    if value >= 0.001:
        return "positive"
    if value <= -0.01:
        return "negative_extreme"
    if value <= -0.001:
        return "negative"
    return "flat"


def _bucket_volatility(value: float) -> str:
    if value >= 0.04:
        return "high"
    if value >= 0.015:
        return "medium"
    return "low"


def _bucket_open_interest(value: float) -> str:
    if value >= 0.15:
        return "rising_fast"
    if value >= 0.03:
        return "rising"
    if value <= -0.15:
        return "falling_fast"
    if value <= -0.03:
        return "falling"
    return "flat"


def _resolve_duplicate_baseline_run_id(
    memory_summary: dict[str, object],
    duplicate_baseline_history: dict[str, object],
) -> str | None:
    baseline_run_id = duplicate_baseline_history.get("duplicate_baseline_run_id")
    if isinstance(baseline_run_id, str) and baseline_run_id:
        return baseline_run_id
    top_duplicate_matches = memory_summary.get("top_duplicate_matches", [])
    if not isinstance(top_duplicate_matches, list) or not top_duplicate_matches:
        return None
    first = top_duplicate_matches[0]
    if isinstance(first, dict) and isinstance(first.get("run_id"), str):
        return str(first["run_id"])
    return None


def _build_advisory_summary(
    *,
    variant_name: str,
    promising_layers: list[str],
    validation_failures: list[object],
    failure_taxonomy_counts: dict[str, int],
    next_hypotheses: list[str],
    stop_reason: str | None,
    regime_coverage_gaps: list[object],
) -> str:
    fragments = [f"{variant_name} bounded advisory proposal"]
    if promising_layers:
        fragments.append(f"promotes {promising_layers[0]} from prior evidence")
    if validation_failures:
        first = validation_failures[0]
        if isinstance(first, dict) and isinstance(first.get("gate_name"), str):
            fragments.append(f"avoids recent {first['gate_name']} failures")
    if regime_coverage_gaps:
        first = regime_coverage_gaps[0]
        if isinstance(first, dict) and isinstance(first.get("regime_label"), str):
            fragments.append(f"keeps focus on the {first['regime_label']} coverage gap")
    top_taxonomy = _top_failure_taxonomy(failure_taxonomy_counts)
    if top_taxonomy is not None:
        fragments.append(f"responds to repeated {top_taxonomy['label']} signals")
    if stop_reason:
        fragments.append(f"respects stop reason {stop_reason}")
    if next_hypotheses:
        fragments.append(f"next action {next_hypotheses[0]}")
    return "; ".join(fragments)


def _build_advisory_evidence(
    memory_summary: dict[str, object],
    *,
    duplicate_baseline_run_id: str | None,
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    promising_layers = memory_summary.get("promising_layers", [])
    if isinstance(promising_layers, list) and promising_layers:
        first = promising_layers[0]
        if isinstance(first, dict):
            evidence.append({"type": "promising_layer", **dict(first)})
    validation_failures = memory_summary.get("validation_failures", [])
    if isinstance(validation_failures, list) and validation_failures:
        first = validation_failures[0]
        if isinstance(first, dict):
            evidence.append({"type": "validation_failure", **dict(first)})
    failure_taxonomy_counts = _coerce_count_mapping(memory_summary.get("failure_taxonomy_counts"))
    top_taxonomy = _top_failure_taxonomy(failure_taxonomy_counts)
    if top_taxonomy is not None:
        evidence.append({"type": "failure_taxonomy", **top_taxonomy})
    stop_reason = memory_summary.get("stop_reason")
    if isinstance(stop_reason, str) and stop_reason:
        evidence.append({"type": "stop_reason", "value": stop_reason})
    next_hypotheses = _coerce_str_list(memory_summary.get("next_hypotheses"))
    if next_hypotheses:
        evidence.append({"type": "next_hypothesis", "value": next_hypotheses[0]})
    regime_coverage_gaps = memory_summary.get("regime_coverage_gaps", [])
    if isinstance(regime_coverage_gaps, list) and regime_coverage_gaps:
        first = regime_coverage_gaps[0]
        if isinstance(first, dict):
            evidence.append({"type": "regime_coverage_gap", **dict(first)})
    upstream_adaptation_summary = memory_summary.get("upstream_adaptation_summary")
    if isinstance(upstream_adaptation_summary, dict):
        linked_resources = upstream_adaptation_summary.get("linked_resources", [])
        if isinstance(linked_resources, list):
            for item in linked_resources:
                if isinstance(item, dict):
                    evidence.append({"type": "upstream_resource", **dict(item)})
    upstream_governance = memory_summary.get("upstream_governance")
    if isinstance(upstream_governance, dict) and upstream_governance:
        evidence.append({"type": "upstream_governance", **dict(upstream_governance)})
    if duplicate_baseline_run_id:
        evidence.append({"type": "duplicate_baseline", "run_id": duplicate_baseline_run_id})
    return evidence


def _build_upstream_adaptation_context(memory_summary: dict[str, object]) -> dict[str, object]:
    summary = memory_summary.get("upstream_adaptation_summary")
    if not isinstance(summary, dict):
        return {
            "linked_resource_count": 0,
            "blocked_resource_count": 0,
            "provenance_gap_count": 0,
            "linked_resources": [],
        }
    linked_resources = summary.get("linked_resources", [])
    return {
        "linked_resource_count": int(summary.get("linked_resource_count", 0) or 0),
        "blocked_resource_count": int(summary.get("blocked_resource_count", 0) or 0),
        "provenance_gap_count": int(summary.get("provenance_gap_count", 0) or 0),
        "linked_resources": [dict(item) for item in linked_resources if isinstance(item, dict)],
    }


def _build_loop_policy_summary(loop_policy: dict[str, object]) -> dict[str, object]:
    summary = {
        "default_mode": "auto",
        "recommended_mode_for_payload": "bounded",
        "bounded_when": "Use bounded for standard study payloads that need full validation, memory, and promotion gates.",
        "karpathy_when": "Use karpathy for one-target python_source program iteration driven by a scalar experiment metric.",
    }
    if isinstance(loop_policy, dict):
        for key in ("default_mode", "recommended_mode_for_payload", "bounded_when", "karpathy_when"):
            value = loop_policy.get(key)
            if isinstance(value, str) and value:
                summary[key] = value
    return summary


def _coerce_str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str)]


def _coerce_count_mapping(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int | float):
            continue
        counts[key] = int(value)
    return counts


def _top_failure_taxonomy(failure_taxonomy_counts: dict[str, int]) -> dict[str, object] | None:
    if not failure_taxonomy_counts:
        return None
    label, count = sorted(
        failure_taxonomy_counts.items(),
        key=lambda item: (-int(item[1]), item[0]),
    )[0]
    return {"label": label, "count": int(count)}
