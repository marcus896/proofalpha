from __future__ import annotations

import json
from pathlib import Path

from engine.validation.bundle import normalize_validation_bundle


def load_dashboard_payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_batch_report_payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_autoresearch_report_payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_campaign_report_payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_dashboard_summary(
    payload: dict[str, object],
    phase_filter: str = "accepted",
    top_candidates: int | None = None,
) -> str:
    lines: list[str] = []
    run_id = str(payload.get("run_id", "unknown"))
    decision = str(payload.get("decision", "unknown"))
    strategy = payload.get("strategy", {})
    metrics = payload.get("metrics", {})
    holdout = payload.get("holdout", {})
    phases = payload.get("phases", [])

    backbone = "unknown"
    if isinstance(strategy, dict):
        backbone = str(strategy.get("backbone", "unknown"))

    lines.append(f"Run {run_id}")
    lines.append(f"Status: {decision}")
    lines.append(f"Backbone: {backbone}")
    if isinstance(metrics, dict):
        sharpe = metrics.get("selection_oos_sharpe")
        net_pnl = metrics.get("selection_oos_net_pnl")
        if sharpe is not None:
            lines.append(f"Selection OOS Sharpe: {sharpe}")
        if net_pnl is not None:
            lines.append(f"Selection OOS Net PnL: {net_pnl}")
    if isinstance(holdout, dict) and holdout:
        lines.append(f"Holdout: {holdout.get('decision', 'unknown')}")
    validation_protocol = payload.get("validation_protocol", {})
    if isinstance(validation_protocol, dict) and validation_protocol:
        validation_bundle = normalize_validation_bundle(validation_protocol)
        lines.append(f"Validation: {validation_bundle.get('status', 'unknown')}")
        dsr = validation_bundle.get("deflated_sharpe_ratio")
        psr = validation_bundle.get("probabilistic_sharpe_ratio")
        pbo = validation_bundle.get("pbo_score")
        spa_pvalue = validation_bundle.get("spa_pvalue")
        if dsr is not None:
            lines.append(f"Deflated Sharpe Ratio: {dsr}")
        if psr is not None:
            lines.append(f"Probabilistic Sharpe Ratio: {psr}")
        if pbo is not None:
            lines.append(f"PBO: {pbo}")
        if spa_pvalue is not None:
            lines.append(f"SPA p-value: {spa_pvalue}")
        failed_gates = validation_bundle.get("failed_gates", [])
        if failed_gates:
            lines.append(f"Failed gates: {', '.join(failed_gates)}")
    runtime_settings = payload.get("runtime_settings", {})
    if isinstance(runtime_settings, dict) and runtime_settings:
        lines.append(f"Runtime settings: {_format_parameters(runtime_settings)}")
    execution_pressure = payload.get("selection_oos_execution_pressure", {})
    if isinstance(execution_pressure, dict) and execution_pressure:
        lines.append(f"Execution pressure: {_format_parameters(execution_pressure)}")
    snapshot_quality = payload.get("snapshot_quality", {})
    if isinstance(snapshot_quality, dict) and snapshot_quality:
        quality_line = f"Snapshot quality: {snapshot_quality.get('status', 'unknown')}"
        quality_report = snapshot_quality.get("report", {})
        if isinstance(quality_report, dict) and quality_report:
            quality_bits: list[str] = []
            if "quality_score" in quality_report:
                quality_bits.append(f"quality_score={quality_report.get('quality_score')}")
            if "passed" in quality_report:
                quality_bits.append(f"passed={quality_report.get('passed')}")
            if quality_bits:
                quality_line += " | " + ", ".join(quality_bits)
        lines.append(quality_line)
    snapshot_provenance = payload.get("snapshot_provenance", {})
    if isinstance(snapshot_provenance, dict) and snapshot_provenance:
        build_version = snapshot_provenance.get("build_version")
        if isinstance(build_version, str) and build_version:
            lines.append(f"Snapshot build: {build_version}")
        source_hash = snapshot_provenance.get("source_hash")
        if isinstance(source_hash, str) and source_hash:
            lines.append(f"Snapshot source hash: {source_hash}")
    scenario_profiles = payload.get("scenario_profiles", {})
    if isinstance(scenario_profiles, dict) and scenario_profiles:
        lines.append("Scenario profiles:")
        for scenario_name in sorted(scenario_profiles):
            profile = scenario_profiles[scenario_name]
            if not isinstance(profile, dict):
                continue
            lines.append(f"- {scenario_name}: {_format_parameters(profile)}")
    stress_metrics = payload.get("stress_liquidity_metrics", {})
    if isinstance(stress_metrics, dict) and stress_metrics:
        lines.append(f"Stress metrics: {_format_parameters(stress_metrics)}")
    regime_scenario_pass_matrix = payload.get("regime_scenario_pass_matrix", {})
    if isinstance(regime_scenario_pass_matrix, dict) and regime_scenario_pass_matrix:
        lines.append(f"Regime/scenario matrix: {_format_parameters(regime_scenario_pass_matrix)}")
    agent_loop_metadata = payload.get("agent_loop_metadata")
    if isinstance(agent_loop_metadata, dict) and agent_loop_metadata:
        loop_id = agent_loop_metadata.get("loop_id", "unknown")
        iteration = agent_loop_metadata.get("iteration", "?")
        stop_reason = agent_loop_metadata.get("stop_reason", "unknown")
        lines.append(f"Agent loop: {loop_id} | iteration={iteration} | stop={stop_reason}")
        requested_loop_mode = agent_loop_metadata.get("requested_loop_mode")
        effective_loop_mode = agent_loop_metadata.get("effective_loop_mode")
        loop_mode_selection_reason = agent_loop_metadata.get("loop_mode_selection_reason")
        if isinstance(effective_loop_mode, str) and effective_loop_mode:
            requested_label = (
                str(requested_loop_mode)
                if isinstance(requested_loop_mode, str) and requested_loop_mode
                else "unknown"
            )
            reason_label = (
                str(loop_mode_selection_reason)
                if isinstance(loop_mode_selection_reason, str) and loop_mode_selection_reason
                else "unknown"
            )
            lines.append(
                f"Loop mode: requested={requested_label} | effective={effective_loop_mode} | reason={reason_label}"
            )
        rendered_taxonomy = _format_failure_taxonomy_counts(agent_loop_metadata.get("failure_taxonomy_counts"))
        if rendered_taxonomy != "none":
            lines.append(f"Loop pressure: {rendered_taxonomy}")
        next_hypotheses = agent_loop_metadata.get("next_hypotheses")
        if isinstance(next_hypotheses, list):
            rendered_hypotheses = [str(item) for item in next_hypotheses if isinstance(item, str) and item]
            if rendered_hypotheses:
                lines.append(f"Next actions: {', '.join(rendered_hypotheses)}")
        upstream_adaptation = agent_loop_metadata.get("upstream_adaptation_summary")
        if isinstance(upstream_adaptation, dict) and upstream_adaptation:
            linked_count = int(upstream_adaptation.get("linked_resource_count", 0) or 0)
            blocked_count = int(upstream_adaptation.get("blocked_resource_count", 0) or 0)
            gap_count = int(upstream_adaptation.get("provenance_gap_count", 0) or 0)
            lines.append(
                f"Upstream adaptation: linked={linked_count} | blocked={blocked_count} | provenance_gaps={gap_count}"
            )
            linked_resources = upstream_adaptation.get("linked_resources", [])
            if isinstance(linked_resources, list) and linked_resources:
                rendered_resources: list[str] = []
                for item in linked_resources[:3]:
                    if not isinstance(item, dict):
                        continue
                    resource_id = item.get("resource_id")
                    intended_usage = item.get("intended_usage")
                    status = item.get("status")
                    if isinstance(resource_id, str) and isinstance(intended_usage, str) and isinstance(status, str):
                        rendered_resources.append(f"{resource_id}({intended_usage}, {status})")
                if rendered_resources:
                    lines.append(f"Upstream resources: {', '.join(rendered_resources)}")
    research_program_version = payload.get("research_program_version")
    if isinstance(research_program_version, str) and research_program_version:
        lines.append(f"Program: {research_program_version}")

    phase_rows = []
    if isinstance(phases, list):
        phase_rows = [
            phase
            for phase in phases
            if isinstance(phase, dict) and _matches_phase_filter(phase, phase_filter)
        ]

    if not phase_rows:
        lines.append(f"{_section_label(phase_filter)}: none")
        return "\n".join(lines)

    lines.append(f"{_section_label(phase_filter)}:")
    for phase in phase_rows:
        layer_name = str(phase.get("layer_name", "unknown"))
        phase_name = str(phase.get("phase_name", "unknown"))
        oos_sharpe = phase.get("oos_sharpe")
        permutation_count = phase.get("permutation_count", 1)
        selected_parameters = phase.get("selected_parameters", {})
        decision_label = str(phase.get("decision", "unknown"))
        lines.append(
            f"- {phase_name} {layer_name} | decision={decision_label} | oos_sharpe={oos_sharpe} | permutations={permutation_count} | selected={_format_parameters(selected_parameters)}"
        )

        search_summary = phase.get("search_summary", [])
        if isinstance(search_summary, list):
            candidates = search_summary[:top_candidates] if top_candidates is not None else search_summary
            for index, candidate in enumerate(candidates, start=1):
                if not isinstance(candidate, dict):
                    continue
                lines.append(
                    "  "
                    + f"{index}. {candidate.get('decision', 'unknown')} | "
                    + f"oos_sharpe={candidate.get('oos_sharpe', 'n/a')} | "
                    + f"params={_format_parameters(candidate.get('parameters', {}))}"
                    + (
                        f" | execution_pressure={_format_parameters(candidate.get('execution_pressure_summary', {}))}"
                        if isinstance(candidate.get("execution_pressure_summary"), dict)
                        and candidate.get("execution_pressure_summary")
                        else ""
                    )
                )
    return "\n".join(lines)


