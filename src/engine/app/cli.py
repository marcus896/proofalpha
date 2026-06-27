from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import replace
import json
import logging
from pathlib import Path
import sys


logger = logging.getLogger(__name__)

from engine import __version__
from engine.agent.controller import AgentLoopController, AgentLoopSettings
from engine.agent.paper_post_run import (
    PaperPostRunSummaryConfig,
    build_paper_post_run_summary,
    write_paper_post_run_summary_artifact,
)
from engine.agent.skills import SkillContract, find_skill_contract, load_repo_skill_contracts
from engine.agent.trace_audit import (
    build_controlled_trace_advisory,
    build_trace_audit_export,
    write_trace_advisory_notes,
    write_trace_audit_export,
)
from engine.agent.research_debate import build_report_only_research_debate, write_research_debate_report
from engine.app.campaigns import build_retry_campaign_manifest, expand_campaign_manifest
from engine.app.cli_commands.core import register_core_commands
from engine.app.cli_commands.data_forecast import register_data_forecast_commands
from engine.app.cli_commands.execution import register_execution_commands
from engine.app.cli_commands.mcp import register_mcp_commands
from engine.app.cli_commands.memory import register_memory_commands
from engine.app.cli_commands.paper import register_paper_commands
from engine.app.cli_commands.reports import register_report_commands
from engine.app.cli_commands.research import register_research_commands
from engine.app.cli_commands.skills import register_skill_commands
from engine.app.cli_commands.status import register_project_status_commands
from engine.app.config import RuntimeSettings, StudyConfig, build_study_signature_from_payload, load_study_config
from engine.app.data_collector import StrictDataCollectorSettings, run_strict_data_collector
from engine.app.guarded_loop import GuardedLoopCycleSettings, GuardedLoopRepeatSettings, run_guarded_loop_cycle, run_guarded_loop_repeat
from engine.app.operator_loop import OperateLoopSettings, run_operate_loop
from engine.app.loop_evidence import build_loop_evidence_ledger
from engine.app.loop_improvement import build_loop_improvement_gate
from engine.app.loop_readiness import build_loop_readiness_report, build_loop_readiness_scan
from engine.app.release import build_release_doctor_payload, render_release_doctor_payload
from engine.app.study_hydration import hydrate_study_liquidations, verify_study_liquidations
from engine.app.autoresearch import (
    build_accepted_duplicate_payload,
    execute_autoresearch,
    execute_autoresearch_batch,
    load_duplicate_baseline_variant_history_for_lineage,
    materialize_next_study_variants,
    write_next_study_payload,
)
from engine.app.examples import write_example_study_config, write_repo_example_artifacts
from engine.app.project_status import (
    load_project_status,
    render_project_status,
    update_project_status,
    write_project_status,
)
from engine.app.runlog import append_run_log_event, build_run_log_path
from engine.app.runtime import build_runtime_functions
from engine.app.schema import build_study_schema
from engine.app.service import execute_research_cycle
from engine.calibration.cost_capacity import (
    build_capacity_report,
    build_cost_capacity_calibration_artifact,
    fit_impact_calibration,
    load_order_telemetry_measurements,
    write_cost_capacity_calibration_artifact,
)
from engine.calibration.paper_feedback import (
    PaperCalibrationFeedbackConfig,
    build_paper_calibration_feedback,
    persist_paper_calibration_feedback,
    write_paper_calibration_feedback_artifact,
)
from engine.data.fetch import fetch_binance_archive_snapshot
from engine.data.dataset_matrix import build_dataset_matrix_from_inventory
from engine.data.microstructure import (
    export_force_order_liquidation_sidecar,
    fetch_binance_microstructure_snapshot,
)
from engine.data.providers import build_snapshot_from_bundle, build_snapshot_from_csv
from engine.execution.paper import paper_fixture_from_payload, run_paper_executor_fixture
from engine.execution.no_key_executor import (
    NoKeyExecutorConfig,
    NoKeyOrderRequest,
    run_phase2_chaos_replay,
    run_single_chaos_scenario,
    write_no_key_executor_report,
)
from engine.execution.paper_collector import (
    PaperWsCollectorConfig,
    PaperWsLiveCollectorConfig,
    run_paper_ws_collector_fixture,
    run_paper_ws_collector_live,
)
from engine.execution.paper_closeout import (
    Phase9ACloseoutConfig,
    build_phase9a_closeout_report,
    write_phase9a_closeout_report,
)
from engine.execution.paper_soak import (
    PaperSoakCloseoutConfig,
    build_public_ws_soak_closeout_report,
    write_public_ws_soak_closeout_report,
)
from engine.execution.paper_daemon import (
    PaperDaemonDryRunConfig,
    PaperRiskLimits,
    load_paper_status,
    run_paper_daemon_dry_run,
)
from engine.execution.paper_dashboard import (
    PaperSessionDashboardConfig,
    build_paper_session_dashboard,
    write_paper_session_dashboard_artifact,
)
from engine.execution.paper_export import export_paper_session, restore_paper_export_smoke
from engine.execution.paper_hosting import (
    HostedPaperOpsConfig,
    build_paper_host_doctor_report,
    write_hosted_paper_ops_templates,
)
from engine.execution.paper_streams import (
    LocalOrderBookSnapshot,
    rebuild_and_record_paper_book_state,
    replay_paper_stream_events,
)
from engine.execution.reconciliation import (
    load_gateway_snapshot,
    reconcile_projection_with_gateway,
    write_reconciliation_report,
)
from engine.features.leakage_audit import build_feature_causality_audit_report
from engine.forecasting.smoke import TimesFmSmokeConfig, run_timesfm_smoke
from engine.forecasting.runtime_profile import (
    TimesFmRuntimeBenchmarkConfig,
    TimesFmWarmBatchBenchmarkConfig,
    attach_forecast_campaign_to_runtime_profile,
    build_timesfm_runtime_matrix,
    run_timesfm_runtime_benchmark,
    run_timesfm_warm_batch_benchmark,
    write_timesfm_runtime_profile,
)
from engine.governance.lifecycle import lifecycle_status
from engine.io.artifacts import write_json_atomic, write_text_atomic
from engine.memory.insights import build_memory_summary, count_excluded_dirty_rows, render_memory_summary, select_memory_rows
from engine.profiling.local_harness import (
    build_fixture_profiling_tasks,
    run_local_profiling_harness,
    write_local_profile_report,
)
from engine.memory.query import (
    query_agent_decisions,
    query_candidate_trials,
    query_data_snapshots,
    query_meta_policies,
    query_resource_index,
    query_run_resource_links,
    query_run_memory,
    query_stress_runs,
    query_validation_runs,
    render_agent_decision_query,
    render_candidate_trial_query,
    render_data_snapshot_query,
    render_memory_query,
    render_meta_policy_query,
    render_resource_index_query,
    render_run_resource_link_query,
    render_stress_run_query,
    render_validation_run_query,
)
from engine.memory.store import ingest_artifact_directory, initialize_memory_db
from engine.portfolio.allocator import (
    HumanOverrideRequest,
    PortfolioArtifactCandidate,
    PortfolioConstraints,
    apply_human_override,
    build_portfolio_artifact,
    build_portfolio_plan,
    build_portfolio_risk_dashboard,
    persist_portfolio_plan,
)
from engine.portfolio.paper_loop import (
    PaperPortfolioLoopConfig,
    build_paper_portfolio_loop_input,
    run_paper_portfolio_allocator_tick,
)
from engine.reporting.compare import (
    build_duplicate_match_compare,
    compare_autoresearch_payloads,
    compare_batch_payloads,
    compare_campaign_payloads,
    compare_dashboard_payloads,
    compare_runcards,
    format_compare_payload,
    format_duplicate_match_compare,
)
from engine.reporting.listing import (
    filter_campaign_reports,
    filter_runcards,
    load_campaign_report_records,
    load_runcard_records,
    list_campaign_reports,
    list_runcards,
    rank_campaign_reports,
    rank_runcards,
    render_campaign_listing,
    render_runcard_listing,
)
from engine.reporting.runcards import load_runcard
from engine.reporting.summary import (
    build_autoresearch_summary,
    build_batch_summary,
    build_campaign_manifest_summary,
    build_campaign_summary,
    build_dashboard_summary,
    build_study_summary,
    load_autoresearch_report_payload,
    load_batch_report_payload,
    load_campaign_report_payload,
    load_dashboard_payload,
)
from engine.strategy.artifacts import list_strategy_artifacts, load_strategy_artifact, validate_strategy_artifact
from engine.validation.robustness_ladder import (
    build_paper_forward_score,
    build_robust_evaluation_scorecard,
    build_sealed_holdout_check,
    build_strategy_evidence_card,
    build_strategy_tournament_report,
)


def _resolve_batch_variant_selection(batch_payload: dict[str, object], variant_name: str) -> tuple[str, Path]:
    selected_variant = variant_name
    if selected_variant == "preferred":
        preferred_variant = batch_payload.get("preferred_variant", {})
        if not isinstance(preferred_variant, dict) or not isinstance(preferred_variant.get("variant"), str):
            raise SystemExit("batch report does not include a preferred variant")
        selected_variant = str(preferred_variant["variant"])

    variant_paths = batch_payload.get("next_study_variant_paths", {})
    if not isinstance(variant_paths, dict):
        raise SystemExit("batch report does not include next-study variant paths")
    selected_path_raw = variant_paths.get(selected_variant)
    if not isinstance(selected_path_raw, str):
        raise SystemExit(f"batch report does not include path for variant '{selected_variant}'")

    return selected_variant, Path(selected_path_raw)


def _load_cli_json_object(path: str | Path | None) -> dict[str, object]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON artifact must be an object: {path}")
    payload.setdefault("path", str(path))
    return payload


def _paper_forward_payload_from_args(args: argparse.Namespace) -> dict[str, object]:
    payload = _load_cli_json_object(args.input) if args.input else {}
    payload.setdefault("candidate_id", args.candidate_id)
    payload.setdefault("data_inventory", _load_cli_json_object(args.data_inventory))
    payload.setdefault("public_ws", _load_cli_json_object(args.public_ws))
    if not payload.get("public_ws") and isinstance(payload.get("data_inventory"), dict):
        nested_public_ws = payload["data_inventory"].get("forward_public_ws_capture")  # type: ignore[index]
        if isinstance(nested_public_ws, dict):
            payload["public_ws"] = nested_public_ws
    payload.setdefault("paper_dashboard", _load_cli_json_object(args.paper_dashboard))
    payload.setdefault("postrun_summary", _load_cli_json_object(args.postrun_summary))
    payload.setdefault("calibration_feedback", _load_cli_json_object(args.calibration_feedback))
    payload.setdefault("capacity_report", _load_cli_json_object(args.capacity_report))
    payload.setdefault(
        "thresholds",
        {
            "minimum_paper_orders": args.minimum_paper_orders,
            "minimum_telemetry_quality": args.minimum_telemetry_quality,
            "max_abs_slip_bps": args.max_abs_slip_bps,
            "max_latency_ms": args.max_latency_ms,
        },
    )
    if args.liquidation_sidecar:
        payload["liquidation_sidecar_ready"] = Path(args.liquidation_sidecar).exists()
    return payload


def _strategy_evidence_card_payload_from_args(args: argparse.Namespace) -> dict[str, object]:
    payload = _load_cli_json_object(args.input) if args.input else {}
    payload.setdefault("candidate_id", args.candidate_id)
    payload.setdefault("data_matrix", _load_cli_json_object(args.data_matrix))
    payload.setdefault("feature_audit", _load_cli_json_object(args.feature_audit))
    payload.setdefault("strategy_tournament", _load_cli_json_object(args.strategy_tournament))
    payload.setdefault("robust_evaluation", _load_cli_json_object(args.robust_evaluation))
    payload.setdefault("sealed_holdout", _load_cli_json_object(args.sealed_holdout))
    payload.setdefault("paper_forward_score", _load_cli_json_object(args.paper_forward_score))
    payload["promotion_governance_approved"] = bool(args.promotion_governance_approved or payload.get("promotion_governance_approved"))
    return payload


