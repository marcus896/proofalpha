from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict, dataclass, is_dataclass, replace
import json
import logging
from pathlib import Path
import sqlite3
from typing import Callable

from engine.agent import artifacts as _agent_artifacts
from engine.agent import validator as _agent_validator
from engine.agent import karpathy_git as _karpathy_git_helpers
from engine.agent import karpathy_target as _karpathy_target_helpers
from engine.agent.model_governance import build_model_change_records, write_model_governance_artifact
from engine.agent.regression import (
    AgentLoopPolicyVariant,
    build_controller_policy_variant,
    run_agent_loop_regression,
)
from engine.agent.scratchpad import LoopIterationResult, ResearchScratchpad
from engine.agent.phase5_cache import (
    is_valid_phase5_regression_cache_payload as _phase5_cache_payload_is_valid,
    load_valid_phase5_regression_cache as _phase5_cache_load_valid,
    phase5_regression_cache_key as _phase5_cache_key,
    write_cached_phase5_regression_artifacts as _phase5_cache_write_artifacts,
)
from engine.io.artifacts import write_json_atomic
from engine.strategy.dsl import build_bounded_strategy_spec_from_payload, validate_bounded_strategy_spec


PlannerFn = Callable[[dict[str, object]], dict[str, object]]
MaterializerFn = Callable[[dict[str, object], dict[str, object]], dict[str, object]]
ValidatorFn = Callable[[dict[str, object], dict[str, object]], dict[str, object]]
MemoryUpdaterFn = Callable[[dict[str, object], LoopIterationResult], dict[str, object]]
RefinementPlannerFn = Callable[[dict[str, object], LoopIterationResult, dict[str, object]], dict[str, object]]
KarpathyGitProbeFn = Callable[[Path], dict[str, object]]

_CONTROLLED_FAILURE_TAXONOMY = (
    "resource_license_risk",
    "upstream_provenance_gap",
    "data_quality_failure",
    "venue_profile_gap",
    "liquidation_realism_failure",
    "insufficient_backtest_length",
    "multiple_testing_failure",
    "overfit_high_pbo",
    "holdout_failure",
    "stress_failure",
    "regime_brittleness",
    "agent_schema_violation",
    "catalog_violation",
    "forecast_unavailable",
    "forecast_leakage",
    "forecast_baseline_failure",
)

_MULTIPLE_TESTING_GATES = {
    "deflated_sharpe_ratio",
    "in_sample_permutation",
    "probabilistic_sharpe_ratio",
    "spa",
    "walk_forward_permutation",
}

_LIQUIDATION_SCENARIO_HINTS = ("cascade", "liquidation", "mark-pressure", "mark_pressure", "squeeze")
_TAXONOMY_ACTION_HINTS = {
    "resource_license_risk": "review_upstream_license_boundary",
    "upstream_provenance_gap": "repair_upstream_provenance",
    "data_quality_failure": "repair_snapshot_quality",
    "venue_profile_gap": "complete_venue_profile",
    "liquidation_realism_failure": "tighten_liquidation_realism",
    "insufficient_backtest_length": "extend_backtest_window",
    "multiple_testing_failure": "reduce_multiple_testing_risk",
    "overfit_high_pbo": "reduce_overfit_risk",
    "holdout_failure": "raise_holdout_robustness",
    "stress_failure": "harden_stress_scenarios",
    "regime_brittleness": "improve_regime_coverage",
    "agent_schema_violation": "repair_agent_schema",
    "catalog_violation": "repair_catalog_bounds",
    "forecast_unavailable": "skip_or_cache_forecast_feature",
    "forecast_leakage": "repair_forecast_timing_contract",
    "forecast_baseline_failure": "compare_forecast_against_baselines",
}
_META_POLICY_ACTION_SPACE = ("balanced", "conservative", "exploratory", "stop")


@dataclass(frozen=True)
class AgentLoopSettings:
    objective: str = "maximize_validation_score"
    loop_mode: str = "auto"
    karpathy_execution_mode: str = "auto"
    karpathy_git_execute_actions: bool | None = None
    karpathy_target_path: str | None = None
    karpathy_target_kind: str = "json_config"
    max_iterations: int = 3
    run_budget: int = 3
    max_stagnation_rounds: int = 2
    max_duplicate_baseline_plateau_rounds: int = 2
    max_repeated_regime_failures: int = 3
    max_repeated_scenario_failures: int = 3
    memory_limit: int = 25
    memory_quality_policy: str = "clean-only"
    trace_advisory_notes_path: str | None = None
    improvement_gate_path: str | None = None
    strict_quality: bool = False