def build_study_summary(study) -> str:
    snapshot = study.snapshot
    total_candles = len(snapshot.candles)
    quality_report = snapshot.quality_report
    provenance = snapshot.provenance if isinstance(snapshot.provenance, dict) else {}
    lines = [
        f"Study: {study.run_id}",
        f"Runtime mode: {study.runtime_mode}",
        f"Snapshot: {snapshot.snapshot_id}",
        f"Market: {snapshot.symbol} @ {snapshot.venue} ({snapshot.timeframe})",
        f"Candles: {total_candles}",
        f"Funding coverage: {_format_sidecar_coverage(snapshot, 'funding_rate', total_candles)}",
        f"Open interest coverage: {_format_sidecar_coverage(snapshot, 'open_interest', total_candles)}",
        f"Liquidation coverage: {_format_sidecar_coverage(snapshot, 'liquidation_notional', total_candles)}",
    ]

    if quality_report is not None:
        lines.append(
            f"Quality report: {'passed' if quality_report.passed else 'failed'} | score={quality_report.quality_score:.3f}"
        )
        candle_span = _format_candle_span(quality_report.metrics if isinstance(quality_report.metrics, dict) else {})
        if candle_span is not None:
            lines.append(f"Candle span: {candle_span}")
    build_version = provenance.get("build_version")
    if isinstance(build_version, str) and build_version:
        lines.append(f"Build version: {build_version}")
    source_hash = provenance.get("source_hash")
    if isinstance(source_hash, str) and source_hash:
        lines.append(f"Source hash: {source_hash}")

    if snapshot.quality_flags:
        lines.append("Quality flags:")
        for flag in snapshot.quality_flags:
            lines.append(f"- {flag}")
    else:
        lines.append("Quality flags: none")
    return "\n".join(lines)