def _resolve_accepted_duplicate_path(report_payload: dict[str, object]) -> Path:
    accepted_duplicate_path = report_payload.get("accepted_duplicate_config_path")
    if not isinstance(accepted_duplicate_path, str) or not accepted_duplicate_path:
        raise SystemExit("autoresearch report does not include accepted_duplicate_config_path")
    return Path(accepted_duplicate_path)


def _find_batch_variant_result(batch_payload: dict[str, object], variant_name: str) -> dict[str, object] | None:
    variant_results = batch_payload.get("variant_results", [])
    if not isinstance(variant_results, list):
        return None
    for result in variant_results:
        if not isinstance(result, dict):
            continue
        if result.get("variant") == variant_name:
            return result
    return None


def _format_top_scenario_profile(raw: object) -> str | None:
    if not isinstance(raw, dict) or not raw:
        return None
    scenario_name, hint = next(iter(raw.items()))
    if not isinstance(scenario_name, str) or not isinstance(hint, dict):
        return None
    profile = hint.get("profile")
    if not isinstance(profile, dict) or not profile:
        return None
    parts = [f"{key}={profile[key]}" for key in sorted(profile)]
    return f"{scenario_name} | " + ", ".join(parts)


def _format_top_runtime_profile(raw: object) -> str | None:
    if not isinstance(raw, dict) or not raw:
        return None
    profile = raw.get("profile")
    if not isinstance(profile, dict) or not profile:
        return None
    parts = [f"{key}={profile[key]}" for key in sorted(profile)]
    return ", ".join(parts)


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


def _load_portfolio_plan_inputs(path: Path) -> tuple[list[PortfolioArtifactCandidate], PortfolioConstraints, dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("portfolio input must be a JSON object")
    raw_candidates = payload.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raise SystemExit("portfolio input candidates must be a list")
    candidates: list[PortfolioArtifactCandidate] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            raise SystemExit("portfolio candidate must be a JSON object")
        candidate_payload = dict(item)
        candidate_payload["symbol_scope"] = tuple(str(value) for value in candidate_payload.get("symbol_scope", []))
        candidate_payload["regime_scope"] = tuple(str(value) for value in candidate_payload.get("regime_scope", []))
        candidates.append(PortfolioArtifactCandidate(**candidate_payload))
    raw_constraints = payload.get("constraints", {})
    if not isinstance(raw_constraints, dict):
        raise SystemExit("portfolio constraints must be a JSON object")
    constraints = PortfolioConstraints(**raw_constraints)
    raw_regimes = payload.get("active_regimes", {})
    if not isinstance(raw_regimes, dict):
        raise SystemExit("active_regimes must be a JSON object")
    active_regimes = {str(key): str(value) for key, value in raw_regimes.items()}
    return candidates, constraints, active_regimes


def _load_book_snapshots(path: Path) -> list[LocalOrderBookSnapshot]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("book snapshot file must be a JSON object")
    raw_snapshots = payload.get("snapshots")
    if not isinstance(raw_snapshots, list):
        raise SystemExit("book snapshot file must contain snapshots list")
    snapshots: list[LocalOrderBookSnapshot] = []
    for item in raw_snapshots:
        if not isinstance(item, dict):
            raise SystemExit("book snapshot entry must be a JSON object")
        snapshots.append(
            LocalOrderBookSnapshot(
                symbol=str(item["symbol"]),
                last_update_id=int(item["last_update_id"]),
                bids=[[str(level[0]), str(level[1])] for level in item.get("bids", [])],
                asks=[[str(level[0]), str(level[1])] for level in item.get("asks", [])],
                received_at_utc=str(item.get("received_at_utc")) if item.get("received_at_utc") else None,
            )
        )
    return snapshots


def _extend_response_with_variant_profile_rationale(
    response: dict[str, object],
    selected_variant_result: object,
    *,
    preferred_variant_result: object | None = None,
) -> None:
    if not isinstance(selected_variant_result, dict):
        return
    response["selected_variant_result"] = selected_variant_result
    duplicate_baseline_history = selected_variant_result.get("duplicate_baseline_history", {})
    if not isinstance(duplicate_baseline_history, dict):
        return
    duplicate_baseline_score = _compute_duplicate_baseline_score(duplicate_baseline_history)
    if duplicate_baseline_score is not None:
        response["selected_duplicate_baseline_score"] = duplicate_baseline_score
        if isinstance(preferred_variant_result, dict):
            preferred_history = preferred_variant_result.get("duplicate_baseline_history", {})
            if isinstance(preferred_history, dict):
                preferred_score = _compute_duplicate_baseline_score(preferred_history)
                if preferred_score is not None:
                    response["selected_duplicate_baseline_delta_vs_preferred"] = round(
                        duplicate_baseline_score - preferred_score,
                        2,
                    )
    top_scenario_profile = _format_top_scenario_profile(
        duplicate_baseline_history.get("scenario_profile_hints")
    )
    if top_scenario_profile is not None:
        response["selected_top_scenario_profile"] = top_scenario_profile
    top_fragile_profile = _format_top_scenario_profile(
        duplicate_baseline_history.get("scenario_profile_avoidance")
    )
    if top_fragile_profile is not None:
        response["selected_top_fragile_profile"] = top_fragile_profile
    top_runtime_profile = _format_top_runtime_profile(
        duplicate_baseline_history.get("runtime_profile_hints")
    )
    if top_runtime_profile is not None:
        response["selected_top_runtime_profile"] = top_runtime_profile


def _format_lineage_summary(report_payload: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"Run: {report_payload.get('run_id', 'unknown')}")
    lines.append(f"Status: {report_payload.get('status', 'unknown')}")
    lineage = report_payload.get("research_lineage", {})
    if not isinstance(lineage, dict) or not lineage:
        lines.append("Lineage: none")
        return "\n".join(lines)

    lines.append(f"Selected variant: {lineage.get('selected_variant', 'unknown')}")
    if "selection_source" in lineage:
        lines.append(f"Selection source: {lineage.get('selection_source', 'unknown')}")
    if "selection_preference_mode" in lineage:
        lines.append(f"Selection mode: {lineage.get('selection_preference_mode', 'unknown')}")
    lines.append(f"Parent batch run: {lineage.get('parent_batch_run_id', 'unknown')}")
    lines.append(f"Parent batch report: {lineage.get('parent_batch_report_path', 'unknown')}")
    lines.append(f"Source config: {lineage.get('source_config_path', 'unknown')}")
    selection_variant_result = lineage.get("selection_variant_result")
    if isinstance(selection_variant_result, dict):
        duplicate_baseline_history = selection_variant_result.get("duplicate_baseline_history", {})
        if isinstance(duplicate_baseline_history, dict):
            duplicate_baseline_score = _compute_duplicate_baseline_score(duplicate_baseline_history)
            if duplicate_baseline_score is not None:
                lines.append(f"Duplicate baseline score: {duplicate_baseline_score:.2f}")
            top_scenario_profile = _format_top_scenario_profile(
                duplicate_baseline_history.get("scenario_profile_hints")
            )
            if top_scenario_profile is not None:
                lines.append(f"Top scenario profile: {top_scenario_profile}")
            top_fragile_profile = _format_top_scenario_profile(
                duplicate_baseline_history.get("scenario_profile_avoidance")
            )
            if top_fragile_profile is not None:
                lines.append(f"Top fragile profile: {top_fragile_profile}")
            top_runtime_profile = _format_top_runtime_profile(
                duplicate_baseline_history.get("runtime_profile_hints")
            )
            if top_runtime_profile is not None:
                lines.append(f"Top runtime profile: {top_runtime_profile}")
    return "\n".join(lines)


def _render_skill_contracts_payload(contracts: list[SkillContract]) -> dict[str, object]:
    return {
        "skill_count": len(contracts),
        "skills": [
            {
                "name": contract.name,
                "path": str(contract.path),
                "purpose": contract.purpose,
                "inputs": list(contract.inputs),
                "outputs": list(contract.outputs),
                "rules": list(contract.rules),
                "forbidden": list(contract.forbidden),
            }
            for contract in contracts
        ],
    }


def _render_skill_contracts_text(contracts: list[SkillContract]) -> str:
    lines: list[str] = []
    for index, contract in enumerate(contracts, start=1):
        lines.append(f"{index}. {contract.name}")
        lines.append(f"   purpose: {contract.purpose}")
        lines.append(f"   path: {contract.path}")
    return "\n".join(lines)


def _render_skill_contract_text(contract: SkillContract) -> str:
    lines = [contract.name]
    lines.append(f"purpose: {contract.purpose}")
    lines.append(f"path: {contract.path}")
    lines.append("inputs: " + ", ".join(contract.inputs))
    lines.append("outputs: " + ", ".join(contract.outputs))
    lines.append("rules: " + ", ".join(contract.rules))
    lines.append("forbidden: " + ", ".join(contract.forbidden))
    return "\n".join(lines)


def _apply_strict_quality_override(study: StudyConfig, strict_quality: bool) -> StudyConfig:
    if not strict_quality:
        return study
    return replace(
        study,
        runtime_settings=replace(study.runtime_settings, fail_on_quality_flags=True),
    )


def _enforce_snapshot_quality(study: StudyConfig, config_path: Path) -> None:
    if not study.runtime_settings.fail_on_quality_flags:
        return
    if not study.snapshot.quality_flags:
        return
    flags = ", ".join(study.snapshot.quality_flags)
    raise SystemExit(
        f"strict-quality preflight blocked run '{study.run_id}' because snapshot "
        f"'{study.snapshot.snapshot_id}' has quality flags: {flags}. "
        f"Inspect it with: python -m engine.app.cli inspect-study --config {config_path}"
    )


def _enforce_loop_readiness(study: StudyConfig, config_path: Path, report: dict[str, object] | None = None) -> None:
    report = report or build_loop_readiness_report(study, config_path=config_path)
    if report["eligible"]:
        return
    blockers = ", ".join(str(item) for item in report.get("blockers", []))
    raise SystemExit(
        f"loop-readiness preflight blocked run '{study.run_id}' because "
        f"the initial study is not eligible: {blockers}. "
        f"Inspect it with: python -m engine.app.cli loop-readiness --config {config_path}"
    )


def _materialize_accepted_duplicate_if_available(
    *,
    base_payload: dict[str, object],
    execution,
    db_path: Path,
    output_dir: Path,
) -> str | None:
    duplicate_match = execution.duplicate_match
    if not isinstance(duplicate_match, dict) or not isinstance(duplicate_match.get("run_id"), str):
        return None
    matched_rows = query_run_memory(db_path, run_id=str(duplicate_match["run_id"]), limit=1)
    if not matched_rows:
        return None
    accepted_payload = build_accepted_duplicate_payload(
        base_payload,
        matched_rows[0],
        source_report_path=str(execution.autoresearch_report_path) if execution.autoresearch_report_path else "",
    )
    output_path = output_dir / f"{execution.run_id}.accepted-duplicate.json"
    write_next_study_payload(output_path, accepted_payload)
    if execution.autoresearch_report_path:
        report_path = Path(execution.autoresearch_report_path)
        report_payload = load_autoresearch_report_payload(report_path)
        report_payload["accepted_duplicate_config_path"] = str(output_path)
        write_json_atomic(report_path, report_payload)
    return str(output_path)


def _log_event(log_path: Path | None, event: str, **fields: object) -> None:
    if log_path is None:
        return
    append_run_log_event(log_path, event, **fields)


def _run_study_execution(
    *,
    config_path: Path,
    raw_payload: dict[str, object],
    study: StudyConfig,
    output_dir: Path,
    log_path: Path | None,
) -> dict[str, object]:
    _log_event(
        log_path,
        "study_loaded",
        command="run",
        run_id=study.run_id,
        config_path=str(config_path),
        output_dir=str(output_dir),
    )
    study_signature = build_study_signature_from_payload(raw_payload)
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
    )
    _log_event(
        log_path,
        "research_cycle_completed",
        command="run",
        run_id=execution.runcard.run_id,
        status=execution.report.status,
        runcard_path=execution.runcard_path,
        dashboard_path=execution.dashboard_path,
    )
    payload = {
        "run_id": execution.runcard.run_id,
        "status": execution.report.status,
        "runcard_path": execution.runcard_path,
        "dashboard_path": execution.dashboard_path,
        "log_path": str(log_path) if log_path is not None else None,
    }
    _log_event(
        log_path,
        "command_completed",
        command="run",
        run_id=execution.runcard.run_id,
        status=execution.report.status,
    )
    return payload