class AgentLoopController:
    def __init__(
        self,
        *,
        settings: AgentLoopSettings,
        planner: PlannerFn | None = None,
        materializer: MaterializerFn | None = None,
        validator: ValidatorFn | None = None,
        memory_updater: MemoryUpdaterFn | None = None,
        refinement_planner: RefinementPlannerFn | None = None,
        karpathy_git_probe: KarpathyGitProbeFn | None = None,
        workspace_root: Path | None = None,
    ) -> None:
        self.settings = settings
        self.planner = planner or _default_planner
        self.materializer = materializer or _default_materializer
        self.validator = validator or _default_validator
        self.memory_updater = memory_updater or _default_memory_updater
        self.refinement_planner = refinement_planner or _default_refinement_planner
        self.karpathy_git_probe = karpathy_git_probe or _default_karpathy_git_probe
        self.workspace_root = workspace_root or Path.cwd()

    def run(
        self,
        *,
        initial_payload: dict[str, object],
        output_dir: Path,
        db_path: Path,
        stop_requested: bool = False,
    ) -> dict[str, object]:
        output_dir.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(__name__)
        requested_loop_mode = self.settings.loop_mode
        effective_loop_mode, loop_mode_selection_reason = _resolve_effective_loop_mode(
            settings=self.settings,
            initial_payload=initial_payload,
        )
        resolved_settings = replace(self.settings, loop_mode=effective_loop_mode)
        scratchpad = ResearchScratchpad(
            objective=resolved_settings.objective,
            study_budget=resolved_settings.run_budget,
            max_iterations=resolved_settings.max_iterations,
            loop_mode=resolved_settings.loop_mode,
            max_stagnation_rounds=resolved_settings.max_stagnation_rounds,
            max_duplicate_baseline_plateau_rounds=resolved_settings.max_duplicate_baseline_plateau_rounds,
            max_repeated_regime_failures=resolved_settings.max_repeated_regime_failures,
            max_repeated_scenario_failures=resolved_settings.max_repeated_scenario_failures,
        )
        current_payload = dict(initial_payload)
        events: list[dict[str, object]] = []
        iteration_results: list[LoopIterationResult] = []
        loop_stop_reason: str | None = None
        follow_up_queue: list[dict[str, object]] = []
        karpathy_kept_next_payload: dict[str, object] | None = None
        karpathy_decisions: list[dict[str, object]] = []
        next_payload_paths_to_refresh: list[Path] = []
        root_run_id = str(initial_payload.get("run_id", "agent-loop"))
        trace_advisory_summary = _merge_advisory_summaries(
            _load_trace_advisory_summary(resolved_settings.trace_advisory_notes_path),
            _load_improvement_gate_advisory_summary(resolved_settings.improvement_gate_path),
        )

        logger.info(
            "Agent loop start: root_run_id=%s objective=%s max_iterations=%s run_budget=%s",
            root_run_id,
            resolved_settings.objective,
            resolved_settings.max_iterations,
            resolved_settings.run_budget,
        )
        mode_runtime = _build_mode_runtime(
            requested_loop_mode=requested_loop_mode,
            effective_loop_mode=effective_loop_mode,
            loop_mode_selection_reason=loop_mode_selection_reason,
            settings=resolved_settings,
        )
        self._emit(events, "mode_selected", **mode_runtime)
        if trace_advisory_summary:
            self._emit(
                events,
                "trace_advisory_loaded",
                path=trace_advisory_summary.get("source_path"),
                failure_taxonomy_hints=trace_advisory_summary.get("failure_taxonomy_hints", []),
                planner_note_count=len(trace_advisory_summary.get("planner_notes", [])),
            )

        if stop_requested:
            loop_stop_reason = "user_stop_requested"
        while loop_stop_reason is None:
            stop_reason = scratchpad.resolve_stop_reason()
            if stop_reason is not None:
                loop_stop_reason = stop_reason
                break

            iteration = scratchpad.iteration_index + 1
            iteration_result: LoopIterationResult | None = None
            working_payload = _load_karpathy_working_payload(
                output_dir=output_dir,
                root_run_id=root_run_id,
                loop_mode=resolved_settings.loop_mode,
                configured_target_path=resolved_settings.karpathy_target_path,
                target_kind=resolved_settings.karpathy_target_kind,
                base_payload=current_payload,
                source_context={
                    "iteration": iteration,
                    "root_run_id": root_run_id,
                    "loop_mode": resolved_settings.loop_mode,
                },
            )
            if isinstance(working_payload, dict):
                current_payload = dict(working_payload)
            context = self._build_context(
                scratchpad=scratchpad,
                current_payload=current_payload,
                output_dir=output_dir,
                db_path=db_path,
                iteration=iteration,
                prior_events=events,
                root_run_id=root_run_id,
                follow_up_queue=follow_up_queue,
                requested_loop_mode=requested_loop_mode,
                effective_loop_mode=effective_loop_mode,
                loop_mode_selection_reason=loop_mode_selection_reason,
                settings=resolved_settings,
                mode_runtime=mode_runtime,
                trace_advisory_summary=trace_advisory_summary,
            )
            logger.info(
                "Iteration %s started: root_run_id=%s run_id=%s",
                iteration,
                root_run_id,
                current_payload.get("run_id"),
            )

            try:
                self._emit(events, "planning_started", iteration=iteration, run_id=current_payload.get("run_id"))
                plan = self.planner(context)
                self._emit(events, "study_proposed", iteration=iteration, plan=plan)
    
                materialized = self.materializer(context, plan)
                self._emit(events, "study_materialized", iteration=iteration, materialized=materialized)
    
                self._emit(events, "validation_started", iteration=iteration)
                validation_result = self.validator(context, materialized)
                validation_result = _augment_validation_result_with_upstream_governance(
                    db_path=db_path,
                    validation_result=validation_result,
                )
                context["validation_result"] = dict(validation_result)
                next_payload_path = validation_result.get("next_payload_path")
                if isinstance(next_payload_path, str) and next_payload_path:
                    next_payload_paths_to_refresh.append(Path(next_payload_path))
                next_payload_paths = validation_result.get("next_payload_paths")
                if isinstance(next_payload_paths, list):
                    next_payload_paths_to_refresh.extend(
                        Path(path)
                        for path in next_payload_paths
                        if isinstance(path, str) and path
                    )
                iteration_result = _normalize_iteration_result(iteration, validation_result)
                self._emit(
                    events,
                    "validation_completed",
                    iteration=iteration,
                    status=iteration_result.status,
                    run_ids=iteration_result.run_ids,
                )
                logger.info(
                    "Validation completed: iteration=%s root_run_id=%s status=%s run_ids=%s",
                    iteration,
                    root_run_id,
                    iteration_result.status,
                    iteration_result.run_ids,
                )
    
                scratchpad = scratchpad.record_iteration(iteration_result)
                iteration_results.append(iteration_result)
    
                memory_summary = self.memory_updater(context, iteration_result)
                memory_summary = _merge_trace_advisory_into_memory_summary(memory_summary, trace_advisory_summary)
                scratchpad = replace(
                    scratchpad,
                    latest_memory_summary=dict(memory_summary),
                )
                self._emit(events, "memory_updated", iteration=iteration, memory_summary=memory_summary)
    
                refinement = self.refinement_planner(context, iteration_result, memory_summary)
                self._emit(events, "batch_refined", iteration=iteration, refinement=refinement)
    
                next_hypotheses = refinement.get("next_hypotheses")
                if isinstance(next_hypotheses, list):
                    merged_next_hypotheses = _merge_trace_advisory_next_hypotheses(
                        [str(item) for item in next_hypotheses if isinstance(item, str)],
                        trace_advisory_summary,
                    )
                    scratchpad = replace(
                        scratchpad,
                        next_hypotheses=merged_next_hypotheses,
                    )
                elif trace_advisory_summary:
                    scratchpad = replace(
                        scratchpad,
                        next_hypotheses=_merge_trace_advisory_next_hypotheses([], trace_advisory_summary),
                    )
    
                queued_payloads = refinement.get("queued_payloads")
                if isinstance(queued_payloads, list):
                    follow_up_queue.extend(
                        [dict(item) for item in queued_payloads if isinstance(item, dict)]
                    )
    
                explicit_stop_reason = refinement.get("stop_reason")
                if isinstance(explicit_stop_reason, str) and explicit_stop_reason:
                    scratchpad = replace(scratchpad, stop_reason=explicit_stop_reason)
    
                next_payload = refinement.get("next_payload")
                if isinstance(next_payload, dict):
                    next_payload = _apply_trace_advisory_to_next_payload(
                        next_payload,
                        trace_advisory_summary,
                        next_hypotheses=list(scratchpad.next_hypotheses),
                    )
                proposed_next_payload = dict(next_payload) if isinstance(next_payload, dict) else None
                karpathy_summary = None
                if resolved_settings.loop_mode == "karpathy":
                    karpathy_summary = _build_karpathy_summary(resolved_settings, iteration_results)
                    if (
                        isinstance(next_payload, dict)
                        and isinstance(karpathy_summary, dict)
                        and karpathy_summary.get("decision") == "discard"
                        and karpathy_kept_next_payload is not None
                    ):
                        next_payload = dict(karpathy_kept_next_payload)
                    elif isinstance(next_payload, dict):
                        karpathy_kept_next_payload = dict(next_payload)
                    decision_entry = _build_karpathy_decision_entry(
                        iteration=iteration,
                        karpathy_summary=karpathy_summary,
                        proposed_next_payload=proposed_next_payload,
                        selected_next_payload=next_payload if isinstance(next_payload, dict) else None,
                    )
                    if decision_entry is not None:
                        karpathy_decisions.append(decision_entry)
                selected_current_payload: dict[str, object] | None = None
                if isinstance(next_payload, dict):
                    current_payload = dict(next_payload)
                    selected_current_payload = dict(current_payload)
                elif follow_up_queue:
                    current_payload = follow_up_queue.pop(0)
                    selected_current_payload = dict(current_payload)
                elif refinement.get("continue") is False and scratchpad.stop_reason is None:
                    scratchpad = replace(scratchpad, stop_reason="refinement_stopped")
                if isinstance(selected_current_payload, dict):
                    _write_karpathy_working_payload(
                        output_dir=output_dir,
                        root_run_id=root_run_id,
                        loop_mode=resolved_settings.loop_mode,
                        configured_target_path=resolved_settings.karpathy_target_path,
                        target_kind=resolved_settings.karpathy_target_kind,
                        payload=selected_current_payload,
                    )
                scratchpad = replace(scratchpad, event_log=list(events))

                logger.info(
                    "Iteration %s ended: root_run_id=%s run_ids=%s status=%s",
                    iteration,
                    root_run_id,
                    iteration_result.run_ids,
                    iteration_result.status,
                )

            except Exception as exc:
                logger.error("Iteration %d failed: %s", iteration, exc, exc_info=True)
                if iteration_result is None:
                    # Treat crashes before validation as failed iterations to avoid infinite retry loops on bad payloads
                    failed_run_id = current_payload.get("run_id", f"crash-iter-{iteration}")
                    iteration_result = LoopIterationResult(
                        iteration=iteration,
                        run_ids=[str(failed_run_id)],
                        promoted_run_ids=[],
                        validation_status="failed",
                    )
                    scratchpad = scratchpad.record_iteration(iteration_result)
                    iteration_results.append(iteration_result)
                self._emit(events, "iteration_crashed", iteration=iteration, error=str(exc))
                if follow_up_queue:
                    current_payload = follow_up_queue.pop(0)
                else:
                    scratchpad = replace(scratchpad, stop_reason="pipeline_crash")

        if loop_stop_reason is None:
            loop_stop_reason = scratchpad.resolve_stop_reason() or "refinement_stopped"

        logger.info(
            "Loop stopped: root_run_id=%s stop_reason=%s completed_iterations=%s",
            root_run_id,
            loop_stop_reason,
            len(iteration_results),
        )

        self._emit(
            events,
            "loop_stopped",
            iteration=scratchpad.iteration_index,
            stop_reason=loop_stop_reason,
        )
        scratchpad = replace(scratchpad, event_log=list(events))
        upstream_adaptation_summary = _build_upstream_adaptation_summary(
            db_path=db_path,
            run_ids=list(scratchpad.completed_runs),
        )
        _refresh_agent_loop_metadata_surfaces(
            output_dir=output_dir,
            db_path=db_path,
            completed_run_ids=list(scratchpad.completed_runs),
            next_payload_paths=next_payload_paths_to_refresh,
            stop_reason=loop_stop_reason,
            failure_taxonomy_counts=dict(scratchpad.failure_taxonomy_counts),
            next_hypotheses=list(scratchpad.next_hypotheses),
            upstream_adaptation_summary=upstream_adaptation_summary,
            trace_advisory_summary=trace_advisory_summary,
        )
        karpathy_summary = _build_karpathy_summary(resolved_settings, iteration_results)
        latest_karpathy_program_result: dict[str, object] | None = None
        latest_karpathy_program_result_mode: str | None = None
        latest_karpathy_program_first = False
        latest_karpathy_primary_artifact_path: str | None = None
        latest_karpathy_primary_artifact_kind: str | None = None
        for result in reversed(iteration_results):
            if isinstance(result.karpathy_program_result, dict):
                latest_karpathy_program_result = dict(result.karpathy_program_result)
                latest_karpathy_program_result_mode = result.karpathy_program_result_mode
                latest_karpathy_program_first = bool(result.karpathy_program_first)
                latest_karpathy_primary_artifact_path = result.karpathy_primary_artifact_path
                latest_karpathy_primary_artifact_kind = result.karpathy_primary_artifact_kind
                break
        karpathy_git_state = _resolve_karpathy_git_state(
            settings=resolved_settings,
            workspace_root=self.workspace_root,
            git_probe=self.karpathy_git_probe,
        )
        karpathy_execution_mode = (
            str(karpathy_git_state.get("effective_mode"))
            if isinstance(karpathy_git_state, dict) and isinstance(karpathy_git_state.get("effective_mode"), str)
            else None
        )
        karpathy_git_action_plan = _build_karpathy_git_action_plan(
            settings=resolved_settings,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            karpathy_git_state=karpathy_git_state,
            karpathy_decisions=karpathy_decisions,
        )
        karpathy_target_path = _resolve_karpathy_target_path(
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            loop_mode=resolved_settings.loop_mode,
            configured_target_path=resolved_settings.karpathy_target_path,
            target_kind=resolved_settings.karpathy_target_kind,
        )
        karpathy_target_kind = resolved_settings.karpathy_target_kind if isinstance(karpathy_target_path, str) else None
        karpathy_program_runtime = _build_karpathy_program_runtime(
            target_path=karpathy_target_path,
            target_kind=karpathy_target_kind,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            iteration=max(1, len(iteration_results)),
            loop_mode=resolved_settings.loop_mode,
            base_payload=karpathy_kept_next_payload or current_payload or initial_payload,
            karpathy_program_first=latest_karpathy_program_first,
            karpathy_primary_artifact_kind=latest_karpathy_primary_artifact_kind,
            karpathy_git_state=karpathy_git_state,
        )
        karpathy_working_config_path = karpathy_target_path
        karpathy_incumbent_artifact_path = _write_karpathy_incumbent_artifact(
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            karpathy_summary=karpathy_summary,
            next_payload=karpathy_kept_next_payload,
            karpathy_decisions=karpathy_decisions,
        )
        karpathy_ledger_artifact_path = _write_karpathy_ledger_artifact(
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            karpathy_decisions=karpathy_decisions,
        )
        karpathy_results_tsv_path = _write_karpathy_results_tsv(
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            karpathy_decisions=karpathy_decisions,
        )
        karpathy_git_state_artifact_path = _write_karpathy_git_state_artifact(
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            karpathy_git_state=karpathy_git_state,
        )
        karpathy_git_action_plan_artifact_path = _write_karpathy_git_action_plan_artifact(
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            karpathy_git_action_plan=karpathy_git_action_plan,
        )
        karpathy_git_execution = _execute_karpathy_git_action_plan(
            settings=resolved_settings,
            workspace_root=self.workspace_root,
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            karpathy_git_state=karpathy_git_state,
            karpathy_git_action_plan=karpathy_git_action_plan,
            karpathy_target_path=karpathy_target_path,
            karpathy_target_kind=karpathy_target_kind,
            karpathy_results_tsv_path=karpathy_results_tsv_path,
        )
        karpathy_git_execution_artifact_path = _write_karpathy_git_execution_artifact(
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            karpathy_git_execution=karpathy_git_execution,
        )
        phase5_baseline_variant = AgentLoopPolicyVariant.baseline()
        phase5_current_variant = build_controller_policy_variant(
            variant_id="current",
            memory_quality_policy=str(resolved_settings.memory_quality_policy),
        )
        (
            phase5_regression_result_payload,
            phase5_frontier_artifact_path,
            phase5_evolution_summary_artifact_path,
            phase5_regression_cache,
        ) = _write_cached_phase5_regression_artifacts(
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            settings=resolved_settings,
            baseline_variant=phase5_baseline_variant,
            current_variant=phase5_current_variant,
        )
        latest_validation_status = (
            str(iteration_results[-1].status)
            if iteration_results
            else "proposed"
        )
        latest_objective_score = (
            float(iteration_results[-1].objective_score)
            if iteration_results and iteration_results[-1].objective_score is not None
            else None
        )
        try:
            model_governance_records = build_model_change_records(
                previous_payload=dict(initial_payload),
                next_payload=dict(current_payload),
                validation_status=latest_validation_status,
                objective_score=latest_objective_score,
            )
        except ValueError:
            model_governance_records = []
        model_governance_artifact_path = write_model_governance_artifact(
            output_dir=output_dir,
            run_id=str(initial_payload.get("run_id", "agent-loop")),
            records=model_governance_records,
        )
        karpathy_program_runtime_artifact_path = _write_karpathy_program_runtime_artifact(
            output_dir=output_dir,
            root_run_id=str(initial_payload.get("run_id", "agent-loop")),
            karpathy_program_runtime=karpathy_program_runtime,
        )
        report_path = output_dir / f"{str(initial_payload.get('run_id', 'agent-loop'))}.agent-loop.json"
        report_payload = {
            "run_id": str(initial_payload.get("run_id", "agent-loop")),
            "status": "stopped",
            "stop_reason": loop_stop_reason,
            "mode_runtime": dict(mode_runtime),
            "controller_inputs": {
                "initial_payload": _json_safe(initial_payload),
                "db_path": str(db_path),
                "output_dir": str(output_dir),
                "trace_advisory_notes_path": resolved_settings.trace_advisory_notes_path,
                "improvement_gate_path": resolved_settings.improvement_gate_path,
            },
            "settings": {
                "objective": self.settings.objective,
                "loop_mode": requested_loop_mode,
                "effective_loop_mode": effective_loop_mode,
                "loop_mode_selection_reason": loop_mode_selection_reason,
                "karpathy_execution_mode": self.settings.karpathy_execution_mode,
                "karpathy_git_execute_actions": self.settings.karpathy_git_execute_actions,
                "karpathy_target_path": self.settings.karpathy_target_path,
                "karpathy_target_kind": self.settings.karpathy_target_kind,
                "max_iterations": self.settings.max_iterations,
                "run_budget": self.settings.run_budget,
                "memory_limit": self.settings.memory_limit,
                "memory_quality_policy": self.settings.memory_quality_policy,
                "strict_quality": self.settings.strict_quality,
                "trace_advisory_notes_path": self.settings.trace_advisory_notes_path,
                "improvement_gate_path": self.settings.improvement_gate_path,
            },
            "iteration_count": len(iteration_results),
            "completed_run_ids": list(scratchpad.completed_runs),
            "promoted_run_ids": list(scratchpad.promoted_runs),
            "iteration_results": [result.to_payload() for result in iteration_results],
            "scratchpad": scratchpad.to_payload(),
            "trace_advisory_summary": trace_advisory_summary,
            "events": events,
            "best_result_summary": scratchpad.best_result.to_payload() if scratchpad.best_result is not None else None,
            "loop_mode_requested": requested_loop_mode,
            "loop_mode": effective_loop_mode,
            "loop_mode_selection_reason": loop_mode_selection_reason,
            "karpathy_summary": karpathy_summary,
            "karpathy_decisions": karpathy_decisions,
            "karpathy_execution_mode": karpathy_execution_mode,
            "karpathy_target_path": karpathy_target_path,
            "karpathy_target_kind": karpathy_target_kind,
            "karpathy_latest_program_result": latest_karpathy_program_result,
            "karpathy_latest_program_result_mode": latest_karpathy_program_result_mode,
            "karpathy_program_first": latest_karpathy_program_first,
            "karpathy_primary_artifact_path": latest_karpathy_primary_artifact_path,
            "karpathy_primary_artifact_kind": latest_karpathy_primary_artifact_kind,
            "karpathy_program_runtime": karpathy_program_runtime,
            "karpathy_git_state": karpathy_git_state,
            "karpathy_git_action_plan": karpathy_git_action_plan,
            "karpathy_git_execution": karpathy_git_execution,
            "karpathy_working_config_path": karpathy_working_config_path,
            "karpathy_incumbent_artifact_path": karpathy_incumbent_artifact_path,
            "karpathy_ledger_artifact_path": karpathy_ledger_artifact_path,
            "karpathy_results_tsv_path": karpathy_results_tsv_path,
            "karpathy_program_runtime_artifact_path": karpathy_program_runtime_artifact_path,
            "karpathy_git_state_artifact_path": karpathy_git_state_artifact_path,
            "karpathy_git_action_plan_artifact_path": karpathy_git_action_plan_artifact_path,
            "karpathy_git_execution_artifact_path": karpathy_git_execution_artifact_path,
            "phase5_regression_result": phase5_regression_result_payload,
            "phase5_regression_cache": phase5_regression_cache,
            "phase5_frontier_artifact_path": str(phase5_frontier_artifact_path),
            "phase5_evolution_summary_artifact_path": str(phase5_evolution_summary_artifact_path),
            "model_governance_artifact_path": model_governance_artifact_path,
            "model_governance_records": model_governance_records,
            "upstream_adaptation_summary": upstream_adaptation_summary,
        }
        _write_agent_loop_report(report_path, report_payload)
        return {
            "run_id": str(initial_payload.get("run_id", "agent-loop")),
            "status": "stopped",
            "stop_reason": loop_stop_reason,
            "iteration_count": len(iteration_results),
            "completed_run_ids": list(scratchpad.completed_runs),
            "promoted_run_ids": list(scratchpad.promoted_runs),
            "settings": dict(report_payload["settings"]),
            "scratchpad": scratchpad.to_payload(),
            "trace_advisory_summary": trace_advisory_summary,
            "events": events,
            "report_path": str(report_path),
            "mode_runtime": dict(mode_runtime),
            "loop_mode_requested": requested_loop_mode,
            "loop_mode": effective_loop_mode,
            "loop_mode_selection_reason": loop_mode_selection_reason,
            "karpathy_summary": karpathy_summary,
            "karpathy_decisions": karpathy_decisions,
            "karpathy_execution_mode": karpathy_execution_mode,
            "karpathy_target_path": karpathy_target_path,
            "karpathy_target_kind": karpathy_target_kind,
            "karpathy_latest_program_result": latest_karpathy_program_result,
            "karpathy_latest_program_result_mode": latest_karpathy_program_result_mode,
            "karpathy_program_first": latest_karpathy_program_first,
            "karpathy_primary_artifact_path": latest_karpathy_primary_artifact_path,
            "karpathy_primary_artifact_kind": latest_karpathy_primary_artifact_kind,
            "karpathy_program_runtime": karpathy_program_runtime,
            "karpathy_git_state": karpathy_git_state,
            "karpathy_git_action_plan": karpathy_git_action_plan,
            "karpathy_git_execution": karpathy_git_execution,
            "karpathy_working_config_path": karpathy_working_config_path,
            "karpathy_incumbent_artifact_path": karpathy_incumbent_artifact_path,
            "karpathy_ledger_artifact_path": karpathy_ledger_artifact_path,
            "karpathy_results_tsv_path": karpathy_results_tsv_path,
            "karpathy_program_runtime_artifact_path": karpathy_program_runtime_artifact_path,
            "karpathy_git_state_artifact_path": karpathy_git_state_artifact_path,
            "karpathy_git_action_plan_artifact_path": karpathy_git_action_plan_artifact_path,
            "karpathy_git_execution_artifact_path": karpathy_git_execution_artifact_path,
            "phase5_regression_result": dict(report_payload["phase5_regression_result"]),
            "phase5_regression_cache": dict(report_payload["phase5_regression_cache"]),
            "phase5_frontier_artifact_path": str(phase5_frontier_artifact_path),
            "phase5_evolution_summary_artifact_path": str(phase5_evolution_summary_artifact_path),
            "model_governance_artifact_path": model_governance_artifact_path,
            "model_governance_records": [dict(record) for record in model_governance_records],
            "upstream_adaptation_summary": upstream_adaptation_summary,
        }

    def _build_context(
        self,
        *,
        scratchpad: ResearchScratchpad,
        current_payload: dict[str, object],
        output_dir: Path,
        db_path: Path,
        iteration: int,
        prior_events: list[dict[str, object]],
        root_run_id: str,
        follow_up_queue: list[dict[str, object]],
        requested_loop_mode: str,
        effective_loop_mode: str,
        loop_mode_selection_reason: str,
        settings: AgentLoopSettings,
        mode_runtime: dict[str, object],
        trace_advisory_summary: dict[str, object],
    ) -> dict[str, object]:
        return {
            "iteration": iteration,
            "root_run_id": root_run_id,
            "payload": dict(current_payload),
            "scratchpad": scratchpad.to_payload(),
            "mode_runtime": dict(mode_runtime),
            "settings": {
                "objective": settings.objective,
                "loop_mode": effective_loop_mode,
                "loop_mode_requested": requested_loop_mode,
                "effective_loop_mode": effective_loop_mode,
                "loop_mode_selection_reason": loop_mode_selection_reason,
                "karpathy_execution_mode": settings.karpathy_execution_mode,
                "karpathy_git_execute_actions": settings.karpathy_git_execute_actions,
                "karpathy_target_path": settings.karpathy_target_path,
                "karpathy_target_kind": settings.karpathy_target_kind,
                "max_iterations": settings.max_iterations,
                "run_budget": settings.run_budget,
                "memory_limit": settings.memory_limit,
                "memory_quality_policy": settings.memory_quality_policy,
                "strict_quality": settings.strict_quality,
                "trace_advisory_notes_path": settings.trace_advisory_notes_path,
                "improvement_gate_path": settings.improvement_gate_path,
            },
            "trace_advisory_summary": dict(trace_advisory_summary),
            "output_dir": output_dir,
            "db_path": db_path,
            "events": list(prior_events),
            "follow_up_queue": [_json_safe(item) for item in follow_up_queue],
        }

    def _emit(self, events: list[dict[str, object]], event_name: str, **payload: object) -> None:
        details = _json_safe(payload)
        events.append(
            {
                "event": event_name,
                "iteration": details.pop("iteration", None),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "role": _event_role(event_name),
                "summary": _event_summary(event_name, details),
                "details": details,
            }
        )