def build_campaign_summary(payload: dict[str, object]) -> str:
    lines: list[str] = []
    campaign_id = str(payload.get("campaign_id", "unknown"))
    status = str(payload.get("status", "unknown"))
    entries = payload.get("entries", [])
    log_path = payload.get("log_path")

    lines.append(f"Campaign {campaign_id}")
    lines.append(f"Status: {status}")
    lines.append(f"Entries: {len(entries) if isinstance(entries, list) else 0}")
    lines.append(f"Completed entries: {payload.get('completed_entries', 0)}")
    lines.append(f"Failed entries: {payload.get('failed_entries', 0)}")
    if isinstance(log_path, str) and log_path:
        lines.append(f"Campaign log: {log_path}")

    if not isinstance(entries, list) or not entries:
        lines.append("Entries detail: none")
        return "\n".join(lines)

    lines.append("Entries detail:")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "unknown"))
        command = str(entry.get("command", "unknown"))
        entry_status = str(entry.get("status", "unknown"))
        lines.append(f"- {name} | {command} | {entry_status}")
        log_path = entry.get("log_path")
        if isinstance(log_path, str) and log_path:
            lines.append(f"  Log: {log_path}")
        error = entry.get("error")
        if isinstance(error, str) and error:
            lines.append(f"  Error: {error}")
    return "\n".join(lines)