def _run_autoresearch_execution(
    *,
    config_path: Path,
    base_payload: dict[str, object],
    study: StudyConfig,
    output_dir: Path,
    db_path: Path,
    memory_dir: Path | None,
    memory_limit: int,
    memory_quality_policy: str,
    log_path: Path | None,
    allow_duplicate_study_signature: bool = False,
) -> dict[str, object]:
    _log_event(
        log_path,
        "study_loaded",
        command="autoresearch",
        run_id=study.run_id,
        config_path=str(config_path),
        output_dir=str(output_dir),
        db_path=str(db_path),
    )
    study_signature = build_study_signature_from_payload(base_payload)
    execution = execute_autoresearch(
        study=study,
        output_dir=output_dir,
        db_path=db_path,
        memory_dir=memory_dir,
        memory_limit=memory_limit,
        memory_quality_policy=memory_quality_policy,
        study_signature=study_signature,
        allow_duplicate_study_signature=allow_duplicate_study_signature,
    )
    _log_event(
        log_path,
        "autoresearch_completed",
        command="autoresearch",
        run_id=execution.run_id,
        status=execution.status,
        skip_reason=execution.skip_reason,
        autoresearch_report_path=execution.autoresearch_report_path,
        runcard_path=execution.runcard_path,
        dashboard_path=execution.dashboard_path,
    )
    accepted_duplicate_config_path = _materialize_accepted_duplicate_if_available(
        base_payload=base_payload,
        execution=execution,
        db_path=db_path,
        output_dir=output_dir,
    )
    if accepted_duplicate_config_path:
        _log_event(
            log_path,
            "accepted_duplicate_materialized",
            command="autoresearch",
            run_id=execution.run_id,
            accepted_duplicate_config_path=accepted_duplicate_config_path,
        )
    duplicate_baseline_history = load_duplicate_baseline_variant_history_for_lineage(
        db_path=db_path,
        research_lineage=study.research_lineage,
        memory_quality_policy=memory_quality_policy,
    )
    next_study_paths = materialize_next_study_variants(
        base_payload,
        execution.memory_summary,
        output_dir,
        study.run_id,
        duplicate_baseline_history_by_variant=duplicate_baseline_history,
    )
    _log_event(
        log_path,
        "next_study_variants_materialized",
        command="autoresearch",
        run_id=execution.run_id,
        variant_count=len(next_study_paths),
        next_study_variant_paths=next_study_paths,
    )
    payload = {
        "run_id": execution.run_id,
        "status": execution.status,
        "skip_reason": execution.skip_reason,
        "duplicate_match": execution.duplicate_match,
        "accepted_duplicate_config_path": accepted_duplicate_config_path,
        "memory_summary": execution.memory_summary,
        "runcard_path": execution.runcard_path,
        "dashboard_path": execution.dashboard_path,
        "autoresearch_report_path": execution.autoresearch_report_path,
        "next_study_config_path": next_study_paths["balanced"],
        "next_study_variant_paths": next_study_paths,
        "log_path": str(log_path) if log_path is not None else None,
    }
    _log_event(
        log_path,
        "command_completed",
        command="autoresearch",
        run_id=execution.run_id,
        status=execution.status,
    )
    return payload


def _run_batch_autoresearch_execution(
    *,
    config_path: Path,
    base_payload: dict[str, object],
    study: StudyConfig,
    output_dir: Path,
    db_path: Path,
    memory_dir: Path | None,
    memory_limit: int,
    memory_quality_policy: str,
    log_path: Path | None,
) -> dict[str, object]:
    _log_event(
        log_path,
        "study_loaded",
        command="batch-autoresearch",
        run_id=study.run_id,
        config_path=str(config_path),
        output_dir=str(output_dir),
        db_path=str(db_path),
    )
    study_signature = build_study_signature_from_payload(base_payload)
    execution = execute_autoresearch_batch(
        study=study,
        base_payload=base_payload,
        output_dir=output_dir,
        db_path=db_path,
        memory_dir=memory_dir,
        memory_limit=memory_limit,
        memory_quality_policy=memory_quality_policy,
        study_signature=study_signature,
    )
    _log_event(
        log_path,
        "batch_autoresearch_completed",
        command="batch-autoresearch",
        run_id=execution.run_id,
        status=execution.status,
        batch_report_path=execution.batch_report_path,
        preferred_variant=execution.preferred_variant.get("variant") if isinstance(execution.preferred_variant, dict) else None,
    )
    payload = {
        "run_id": execution.run_id,
        "status": execution.status,
        "autoresearch_report_path": execution.autoresearch_report_path,
        "accepted_duplicate_config_path": execution.accepted_duplicate_config_path,
        "next_study_variant_paths": execution.next_study_variant_paths,
        "batch_report_path": execution.batch_report_path,
        "base_run": execution.base_run,
        "preferred_variant": execution.preferred_variant,
        "variant_runs": execution.variant_runs,
        "log_path": str(log_path) if log_path is not None else None,
    }
    _log_event(
        log_path,
        "command_completed",
        command="batch-autoresearch",
        run_id=execution.run_id,
        status=execution.status,
    )
    return payload