def _write_cached_phase5_regression_artifacts(
    *,
    output_dir: Path,
    root_run_id: str,
    settings: AgentLoopSettings,
    baseline_variant: AgentLoopPolicyVariant,
    current_variant: AgentLoopPolicyVariant,
) -> tuple[dict[str, object], Path, Path, dict[str, object]]:
    artifacts = _phase5_cache_write_artifacts(
        output_dir=output_dir,
        root_run_id=root_run_id,
        settings=settings,
        baseline_variant=baseline_variant,
        current_variant=current_variant,
        regression_runner=run_agent_loop_regression,
    )
    return (
        artifacts.regression_payload,
        artifacts.frontier_artifact_path,
        artifacts.evolution_summary_artifact_path,
        artifacts.cache_info,
    )


def _load_valid_phase5_regression_cache(cache_path: Path, cache_key: str) -> dict[str, object] | None:
    return _phase5_cache_load_valid(cache_path, cache_key)


def _is_valid_phase5_regression_cache_payload(payload: dict[str, object], cache_key: str) -> bool:
    return _phase5_cache_payload_is_valid(payload, cache_key)


def _phase5_regression_cache_key(
    *,
    settings: AgentLoopSettings,
    baseline_variant: AgentLoopPolicyVariant,
    current_variant: AgentLoopPolicyVariant,
) -> str:
    return _phase5_cache_key(
        settings=settings,
        baseline_variant=baseline_variant,
        current_variant=current_variant,
    )


def _write_agent_loop_report(report_path: Path, report_payload: dict[str, object]) -> str:
    return _agent_artifacts.write_agent_loop_report(report_path, report_payload)


def _resolve_effective_loop_mode(
    *,
    settings: AgentLoopSettings,
    initial_payload: dict[str, object],
) -> tuple[str, str]:
    requested_mode = str(settings.loop_mode or "bounded")
    if requested_mode == "karpathy":
        return "karpathy", "explicit_karpathy_requested"
    if requested_mode == "bounded":
        return "bounded", "explicit_bounded_requested"
    target_kind = str(settings.karpathy_target_kind or "json_config")
    if target_kind == "python_source":
        return "karpathy", "auto_selected_karpathy_python_source_target"
    if isinstance(initial_payload.get("karpathy_target_kind"), str) and str(initial_payload.get("karpathy_target_kind")) == "python_source":
        return "karpathy", "auto_selected_karpathy_python_source_payload"
    return "bounded", "auto_selected_bounded_standard_study_loop"