def build_campaign_manifest_summary(payload: dict[str, object]) -> str:
    lines: list[str] = []
    campaign_id = str(payload.get("campaign_id", "unknown"))
    entries = payload.get("entries", [])
    defaults = payload.get("defaults", {})

    lines.append(f"Campaign {campaign_id}")
    lines.append(f"Expanded entries: {len(entries) if isinstance(entries, list) else 0}")
    if isinstance(defaults, dict) and defaults:
        lines.append(f"Defaults: {_format_parameters(defaults)}")

    if not isinstance(entries, list) or not entries:
        lines.append("Entries: none")
        return "\n".join(lines)

    lines.append("Entries:")
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        lines.append(
            f"{index}. {entry.get('name', 'unknown')} | {entry.get('command', 'unknown')} | output_dir={entry.get('output_dir', 'unknown')}"
        )
    return "\n".join(lines)


def build_batch_summary(payload: dict[str, object], top_variants: int | None = None) -> str:
    lines: list[str] = []
    run_id = str(payload.get("run_id", "unknown"))
    status = str(payload.get("status", "unknown"))
    accepted_duplicate_config_path = payload.get("accepted_duplicate_config_path")
    duplicate_baseline_run_id = payload.get("duplicate_baseline_run_id")
    preferred_variant = payload.get("preferred_variant", {})
    base_run = payload.get("base_run", {})
    variant_results = payload.get("variant_results", [])

    lines.append(f"Batch run {run_id}")
    lines.append(f"Status: {status}")
    if isinstance(accepted_duplicate_config_path, str) and accepted_duplicate_config_path:
        lines.append(f"Accepted duplicate config: {accepted_duplicate_config_path}")
    if isinstance(duplicate_baseline_run_id, str) and duplicate_baseline_run_id:
        lines.append(f"Duplicate baseline: {duplicate_baseline_run_id}")

    if isinstance(base_run, dict):
        base_run_id = str(base_run.get("run_id", "unknown"))
        base_status = str(base_run.get("status", "unknown"))
        lines.append(f"Base run: {base_run_id} ({base_status})")
        metrics = base_run.get("metrics", {})
        if isinstance(metrics, dict):
            base_sharpe = metrics.get("selection_oos_sharpe")
            base_drawdown = metrics.get("selection_oos_drawdown")
            if base_sharpe is not None or base_drawdown is not None:
                lines.append(
                    f"Base metrics: sharpe={base_sharpe if base_sharpe is not None else 'n/a'} | drawdown={base_drawdown if base_drawdown is not None else 'n/a'}"
                )
        base_loop_metadata = base_run.get("agent_loop_metadata")
        if isinstance(base_loop_metadata, dict) and base_loop_metadata:
            rendered_taxonomy = _format_failure_taxonomy_counts(base_loop_metadata.get("failure_taxonomy_counts"))
            if rendered_taxonomy != "none":
                lines.append(f"Base loop pressure: {rendered_taxonomy}")
            next_hypotheses = base_loop_metadata.get("next_hypotheses")
            if isinstance(next_hypotheses, list):
                rendered_hypotheses = [str(item) for item in next_hypotheses if isinstance(item, str) and item]
                if rendered_hypotheses:
                    lines.append(f"Base next actions: {', '.join(rendered_hypotheses)}")

    if isinstance(preferred_variant, dict) and preferred_variant:
        lines.append(
            f"Preferred variant: {preferred_variant.get('variant', 'unknown')} | status={preferred_variant.get('status', 'unknown')} | sharpe={preferred_variant.get('selection_oos_sharpe', 'n/a')}"
        )
        preferred_loop_metadata = preferred_variant.get("agent_loop_metadata")
        if isinstance(preferred_loop_metadata, dict) and preferred_loop_metadata:
            rendered_taxonomy = _format_failure_taxonomy_counts(preferred_loop_metadata.get("failure_taxonomy_counts"))
            if rendered_taxonomy != "none":
                lines.append(f"Preferred loop pressure: {rendered_taxonomy}")
            next_hypotheses = preferred_loop_metadata.get("next_hypotheses")
            if isinstance(next_hypotheses, list):
                rendered_hypotheses = [str(item) for item in next_hypotheses if isinstance(item, str) and item]
                if rendered_hypotheses:
                    lines.append(f"Preferred next actions: {', '.join(rendered_hypotheses)}")
        preferred_history = preferred_variant.get("duplicate_baseline_history", {})
        preferred_score: float | None = None
        if isinstance(preferred_history, dict) and preferred_history:
            lines.append(f"Preferred history: {_format_duplicate_history(preferred_history)}")
            preferred_score = _compute_duplicate_baseline_score(preferred_history)
            if preferred_score is not None:
                lines.append(f"Preferred duplicate baseline score: {preferred_score:.2f}")
            top_scenario_profile = _format_top_scenario_profile(preferred_history.get("scenario_profile_hints"))
            if top_scenario_profile != "none":
                lines.append(f"Preferred top scenario profile: {top_scenario_profile}")
            top_fragile_profile = _format_top_scenario_profile(preferred_history.get("scenario_profile_avoidance"))
            if top_fragile_profile != "none":
                lines.append(f"Preferred top fragile profile: {top_fragile_profile}")
            top_runtime_profile = _format_top_runtime_profile(preferred_history.get("runtime_profile_hints"))
            if top_runtime_profile != "none":
                lines.append(f"Preferred top runtime profile: {top_runtime_profile}")
    else:
        preferred_score = None

    if not isinstance(variant_results, list) or not variant_results:
        lines.append("Variants: none")
        return "\n".join(lines)

    rows = variant_results[:top_variants] if top_variants is not None else variant_results
    lines.append("Variants:")
    for index, result in enumerate(rows, start=1):
        if not isinstance(result, dict):
            continue
        lines.append(
            f"- {index}. {result.get('variant', 'unknown')} | status={result.get('status', 'unknown')} | sharpe={result.get('selection_oos_sharpe', 'n/a')} | pass_rate={result.get('scenario_pass_rate', 'n/a')}"
        )
        loop_metadata = result.get("agent_loop_metadata")
        if isinstance(loop_metadata, dict) and loop_metadata:
            rendered_taxonomy = _format_failure_taxonomy_counts(loop_metadata.get("failure_taxonomy_counts"))
            if rendered_taxonomy != "none":
                lines.append(f"  Loop pressure: {rendered_taxonomy}")
            next_hypotheses = loop_metadata.get("next_hypotheses")
            if isinstance(next_hypotheses, list):
                rendered_hypotheses = [str(item) for item in next_hypotheses if isinstance(item, str) and item]
                if rendered_hypotheses:
                    lines.append(f"  Next actions: {', '.join(rendered_hypotheses)}")
        duplicate_history = result.get("duplicate_baseline_history", {})
        if isinstance(duplicate_history, dict) and duplicate_history:
            lines.append(f"  History vs baseline: {_format_duplicate_history(duplicate_history)}")
            top_scenario_profile = _format_top_scenario_profile(duplicate_history.get("scenario_profile_hints"))
            if top_scenario_profile != "none":
                lines.append(f"  History scenario profile: {top_scenario_profile}")
            top_fragile_profile = _format_top_scenario_profile(duplicate_history.get("scenario_profile_avoidance"))
            if top_fragile_profile != "none":
                lines.append(f"  History fragile profile: {top_fragile_profile}")
            top_runtime_profile = _format_top_runtime_profile(duplicate_history.get("runtime_profile_hints"))
            if top_runtime_profile != "none":
                lines.append(f"  History runtime profile: {top_runtime_profile}")
            history_score = _compute_duplicate_baseline_score(duplicate_history)
            if history_score is not None:
                lines.append(f"  History score: {history_score:.2f}")
                if preferred_score is not None:
                    lines.append(f"  History delta vs preferred: {history_score - preferred_score:+.2f}")
        compare_to_base = result.get("compare_to_base", {})
        if isinstance(compare_to_base, dict):
            metric_deltas = compare_to_base.get("metric_deltas", {})
            if isinstance(metric_deltas, dict) and metric_deltas:
                lines.append(f"  Delta vs base: {_format_metric_deltas(metric_deltas)}")
    return "\n".join(lines)