def _run_campaign_manifest(manifest_path: Path, output_report_path: Path) -> dict[str, object]:
    manifest = expand_campaign_manifest(manifest_path, output_report_path)
    campaign_id = str(manifest.get("campaign_id", output_report_path.stem))
    entries = manifest.get("entries", [])

    campaign_log_path = output_report_path.with_suffix(".events.jsonl")
    _log_event(
        campaign_log_path,
        "campaign_started",
        campaign_id=campaign_id,
        manifest_path=str(manifest_path),
        output_report_path=str(output_report_path),
    )

    continue_on_error = bool(manifest.get("continue_on_error", True))

    entry_results: list[dict[str, object]] = []
    failed_entries = 0
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            failed_entries += 1
            entry_results.append(
                {"name": f"entry-{index}", "command": "unknown", "status": "failed", "error": "entry must be an object"}
            )
            if not continue_on_error:
                break
            continue

        name = str(entry.get("name", f"entry-{index}"))
        command = str(entry.get("command", "run"))
        config_path = Path(str(entry.get("config_path", "")))
        output_dir = Path(str(entry.get("output_dir", output_report_path.parent / name)))
        db_raw = entry.get("db_path")
        db_path = Path(str(db_raw)) if db_raw is not None else None
        memory_dir_raw = entry.get("memory_dir")
        memory_dir = Path(str(memory_dir_raw)) if memory_dir_raw is not None else None
        memory_limit = int(entry.get("memory_limit", 25))
        memory_quality_policy = str(entry.get("memory_quality_policy", "clean-only"))
        strict_quality = bool(entry.get("strict_quality", False))

        try:
            raw_payload = json.loads(config_path.read_text(encoding="utf-8"))
            study = _apply_strict_quality_override(load_study_config(config_path), strict_quality)
            _enforce_snapshot_quality(study, config_path)
            log_path = build_run_log_path(output_dir, study.run_id)

            if command == "run":
                result = _run_study_execution(
                    config_path=config_path,
                    raw_payload=raw_payload,
                    study=study,
                    output_dir=output_dir,
                    log_path=log_path,
                )
            elif command == "autoresearch":
                if db_path is None:
                    raise SystemExit("campaign autoresearch entries require db")
                result = _run_autoresearch_execution(
                    config_path=config_path,
                    base_payload=raw_payload,
                    study=study,
                    output_dir=output_dir,
                    db_path=db_path,
                    memory_dir=memory_dir,
                    memory_limit=memory_limit,
                    memory_quality_policy=memory_quality_policy,
                    log_path=log_path,
                )
            elif command == "batch-autoresearch":
                if db_path is None:
                    raise SystemExit("campaign batch-autoresearch entries require db")
                result = _run_batch_autoresearch_execution(
                    config_path=config_path,
                    base_payload=raw_payload,
                    study=study,
                    output_dir=output_dir,
                    db_path=db_path,
                    memory_dir=memory_dir,
                    memory_limit=memory_limit,
                    memory_quality_policy=memory_quality_policy,
                    log_path=log_path,
                )
            else:
                raise SystemExit(f"unsupported campaign command '{command}'")

            result.update(
                {
                    "name": name,
                    "command": command,
                    "config_path": str(config_path),
                    "output_dir": str(output_dir),
                    "db_path": str(db_path) if db_path is not None else None,
                    "memory_dir": str(memory_dir) if memory_dir is not None else None,
                    "memory_limit": memory_limit,
                    "memory_quality_policy": memory_quality_policy,
                    "strict_quality": strict_quality,
                    "template_values": dict(entry.get("template_values", {})),
                }
            )
            entry_results.append(result)
            _log_event(
                campaign_log_path,
                "campaign_entry_completed",
                campaign_id=campaign_id,
                name=name,
                command=command,
                status=result.get("status"),
                entry_log_path=result.get("log_path"),
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            failed_entries += 1
            error_message = str(exc)
            entry_result = {
                "name": name,
                "command": command,
                "status": "failed",
                "error": error_message,
                "config_path": str(config_path),
                "output_dir": str(output_dir),
                "db_path": str(db_path) if db_path is not None else None,
                "memory_dir": str(memory_dir) if memory_dir is not None else None,
                "memory_limit": memory_limit,
                "memory_quality_policy": memory_quality_policy,
                "strict_quality": strict_quality,
                "template_values": dict(entry.get("template_values", {})),
            }
            entry_results.append(entry_result)
            _log_event(
                campaign_log_path,
                "campaign_entry_failed",
                campaign_id=campaign_id,
                name=name,
                command=command,
                error=error_message,
            )
            if not continue_on_error:
                break

    completed_entries = sum(1 for entry in entry_results if entry.get("status") != "failed")
    status = "completed" if failed_entries == 0 else "completed_with_failures"
    report_payload = {
        "campaign_id": campaign_id,
        "status": status,
        "manifest_path": str(manifest_path),
        "report_path": str(output_report_path),
        "log_path": str(campaign_log_path),
        "defaults": manifest.get("defaults", {}),
        "entry_count": len(entry_results),
        "completed_entries": completed_entries,
        "failed_entries": failed_entries,
        "entries": entry_results,
    }
    output_report_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_report_path, report_payload)
    _log_event(
        campaign_log_path,
        "campaign_completed",
        campaign_id=campaign_id,
        status=status,
        entry_count=len(entry_results),
        completed_entries=completed_entries,
        failed_entries=failed_entries,
    )
    return report_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run or initialize ProofAlpha studies.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"proofalpha {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_core_commands(subparsers)

    register_data_forecast_commands(subparsers)

    register_paper_commands(subparsers)

    register_execution_commands(subparsers)

    register_report_commands(subparsers)
    register_memory_commands(subparsers)
    register_project_status_commands(subparsers)
    register_research_commands(subparsers)
    register_skill_commands(subparsers)
    register_mcp_commands(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from engine.app.logging_config import configure_engine_logging

    configure_engine_logging()

    known_commands = {"init-example", "init-example-bundle", "inspect-study", "loop-readiness", "loop-readiness-scan", "doctor", "inspect-campaign", "retry-campaign", "run", "export-schema", "refresh-examples", "fetch-microstructure", "hydrate-study-liquidations", "verify-study-liquidations", "export-forceorder-liquidations", "timesfm-smoke", "timesfm-benchmark", "profile-local-harness", "dataset-matrix", "fetch-binance-archive", "strict-data-collect", "validate-artifact", "list-artifacts", "paper-run-artifact", "paper-daemon", "paper-status", "paper-session-dashboard", "paper-ws-collect", "paper-ws-run", "paper-replay", "paper-export", "paper-host-doctor", "paper-book-replay", "paper-phase9a-closeout", "paper-soak-closeout", "no-key-executor-chaos", "phase3-reconcile", "portfolio-plan", "paper-portfolio-loop", "portfolio-override", "calibrate-cost-capacity", "paper-calibration-feedback", "paper-post-run-summary", "lifecycle-status", "summarize-run", "summarize-autoresearch", "summarize-batch", "summarize-campaign", "select-batch-variant", "continue-batch", "continue-accepted-duplicate", "trace-lineage", "trace-audit-export", "loop-evidence-ledger", "feature-causality-audit", "strategy-tournament", "robust-evaluate", "sealed-holdout-check", "paper-forward-score", "strategy-evidence-card", "loop-improvement-gate", "trace-audit-ingest", "research-debate-report", "compare-runs", "compare-duplicate-match", "accept-duplicate-match", "list-runs", "list-campaigns", "ingest-memory", "query-memory", "query-candidate-trials", "query-validation-runs", "query-stress-runs", "query-agent-decisions", "query-data-snapshots", "query-resource-index", "query-run-resource-links", "query-meta-policies", "summarize-memory", "project-status", "autoresearch", "batch-autoresearch", "agent-loop", "guarded-loop-cycle", "guarded-loop-repeat", "operate-loop", "list-skills", "inspect-skill", "run-campaign", "mcp-list-profiles", "mcp-list-tools", "mcp-call"}
    if argv and argv[0] not in known_commands and argv[0] not in {"-h", "--help", "--version"}:
        argv = ["run", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-example":
        snapshot = build_snapshot_from_csv(
            path=Path(args.csv),
            snapshot_id=args.snapshot_id,
            symbol=args.symbol,
            venue=args.venue,
            timeframe=args.timeframe,
            maker_fee_bps=args.maker_fee_bps,
            taker_fee_bps=args.taker_fee_bps,
        )
        output_path = Path(args.config_out)
        write_example_study_config(output_path, snapshot, run_id=args.run_id, seed=args.seed)
        print(json.dumps({"config_path": str(output_path), "run_id": args.run_id}, sort_keys=True))
        return 0

    if args.command == "init-example-bundle":
        snapshot = build_snapshot_from_bundle(
            candles_path=Path(args.candles_csv),
            funding_path=Path(args.funding_csv) if args.funding_csv else None,
            open_interest_path=Path(args.open_interest_csv) if args.open_interest_csv else None,
            liquidation_notional_path=Path(args.liquidations_csv) if args.liquidations_csv else None,
            snapshot_id=args.snapshot_id,
            symbol=args.symbol,
            venue=args.venue,
            timeframe=args.timeframe,
            maker_fee_bps=args.maker_fee_bps,
            taker_fee_bps=args.taker_fee_bps,
        )
        output_path = Path(args.config_out)
        write_example_study_config(output_path, snapshot, run_id=args.run_id, seed=args.seed)
        print(json.dumps({"config_path": str(output_path), "run_id": args.run_id}, sort_keys=True))
        return 0

    if args.command == "fetch-microstructure":
        paths = fetch_binance_microstructure_snapshot(
            output_dir=Path(args.output_dir),
            symbol=args.symbol,
            depth_limit=args.depth_limit,
            agg_trade_limit=args.agg_trade_limit,
            samples=args.samples,
            sample_interval_seconds=args.sample_interval_seconds,
            retention_hours=args.retention_hours,
            max_raw_events=args.max_raw_events,
        )
        print(json.dumps({key: str(path) for key, path in paths.items()}, sort_keys=True))
        return 0

    if args.command == "hydrate-study-liquidations":
        if args.require_ready:
            verification = verify_study_liquidations(
                config_path=Path(args.config),
                liquidations_path=Path(args.liquidations),
            )
            if verification["status"] != "ready":
                print(json.dumps(verification, sort_keys=True))
                return 2
        payload = hydrate_study_liquidations(
            config_path=Path(args.config),
            liquidations_path=Path(args.liquidations),
            output_path=Path(args.output),
        )
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["status"] == "hydrated" else 2

    if args.command == "verify-study-liquidations":
        payload = verify_study_liquidations(
            config_path=Path(args.config),
            liquidations_path=Path(args.liquidations),
            output_path=Path(args.output) if args.output else None,
        )
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["status"] == "ready" else 2

    if args.command == "export-forceorder-liquidations":
        payload = export_force_order_liquidation_sidecar(
            db_path=Path(args.db),
            session_id=args.session_id,
            output_path=Path(args.output),
            timeframe=args.timeframe,
            include_observed_zero_buckets=args.include_observed_zero_buckets,
        )
        print(json.dumps(payload, sort_keys=True))
        return 0

    if args.command == "timesfm-smoke":
        payload = run_timesfm_smoke(
            TimesFmSmokeConfig(
                symbol=args.symbol,
                horizon=args.horizon,
                backend=args.backend,
                model_id=args.model_id,
                model_weights_path=args.model_weights_path,
                sidecar_python_path=args.sidecar_python_path,
                sidecar_timeout_seconds=args.sidecar_timeout_seconds,
                use_fixture=args.fixture,
            )
        )
        print(json.dumps(payload, sort_keys=True))
        return 0

    if args.command == "timesfm-benchmark":
        if args.warm_batch:
            report = run_timesfm_warm_batch_benchmark(
                TimesFmWarmBatchBenchmarkConfig(
                    symbols=tuple(args.warm_batch_symbol) if args.warm_batch_symbol else ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                    use_fixture=args.fixture,
                    model_id=args.model_id,
                    backend=args.backend,
                    model_weights_path=args.model_weights_path,
                    sidecar_python_path=args.sidecar_python_path,
                    sidecar_timeout_seconds=args.sidecar_timeout_seconds,
                    max_context=(args.context_length[-1] if args.context_length else 512),
                    horizon=(args.horizon[-1] if args.horizon else 3),
                    batch_size=(args.batch_size[-1] if args.batch_size else 3),
                    device=(args.device[-1] if args.device else "cpu"),
                    torch_compile=args.include_torch_compile,
                    resident_sidecar=args.resident_sidecar,
                )
            )
            if args.include_forecast_campaign:
                report = attach_forecast_campaign_to_runtime_profile(
                    report,
                    symbols=tuple(args.forecast_campaign_symbol)
                    if args.forecast_campaign_symbol
                    else ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                )
            output = write_timesfm_runtime_profile(Path(args.output), report)
            print(json.dumps({**report, "output": str(output)}, sort_keys=True))
            return 0 if report.get("status") in {"completed", "skipped"} else 2

        matrix = build_timesfm_runtime_matrix(
            model_id=args.model_id,
            backend=args.backend,
            context_lengths=tuple(args.context_length) if args.context_length else (128, 256, 512),
            horizons=tuple(args.horizon) if args.horizon else (1, 2, 3, 6),
            batch_sizes=tuple(args.batch_size) if args.batch_size else (1, 3, 4),
            torch_compile_options=(False, True) if args.include_torch_compile else (False,),
            devices=tuple(args.device) if args.device else ("cpu",),
        )
        report = run_timesfm_runtime_benchmark(
            TimesFmRuntimeBenchmarkConfig(
                matrix=matrix,
                use_fixture=args.fixture,
                model_id=args.model_id,
                backend=args.backend,
                model_weights_path=args.model_weights_path,
                sidecar_python_path=args.sidecar_python_path,
                sidecar_timeout_seconds=args.sidecar_timeout_seconds,
            )
        )
        if args.include_forecast_campaign:
            report = attach_forecast_campaign_to_runtime_profile(
                report,
                symbols=tuple(args.forecast_campaign_symbol)
                if args.forecast_campaign_symbol
                else ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            )
        output = write_timesfm_runtime_profile(Path(args.output), report)
        print(json.dumps({**report, "output": str(output)}, sort_keys=True))
        return 0 if report.get("status") in {"completed", "skipped"} else 2

    if args.command == "profile-local-harness":
        tasks = build_fixture_profiling_tasks()
        report = run_local_profiling_harness(tasks)
        output = write_local_profile_report(Path(args.output), report)
        print(json.dumps({**report, "output": str(output)}, sort_keys=True))
        return 0 if report.get("status") in {"completed", "completed_with_errors"} else 2

    if args.command == "dataset-matrix":
        inventory_path = Path(args.inventory)
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        report = build_dataset_matrix_from_inventory(
            inventory,
            workspace=Path(args.workspace),
            required_symbols=tuple(args.symbol or ()),
            required_timeframes=tuple(args.timeframe or ()),
            minimum_distinct_years=args.minimum_distinct_years,
            required_sidecar_fields=tuple(args.required_sidecar or ()),
        )
        write_json_atomic(Path(args.output), report)
        print(json.dumps(report, sort_keys=True))
        return 0 if report.get("status") == "ready" else 2

    if args.command == "fetch-binance-archive":
        paths = fetch_binance_archive_snapshot(
            output_dir=Path(args.output_dir),
            symbol=args.symbol,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            include_agg_trades=not args.skip_agg_trades,
        )
        print(json.dumps({key: str(path) for key, path in paths.items()}, sort_keys=True))
        return 0

    if args.command == "validate-artifact":
        payload = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
        validation = validate_strategy_artifact(payload if isinstance(payload, dict) else {})
        print(
            json.dumps(
                {
                    "artifact_path": str(Path(args.artifact)),
                    "artifact_id": payload.get("artifact_id") if isinstance(payload, dict) else None,
                    "passed": validation.passed,
                    "reasons": validation.reasons,
                    "artifact_sha256": validation.artifact_sha256,
                },
                sort_keys=True,
            )
        )
        return 0 if validation.passed else 2

    if args.command == "list-artifacts":
        print(json.dumps({"artifacts": list_strategy_artifacts(Path(args.dir))}, sort_keys=True))
        return 0

    if args.command == "paper-run-artifact":
        artifact = load_strategy_artifact(Path(args.artifact))
        fixture_payload = json.loads(Path(args.market_fixture).read_text(encoding="utf-8"))
        if not isinstance(fixture_payload, dict):
            raise SystemExit("market fixture must be a JSON object")
        order_intents, market_snapshots = paper_fixture_from_payload(fixture_payload)
        result = run_paper_executor_fixture(
            artifact,
            order_intents=order_intents,
            market_snapshots=market_snapshots,
        )
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "paper-daemon":
        if not args.dry_run:
            raise SystemExit("paper-daemon currently requires --dry-run; public WS daemon is a later Phase 9A slice")
        status = run_paper_daemon_dry_run(
            PaperDaemonDryRunConfig(
                db_path=Path(args.db),
                artifact_paths=tuple(Path(path) for path in args.artifact),
                market_fixture_path=Path(args.market_fixture),
                session_id=args.session_id,
                host_id=args.host_id,
                portfolio_plan_id=args.portfolio_plan_id,
                risk_limits=PaperRiskLimits(
                    max_per_symbol_notional=args.max_per_symbol_notional,
                    max_aggregate_notional=args.max_aggregate_notional,
                    max_spread_bps=args.max_spread_bps,
                    min_visible_depth_qty=args.min_visible_depth_qty,
                    max_order_rate_per_minute=args.max_order_rate_per_minute,
                ),
            )
        )
        print(json.dumps(status, sort_keys=True))
        return 0

    if args.command == "paper-status":
        print(json.dumps(load_paper_status(Path(args.db), session_id=args.session_id), sort_keys=True))
        return 0

    if args.command == "paper-session-dashboard":
        dashboard = build_paper_session_dashboard(
            PaperSessionDashboardConfig(
                db_path=Path(args.db),
                session_id=args.session_id,
                now_utc=args.now,
                max_stream_staleness_seconds=args.max_stream_staleness_seconds,
            )
        )
        write_paper_session_dashboard_artifact(Path(args.output), dashboard)
        print(
            json.dumps(
                {
                    "output": str(Path(args.output)),
                    "artifact_id": dashboard["artifact_id"],
                    "status": dashboard["status"],
                    "risk_block_count": dashboard["risk"]["risk_block_count"],
                    "stale_stream_count": len(dashboard["streams"]["stale_streams"]),
                },
                sort_keys=True,
            )
        )
        return 0 if dashboard.get("status") in {"healthy", "attention"} else 2

    if args.command == "paper-ws-collect":
        result = run_paper_ws_collector_fixture(
            PaperWsCollectorConfig(
                db_path=Path(args.db),
                artifact_paths=tuple(Path(path) for path in args.artifact),
                fixture_path=Path(args.fixture),
                session_id=args.session_id,
                host_id=args.host_id,
                symbols=tuple(args.symbol or ["BTCUSDT"]),
                stream_kinds=tuple(args.stream_kind or ["aggTrade", "bookTicker", "markPrice@1s", "depth", "forceOrder"]),
                max_stream_staleness_seconds=args.max_stream_staleness_seconds,
            )
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("status") == "completed" else 2

    if args.command == "paper-ws-run":
        result = run_paper_ws_collector_live(
            PaperWsLiveCollectorConfig(
                db_path=Path(args.db),
                artifact_paths=tuple(Path(path) for path in args.artifact),
                session_id=args.session_id,
                host_id=args.host_id,
                symbols=tuple(args.symbol or ["BTCUSDT"]),
                stream_kinds=tuple(args.stream_kind or ["aggTrade", "bookTicker", "markPrice@1s", "depth", "forceOrder"]),
                max_stream_staleness_seconds=args.max_stream_staleness_seconds,
                max_messages=args.max_messages,
                max_duration_seconds=args.max_duration_seconds,
                no_message_timeout_seconds=args.no_message_timeout_seconds,
                heartbeat_interval_seconds=args.heartbeat_interval_seconds,
                reconnect_attempts=args.reconnect_attempts,
                backoff_seconds=args.backoff_seconds,
                capture_only=args.capture_only,
            )
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("status") == "completed" else 2

    if args.command == "paper-replay":
        replay = replay_paper_stream_events(Path(args.db), session_id=args.session_id)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(output_path, replay)
            replay["output"] = str(output_path)
        print(json.dumps(replay, sort_keys=True))
        return 0

    if args.command == "paper-export":
        export = export_paper_session(
            Path(args.db),
            session_id=args.session_id,
            output_dir=Path(args.output_dir),
        )
        if args.restore_smoke_db:
            export["restore_smoke"] = restore_paper_export_smoke(
                Path(export["bundle_dir"]),
                restore_db_path=Path(args.restore_smoke_db),
            )
        print(json.dumps(export, sort_keys=True))
        return 0 if export.get("status") == "exported" else 2

    if args.command == "paper-host-doctor":
        template_root = Path(args.template_root)
        if args.write_templates:
            write_hosted_paper_ops_templates(template_root)
        report = build_paper_host_doctor_report(
            HostedPaperOpsConfig(
                repo_dir=Path(args.repo_dir),
                state_dir=Path(args.state_dir),
                log_dir=Path(args.log_dir),
                backup_dir=Path(args.backup_dir),
                db_path=Path(args.db),
                template_root=template_root,
                min_free_mb=args.min_free_mb,
            )
        )
        print(json.dumps(report, sort_keys=True))
        return 0 if report.get("status") == "pass" else 2

    if args.command == "paper-book-replay":
        book_state = rebuild_and_record_paper_book_state(
            Path(args.db),
            session_id=args.session_id,
            snapshots=_load_book_snapshots(Path(args.snapshot)),
            now_utc=args.now,
            max_staleness_ms=args.max_staleness_ms,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(output_path, book_state)
            book_state["output"] = str(output_path)
        print(json.dumps(book_state, sort_keys=True))
        return 0 if book_state.get("status") == "active" else 2

    if args.command == "paper-phase9a-closeout":
        report = build_phase9a_closeout_report(
            Phase9ACloseoutConfig(
                db_path=Path(args.db),
                session_id=args.session_id,
                export_dir=Path(args.export_dir),
                restore_db_path=Path(args.restore_db),
                hosted_repo_dir=Path(args.hosted_repo_dir),
                hosted_state_dir=Path(args.hosted_state_dir),
                hosted_log_dir=Path(args.hosted_log_dir),
                hosted_backup_dir=Path(args.hosted_backup_dir),
                hosted_template_root=Path(args.hosted_template_root),
                minimum_soak_seconds=args.minimum_soak_seconds,
                require_live_network_soak=args.require_live_network_soak,
            )
        )
        if args.output:
            write_phase9a_closeout_report(Path(args.output), report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "session_id": report["session_id"],
                    "artifact_id": report["artifact_id"],
                    "blockers": report["blockers"],
                    "output": args.output,
                },
                sort_keys=True,
            )
        )
        return 0 if report.get("status") == "ready_to_close" else 2

    if args.command == "paper-soak-closeout":
        report = build_public_ws_soak_closeout_report(
            PaperSoakCloseoutConfig(
                db_path=Path(args.db),
                session_id=args.session_id,
                export_dir=Path(args.export_dir),
                restore_db_path=Path(args.restore_db),
                hosted_repo_dir=Path(args.hosted_repo_dir),
                hosted_state_dir=Path(args.hosted_state_dir),
                hosted_log_dir=Path(args.hosted_log_dir),
                hosted_backup_dir=Path(args.hosted_backup_dir),
                hosted_template_root=Path(args.hosted_template_root),
                minimum_soak_seconds=args.minimum_soak_seconds,
            )
        )
        output = write_public_ws_soak_closeout_report(Path(args.output), report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "session_id": report["session_id"],
                    "artifact_id": report["artifact_id"],
                    "blockers": report["blockers"],
                    "output": str(output),
                },
                sort_keys=True,
            )
        )
        return 0 if report.get("status") == "ready_to_close" else 2

    if args.command == "no-key-executor-chaos":
        config = NoKeyExecutorConfig(
            db_path=Path(args.db),
            scenario_id=str(args.scenario),
            session_id=str(args.session_id),
        )
        order_request = NoKeyOrderRequest(
            symbol=str(args.symbol),
            side=str(args.side).upper(),
            qty=float(args.qty),
            price=float(args.price),
            client_order_id=str(args.client_order_id),
        )
        if args.scenario == "all":
            report = run_phase2_chaos_replay(config, order_request=order_request)
        else:
            report = run_single_chaos_scenario(config, order_request=order_request, scenario_id=str(args.scenario))
        output = write_no_key_executor_report(Path(args.output), report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "scenario_id": report["scenario_id"],
                    "private_keys_required": report["private_keys_required"],
                    "live_order_path_enabled": report["live_order_path_enabled"],
                    "output": str(output),
                },
                sort_keys=True,
            )
        )
        return 0

    if args.command == "phase3-reconcile":
        snapshot = load_gateway_snapshot(Path(args.snapshot))
        report = reconcile_projection_with_gateway(
            Path(args.db),
            snapshot,
            operator_id=str(args.operator_id),
            artifact_id=str(args.artifact_id),
        )
        output = write_reconciliation_report(Path(args.output), report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "blocker_codes": report["blocker_codes"],
                    "safe_actions": report["safe_actions"],
                    "output": str(output),
                },
                sort_keys=True,
            )
        )
        return 0 if report.get("status") == "matched" else 2

    if args.command == "portfolio-plan":
        candidates, constraints, active_regimes = _load_portfolio_plan_inputs(Path(args.input))
        plan = build_portfolio_plan(candidates, constraints, active_regimes=active_regimes)
        artifact = build_portfolio_artifact(plan)
        dashboard = build_portfolio_risk_dashboard(plan)
        response = {"artifact": artifact, "dashboard": dashboard}
        if args.db:
            response["persisted_plan_id"] = persist_portfolio_plan(Path(args.db), plan)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(output_path, artifact)
            response["output"] = str(output_path)
        print(json.dumps(response, sort_keys=True))
        return 0 if plan.accepted else 2

    if args.command == "paper-portfolio-loop":
        payload = build_paper_portfolio_loop_input(Path(args.input))
        result = run_paper_portfolio_allocator_tick(
            PaperPortfolioLoopConfig(
                db_path=Path(args.db),
                session_id=args.session_id,
                constraints=payload["constraints"],  # type: ignore[arg-type]
                active_regimes=payload["active_regimes"],  # type: ignore[arg-type]
                interval_seconds=int(payload["interval_seconds"]),
                min_calibration_samples=int(payload["min_calibration_samples"]),
                max_paper_slip_bps=float(payload["max_paper_slip_bps"]),
            )
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(output_path, result)
            result["output"] = str(output_path)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("status") == "accepted" else 2

    if args.command == "portfolio-override":
        result = apply_human_override(
            Path(args.db),
            HumanOverrideRequest(
                action=args.action,
                operator_id=args.operator_id,
                artifact_id=args.artifact_id,
                confirmation=args.confirmation,
                reason=args.reason,
            ),
        )
        print(json.dumps(asdict(result), sort_keys=True))
        return 0 if result.applied else 2

    if args.command == "calibrate-cost-capacity":
        measurements = load_order_telemetry_measurements(Path(args.db))
        model = fit_impact_calibration(
            measurements,
            source_model_version=args.source_model_version,
            minimum_orders_per_bucket=args.minimum_orders_per_bucket,
            max_participation_rate=args.max_participation_rate,
        )
        report = build_capacity_report(
            measurements,
            model=model,
            baseline_edge_bps=args.baseline_edge_bps,
            max_participation_rate=args.max_participation_rate,
        )
        artifact = build_cost_capacity_calibration_artifact(
            model=model,
            capacity_report=report,
            source=str(Path(args.db)),
        )
        write_cost_capacity_calibration_artifact(Path(args.output), artifact)
        print(
            json.dumps(
                {
                    "output": str(Path(args.output)),
                    "cost_model_version": artifact["cost_model_version"],
                    "status": artifact["status"],
                    "sample_count": model.sample_count,
                    "capacity_passed": report.passed,
                    "failure_reasons": report.failure_reasons,
                },
                sort_keys=True,
            )
        )
        return 0 if model.sample_count > 0 else 2

    if args.command == "paper-calibration-feedback":
        artifact = build_paper_calibration_feedback(
            PaperCalibrationFeedbackConfig(
                db_path=Path(args.db),
                session_id=args.session_id,
                source_model_version=args.source_model_version,
                minimum_samples_per_bucket=args.minimum_samples_per_bucket,
                shrinkage_alpha=args.shrinkage_alpha,
            )
        )
        write_paper_calibration_feedback_artifact(Path(args.output), artifact)
        persist_paper_calibration_feedback(Path(args.db), artifact)
        print(
            json.dumps(
                {
                    "output": str(Path(args.output)),
                    "artifact_id": artifact["artifact_id"],
                    "status": artifact["status"],
                    "sample_count": artifact["sample_count"],
                    "telemetry_quality_score": artifact["telemetry_quality"]["score"],
                    "live_promotion_allowed": artifact["live_promotion_allowed"],
                    "can_lower_live_costs": artifact["can_lower_live_costs"],
                },
                sort_keys=True,
            )
        )
        return 0 if artifact.get("sample_count", 0) else 2

    if args.command == "paper-post-run-summary":
        summary = build_paper_post_run_summary(
            PaperPostRunSummaryConfig(
                db_path=Path(args.db),
                session_id=args.session_id,
                max_items=args.max_items,
            )
        )
        write_paper_post_run_summary_artifact(Path(args.output), summary)
        print(
            json.dumps(
                {
                    "output": str(Path(args.output)),
                    "artifact_id": summary["artifact_id"],
                    "status": summary["status"],
                    "top_failure_reason_count": len(summary["top_failure_reasons"]),
                    "weak_artifact_count": len(summary["weak_artifacts"]),
                    "suggested_next_experiment_count": len(summary["suggested_next_experiments"]),
                },
                sort_keys=True,
            )
        )
        return 0

    if args.command == "lifecycle-status":
        print(json.dumps(lifecycle_status(Path(args.db), args.artifact_id), sort_keys=True))
        return 0

    if args.command == "inspect-study":
        study = load_study_config(Path(args.config))
        print(build_study_summary(study))
        return 0

    if args.command == "loop-readiness":
        config_path = Path(args.config)
        report = build_loop_readiness_report(load_study_config(config_path), config_path=config_path)
        if args.output:
            write_json_atomic(Path(args.output), report)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["eligible"] else 2

    if args.command == "loop-readiness-scan":
        report = build_loop_readiness_scan(Path(args.dir))
        if args.output:
            write_json_atomic(Path(args.output), report)
        print(json.dumps(report, sort_keys=True))
        if args.require_eligible and report["eligible_count"] <= 0:
            return 2
        return 0

    if args.command == "doctor":
        payload = build_release_doctor_payload(Path.cwd())
        print(render_release_doctor_payload(payload, fmt=args.format))
        return 0

    if args.command == "export-schema":
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(output_path, build_study_schema())
        print(json.dumps({"schema_path": str(output_path)}, sort_keys=True))
        return 0

    if args.command == "refresh-examples":
        output_dir = Path(args.dir)
        write_repo_example_artifacts(output_dir)
        print(json.dumps({"examples_dir": str(output_dir)}, sort_keys=True))
        return 0

    if args.command == "summarize-run":
        payload = load_dashboard_payload(Path(args.dashboard))
        print(build_dashboard_summary(payload, phase_filter=args.phase_filter, top_candidates=args.top))
        return 0

    if args.command == "summarize-autoresearch":
        payload = load_autoresearch_report_payload(Path(args.autoresearch_report))
        print(build_autoresearch_summary(payload))
        return 0

    if args.command == "summarize-batch":
        payload = load_batch_report_payload(Path(args.batch_report))
        print(build_batch_summary(payload, top_variants=args.top))
        return 0

    if args.command == "summarize-campaign":
        payload = load_campaign_report_payload(Path(args.campaign_report))
        print(build_campaign_summary(payload))
        return 0

    if args.command == "inspect-campaign":
        payload = expand_campaign_manifest(Path(args.manifest), Path(args.manifest).with_suffix(".campaign.json"))
        print(build_campaign_manifest_summary(payload))
        return 0

    if args.command == "retry-campaign":
        output_report_path = Path(args.output_report)
        retry_manifest_path = output_report_path.with_suffix(".retry-manifest.json")
        retry_manifest = build_retry_campaign_manifest(
            Path(args.campaign_report),
            output_report_path,
            entry_status=args.entry_status,
        )
        retry_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(retry_manifest_path, retry_manifest)
        payload = _run_campaign_manifest(retry_manifest_path, output_report_path)
        payload.update(
            {
                "source_campaign_report_path": str(Path(args.campaign_report)),
                "retry_manifest_path": str(retry_manifest_path),
                "entry_status": args.entry_status,
            }
        )
        print(json.dumps(payload, sort_keys=True))
        return 0

    if args.command == "select-batch-variant":
        payload = load_batch_report_payload(Path(args.batch_report))
        selected_variant, selected_path = _resolve_batch_variant_selection(payload, args.variant)
        selected_variant_result = _find_batch_variant_result(payload, selected_variant)
        preferred_variant_result = payload.get("preferred_variant")
        output_config_path = selected_path
        if args.output_config:
            output_config_path = Path(args.output_config)
            output_config_path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(output_config_path, selected_path.read_text(encoding="utf-8"))

        response = {
            "selected_variant": selected_variant,
            "source_config_path": str(selected_path),
            "output_config_path": str(output_config_path),
        }
        _extend_response_with_variant_profile_rationale(
            response,
            selected_variant_result,
            preferred_variant_result=preferred_variant_result,
        )

        print(json.dumps(response, sort_keys=True))
        return 0

    if args.command == "continue-batch":
        batch_payload = load_batch_report_payload(Path(args.batch_report))
        selected_variant, selected_path = _resolve_batch_variant_selection(batch_payload, args.variant)
        selected_variant_result = _find_batch_variant_result(batch_payload, selected_variant)
        preferred_variant_result = batch_payload.get("preferred_variant")
        selected_payload = json.loads(selected_path.read_text(encoding="utf-8"))
        base_run_id = str(selected_payload.get("run_id", selected_path.stem))
        continued_run_id = f"{base_run_id}-continued"
        selected_payload["run_id"] = continued_run_id
        selected_payload["research_lineage"] = {
            "selected_variant": selected_variant,
            "selection_source": "batch_report",
            "selection_preference_mode": args.variant,
            "selection_variant_result": selected_variant_result if isinstance(selected_variant_result, dict) else {},
            "parent_batch_run_id": batch_payload.get("run_id"),
            "parent_batch_report_path": str(Path(args.batch_report)),
            "source_config_path": str(selected_path),
        }
        continued_output_dir = Path(args.output_dir)
        continued_output_dir.mkdir(parents=True, exist_ok=True)
        continued_config_path = continued_output_dir / f"{continued_run_id}.continued-study.json"
        write_json_atomic(continued_config_path, selected_payload)

        study = _apply_strict_quality_override(load_study_config(continued_config_path), args.strict_quality)
        _enforce_snapshot_quality(study, continued_config_path)
        response = _run_autoresearch_execution(
            config_path=continued_config_path,
            base_payload=selected_payload,
            study=study,
            output_dir=continued_output_dir,
            db_path=Path(args.db),
            memory_dir=Path(args.memory_dir) if args.memory_dir else None,
            memory_limit=args.memory_limit,
            memory_quality_policy=args.memory_quality_policy,
            log_path=build_run_log_path(continued_output_dir, study.run_id),
            allow_duplicate_study_signature=True,
        )
        duplicate_baseline_history = load_duplicate_baseline_variant_history_for_lineage(
            db_path=Path(args.db),
            research_lineage=study.research_lineage,
            memory_quality_policy=args.memory_quality_policy,
        )
        response.update(
            {
                "selected_variant": selected_variant,
                "source_config_path": str(selected_path),
                "continued_config_path": str(continued_config_path),
            }
        )
        _extend_response_with_variant_profile_rationale(
            response,
            selected_variant_result,
            preferred_variant_result=preferred_variant_result,
        )
        print(json.dumps(response, sort_keys=True))
        return 0

    if args.command == "continue-accepted-duplicate":
        report_path = Path(args.autoresearch_report)
        report_payload = load_autoresearch_report_payload(report_path)
        accepted_config_path = _resolve_accepted_duplicate_path(report_payload)
        accepted_payload = json.loads(accepted_config_path.read_text(encoding="utf-8"))
        base_run_id = str(accepted_payload.get("run_id", accepted_config_path.stem))
        continued_run_id = f"{base_run_id}-continued"
        accepted_payload["run_id"] = continued_run_id
        lineage = accepted_payload.get("research_lineage", {})
        if not isinstance(lineage, dict):
            lineage = {}
        accepted_payload["research_lineage"] = {
            **lineage,
            "accepted_duplicate_source_config_path": str(accepted_config_path),
            "accepted_duplicate_source_report_path": str(report_path),
        }
        continued_output_dir = Path(args.output_dir)
        continued_output_dir.mkdir(parents=True, exist_ok=True)
        continued_config_path = continued_output_dir / f"{continued_run_id}.continued-study.json"
        write_json_atomic(continued_config_path, accepted_payload)

        study = _apply_strict_quality_override(load_study_config(continued_config_path), args.strict_quality)
        _enforce_snapshot_quality(study, continued_config_path)
        response = _run_autoresearch_execution(
            config_path=continued_config_path,
            base_payload=accepted_payload,
            study=study,
            output_dir=continued_output_dir,
            db_path=Path(args.db),
            memory_dir=Path(args.memory_dir) if args.memory_dir else None,
            memory_limit=args.memory_limit,
            memory_quality_policy=args.memory_quality_policy,
            log_path=build_run_log_path(continued_output_dir, study.run_id),
            allow_duplicate_study_signature=True,
        )
        duplicate_baseline_history = load_duplicate_baseline_variant_history_for_lineage(
            db_path=Path(args.db),
            research_lineage=study.research_lineage,
            memory_quality_policy=args.memory_quality_policy,
        )
        response.update(
            {
                "source_config_path": str(accepted_config_path),
                "continued_config_path": str(continued_config_path),
            }
        )
        _extend_response_with_variant_profile_rationale(
            response,
            {"duplicate_baseline_history": duplicate_baseline_history.get("balanced", {})},
        )
        print(json.dumps(response, sort_keys=True))
        return 0

    if args.command == "trace-lineage":
        report_payload = json.loads(Path(args.autoresearch_report).read_text(encoding="utf-8"))
        print(_format_lineage_summary(report_payload))
        return 0

    if args.command == "trace-audit-export":
        report_path = Path(args.agent_loop_report)
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report_payload, dict):
            raise SystemExit("agent-loop report must be a JSON object")
        payload = build_trace_audit_export(report_payload, source_path=str(report_path))
        output_path = write_trace_audit_export(Path(args.output), payload)
        print(json.dumps({**payload, "output": str(output_path)}, sort_keys=True))
        return 0

    if args.command == "loop-evidence-ledger":
        payload = build_loop_evidence_ledger(
            agent_loop_report_paths=[Path(path) for path in args.agent_loop_report],
            readiness_scan_paths=[Path(path) for path in args.readiness_scan],
            readiness_report_paths=[Path(path) for path in args.readiness_report],
            paper_dashboard_paths=[Path(path) for path in args.paper_dashboard],
            paper_postrun_summary_paths=[Path(path) for path in args.paper_postrun_summary],
            paper_calibration_feedback_paths=[Path(path) for path in args.paper_calibration_feedback],
        )
        write_json_atomic(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True))
        return 0

    if args.command == "feature-causality-audit":
        input_payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        if not isinstance(input_payload, dict):
            raise SystemExit("feature-causality-audit input must be a JSON object")
        payload = build_feature_causality_audit_report(input_payload)
        write_json_atomic(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload.get("passed") else 2

    if args.command == "strategy-tournament":
        input_payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        if isinstance(input_payload, dict):
            rows = input_payload.get("rows", input_payload.get("candidates", []))
        else:
            rows = input_payload
        if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
            raise SystemExit("strategy-tournament input must be a JSON array or object containing rows/candidates")
        payload = build_strategy_tournament_report(
            [dict(item) for item in rows],
            minimum_bucket_count=args.minimum_bucket_count,
        )
        write_json_atomic(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload.get("status") == "ready" else 2

    if args.command == "robust-evaluate":
        input_payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        if not isinstance(input_payload, dict):
            raise SystemExit("robust-evaluate input must be a JSON object")
        payload = build_robust_evaluation_scorecard(input_payload)
        write_json_atomic(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload.get("robustness_ready") else 2

    if args.command == "sealed-holdout-check":
        input_payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        if not isinstance(input_payload, dict):
            raise SystemExit("sealed-holdout-check input must be a JSON object")
        payload = build_sealed_holdout_check(input_payload)
        write_json_atomic(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload.get("passed") else 2

    if args.command == "paper-forward-score":
        payload = build_paper_forward_score(_paper_forward_payload_from_args(args))
        write_json_atomic(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload.get("status") == "ready" else 2

    if args.command == "strategy-evidence-card":
        payload = build_strategy_evidence_card(_strategy_evidence_card_payload_from_args(args))
        write_json_atomic(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload.get("can_claim_strategy_improvement") else 2

    if args.command == "loop-improvement-gate":
        payload = build_loop_improvement_gate(
            ledger_path=Path(args.ledger),
            paper_dashboard_path=Path(args.paper_dashboard),
            postrun_summary_path=Path(args.postrun_summary),
            calibration_feedback_path=Path(args.calibration_feedback),
            data_sufficiency_path=Path(args.data_sufficiency) if args.data_sufficiency else None,
            max_abs_slip_bps=args.max_abs_slip_bps,
            minimum_paper_orders=args.minimum_paper_orders,
            minimum_telemetry_quality=args.minimum_telemetry_quality,
        )
        write_json_atomic(Path(args.output), payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["strategy_improvement_supported"] else 2

    if args.command == "trace-audit-ingest":
        advisory_path = Path(args.advisory_report)
        advisory_payload = json.loads(advisory_path.read_text(encoding="utf-8"))
        if not isinstance(advisory_payload, dict):
            raise SystemExit("advisory report must be a JSON object")
        trace_export = None
        if args.trace_export:
            trace_payload = json.loads(Path(args.trace_export).read_text(encoding="utf-8"))
            if not isinstance(trace_payload, dict):
                raise SystemExit("trace export must be a JSON object")
            trace_export = trace_payload
        payload = build_controlled_trace_advisory(advisory_payload, trace_export=trace_export)
        output_path = write_trace_advisory_notes(Path(args.output), payload)
        print(json.dumps({**payload, "output": str(output_path)}, sort_keys=True))
        return 0

    if args.command == "research-debate-report":
        candidate_path = Path(args.candidate_report)
        candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        if not isinstance(candidate_payload, dict):
            raise SystemExit("candidate report must be a JSON object")
        trace_advisory_notes = None
        if args.trace_advisory_notes:
            notes_payload = json.loads(Path(args.trace_advisory_notes).read_text(encoding="utf-8"))
            if not isinstance(notes_payload, dict):
                raise SystemExit("trace advisory notes must be a JSON object")
            trace_advisory_notes = notes_payload
        payload = build_report_only_research_debate(
            candidate_payload,
            trace_advisory_notes=trace_advisory_notes,
            source_path=str(candidate_path),
        )
        output_path = write_research_debate_report(Path(args.output), payload)
        print(json.dumps({**payload, "output": str(output_path)}, sort_keys=True))
        return 0

    if args.command == "compare-runs":
        if args.kind == "runcard":
            payload = compare_runcards(load_runcard(Path(args.left)), load_runcard(Path(args.right)))
        elif args.kind == "autoresearch":
            payload = compare_autoresearch_payloads(
                load_autoresearch_report_payload(Path(args.left)),
                load_autoresearch_report_payload(Path(args.right)),
            )
        elif args.kind == "batch":
            payload = compare_batch_payloads(
                load_batch_report_payload(Path(args.left)),
                load_batch_report_payload(Path(args.right)),
            )
        elif args.kind == "campaign":
            payload = compare_campaign_payloads(
                load_campaign_report_payload(Path(args.left)),
                load_campaign_report_payload(Path(args.right)),
            )
        else:
            left_payload = load_dashboard_payload(Path(args.left))
            right_payload = load_dashboard_payload(Path(args.right))
            payload = compare_dashboard_payloads(left_payload, right_payload)
        rendered = format_compare_payload(payload) if args.format == "text" else json.dumps(payload, sort_keys=True)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if args.format == "text":
                write_text_atomic(output_path, rendered)
            else:
                write_json_atomic(output_path, payload)
        print(rendered)
        return 0

    if args.command == "compare-duplicate-match":
        report_payload = load_autoresearch_report_payload(Path(args.autoresearch_report))
        duplicate_match = report_payload.get("duplicate_match", {})
        if not isinstance(duplicate_match, dict) or not isinstance(duplicate_match.get("run_id"), str):
            raise SystemExit("autoresearch report does not include duplicate_match.run_id")
        matched_rows = query_run_memory(Path(args.db), run_id=str(duplicate_match["run_id"]), limit=1)
        if not matched_rows:
            raise SystemExit(f"matched run '{duplicate_match['run_id']}' was not found in research memory")
        config_payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
        payload = build_duplicate_match_compare(report_payload, config_payload, matched_rows[0])
        rendered = format_duplicate_match_compare(payload) if args.format == "text" else json.dumps(payload, sort_keys=True)
        print(rendered)
        return 0

    if args.command == "accept-duplicate-match":
        report_payload = load_autoresearch_report_payload(Path(args.autoresearch_report))
        duplicate_match = report_payload.get("duplicate_match", {})
        if not isinstance(duplicate_match, dict) or not isinstance(duplicate_match.get("run_id"), str):
            raise SystemExit("autoresearch report does not include duplicate_match.run_id")
        matched_rows = query_run_memory(Path(args.db), run_id=str(duplicate_match["run_id"]), limit=1)
        if not matched_rows:
            raise SystemExit(f"matched run '{duplicate_match['run_id']}' was not found in research memory")
        config_payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
        accepted_payload = build_accepted_duplicate_payload(
            config_payload,
            matched_rows[0],
            source_report_path=str(Path(args.autoresearch_report)),
        )
        output_path = Path(args.output_config)
        write_next_study_payload(output_path, accepted_payload)
        print(
            json.dumps(
                {
                    "matched_run_id": matched_rows[0].get("run_id"),
                    "output_config_path": str(output_path),
                    "run_id": accepted_payload.get("run_id"),
                },
                sort_keys=True,
            )
        )
        return 0

    if args.command == "list-runs":
        runcards, skipped_malformed = load_runcard_records(Path(args.dir))
        filtered = filter_runcards(
            runcards,
            decision=args.decision,
            symbol=args.symbol,
            quality_status=args.quality_status,
        )
        ranked = rank_runcards(filtered, sort_by=args.sort_by, limit=args.limit)
        rendered = render_runcard_listing(ranked, sort_by=args.sort_by, fmt=args.format)
        if args.format == "text" and skipped_malformed:
            rendered = f"{rendered}\nskipped malformed runcards: {skipped_malformed}"
        print(rendered)
        if args.format == "json" and skipped_malformed:
            logger.warning("Skipped malformed runcards: %s", skipped_malformed)
        return 0

    if args.command == "list-campaigns":
        reports, skipped_malformed = load_campaign_report_records(Path(args.dir))
        filtered = filter_campaign_reports(reports, status=args.status)
        ranked = rank_campaign_reports(filtered, sort_by=args.sort_by, limit=args.limit)
        rendered = render_campaign_listing(ranked, sort_by=args.sort_by, fmt=args.format)
        if args.format == "text" and skipped_malformed:
            rendered = f"{rendered}\nskipped malformed campaigns: {skipped_malformed}"
        print(rendered)
        if args.format == "json" and skipped_malformed:
            logger.warning("Skipped malformed campaigns: %s", skipped_malformed)
        return 0

    if args.command == "ingest-memory":
        db_path = Path(args.db)
        initialize_memory_db(db_path)
        ingested_runs = ingest_artifact_directory(db_path, Path(args.dir))
        print(json.dumps({"db_path": str(db_path), "ingested_runs": ingested_runs}, sort_keys=True))
        return 0

    if args.command == "query-memory":
        rows = query_run_memory(
            Path(args.db),
            symbol=args.symbol,
            layer=args.layer,
            decision=args.decision,
            quality_status=args.quality_status,
            build_version=args.build_version,
            source_hash=args.source_hash,
            selected_variant=args.selected_variant,
            parent_batch_run_id=args.parent_batch_run_id,
            accepted_duplicate_match_run_id=args.accepted_duplicate_match_run_id,
            candidate_pressure_only=args.candidate_pressure_only,
            sort_by=args.sort_by,
            limit=args.limit,
        )
        print(render_memory_query(rows, fmt=args.format))
        return 0

    if args.command == "query-candidate-trials":
        rows = query_candidate_trials(
            Path(args.db),
            run_id=args.run_id,
            layer_name=args.layer,
            decision=args.decision,
            pressured_only=args.pressured_only,
            sort_by=args.sort_by,
            limit=args.limit,
        )
        print(render_candidate_trial_query(rows, fmt=args.format))
        return 0

    if args.command == "query-validation-runs":
        rows = query_validation_runs(
            Path(args.db),
            run_id=args.run_id,
            validation_status=args.validation_status,
            min_deflated_sharpe_ratio=args.min_dsr,
            max_pbo_score=args.max_pbo,
            limit=args.limit,
        )
        print(render_validation_run_query(rows, fmt=args.format))
        return 0

    if args.command == "query-stress-runs":
        rows = query_stress_runs(
            Path(args.db),
            run_id=args.run_id,
            scenario_name=args.scenario_name,
            passed=(args.passed == "true") if args.passed is not None else None,
            target_regime=args.target_regime,
            limit=args.limit,
        )
        print(render_stress_run_query(rows, fmt=args.format))
        return 0

    if args.command == "query-agent-decisions":
        rows = query_agent_decisions(
            Path(args.db),
            run_id=args.run_id,
            decision_family=args.decision_family,
            decision=args.decision,
            validation_status=args.validation_status,
            limit=args.limit,
        )
        print(render_agent_decision_query(rows, fmt=args.format))
        return 0

    if args.command == "query-data-snapshots":
        rows = query_data_snapshots(
            Path(args.db),
            snapshot_id=args.snapshot_id,
            symbol=args.symbol,
            venue=args.venue,
            build_version=args.build_version,
            source_hash=args.source_hash,
            quality_status=args.quality_status,
            limit=args.limit,
        )
        print(render_data_snapshot_query(rows, fmt=args.format))
        return 0

    if args.command == "query-resource-index":
        rows = query_resource_index(
            Path(args.db),
            resource_group=args.resource_group,
            status=args.status,
            license=args.license,
            intended_usage=args.intended_usage,
            limit=args.limit,
        )
        print(render_resource_index_query(rows, fmt=args.format))
        return 0

    if args.command == "query-run-resource-links":
        rows = query_run_resource_links(
            Path(args.db),
            run_id=args.run_id,
            resource_id=args.resource_id,
            link_role=args.link_role,
            evidence_source=args.evidence_source,
            limit=args.limit,
        )
        print(render_run_resource_link_query(rows, fmt=args.format))
        return 0

    if args.command == "query-meta-policies":
        rows = query_meta_policies(
            Path(args.db),
            run_id=args.run_id,
            policy_family=args.policy_family,
            status=args.status,
            eval_validation_run_id=args.eval_validation_run_id,
            limit=args.limit,
        )
        print(render_meta_policy_query(rows, fmt=args.format))
        return 0

    if args.command == "summarize-memory":
        all_rows = query_run_memory(Path(args.db), symbol=args.symbol)
        selected_rows = select_memory_rows(
            all_rows,
            memory_quality_policy=args.memory_quality_policy,
            limit=args.limit,
        )
        summary = build_memory_summary(
            selected_rows,
            excluded_dirty_runs=count_excluded_dirty_rows(all_rows, selected_rows),
            memory_quality_policy=args.memory_quality_policy,
        )
        print(render_memory_summary(summary, fmt=args.format))
        return 0

    if args.command == "project-status":
        status_json_path = Path(args.status_json)
        payload = load_project_status(status_json_path)
        if args.project_status_action == "update":
            try:
                payload = update_project_status(
                    payload,
                    phase_id=args.phase,
                    status=args.status,
                    note=args.note,
                    next_phase_id=args.set_next,
                    execution_state=args.execution_state,
                )
            except ValueError as exc:
                raise SystemExit(str(exc))
            write_project_status(
                status_json_path=status_json_path,
                payload=payload,
            )
        print(
            render_project_status(
                payload,
                fmt=args.format,
                status_json_path=status_json_path,
            )
        )
        return 0

    if args.command == "list-skills":
        contracts = load_repo_skill_contracts()
        payload = _render_skill_contracts_payload(contracts)
        if args.format == "json":
            print(json.dumps(payload, sort_keys=True))
        else:
            print(_render_skill_contracts_text(contracts))
        return 0

    if args.command == "inspect-skill":
        contract = find_skill_contract(args.name)
        payload = _render_skill_contracts_payload([contract])["skills"][0]
        if args.format == "json":
            print(json.dumps(payload, sort_keys=True))
        else:
            print(_render_skill_contract_text(contract))
        return 0

    if args.command == "run-campaign":
        payload = _run_campaign_manifest(Path(args.manifest), Path(args.output_report))
        print(json.dumps(payload, sort_keys=True))
        return 0

    if args.command == "mcp-list-profiles":
        from engine.mcp.profiles import list_profile_names
        print(json.dumps({"profiles": list_profile_names()}, sort_keys=True))
        return 0

    if args.command == "mcp-list-tools":
        from engine.mcp.config import MCPProfile
        from engine.mcp.server import build_mcp_server
        profile = MCPProfile(args.profile)
        server = build_mcp_server(
            profile,
            output_dir=Path("."),
            db_path=Path("outputs/research-memory.sqlite"),
        )
        print(json.dumps(server.describe(), indent=2, sort_keys=True))
        return 0

    if args.command == "mcp-call":
        from engine.mcp.config import MCPProfile
        from engine.mcp.server import build_mcp_server
        profile = MCPProfile(args.profile)
        params = json.loads(args.params)
        server = build_mcp_server(
            profile,
            output_dir=Path(args.output_dir),
            db_path=Path(args.db),
        )
        result = server.call_tool(args.tool, params)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0

    if args.command == "autoresearch":
        base_payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
        study = _apply_strict_quality_override(load_study_config(Path(args.config)), args.strict_quality)
        _enforce_snapshot_quality(study, Path(args.config))
        payload = _run_autoresearch_execution(
            config_path=Path(args.config),
            base_payload=base_payload,
            study=study,
            output_dir=Path(args.output_dir),
            db_path=Path(args.db),
            memory_dir=Path(args.memory_dir) if args.memory_dir else None,
            memory_limit=args.memory_limit,
            memory_quality_policy=args.memory_quality_policy,
            log_path=build_run_log_path(Path(args.output_dir), study.run_id),
        )
        print(json.dumps(payload, sort_keys=True))
        return 0

    if args.command == "batch-autoresearch":
        base_payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
        study = _apply_strict_quality_override(load_study_config(Path(args.config)), args.strict_quality)
        _enforce_snapshot_quality(study, Path(args.config))
        payload = _run_batch_autoresearch_execution(
            config_path=Path(args.config),
            base_payload=base_payload,
            study=study,
            output_dir=Path(args.output_dir),
            db_path=Path(args.db),
            memory_dir=Path(args.memory_dir) if args.memory_dir else None,
            memory_limit=args.memory_limit,
            memory_quality_policy=args.memory_quality_policy,
            log_path=build_run_log_path(Path(args.output_dir), study.run_id),
        )
        print(json.dumps(payload, sort_keys=True))
        return 0

    if args.command == "agent-loop":
        config_path = Path(args.config)
        base_payload = json.loads(config_path.read_text(encoding="utf-8"))
        study = _apply_strict_quality_override(load_study_config(config_path), args.strict_quality)
        _enforce_snapshot_quality(study, config_path)
        readiness_report = None
        readiness_report_path = Path(args.readiness_report_output) if args.readiness_report_output else None
        if args.readiness_report_output or args.require_loop_readiness:
            readiness_report = build_loop_readiness_report(study, config_path=config_path)
            if readiness_report_path:
                write_json_atomic(readiness_report_path, readiness_report)
        if args.require_loop_readiness:
            if args.evidence_ledger_output and readiness_report_path and not bool((readiness_report or {}).get("eligible", False)):
                evidence_ledger = build_loop_evidence_ledger(
                    agent_loop_report_paths=[],
                    readiness_scan_paths=[],
                    readiness_report_paths=[readiness_report_path],
                )
                write_json_atomic(Path(args.evidence_ledger_output), evidence_ledger)
            _enforce_loop_readiness(study, config_path, readiness_report)
        controller = AgentLoopController(
            settings=AgentLoopSettings(
                loop_mode=args.loop_mode,
                karpathy_execution_mode=args.karpathy_execution,
                karpathy_git_execute_actions=args.karpathy_execute_git_actions,
                karpathy_target_path=args.karpathy_target_path,
                karpathy_target_kind=args.karpathy_target_kind,
                max_iterations=args.iterations,
                run_budget=args.run_budget,
                memory_limit=args.memory_limit,
                memory_quality_policy=args.memory_quality_policy,
                trace_advisory_notes_path=args.trace_advisory_notes,
                improvement_gate_path=args.improvement_gate,
                strict_quality=args.strict_quality,
            )
        )
        report = controller.run(
            initial_payload=base_payload,
            output_dir=Path(args.output_dir),
            db_path=Path(args.db),
        )
        evidence_ledger_path = None
        if args.evidence_ledger_output:
            evidence_ledger = build_loop_evidence_ledger(
                agent_loop_report_paths=[Path(report["report_path"])],
                readiness_scan_paths=[],
                readiness_report_paths=[readiness_report_path] if readiness_report_path else [],
            )
            evidence_ledger_path = write_json_atomic(Path(args.evidence_ledger_output), evidence_ledger)
        print(
            json.dumps(
                {
                    "run_id": study.run_id,
                    "status": report["status"],
                    "mode_runtime": report["mode_runtime"],
                    "loop_mode_requested": report["loop_mode_requested"],
                    "loop_mode": report["loop_mode"],
                    "loop_mode_selection_reason": report["loop_mode_selection_reason"],
                    "stop_reason": report["stop_reason"],
                    "iteration_count": report["iteration_count"],
                    "completed_run_ids": report["completed_run_ids"],
                    "promoted_run_ids": report["promoted_run_ids"],
                    "agent_loop_report_path": report["report_path"],
                    "agent_loop_evidence_ledger_path": str(evidence_ledger_path) if evidence_ledger_path else None,
                    "trace_advisory_summary": report.get("trace_advisory_summary"),
                    "karpathy_summary": report.get("karpathy_summary"),
                    "karpathy_decisions": report.get("karpathy_decisions"),
                    "karpathy_execution_mode": report.get("karpathy_execution_mode"),
                    "karpathy_target_path": report.get("karpathy_target_path"),
                    "karpathy_target_kind": report.get("karpathy_target_kind"),
                    "karpathy_latest_program_result": report.get("karpathy_latest_program_result"),
                    "karpathy_latest_program_result_mode": report.get("karpathy_latest_program_result_mode"),
                    "karpathy_program_runtime": report.get("karpathy_program_runtime"),
                    "karpathy_git_state": report.get("karpathy_git_state"),
                    "karpathy_git_action_plan": report.get("karpathy_git_action_plan"),
                    "karpathy_git_execution": report.get("karpathy_git_execution"),
                    "karpathy_working_config_path": report.get("karpathy_working_config_path"),
                    "karpathy_incumbent_artifact_path": report.get("karpathy_incumbent_artifact_path"),
                    "karpathy_ledger_artifact_path": report.get("karpathy_ledger_artifact_path"),
                    "karpathy_results_tsv_path": report.get("karpathy_results_tsv_path"),
                    "karpathy_program_runtime_artifact_path": report.get("karpathy_program_runtime_artifact_path"),
                    "karpathy_git_state_artifact_path": report.get("karpathy_git_state_artifact_path"),
                    "karpathy_git_action_plan_artifact_path": report.get("karpathy_git_action_plan_artifact_path"),
                    "karpathy_git_execution_artifact_path": report.get("karpathy_git_execution_artifact_path"),
                },
                sort_keys=True,
            )
        )
        return 0

    if args.command == "guarded-loop-cycle":
        payload = run_guarded_loop_cycle(
            GuardedLoopCycleSettings(
                config_path=Path(args.config),
                output_dir=Path(args.output_dir),
                db_path=Path(args.db),
                liquidations_path=Path(args.liquidations) if args.liquidations else None,
                hydrated_config_path=Path(args.hydrated_config) if args.hydrated_config else None,
                iterations=args.iterations,
                run_budget=args.run_budget,
                loop_mode=args.loop_mode,
                karpathy_execution=args.karpathy_execution,
                karpathy_target_path=args.karpathy_target_path,
                karpathy_target_kind=args.karpathy_target_kind,
                karpathy_execute_git_actions=args.karpathy_execute_git_actions,
                memory_limit=args.memory_limit,
                memory_quality_policy=args.memory_quality_policy,
                trace_advisory_notes_path=args.trace_advisory_notes,
                improvement_gate_path=args.improvement_gate,
                paper_dashboard_path=Path(args.paper_dashboard) if args.paper_dashboard else None,
                paper_postrun_summary_path=Path(args.paper_postrun_summary) if args.paper_postrun_summary else None,
                paper_calibration_feedback_path=Path(args.paper_calibration_feedback)
                if args.paper_calibration_feedback
                else None,
                max_abs_slip_bps=args.max_abs_slip_bps,
                minimum_paper_orders=args.minimum_paper_orders,
                minimum_telemetry_quality=args.minimum_telemetry_quality,
            )
        )
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["status"] not in {"blocked_sidecar_not_ready", "blocked_hydration_not_ready", "blocked_loop_readiness", "blocked_paper_feedback_incomplete"} else 2

    if args.command == "guarded-loop-repeat":
        payload = run_guarded_loop_repeat(
            GuardedLoopRepeatSettings(
                output_dir=Path(args.output_dir),
                db_path=Path(args.db),
                study_dir=Path(args.study_dir) if args.study_dir else None,
                config_path=Path(args.config) if args.config else None,
                liquidations_path=Path(args.liquidations) if args.liquidations else None,
                hydrated_config_path=Path(args.hydrated_config) if args.hydrated_config else None,
                max_cycles=args.max_cycles,
                iterations=args.iterations,
                run_budget=args.run_budget,
                loop_mode=args.loop_mode,
                karpathy_execution=args.karpathy_execution,
                karpathy_target_kind=args.karpathy_target_kind,
                karpathy_execute_git_actions=args.karpathy_execute_git_actions,
                memory_limit=args.memory_limit,
                memory_quality_policy=args.memory_quality_policy,
                trace_advisory_notes_path=args.trace_advisory_notes,
                paper_dashboard_path=Path(args.paper_dashboard) if args.paper_dashboard else None,
                paper_postrun_summary_path=Path(args.paper_postrun_summary) if args.paper_postrun_summary else None,
                paper_calibration_feedback_path=Path(args.paper_calibration_feedback)
                if args.paper_calibration_feedback
                else None,
                max_abs_slip_bps=args.max_abs_slip_bps,
                minimum_paper_orders=args.minimum_paper_orders,
                minimum_telemetry_quality=args.minimum_telemetry_quality,
            )
        )
        print(json.dumps(payload, sort_keys=True))
        blocked_statuses = {
            "blocked_missing_initial_study",
            "blocked_no_eligible_study",
            "blocked_zero_cycle_budget",
            "blocked_sidecar_not_ready",
            "blocked_hydration_not_ready",
            "blocked_loop_readiness",
            "blocked_paper_feedback_incomplete",
            "stopped_next_candidate_not_ready",
        }
        return 0 if payload["status"] not in blocked_statuses else 2

    if args.command == "operate-loop":
        payload = run_operate_loop(
            OperateLoopSettings(
                config_path=Path(args.config) if args.config else None,
                study_dir=Path(args.study_dir) if args.study_dir else None,
                output_dir=Path(args.output_dir),
                db_path=Path(args.db),
                profile=args.profile,
                max_cycles=args.max_cycles,
                iterations=args.iterations,
                run_budget=args.run_budget,
                paper_dashboard_path=Path(args.paper_dashboard) if args.paper_dashboard else None,
                paper_postrun_summary_path=Path(args.paper_postrun_summary) if args.paper_postrun_summary else None,
                paper_calibration_feedback_path=Path(args.paper_calibration_feedback)
                if args.paper_calibration_feedback
                else None,
                strategy_evidence_card_path=Path(args.strategy_evidence_card) if args.strategy_evidence_card else None,
                require_research_ready=args.require_research_ready,
                require_improvement_ready=args.require_improvement_ready,
                allow_smoke=args.allow_smoke,
                candidate_queue_path=Path(args.candidate_queue) if args.candidate_queue else None,
            )
        )
        print(json.dumps(payload, sort_keys=True))
        return 2 if str(payload.get("status") or "").startswith("blocked_") else 0

    if args.command == "strict-data-collect":
        payload = run_strict_data_collector(
            StrictDataCollectorSettings(
                data_root=Path(args.data_root),
                public_ws_db=Path(args.public_ws_db),
                inventory_output=Path(args.inventory_output),
                plan_status_path=Path(args.plan_status),
                liquidation_output=Path(args.liquidation_output),
                session_id=args.session_id,
                min_forward_seconds=args.min_forward_seconds,
                target_forward_seconds=args.target_forward_seconds,
                strong_forward_seconds=args.strong_forward_seconds,
                max_observed_gap_seconds=args.max_observed_gap_seconds,
                export_timeframe=args.export_timeframe,
                export_liquidations_when_ready=args.export_liquidations_when_ready,
                include_observed_zero_buckets=not args.no_observed_zero_buckets,
                sync_plan_status=args.sync_plan_status,
            )
        )
        print(json.dumps(payload, sort_keys=True))
        return 0

    raw_payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
    study = _apply_strict_quality_override(load_study_config(Path(args.config)), args.strict_quality)
    _enforce_snapshot_quality(study, Path(args.config))
    payload = _run_study_execution(
        config_path=Path(args.config),
        raw_payload=raw_payload,
        study=study,
        output_dir=Path(args.output_dir),
        log_path=build_run_log_path(Path(args.output_dir), study.run_id),
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