def _build_mode_runtime(
    *,
    requested_loop_mode: str,
    effective_loop_mode: str,
    loop_mode_selection_reason: str,
    settings: AgentLoopSettings,
) -> dict[str, object]:
    return {
        "requested_loop_mode": requested_loop_mode,
        "effective_loop_mode": effective_loop_mode,
        "loop_mode_selection_reason": loop_mode_selection_reason,
        "karpathy_execution_mode_requested": settings.karpathy_execution_mode,
        "karpathy_target_kind": settings.karpathy_target_kind,
        "karpathy_target_path": settings.karpathy_target_path,
    }


def _normalize_iteration_result(iteration: int, payload: dict[str, object]) -> LoopIterationResult:
    run_ids = payload.get("run_ids", [])
    promoted_run_ids = payload.get("promoted_run_ids", [])
    metric_name = payload.get("metric_name")
    metric_direction = payload.get("metric_direction")
    karpathy_program_result = payload.get("karpathy_program_result")
    karpathy_program_result_mode = payload.get("karpathy_program_result_mode")
    karpathy_program_first = bool(payload.get("karpathy_program_first"))
    karpathy_primary_artifact_path = payload.get("karpathy_primary_artifact_path")
    karpathy_primary_artifact_kind = payload.get("karpathy_primary_artifact_kind")
    return LoopIterationResult(
        iteration=iteration,
        run_ids=[str(value) for value in run_ids] if isinstance(run_ids, list) else [],
        promoted_run_ids=[str(value) for value in promoted_run_ids] if isinstance(promoted_run_ids, list) else [],
        validation_status=str(payload.get("status", "unknown")),
        objective_score=_to_float_or_none(payload.get("objective_score")),
        metric_name=str(metric_name) if isinstance(metric_name, str) else None,
        metric_value=_to_float_or_none(payload.get("metric_value")),
        metric_direction=str(metric_direction) if isinstance(metric_direction, str) else None,
        karpathy_program_result=(
            {str(key): value for key, value in karpathy_program_result.items()}
            if isinstance(karpathy_program_result, dict)
            else None
        ),
        karpathy_program_result_mode=(
            str(karpathy_program_result_mode) if isinstance(karpathy_program_result_mode, str) else None
        ),
        karpathy_program_first=karpathy_program_first,
        karpathy_primary_artifact_path=(
            str(karpathy_primary_artifact_path) if isinstance(karpathy_primary_artifact_path, str) else None
        ),
        karpathy_primary_artifact_kind=(
            str(karpathy_primary_artifact_kind) if isinstance(karpathy_primary_artifact_kind, str) else None
        ),
        failed_gates=_coerce_str_list(payload.get("failed_gates")),
        regime_failure_labels=_coerce_str_list(payload.get("regime_failure_labels")),
        scenario_failure_names=_coerce_str_list(payload.get("scenario_failure_names")),
        failure_taxonomy=_coerce_failure_taxonomy(payload.get("failure_taxonomy")),
        duplicate_baseline_score=_to_float_or_none(payload.get("duplicate_baseline_score")),
        next_hypotheses=_coerce_str_list(payload.get("next_hypotheses")),
        note=str(payload["note"]) if isinstance(payload.get("note"), str) else None,
    )


def _augment_validation_result_with_upstream_governance(
    *,
    db_path: Path,
    validation_result: dict[str, object],
) -> dict[str, object]:
    updated = dict(validation_result)
    upstream_adaptation_summary = _build_upstream_adaptation_summary(
        db_path=db_path,
        run_ids=_coerce_str_list(updated.get("run_ids")),
    )
    if not upstream_adaptation_summary:
        return updated

    memory_summary = updated.get("memory_summary")
    resolved_memory_summary = dict(memory_summary) if isinstance(memory_summary, dict) else {}
    resolved_memory_summary["upstream_adaptation_summary"] = dict(upstream_adaptation_summary)
    upstream_governance = {
        "has_blocked_resources": bool(upstream_adaptation_summary.get("blocked_resource_count", 0)),
        "has_provenance_gaps": bool(upstream_adaptation_summary.get("provenance_gap_count", 0)),
        "blocked_resource_ids": list(upstream_adaptation_summary.get("blocked_resource_ids", [])),
        "provenance_gap_resource_ids": list(upstream_adaptation_summary.get("provenance_gap_resource_ids", [])),
        "recommended_stop_reason": upstream_adaptation_summary.get("recommended_stop_reason"),
    }
    resolved_memory_summary["upstream_governance"] = upstream_governance
    updated["memory_summary"] = resolved_memory_summary

    failure_taxonomy = set(_coerce_str_list(updated.get("failure_taxonomy")))
    if upstream_governance["has_blocked_resources"]:
        failure_taxonomy.add("resource_license_risk")
    if upstream_governance["has_provenance_gaps"]:
        failure_taxonomy.add("upstream_provenance_gap")
    updated["failure_taxonomy"] = [
        label for label in _CONTROLLED_FAILURE_TAXONOMY if label in failure_taxonomy
    ]
    return updated


def _build_upstream_adaptation_summary(
    *,
    db_path: Path,
    run_ids: list[str],
) -> dict[str, object]:
    if not run_ids or not db_path.exists():
        return {}

    placeholders = ", ".join("?" for _ in run_ids)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        rows = connection.execute(
            f"""
            SELECT
                run_resource_links.run_id,
                run_resource_links.resource_id,
                run_resource_links.link_role,
                run_resource_links.evidence_source,
                resource_index.resource_group,
                resource_index.title,
                resource_index.license,
                resource_index.status,
                resource_index.intended_usage,
                resource_index.pinned_ref
            FROM run_resource_links
            LEFT JOIN resource_index ON resource_index.resource_id = run_resource_links.resource_id
            WHERE run_resource_links.run_id IN ({placeholders})
            ORDER BY run_resource_links.resource_id ASC, run_resource_links.link_role ASC
            """,
            run_ids,
        ).fetchall()
    finally:
        connection.close()

    linked_by_resource: dict[str, dict[str, object]] = {}
    for row in rows:
        intended_usage = str(row[8]) if row[8] is not None else ""
        if intended_usage not in {"adapter_only", "reference_only"}:
            continue
        resource_id = str(row[1])
        entry = linked_by_resource.setdefault(
            resource_id,
            {
                "resource_id": resource_id,
                "resource_group": str(row[4]) if row[4] is not None else None,
                "title": str(row[5]) if row[5] is not None else resource_id,
                "license": str(row[6]) if row[6] is not None else None,
                "status": str(row[7]) if row[7] is not None else None,
                "intended_usage": intended_usage,
                "pinned_ref": str(row[9]) if row[9] is not None else None,
                "run_ids": set(),
                "link_roles": set(),
                "evidence_sources": set(),
            },
        )
        entry["run_ids"].add(str(row[0]))
        entry["link_roles"].add(str(row[2]))
        entry["evidence_sources"].add(str(row[3]))

    if not linked_by_resource:
        return {}

    linked_resources: list[dict[str, object]] = []
    blocked_resource_ids: list[str] = []
    provenance_gap_resource_ids: list[str] = []
    for resource_id in sorted(linked_by_resource):
        entry = linked_by_resource[resource_id]
        status = str(entry.get("status") or "")
        license_label = str(entry.get("license") or "")
        pinned_ref = str(entry.get("pinned_ref") or "")
        intended_usage = str(entry.get("intended_usage") or "")
        if status.startswith("blocked"):
            blocked_resource_ids.append(resource_id)
        requires_code_provenance = intended_usage == "adapter_only"
        if (
            not status
            or status in {"indexed_not_yet_reviewed", "unknown"}
            or (requires_code_provenance and not license_label)
            or (requires_code_provenance and not pinned_ref)
        ):
            provenance_gap_resource_ids.append(resource_id)
        linked_resources.append(
            {
                "resource_id": resource_id,
                "resource_group": entry.get("resource_group"),
                "title": entry.get("title"),
                "license": entry.get("license"),
                "status": entry.get("status"),
                "intended_usage": entry.get("intended_usage"),
                "pinned_ref": entry.get("pinned_ref"),
                "run_ids": sorted(entry["run_ids"]),
                "link_roles": sorted(entry["link_roles"]),
                "evidence_sources": sorted(entry["evidence_sources"]),
            }
        )

    recommended_stop_reason = None
    if blocked_resource_ids:
        recommended_stop_reason = "resource_license_risk"
    elif provenance_gap_resource_ids:
        recommended_stop_reason = "upstream_provenance_gap"

    return {
        "linked_resource_count": len(linked_resources),
        "blocked_resource_count": len(blocked_resource_ids),
        "provenance_gap_count": len(provenance_gap_resource_ids),
        "linked_resources": linked_resources,
        "blocked_resource_ids": blocked_resource_ids,
        "provenance_gap_resource_ids": provenance_gap_resource_ids,
        "recommended_stop_reason": recommended_stop_reason,
    }


def _build_karpathy_summary(
    settings: AgentLoopSettings,
    iteration_results: list[LoopIterationResult],
) -> dict[str, object] | None:
    if settings.loop_mode != "karpathy":
        return None
    if not iteration_results:
        return {
            "objective": settings.objective,
            "decision": "hold",
            "reason": "no_iterations",
            "candidate_run_ids": [],
            "candidate_score": None,
            "incumbent_run_ids": [],
            "incumbent_score": None,
            "kept_run_ids": [],
            "kept_score": None,
        }

    candidate = iteration_results[-1]
    incumbent = _best_scored_result(iteration_results[:-1])
    candidate_score = candidate.objective_score
    incumbent_score = incumbent.objective_score if incumbent is not None else None

    if candidate_score is None:
        decision = "discard"
        reason = "missing_objective_score"
        kept_result = incumbent
    elif incumbent_score is None:
        decision = "keep"
        reason = "first_scored_run"
        kept_result = candidate
    elif candidate_score > incumbent_score:
        decision = "keep"
        reason = "objective_improved"
        kept_result = candidate
    else:
        decision = "discard"
        reason = "objective_not_improved"
        kept_result = incumbent

    return {
        "objective": settings.objective,
        "decision": decision,
        "reason": reason,
        "validation_status": candidate.validation_status,
        "metric_name": candidate.metric_name or settings.objective,
        "metric_value": candidate.metric_value if candidate.metric_value is not None else candidate_score,
        "metric_direction": candidate.metric_direction,
        "candidate_run_ids": list(candidate.run_ids),
        "candidate_score": candidate_score,
        "incumbent_run_ids": list(incumbent.run_ids) if incumbent is not None else [],
        "incumbent_score": incumbent_score,
        "kept_run_ids": list(kept_result.run_ids) if kept_result is not None else [],
        "kept_score": kept_result.objective_score if kept_result is not None else None,
    }


def _default_karpathy_git_probe(workspace_root: Path) -> dict[str, object]:
    return _karpathy_git_helpers.default_karpathy_git_probe(workspace_root)


def _resolve_karpathy_git_state(
    *,
    settings: AgentLoopSettings,
    workspace_root: Path,
    git_probe: KarpathyGitProbeFn,
) -> dict[str, object] | None:
    return _karpathy_git_helpers.resolve_karpathy_git_state(
        settings=settings,
        workspace_root=workspace_root,
        git_probe=git_probe,
    )


def _write_karpathy_incumbent_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_summary: dict[str, object] | None,
    next_payload: dict[str, object] | None,
    karpathy_decisions: list[dict[str, object]],
) -> str | None:
    return _agent_artifacts.write_karpathy_incumbent_artifact(
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_summary=karpathy_summary,
        next_payload=next_payload,
        karpathy_decisions=karpathy_decisions,
    )