def build_autoresearch_summary(payload: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"Autoresearch {payload.get('run_id', 'unknown')}")
    lines.append(f"Status: {payload.get('status', 'unknown')}")

    skip_reason = payload.get("skip_reason")
    if skip_reason:
        lines.append(f"Skip reason: {skip_reason}")

    accepted_duplicate_config_path = payload.get("accepted_duplicate_config_path")
    if isinstance(accepted_duplicate_config_path, str) and accepted_duplicate_config_path:
        lines.append(f"Accepted duplicate config: {accepted_duplicate_config_path}")

    duplicate_match = payload.get("duplicate_match", {})
    if isinstance(duplicate_match, dict) and duplicate_match:
        lines.append(
            "Duplicate match: "
            + f"{duplicate_match.get('match_type', 'unknown')} -> {duplicate_match.get('run_id', 'unknown')}"
        )

    memory_summary = payload.get("memory_summary", {})
    if isinstance(memory_summary, dict) and memory_summary:
        lines.append(
            "Memory: "
            + f"prior_runs={memory_summary.get('prior_runs', 0)}"
            + f" | promoted={memory_summary.get('promoted_runs', 0)}"
            + f" | blocked={memory_summary.get('blocked_runs', 0)}"
            + f" | excluded_dirty={memory_summary.get('excluded_dirty_runs', 0)}"
        )
        lines.append(
            "Recovered duplicates: "
            + f"{memory_summary.get('recovered_duplicate_runs', 0)}"
            + " | top_matches="
            + _format_ranked_items(memory_summary.get("top_duplicate_matches", []), key_name="run_id")
        )
        top_scenario_profile = _format_top_scenario_profile(memory_summary.get("scenario_profile_hints"))
        if top_scenario_profile != "none":
            lines.append(f"Top scenario profile: {top_scenario_profile}")
        top_runtime_profile = _format_top_runtime_profile(memory_summary.get("runtime_profile_hints"))
        if top_runtime_profile != "none":
            lines.append(f"Top runtime profile: {top_runtime_profile}")
        top_fragile_profile = _format_top_scenario_profile(memory_summary.get("scenario_profile_avoidance"))
        if top_fragile_profile != "none":
            lines.append(f"Top fragile profile: {top_fragile_profile}")
        top_loop_pressure = _format_ranked_items(
            memory_summary.get("loop_failure_taxonomy_counts", []),
            key_name="taxonomy_label",
        )
        if top_loop_pressure != "none":
            lines.append(f"Loop pressure: {top_loop_pressure}")
        top_next_actions = _format_ranked_items(memory_summary.get("next_actions", []), key_name="action")
        if top_next_actions != "none":
            lines.append(f"Top next actions: {top_next_actions}")

    research_lineage = payload.get("research_lineage", {})
    if isinstance(research_lineage, dict) and research_lineage:
        selection_variant_result = research_lineage.get("selection_variant_result", {})
        if isinstance(selection_variant_result, dict):
            duplicate_history = selection_variant_result.get("duplicate_baseline_history", {})
            if isinstance(duplicate_history, dict) and duplicate_history:
                selected_scenario_profile = _format_top_scenario_profile(
                    duplicate_history.get("scenario_profile_hints")
                )
                if selected_scenario_profile != "none":
                    lines.append(f"Selected scenario profile: {selected_scenario_profile}")
                selected_runtime_profile = _format_top_runtime_profile(
                    duplicate_history.get("runtime_profile_hints")
                )
                if selected_runtime_profile != "none":
                    lines.append(f"Selected runtime profile: {selected_runtime_profile}")
                selected_fragile_profile = _format_top_scenario_profile(
                    duplicate_history.get("scenario_profile_avoidance")
                )
                if selected_fragile_profile != "none":
                    lines.append(f"Selected fragile profile: {selected_fragile_profile}")

    hypotheses = payload.get("hypotheses", [])
    if isinstance(hypotheses, list) and hypotheses:
        lines.append("Hypotheses:")
        for hypothesis in hypotheses:
            if not isinstance(hypothesis, dict):
                continue
            hypothesis_type = hypothesis.get("type", "unknown")
            subject = hypothesis.get("layer_name")
            if not isinstance(subject, str):
                subject = hypothesis.get("scenario_name")
            if not isinstance(subject, str):
                subject = hypothesis.get("run_id", "unknown")
            count = hypothesis.get("count", "n/a")
            lines.append(f"- {hypothesis_type} {subject} (count={count})")
    else:
        lines.append("Hypotheses: none")

    return "\n".join(lines)