def _write_karpathy_ledger_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_decisions: list[dict[str, object]],
) -> str | None:
    return _agent_artifacts.write_karpathy_ledger_artifact(
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_decisions=karpathy_decisions,
    )


def _write_karpathy_results_tsv(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_decisions: list[dict[str, object]],
) -> str | None:
    return _agent_artifacts.write_karpathy_results_tsv(
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_decisions=karpathy_decisions,
    )


def _write_karpathy_git_state_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_git_state: dict[str, object] | None,
) -> str | None:
    return _karpathy_git_helpers.write_karpathy_git_state_artifact(
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_git_state=karpathy_git_state,
    )


def _build_karpathy_git_action_plan(
    *,
    settings: AgentLoopSettings,
    root_run_id: str,
    karpathy_git_state: dict[str, object] | None,
    karpathy_decisions: list[dict[str, object]],
) -> dict[str, object] | None:
    return _karpathy_git_helpers.build_karpathy_git_action_plan(
        settings=settings,
        root_run_id=root_run_id,
        karpathy_git_state=karpathy_git_state,
        karpathy_decisions=karpathy_decisions,
    )


def _write_karpathy_git_action_plan_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_git_action_plan: dict[str, object] | None,
) -> str | None:
    return _karpathy_git_helpers.write_karpathy_git_action_plan_artifact(
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_git_action_plan=karpathy_git_action_plan,
    )


def _execute_karpathy_git_action_plan(
    *,
    settings: AgentLoopSettings,
    workspace_root: Path,
    output_dir: Path,
    root_run_id: str,
    karpathy_git_state: dict[str, object] | None,
    karpathy_git_action_plan: dict[str, object] | None,
    karpathy_target_path: str | None,
    karpathy_target_kind: str | None,
    karpathy_results_tsv_path: str | None,
) -> dict[str, object] | None:
    return _karpathy_git_helpers.execute_karpathy_git_action_plan(
        settings=settings,
        workspace_root=workspace_root,
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_git_state=karpathy_git_state,
        karpathy_git_action_plan=karpathy_git_action_plan,
        karpathy_target_path=karpathy_target_path,
        karpathy_target_kind=karpathy_target_kind,
        karpathy_results_tsv_path=karpathy_results_tsv_path,
    )


def _should_execute_karpathy_git_actions(
    settings: AgentLoopSettings,
    karpathy_git_state: dict[str, object] | None,
) -> bool:
    return _karpathy_git_helpers.should_execute_karpathy_git_actions(settings, karpathy_git_state)


def _collect_karpathy_git_managed_paths(
    *,
    workspace_root: Path,
    output_dir: Path,
    root_run_id: str,
    karpathy_target_path: str | None,
    karpathy_target_kind: str | None,
) -> list[str]:
    return _karpathy_git_helpers.collect_karpathy_git_managed_paths(
        workspace_root=workspace_root,
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_target_path=karpathy_target_path,
        karpathy_target_kind=karpathy_target_kind,
    )


def _karpathy_local_exclude_paths(
    *,
    workspace_root: Path,
    output_dir: Path,
    root_run_id: str,
    karpathy_results_tsv_path: str | None,
) -> list[str]:
    return _karpathy_git_helpers.karpathy_local_exclude_paths(
        workspace_root=workspace_root,
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_results_tsv_path=karpathy_results_tsv_path,
    )


def _run_git_command(workspace_root: Path, args: list[str]) -> None:
    _karpathy_git_helpers.run_git_command(workspace_root, args)


def _ensure_karpathy_git_local_excludes(*, workspace_root: Path, relative_paths: list[str]) -> None:
    _karpathy_git_helpers.ensure_karpathy_git_local_excludes(
        workspace_root=workspace_root,
        relative_paths=relative_paths,
    )


def _write_karpathy_git_execution_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_git_execution: dict[str, object] | None,
) -> str | None:
    return _karpathy_git_helpers.write_karpathy_git_execution_artifact(
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_git_execution=karpathy_git_execution,
    )


def _write_karpathy_program_runtime_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_program_runtime: dict[str, object] | None,
) -> str | None:
    return _agent_artifacts.write_karpathy_program_runtime_artifact(
        output_dir=output_dir,
        root_run_id=root_run_id,
        karpathy_program_runtime=karpathy_program_runtime,
    )


def _resolve_materialized_config_path(
    *,
    output_dir: Path,
    payload: dict[str, object],
    iteration: int,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None = None,
    target_kind: str = "json_config",
) -> Path:
    if loop_mode == "karpathy":
        if target_kind == "python_source":
            return output_dir / f"{root_run_id}.karpathy-materialized.json"
        return _karpathy_target_path(
            output_dir=output_dir,
            root_run_id=root_run_id,
            loop_mode=loop_mode,
            configured_target_path=configured_target_path,
            target_kind=target_kind,
        )
    return output_dir / f"{str(payload.get('run_id', 'study'))}.agent-loop.iteration-{iteration}.json"


def _karpathy_default_working_config_path(*, output_dir: Path, root_run_id: str) -> Path:
    return _karpathy_target_helpers.karpathy_default_working_config_path(output_dir=output_dir, root_run_id=root_run_id)


def _karpathy_target_path(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None,
    target_kind: str = "json_config",
) -> Path:
    return _karpathy_target_helpers.karpathy_target_path(
        output_dir=output_dir,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=configured_target_path,
        target_kind=target_kind,
    )


def _resolve_karpathy_target_path(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None = None,
    target_kind: str = "json_config",
) -> str | None:
    return _karpathy_target_helpers.resolve_karpathy_target_path(
        output_dir=output_dir,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=configured_target_path,
        target_kind=target_kind,
    )


def _resolve_karpathy_working_config_path(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None = None,
    target_kind: str = "json_config",
) -> str | None:
    return _karpathy_target_helpers.resolve_karpathy_working_config_path(
        output_dir=output_dir,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=configured_target_path,
        target_kind=target_kind,
    )


def _load_karpathy_working_payload(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None = None,
    target_kind: str = "json_config",
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, object] | None:
    return _karpathy_target_helpers.load_karpathy_working_payload(
        output_dir=output_dir,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=configured_target_path,
        target_kind=target_kind,
        base_payload=base_payload,
        source_context=source_context,
    )


def _write_karpathy_working_payload(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None = None,
    target_kind: str = "json_config",
    payload: dict[str, object],
) -> None:
    _karpathy_target_helpers.write_karpathy_working_payload(
        output_dir=output_dir,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=configured_target_path,
        target_kind=target_kind,
        payload=payload,
    )


def _build_karpathy_program_runtime(
    *,
    target_path: str | None,
    target_kind: str | None,
    root_run_id: str,
    iteration: int,
    loop_mode: str,
    base_payload: dict[str, object] | None,
    karpathy_program_first: bool,
    karpathy_primary_artifact_kind: str | None,
    karpathy_git_state: dict[str, object] | None,
) -> dict[str, object] | None:
    return _karpathy_target_helpers.build_karpathy_program_runtime(
        target_path=target_path,
        target_kind=target_kind,
        root_run_id=root_run_id,
        iteration=iteration,
        loop_mode=loop_mode,
        base_payload=base_payload,
        karpathy_program_first=karpathy_program_first,
        karpathy_primary_artifact_kind=karpathy_primary_artifact_kind,
        karpathy_git_state=karpathy_git_state,
    )


def _read_karpathy_python_target_program_bundle(
    target_path: Path,
    *,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, dict[str, object] | None] | None:
    return _karpathy_target_helpers.read_karpathy_python_target_program_bundle(
        target_path,
        base_payload=base_payload,
        source_context=source_context,
    )


def _karpathy_python_target_has_study_contract(
    target_path: Path,
    *,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> bool:
    return _karpathy_target_helpers.karpathy_python_target_has_study_contract(
        target_path,
        base_payload=base_payload,
        source_context=source_context,
    )


def _read_karpathy_python_target_payload(
    target_path: Path,
    *,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, object]:
    return _karpathy_target_helpers.read_karpathy_python_target_payload(
        target_path,
        base_payload=base_payload,
        source_context=source_context,
    )


def _read_karpathy_python_target_eval_via_main(
    target_path: Path,
    *,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, object]:
    return _karpathy_target_helpers.read_karpathy_python_target_eval_via_main(
        target_path,
        base_payload=base_payload,
        source_context=source_context,
    )


def _normalize_karpathy_experiment_result(raw_result: object, *, payload: dict[str, object]) -> dict[str, object]:
    return _karpathy_target_helpers.normalize_karpathy_experiment_result(raw_result, payload=payload)


def _write_karpathy_python_target_payload(target_path: Path, payload: dict[str, object]) -> None:
    _karpathy_target_helpers.write_karpathy_python_target_payload(target_path, payload)



def _build_karpathy_decision_entry(
    *,
    iteration: int,
    karpathy_summary: dict[str, object] | None,
    proposed_next_payload: dict[str, object] | None,
    selected_next_payload: dict[str, object] | None,
) -> dict[str, object] | None:
    if not isinstance(karpathy_summary, dict):
        return None
    entry = dict(karpathy_summary)
    entry["iteration"] = iteration
    entry["proposed_next_payload_run_id"] = (
        str(proposed_next_payload.get("run_id"))
        if isinstance(proposed_next_payload, dict) and proposed_next_payload.get("run_id") is not None
        else None
    )
    entry["selected_next_payload_run_id"] = (
        str(selected_next_payload.get("run_id"))
        if isinstance(selected_next_payload, dict) and selected_next_payload.get("run_id") is not None
        else None
    )
    entry["validation_status"] = str(karpathy_summary.get("validation_status", ""))
    return entry


def _default_planner(context: dict[str, object]) -> dict[str, object]:
    return {
        "mode": "single",
        "variant": "balanced",
        "iteration": context["iteration"],
    }


def _default_materializer(context: dict[str, object], plan: dict[str, object]) -> dict[str, object]:
    output_dir = Path(context["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    iteration = int(context["iteration"])
    payload = dict(context["payload"])
    settings = context.get("settings", {})
    loop_mode = str(settings.get("loop_mode", "bounded"))
    root_run_id = str(context.get("root_run_id", payload.get("run_id", "study")))
    karpathy_target_kind = str(settings.get("karpathy_target_kind", "json_config"))
    karpathy_target_path = _resolve_karpathy_target_path(
        output_dir=output_dir,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=(
            str(settings.get("karpathy_target_path"))
            if settings.get("karpathy_target_path") is not None
            else None
        ),
        target_kind=karpathy_target_kind,
    )
    config_path = _resolve_materialized_config_path(
        output_dir=output_dir,
        payload=payload,
        iteration=iteration,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=(
            str(settings.get("karpathy_target_path"))
            if settings.get("karpathy_target_path") is not None
            else None
        ),
        target_kind=karpathy_target_kind,
    )
    if loop_mode == "karpathy":
        _write_karpathy_working_payload(
            output_dir=output_dir,
            root_run_id=root_run_id,
            loop_mode=loop_mode,
            configured_target_path=(
                str(settings.get("karpathy_target_path"))
                if settings.get("karpathy_target_path") is not None
                else None
            ),
            target_kind=karpathy_target_kind,
            payload=payload,
        )
    karpathy_program_result: dict[str, object] | None = None
    karpathy_program_result_mode: str | None = None
    karpathy_program_first = False
    karpathy_primary_artifact_path: str | None = None
    karpathy_primary_artifact_kind: str | None = None
    if loop_mode == "karpathy" and karpathy_target_kind == "python_source" and isinstance(karpathy_target_path, str):
        source_context = {
            "iteration": iteration,
            "root_run_id": root_run_id,
            "loop_mode": loop_mode,
        }
        program_bundle = _read_karpathy_python_target_program_bundle(
            Path(karpathy_target_path),
            base_payload=payload,
            source_context=source_context,
        )
        if isinstance(program_bundle, dict):
            study_payload = program_bundle.get("study")
            if isinstance(study_payload, dict):
                payload = dict(study_payload)
            if isinstance(program_bundle.get("evaluation"), dict):
                karpathy_program_result = dict(program_bundle["evaluation"])
                karpathy_program_result_mode = "bundle:evaluation"
            elif isinstance(program_bundle.get("experiment"), dict):
                karpathy_program_result = dict(program_bundle["experiment"])
                karpathy_program_result_mode = "bundle:experiment"
        if karpathy_program_result is not None and not isinstance(program_bundle.get("study"), dict):
            karpathy_program_first = True
        elif karpathy_program_result is None:
            karpathy_program_first = not _karpathy_python_target_has_study_contract(
                Path(karpathy_target_path),
                base_payload=payload,
                source_context=source_context,
            )
        if karpathy_program_first:
            karpathy_primary_artifact_path = karpathy_target_path
            karpathy_primary_artifact_kind = "python_source_target"
    bounded_strategy_validation = None
    bounded_strategy_artifact_path: Path | None = None
    if _should_enforce_bounded_strategy_contract(payload, loop_mode=loop_mode):
        bounded_strategy_spec = build_bounded_strategy_spec_from_payload(payload)
        bounded_strategy_validation = validate_bounded_strategy_spec(bounded_strategy_spec)
        if not bounded_strategy_validation.passed:
            raise ValueError(";".join(bounded_strategy_validation.reasons))
        bounded_strategy_artifact_path = output_dir / f"{root_run_id}.bounded-strategy.json"
        write_json_atomic(
            bounded_strategy_artifact_path,
            {
                "run_id": root_run_id,
                "identity_hash": bounded_strategy_validation.identity_hash,
                "spec": bounded_strategy_validation.normalized_spec,
            },
        )
    if not karpathy_program_first:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(config_path, payload)
        karpathy_primary_artifact_path = str(config_path)
        karpathy_primary_artifact_kind = "materialized_study"
    return {
        "plan": dict(plan),
        "config_paths": [] if karpathy_program_first else [config_path],
        "payload": payload,
        "bounded_strategy_spec": (
            bounded_strategy_validation.normalized_spec if bounded_strategy_validation is not None else None
        ),
        "bounded_strategy_identity_hash": (
            bounded_strategy_validation.identity_hash if bounded_strategy_validation is not None else None
        ),
        "bounded_strategy_artifact_path": str(bounded_strategy_artifact_path) if bounded_strategy_artifact_path is not None else None,
        "karpathy_target_path": karpathy_target_path,
        "karpathy_target_kind": karpathy_target_kind,
        "karpathy_program_result": karpathy_program_result,
        "karpathy_program_result_mode": karpathy_program_result_mode,
        "karpathy_program_first": karpathy_program_first,
        "karpathy_primary_artifact_path": karpathy_primary_artifact_path,
        "karpathy_primary_artifact_kind": karpathy_primary_artifact_kind,
    }


def _should_enforce_bounded_strategy_contract(payload: dict[str, object], *, loop_mode: str) -> bool:
    if loop_mode == "karpathy":
        return False
    strategy_signal_fields = {
        "snapshot",
        "incumbent",
        "backbone",
        "parameter_grids",
    }
    return any(field_name in payload for field_name in strategy_signal_fields)


def _try_read_karpathy_python_target_direct_eval(
    context: dict[str, object],
    materialized: dict[str, object],
) -> dict[str, object] | None:
    return _karpathy_target_helpers.try_read_karpathy_python_target_direct_eval(
        context,
        materialized,
    )



def _default_validator(context: dict[str, object], materialized: dict[str, object]) -> dict[str, object]:
    return _agent_validator.default_validator(context, materialized)


def _build_meta_policy_training_examples(
    rows: list[dict[str, object]],
    *,
    exclude_run_id: str | None = None,
) -> list[dict[str, object]]:
    examples: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("run_id", "")) == str(exclude_run_id or ""):
            continue
        action = row.get("selected_variant")
        if not isinstance(action, str) or action not in _META_POLICY_ACTION_SPACE or action == "stop":
            continue
        failed_gates = row.get("failed_validation_gates")
        if not isinstance(failed_gates, list):
            failed_gates = []
        examples.append(
            {
                "run_id": str(row.get("run_id", "")),
                "action": action,
                "reward": _meta_policy_reward_from_memory_row(row),
                "decision": str(row.get("decision", "")),
                "failed_gate_count": len(failed_gates),
            }
        )
    return examples


def _meta_policy_reward_from_memory_row(row: dict[str, object]) -> float:
    reward = _to_float_or_none(row.get("selection_oos_sharpe")) or 0.0
    decision = str(row.get("decision", ""))
    if decision == "promoted":
        reward += 1.0
    elif decision == "blocked":
        reward -= 1.0
    failed_gates = row.get("failed_validation_gates")
    if isinstance(failed_gates, list):
        reward -= 0.25 * len(failed_gates)
    summary = row.get("candidate_trial_summary")
    if isinstance(summary, dict):
        pressured_count = _to_float_or_none(summary.get("pressured_trial_count"))
        if pressured_count is not None and pressured_count > 0:
            reward -= min(1.0, 0.1 * pressured_count)
    return float(reward)


def _mean_training_reward_by_action(training_examples: list[dict[str, object]]) -> dict[str, float]:
    rewards: dict[str, list[float]] = {action: [] for action in _META_POLICY_ACTION_SPACE}
    for example in training_examples:
        action = example.get("action")
        reward = _to_float_or_none(example.get("reward"))
        if isinstance(action, str) and action in rewards and reward is not None:
            rewards[action].append(float(reward))
    return {
        action: sum(values) / len(values)
        for action, values in rewards.items()
        if values
    }


def _training_support_by_action(training_examples: list[dict[str, object]]) -> dict[str, int]:
    support = {action: 0 for action in _META_POLICY_ACTION_SPACE}
    for example in training_examples:
        action = example.get("action")
        reward = _to_float_or_none(example.get("reward"))
        if isinstance(action, str) and action in support and reward is not None:
            support[action] += 1
    return {action: count for action, count in support.items() if count}


def _build_meta_policy_offline_evaluation(
    *,
    selected_action: str,
    training_examples: list[dict[str, object]],
) -> dict[str, object]:
    mean_reward_by_action = _mean_training_reward_by_action(training_examples)
    support_by_action = _training_support_by_action(training_examples)
    best_action: str | None = None
    best_reward: float | None = None
    if mean_reward_by_action:
        best_action, best_reward = sorted(
            mean_reward_by_action.items(),
            key=lambda item: (-float(item[1]), _META_POLICY_ACTION_SPACE.index(item[0])),
        )[0]
    selected_reward = mean_reward_by_action.get(selected_action)
    regret = None
    if best_reward is not None and selected_reward is not None:
        regret = max(0.0, float(best_reward) - float(selected_reward))
    return {
        "method": "logged_bandit_mean_reward_v1" if training_examples else "heuristic_fallback",
        "training_example_count": len(training_examples),
        "action_support": support_by_action,
        "mean_reward_by_action": mean_reward_by_action,
        "selected_action": selected_action,
        "selected_action_support": support_by_action.get(selected_action, 0),
        "selected_action_observed_reward": selected_reward,
        "best_observed_action": best_action,
        "best_observed_reward": best_reward,
        "regret_to_best_observed": regret,
        "counterfactual_limit": "logged rewards only; unobserved action rewards are not inferred",
        "validation_stress_gates_required": True,
        "direct_trading_action_bypass": False,
        "action_space": list(_META_POLICY_ACTION_SPACE),
    }


def _score_bounded_meta_policy_actions(
    *,
    execution_status: str,
    objective_score: float | None,
    failed_gates: list[str],
    regime_failure_labels: list[str],
    scenario_failure_names: list[str],
    failure_taxonomy: list[str],
    training_examples: list[dict[str, object]] | None = None,
) -> dict[str, float]:
    scores = {action: 0.0 for action in _META_POLICY_ACTION_SPACE}
    scores["balanced"] += 1.0
    if execution_status == "promoted":
        scores["balanced"] += 1.0
    if objective_score is not None and objective_score >= 1.5 and not failure_taxonomy and not failed_gates:
        scores["exploratory"] += 5.0
    if execution_status == "blocked":
        scores["conservative"] += 2.0
        scores["stop"] += 1.0
    if failed_gates:
        scores["conservative"] += 1.5 + float(len(failed_gates))
        scores["exploratory"] -= 1.0
    if regime_failure_labels or scenario_failure_names:
        scores["conservative"] += 1.0 + float(len(regime_failure_labels) + len(scenario_failure_names))
        scores["exploratory"] -= 1.0
    taxonomy = set(failure_taxonomy)
    if {"resource_license_risk", "upstream_provenance_gap"} & taxonomy:
        scores["stop"] += 5.0
    if {"data_quality_failure", "venue_profile_gap"} & taxonomy:
        scores["stop"] += 3.0
        scores["conservative"] += 1.0
    if {"multiple_testing_failure", "overfit_high_pbo", "holdout_failure", "stress_failure", "regime_brittleness"} & taxonomy:
        scores["conservative"] += 3.0
        scores["exploratory"] -= 1.0
    if not taxonomy and not failed_gates and not regime_failure_labels and not scenario_failure_names:
        scores["balanced"] += 2.0
    for action, reward in _mean_training_reward_by_action(training_examples or []).items():
        scores[action] += reward
    return scores


def _build_bounded_meta_policy(
    *,
    run_id: str,
    execution_status: str,
    objective_score: float | None,
    failed_gates: list[str],
    regime_failure_labels: list[str],
    scenario_failure_names: list[str],
    failure_taxonomy: list[str],
    next_study_paths: dict[str, str],
    training_examples: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    action_scores = _score_bounded_meta_policy_actions(
        execution_status=execution_status,
        objective_score=objective_score,
        failed_gates=failed_gates,
        regime_failure_labels=regime_failure_labels,
        scenario_failure_names=scenario_failure_names,
        failure_taxonomy=failure_taxonomy,
        training_examples=training_examples,
    )
    selected_action = sorted(
        action_scores.items(),
        key=lambda item: (-float(item[1]), _META_POLICY_ACTION_SPACE.index(item[0])),
    )[0][0]
    selected_variant_path = next_study_paths.get(selected_action) if selected_action != "stop" else None
    training_examples = training_examples or []
    mean_reward_by_action = _mean_training_reward_by_action(training_examples)
    offline_evaluation = _build_meta_policy_offline_evaluation(
        selected_action=selected_action,
        training_examples=training_examples,
    )
    return {
        "policy_id": f"{run_id}-meta-bandit-v1",
        "policy_family": "bandit",
        "status": "trained" if training_examples else "validated",
        "action_map": {action: float(action_scores[action]) for action in _META_POLICY_ACTION_SPACE},
        "training_stats": {
            "contexts_seen": 1 + len(training_examples),
            "reward_metric": "selection_oos_sharpe",
            "objective_score": objective_score,
            "execution_status": execution_status,
            "action_space": list(_META_POLICY_ACTION_SPACE),
            "selected_action": selected_action,
            "training_example_count": len(training_examples),
            "mean_reward_by_action": mean_reward_by_action,
            "offline_evaluation_method": offline_evaluation["method"],
        },
        "offline_evaluation": offline_evaluation,
        "eval_validation_run_id": run_id,
        "eval_stress_summary": {
            "failed_gates": list(failed_gates),
            "regime_failure_labels": list(regime_failure_labels),
            "scenario_failure_names": list(scenario_failure_names),
            "failure_taxonomy": list(failure_taxonomy),
        },
        "artifact_path": None,
        "payload": {
            "selected_action": selected_action,
            "selected_variant_path": selected_variant_path,
            "next_study_paths": dict(next_study_paths),
            "offline_evaluation": offline_evaluation,
            "safety_contract": {
                "action_space": list(_META_POLICY_ACTION_SPACE),
                "routes_study_variants_only": True,
                "direct_trading_action_bypass": False,
                "validation_stress_gates_required": True,
            },
        },
    }


def _write_meta_policy_artifact(
    *,
    output_dir: Path,
    run_id: str,
    meta_policy: dict[str, object],
) -> str:
    return _agent_artifacts.write_meta_policy_artifact(
        output_dir=output_dir,
        run_id=run_id,
        meta_policy=meta_policy,
    )


def _default_memory_updater(context: dict[str, object], result: LoopIterationResult) -> dict[str, object]:
    del result
    validation_result = context.get("validation_result")
    if isinstance(validation_result, dict):
        memory_summary = validation_result.get("memory_summary")
        if isinstance(memory_summary, dict):
            return dict(memory_summary)
    return {}


def _default_refinement_planner(
    context: dict[str, object],
    result: LoopIterationResult,
    memory_summary: dict[str, object],
) -> dict[str, object]:
    validation_result = context.get("validation_result")
    next_payload: dict[str, object] | None = None
    next_payload_path: str | None = None
    meta_policy_selected_action: str | None = None
    if isinstance(validation_result, dict):
        if isinstance(validation_result.get("next_payload"), dict):
            next_payload = dict(validation_result["next_payload"])
        if isinstance(validation_result.get("next_payload_path"), str):
            next_payload_path = str(validation_result["next_payload_path"])
        if isinstance(validation_result.get("meta_policy_selected_action"), str):
            meta_policy_selected_action = str(validation_result["meta_policy_selected_action"])
    next_hypotheses = _build_next_hypotheses_from_result(result)
    if isinstance(meta_policy_selected_action, str) and meta_policy_selected_action:
        next_hypotheses = [f"meta_policy:{meta_policy_selected_action}", *next_hypotheses]
    upstream_governance = memory_summary.get("upstream_governance")
    if isinstance(upstream_governance, dict):
        recommended_stop_reason = upstream_governance.get("recommended_stop_reason")
        if isinstance(recommended_stop_reason, str) and recommended_stop_reason:
            return {
                "continue": False,
                "next_hypotheses": next_hypotheses,
                "next_payload": None,
                "next_payload_path": None,
                "queued_payloads": [],
                "stop_reason": recommended_stop_reason,
            }
    return {
        "continue": next_payload is not None,
        "next_hypotheses": next_hypotheses,
        "next_payload": next_payload,
        "next_payload_path": next_payload_path,
        "queued_payloads": [],
        "stop_reason": (
            None
            if next_payload is not None
            else ("meta_policy_stop" if meta_policy_selected_action == "stop" else "no_follow_up_candidate")
        ),
    }


def _coerce_str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str)]


def _coerce_failure_taxonomy(raw: object) -> list[str]:
    labels = set(_coerce_str_list(raw))
    return [label for label in _CONTROLLED_FAILURE_TAXONOMY if label in labels]


def _load_trace_advisory_summary(path: str | None) -> dict[str, object]:
    if not isinstance(path, str) or not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("trace advisory notes must be a JSON object")
    if payload.get("artifact_type") != "agent_loop_trace_advisory_notes":
        raise ValueError("trace advisory notes must use artifact_type=agent_loop_trace_advisory_notes")
    return _coerce_trace_advisory_summary(payload, source_path=path)


def _load_improvement_gate_advisory_summary(path: str | None) -> dict[str, object]:
    if not isinstance(path, str) or not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("improvement gate must be a JSON object")
    if payload.get("artifact_type") != "loop_improvement_gate":
        raise ValueError("improvement gate must use artifact_type=loop_improvement_gate")
    action_ids: list[str] = []
    for item in payload.get("next_actions", []):
        if not isinstance(item, dict):
            continue
        action_id = item.get("id")
        if isinstance(action_id, str) and action_id and action_id not in action_ids:
            action_ids.append(action_id)
    return {
        "artifact_type": "agent_loop_improvement_gate_advisory_summary",
        "source_path": path,
        "research_only": True,
        "advisory_only": True,
        "failure_taxonomy_hints": [],
        "planner_notes": [],
        "next_hypotheses": [f"improvement_gate_action:{action_id}" for action_id in action_ids],
        "improvement_gate_status": payload.get("status"),
        "strategy_improvement_supported": bool(payload.get("strategy_improvement_supported")),
    }


def _coerce_trace_advisory_summary(payload: dict[str, object], *, source_path: str | None = None) -> dict[str, object]:
    labels: list[str] = []
    planner_notes: list[str] = []
    for item in payload.get("controlled_failure_taxonomy_hints", []):
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if isinstance(label, str) and label in _CONTROLLED_FAILURE_TAXONOMY and label not in labels:
            labels.append(label)
    for item in payload.get("planner_notes", []):
        if isinstance(item, str) and item and item not in planner_notes:
            planner_notes.append(item)
    next_hypotheses = _merge_trace_advisory_next_hypotheses([], {
        "failure_taxonomy_hints": labels,
        "planner_notes": planner_notes,
    })
    return {
        "artifact_type": "agent_loop_trace_advisory_summary",
        "source_path": source_path,
        "research_only": True,
        "advisory_only": True,
        "failure_taxonomy_hints": labels,
        "planner_notes": planner_notes,
        "next_hypotheses": next_hypotheses,
    }


def _str_or_none(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _merge_advisory_summaries(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    if not left:
        return dict(right)
    if not right:
        return dict(left)
    source_paths = [
        path
        for path in [_str_or_none(left.get("source_path")), _str_or_none(right.get("source_path"))]
        if path
    ]
    return {
        "artifact_type": "agent_loop_merged_advisory_summary",
        "source_path": source_paths[0] if source_paths else None,
        "source_paths": source_paths,
        "research_only": True,
        "advisory_only": True,
        "failure_taxonomy_hints": _merge_string_lists(
            _coerce_str_list(left.get("failure_taxonomy_hints")),
            _coerce_str_list(right.get("failure_taxonomy_hints")),
        ),
        "planner_notes": _merge_string_lists(
            _coerce_str_list(left.get("planner_notes")),
            _coerce_str_list(right.get("planner_notes")),
        ),
        "next_hypotheses": _merge_string_lists(
            _coerce_str_list(left.get("next_hypotheses")),
            _coerce_str_list(right.get("next_hypotheses")),
        ),
        "improvement_gate_status": right.get("improvement_gate_status") or left.get("improvement_gate_status"),
        "strategy_improvement_supported": bool(
            right.get("strategy_improvement_supported") or left.get("strategy_improvement_supported")
        ),
    }


def _merge_trace_advisory_into_memory_summary(
    memory_summary: dict[str, object],
    trace_advisory_summary: dict[str, object],
) -> dict[str, object]:
    if not trace_advisory_summary:
        return dict(memory_summary)
    merged = dict(memory_summary)
    merged["trace_advisory"] = dict(trace_advisory_summary)
    merged["failure_taxonomy_hints"] = _merge_string_lists(
        _coerce_str_list(merged.get("failure_taxonomy_hints")),
        _coerce_str_list(trace_advisory_summary.get("failure_taxonomy_hints")),
    )
    merged["next_hypotheses"] = _merge_trace_advisory_next_hypotheses(
        _coerce_str_list(merged.get("next_hypotheses")),
        trace_advisory_summary,
    )
    return merged


def _merge_trace_advisory_next_hypotheses(
    existing: list[str],
    trace_advisory_summary: dict[str, object],
) -> list[str]:
    hypotheses = list(existing)
    hypotheses.extend(_coerce_str_list(trace_advisory_summary.get("next_hypotheses")))
    for label in _coerce_str_list(trace_advisory_summary.get("failure_taxonomy_hints")):
        action = _TAXONOMY_ACTION_HINTS.get(label)
        if isinstance(action, str):
            hypotheses.append(action)
    for note in _coerce_str_list(trace_advisory_summary.get("planner_notes")):
        hypotheses.append(f"trace_advisory_note:{note}")
    return _dedupe_strings(hypotheses)


def _apply_trace_advisory_to_next_payload(
    next_payload: dict[str, object],
    trace_advisory_summary: dict[str, object],
    *,
    next_hypotheses: list[str],
) -> dict[str, object]:
    if not trace_advisory_summary:
        return dict(next_payload)
    updated = dict(next_payload)
    research_hypotheses = updated.get("research_hypotheses")
    if not isinstance(research_hypotheses, dict):
        research_hypotheses = {}
    research_hypotheses = dict(research_hypotheses)
    research_hypotheses["next_hypotheses"] = _merge_string_lists(
        _coerce_str_list(research_hypotheses.get("next_hypotheses")),
        next_hypotheses,
    )
    research_hypotheses["trace_advisory"] = {
        "failure_taxonomy_hints": _coerce_str_list(trace_advisory_summary.get("failure_taxonomy_hints")),
        "planner_notes": _coerce_str_list(trace_advisory_summary.get("planner_notes")),
    }
    updated["research_hypotheses"] = research_hypotheses
    return updated


def _merge_string_lists(left: list[str], right: list[str]) -> list[str]:
    return _dedupe_strings([*left, *right])


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _build_next_hypotheses_from_result(result: LoopIterationResult) -> list[str]:
    hypotheses: list[str] = []
    seen: set[str] = set()
    for label in result.failure_taxonomy:
        action = _TAXONOMY_ACTION_HINTS.get(label)
        if isinstance(action, str) and action not in seen:
            hypotheses.append(action)
            seen.add(action)
    for gate_name in result.failed_gates:
        if gate_name not in seen:
            hypotheses.append(gate_name)
            seen.add(gate_name)
    return hypotheses


def _best_scored_result(results: list[LoopIterationResult]) -> LoopIterationResult | None:
    best_result: LoopIterationResult | None = None
    for result in results:
        if result.objective_score is None:
            continue
        if best_result is None or float(result.objective_score) > float(best_result.objective_score or float("-inf")):
            best_result = result
    return best_result


def _to_float_or_none(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    return None


def _failed_gate_names(raw: object) -> list[str]:
    if not isinstance(raw, str) or not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    return sorted(str(gate_name) for gate_name, passed in payload.items() if passed is False)


def _regime_failure_labels(raw: object) -> list[str]:
    if not isinstance(raw, dict):
        return []
    labels: list[str] = []
    for regime_label, scenario_results in raw.items():
        if not isinstance(regime_label, str) or not isinstance(scenario_results, dict):
            continue
        if any(value is False for value in scenario_results.values()):
            labels.append(regime_label)
    return sorted(labels)


def _scenario_failure_names(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    failures: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("passed") is False and isinstance(item.get("scenario_name"), str):
            failures.append(str(item["scenario_name"]))
    return sorted(failures)


def _build_failure_taxonomy(
    *,
    failed_gates: list[str],
    regime_failure_labels: list[str],
    scenario_failure_names: list[str],
    quality_flags: list[str],
    has_venue_profile: bool,
) -> list[str]:
    labels: set[str] = set()
    gate_names = {str(name) for name in failed_gates if isinstance(name, str)}
    scenario_names = [str(name).lower() for name in scenario_failure_names if isinstance(name, str)]

    if quality_flags:
        labels.add("data_quality_failure")
    if not has_venue_profile:
        labels.add("venue_profile_gap")
    if "minimum_backtest_length" in gate_names:
        labels.add("insufficient_backtest_length")
    if gate_names.intersection(_MULTIPLE_TESTING_GATES):
        labels.add("multiple_testing_failure")
    if "pbo" in gate_names:
        labels.add("overfit_high_pbo")
    if gate_names.intersection({"final_holdout_drawdown", "final_holdout_excellence"}):
        labels.add("holdout_failure")
    if any(hint in scenario_name for scenario_name in scenario_names for hint in _LIQUIDATION_SCENARIO_HINTS):
        labels.add("liquidation_realism_failure")
    if scenario_names:
        labels.add("stress_failure")
    if regime_failure_labels:
        labels.add("regime_brittleness")
    if "agent_schema_violation" in gate_names:
        labels.add("agent_schema_violation")
    if "catalog_violation" in gate_names:
        labels.add("catalog_violation")
    if "forecast_unavailable" in gate_names:
        labels.add("forecast_unavailable")
    if "forecast_leakage" in gate_names:
        labels.add("forecast_leakage")
    if "forecast_baseline_failure" in gate_names:
        labels.add("forecast_baseline_failure")
    return [label for label in _CONTROLLED_FAILURE_TAXONOMY if label in labels]


def _json_safe(raw: object) -> object:
    if isinstance(raw, Path):
        return str(raw)
    if isinstance(raw, dict):
        return {str(key): _json_safe(value) for key, value in raw.items()}
    if isinstance(raw, list):
        return [_json_safe(value) for value in raw]
    return raw


def _attach_agent_loop_metadata(
    payload: dict[str, object],
    *,
    root_run_id: str,
    iteration: int,
    source_run_id: str,
    completed_run_ids: list[str],
    requested_loop_mode: str,
    effective_loop_mode: str,
    loop_mode_selection_reason: str,
    karpathy_target_kind: str,
    stop_reason: str | None = None,
) -> dict[str, object]:
    updated = dict(payload)
    updated["agent_loop_metadata"] = {
        "loop_id": root_run_id,
        "parent_loop_run_id": root_run_id,
        "iteration": iteration,
        "source_run_id": source_run_id,
        "completed_run_ids": list(completed_run_ids),
        "requested_loop_mode": requested_loop_mode,
        "effective_loop_mode": effective_loop_mode,
        "loop_mode_selection_reason": loop_mode_selection_reason,
        "karpathy_target_kind": karpathy_target_kind,
        "stop_reason": stop_reason,
    }
    lineage = updated.get("research_lineage")
    if not isinstance(lineage, dict):
        lineage = {}
    lineage.update(
        {
            "agent_loop_parent_run_id": root_run_id,
            "agent_loop_iteration": iteration,
            "agent_loop_source_run_id": source_run_id,
        }
    )
    updated["research_lineage"] = lineage
    return updated


def _refresh_agent_loop_metadata_surfaces(
    *,
    output_dir: Path,
    db_path: Path,
    completed_run_ids: list[str],
    next_payload_paths: list[Path],
    stop_reason: str,
    failure_taxonomy_counts: dict[str, int],
    next_hypotheses: list[str],
    upstream_adaptation_summary: dict[str, object],
    trace_advisory_summary: dict[str, object],
) -> None:
    for payload_path in next_payload_paths:
        _refresh_agent_loop_metadata_json_file(
            payload_path,
            completed_run_ids=completed_run_ids,
            stop_reason=stop_reason,
            failure_taxonomy_counts=failure_taxonomy_counts,
            next_hypotheses=next_hypotheses,
            upstream_adaptation_summary=upstream_adaptation_summary,
            trace_advisory_summary=trace_advisory_summary,
        )
    for run_id in completed_run_ids:
        _refresh_agent_loop_metadata_json_file(
            output_dir / f"{run_id}.dashboard.json",
            completed_run_ids=completed_run_ids,
            stop_reason=stop_reason,
            failure_taxonomy_counts=failure_taxonomy_counts,
            next_hypotheses=next_hypotheses,
            upstream_adaptation_summary=upstream_adaptation_summary,
            trace_advisory_summary=trace_advisory_summary,
        )
        _refresh_agent_loop_metadata_json_file(
            output_dir / f"{run_id}.autoresearch.json",
            completed_run_ids=completed_run_ids,
            stop_reason=stop_reason,
            failure_taxonomy_counts=failure_taxonomy_counts,
            next_hypotheses=next_hypotheses,
            upstream_adaptation_summary=upstream_adaptation_summary,
            trace_advisory_summary=trace_advisory_summary,
        )
        _refresh_agent_loop_metadata_runcard_file(
            output_dir / f"{run_id}.runcard.json",
            completed_run_ids=completed_run_ids,
            stop_reason=stop_reason,
            failure_taxonomy_counts=failure_taxonomy_counts,
            next_hypotheses=next_hypotheses,
            upstream_adaptation_summary=upstream_adaptation_summary,
            trace_advisory_summary=trace_advisory_summary,
        )
    _refresh_agent_loop_metadata_db(
        db_path=db_path,
        completed_run_ids=completed_run_ids,
        stop_reason=stop_reason,
        failure_taxonomy_counts=failure_taxonomy_counts,
        next_hypotheses=next_hypotheses,
        upstream_adaptation_summary=upstream_adaptation_summary,
        trace_advisory_summary=trace_advisory_summary,
    )


def _refresh_agent_loop_metadata_json_file(
    path: Path,
    *,
    completed_run_ids: list[str],
    stop_reason: str,
    failure_taxonomy_counts: dict[str, int],
    next_hypotheses: list[str],
    upstream_adaptation_summary: dict[str, object],
    trace_advisory_summary: dict[str, object],
) -> None:
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    agent_loop_metadata = payload.get("agent_loop_metadata")
    if not isinstance(agent_loop_metadata, dict):
        return
    updated_metadata = dict(agent_loop_metadata)
    updated_metadata["completed_run_ids"] = list(completed_run_ids)
    updated_metadata["stop_reason"] = stop_reason
    updated_metadata["failure_taxonomy_counts"] = dict(failure_taxonomy_counts)
    updated_metadata["next_hypotheses"] = list(next_hypotheses)
    if upstream_adaptation_summary:
        updated_metadata["upstream_adaptation_summary"] = dict(upstream_adaptation_summary)
    if trace_advisory_summary:
        updated_metadata["trace_advisory_summary"] = dict(trace_advisory_summary)
    payload["agent_loop_metadata"] = updated_metadata
    if trace_advisory_summary:
        payload = _apply_trace_advisory_to_next_payload(
            payload,
            trace_advisory_summary,
            next_hypotheses=next_hypotheses,
        )
    write_json_atomic(path, payload)


def _refresh_agent_loop_metadata_runcard_file(
    path: Path,
    *,
    completed_run_ids: list[str],
    stop_reason: str,
    failure_taxonomy_counts: dict[str, int],
    next_hypotheses: list[str],
    upstream_adaptation_summary: dict[str, object],
    trace_advisory_summary: dict[str, object],
) -> None:
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return
    raw_metadata = artifacts.get("agent_loop_metadata_json", "{}")
    try:
        agent_loop_metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else {}
    except json.JSONDecodeError:
        agent_loop_metadata = {}
    if not isinstance(agent_loop_metadata, dict):
        agent_loop_metadata = {}
    if not agent_loop_metadata:
        return
    agent_loop_metadata["completed_run_ids"] = list(completed_run_ids)
    agent_loop_metadata["stop_reason"] = stop_reason
    agent_loop_metadata["failure_taxonomy_counts"] = dict(failure_taxonomy_counts)
    agent_loop_metadata["next_hypotheses"] = list(next_hypotheses)
    if upstream_adaptation_summary:
        agent_loop_metadata["upstream_adaptation_summary"] = dict(upstream_adaptation_summary)
    if trace_advisory_summary:
        agent_loop_metadata["trace_advisory_summary"] = dict(trace_advisory_summary)
    artifacts = dict(artifacts)
    artifacts["agent_loop_metadata_json"] = json.dumps(agent_loop_metadata, sort_keys=True)
    payload["artifacts"] = artifacts
    write_json_atomic(path, payload)


def _refresh_agent_loop_metadata_db(
    *,
    db_path: Path,
    completed_run_ids: list[str],
    stop_reason: str,
    failure_taxonomy_counts: dict[str, int],
    next_hypotheses: list[str],
    upstream_adaptation_summary: dict[str, object],
    trace_advisory_summary: dict[str, object],
) -> None:
    if not completed_run_ids or not db_path.exists():
        return
    placeholders = ", ".join("?" for _ in completed_run_ids)
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            f"SELECT run_id, agent_loop_metadata_json FROM research_runs WHERE run_id IN ({placeholders})",
            tuple(completed_run_ids),
        ).fetchall()
        for run_id, raw_metadata in rows:
            try:
                metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else {}
            except json.JSONDecodeError:
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            if not metadata:
                continue
            metadata["completed_run_ids"] = list(completed_run_ids)
            metadata["stop_reason"] = stop_reason
            metadata["failure_taxonomy_counts"] = dict(failure_taxonomy_counts)
            metadata["next_hypotheses"] = list(next_hypotheses)
            if upstream_adaptation_summary:
                metadata["upstream_adaptation_summary"] = dict(upstream_adaptation_summary)
            if trace_advisory_summary:
                metadata["trace_advisory_summary"] = dict(trace_advisory_summary)
            connection.execute(
                "UPDATE research_runs SET agent_loop_metadata_json = ? WHERE run_id = ?",
                (json.dumps(metadata, sort_keys=True), run_id),
            )
        connection.commit()
    finally:
        connection.close()


def _event_role(event_name: str) -> str:
    roles = {
        "mode_selected": "Controller",
        "planning_started": "ResearchPlanner",
        "study_proposed": "ResearchPlanner",
        "study_materialized": "StudyMaterializer",
        "validation_started": "ValidationExecutor",
        "validation_completed": "ValidationExecutor",
        "memory_updated": "MemoryUpdater",
        "trace_advisory_loaded": "TraceAuditAdvisor",
        "batch_refined": "RefinementPlanner",
        "loop_stopped": "Controller",
    }
    return roles.get(event_name, "Controller")


def _event_summary(event_name: str, details: dict[str, object]) -> str:
    if event_name == "mode_selected":
        return (
            f"Loop mode resolved to {details.get('effective_loop_mode', 'unknown')} "
            f"from {details.get('requested_loop_mode', 'unknown')}."
        )
    if event_name == "planning_started":
        return f"Planning iteration {details.get('run_id', 'unknown')}."
    if event_name == "study_proposed":
        return "Planner proposed the next bounded study."
    if event_name == "study_materialized":
        return "Materializer wrote executable study payloads."
    if event_name == "validation_started":
        return "Validation execution started."
    if event_name == "validation_completed":
        return f"Validation completed with status {details.get('status', 'unknown')}."
    if event_name == "memory_updated":
        return "Memory summary refreshed from the latest validation result."
    if event_name == "trace_advisory_loaded":
        return "Controlled trace advisory notes loaded."
    if event_name == "batch_refined":
        return "Refinement planner decided the next bounded step."
    if event_name == "loop_stopped":
        return f"Loop stopped with reason {details.get('stop_reason', 'unknown')}."
    return event_name