def _format_parameters(parameters: object) -> str:
    if not isinstance(parameters, dict) or not parameters:
        return "none"
    parts = [f"{key}={parameters[key]}" for key in sorted(parameters)]
    return ", ".join(parts)


def _format_failure_taxonomy_counts(raw: object) -> str:
    if not isinstance(raw, dict) or not raw:
        return "none"
    parts: list[tuple[str, int]] = []
    for key, value in raw.items():
        if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int | float):
            continue
        parts.append((key, int(value)))
    if not parts:
        return "none"
    parts.sort(key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{label}={count}" for label, count in parts)


def _matches_phase_filter(phase: dict[str, object], phase_filter: str) -> bool:
    if phase_filter == "all":
        return True
    accepted = bool(phase.get("accepted"))
    if phase_filter == "rejected":
        return not accepted
    return accepted


def _section_label(phase_filter: str) -> str:
    if phase_filter == "all":
        return "Phases"
    if phase_filter == "rejected":
        return "Rejected phases"
    return "Accepted layers"


def _format_metric_deltas(metric_deltas: dict[str, object]) -> str:
    parts: list[str] = []
    for key in sorted(metric_deltas):
        value = metric_deltas[key]
        if isinstance(value, int | float) and not isinstance(value, bool):
            parts.append(f"{key}={value:+.2f}")
    return ", ".join(parts) if parts else "none"


def _format_ranked_items(raw: object, key_name: str) -> str:
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


def _format_duplicate_history(history: dict[str, object]) -> str:
    rendered = (
        f"samples={history.get('sample_count', 0)}"
        + f" | promoted={history.get('promoted_count', 0)}"
        + f" | success_rate={history.get('success_rate', 0)}"
        + f" | average_sharpe={history.get('average_sharpe', 0)}"
    )
    avoidance_count = history.get("scenario_profile_avoidance_count")
    if isinstance(avoidance_count, int | float) and float(avoidance_count) > 0:
        rendered += f" | avoided_profiles={int(avoidance_count)}"
    return rendered


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


def _format_sidecar_coverage(snapshot, series_name: str, total_candles: int) -> str:
    quality_report = getattr(snapshot, "quality_report", None)
    metrics = getattr(quality_report, "metrics", None)
    coverage_key = f"{series_name}_coverage_ratio"
    if isinstance(metrics, dict):
        coverage_ratio = metrics.get(coverage_key)
        if isinstance(coverage_ratio, int | float) and not isinstance(coverage_ratio, bool):
            covered = round(float(coverage_ratio) * total_candles)
            coverage_pct = float(coverage_ratio) * 100.0
            return f"{covered}/{total_candles} ({coverage_pct:.1f}%)"
    if total_candles <= 0:
        return "0/0 (0.0%)"
    quality_flags = getattr(snapshot, "quality_flags", [])
    missing_count = _extract_quality_count(quality_flags, f"missing_{series_name}_count=")
    covered = max(0, total_candles - missing_count)
    coverage_pct = (covered / total_candles) * 100.0
    return f"{covered}/{total_candles} ({coverage_pct:.1f}%)"


def _format_candle_span(metrics: dict[str, object]) -> str | None:
    first_candle_ts = metrics.get("first_candle_ts")
    last_candle_ts = metrics.get("last_candle_ts")
    if not isinstance(first_candle_ts, str) or not first_candle_ts:
        return None
    if not isinstance(last_candle_ts, str) or not last_candle_ts:
        return None
    return f"{first_candle_ts} -> {last_candle_ts}"


def _extract_quality_count(quality_flags: list[str], prefix: str) -> int:
    for flag in quality_flags:
        if flag.startswith(prefix):
            try:
                return int(flag.split("=", 1)[1])
            except ValueError:
                return 0
    return 0
