from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class LoopIterationResult:
    iteration: int
    run_ids: list[str]
    promoted_run_ids: list[str]
    validation_status: str
    objective_score: float | None = None
    metric_name: str | None = None
    metric_value: float | None = None
    metric_direction: str | None = None
    karpathy_program_result: dict[str, object] | None = None
    karpathy_program_result_mode: str | None = None
    karpathy_program_first: bool = False
    karpathy_primary_artifact_path: str | None = None
    karpathy_primary_artifact_kind: str | None = None
    failed_gates: list[str] = field(default_factory=list)
    regime_failure_labels: list[str] = field(default_factory=list)
    scenario_failure_names: list[str] = field(default_factory=list)
    failure_taxonomy: list[str] = field(default_factory=list)
    duplicate_baseline_score: float | None = None
    next_hypotheses: list[str] = field(default_factory=list)
    note: str | None = None

    @property
    def status(self) -> str:
        return self.validation_status

    def to_payload(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "run_ids": list(self.run_ids),
            "promoted_run_ids": list(self.promoted_run_ids),
            "status": self.validation_status,
            "objective_score": self.objective_score,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "metric_direction": self.metric_direction,
            "karpathy_program_result": dict(self.karpathy_program_result) if isinstance(self.karpathy_program_result, dict) else None,
            "karpathy_program_result_mode": self.karpathy_program_result_mode,
            "karpathy_program_first": self.karpathy_program_first,
            "karpathy_primary_artifact_path": self.karpathy_primary_artifact_path,
            "karpathy_primary_artifact_kind": self.karpathy_primary_artifact_kind,
            "failed_gates": list(self.failed_gates),
            "regime_failure_labels": list(self.regime_failure_labels),
            "scenario_failure_names": list(self.scenario_failure_names),
            "failure_taxonomy": list(self.failure_taxonomy),
            "duplicate_baseline_score": self.duplicate_baseline_score,
            "next_hypotheses": list(self.next_hypotheses),
            "note": self.note,
        }


@dataclass(frozen=True)
class ResearchScratchpad:
    objective: str
    study_budget: int
    max_iterations: int
    loop_mode: str = "bounded"
    max_stagnation_rounds: int = 2
    max_duplicate_baseline_plateau_rounds: int = 2
    max_repeated_regime_failures: int = 3
    max_repeated_scenario_failures: int = 3
    iteration_index: int = 0
    remaining_budget: int | None = None
    completed_runs: list[str] = field(default_factory=list)
    promoted_runs: list[str] = field(default_factory=list)
    failed_gates: dict[str, int] = field(default_factory=dict)
    failure_taxonomy_counts: dict[str, int] = field(default_factory=dict)
    repeated_regime_failure_counts: dict[str, int] = field(default_factory=dict)
    repeated_scenario_failure_counts: dict[str, int] = field(default_factory=dict)
    regime_coverage_gaps: list[str] = field(default_factory=list)
    fragile_scenario_profiles: list[str] = field(default_factory=list)
    top_runtime_profiles: list[str] = field(default_factory=list)
    next_hypotheses: list[str] = field(default_factory=list)
    event_log: list[dict[str, object]] = field(default_factory=list)
    latest_memory_summary: dict[str, object] = field(default_factory=dict)
    stop_reason: str | None = None
    best_result: LoopIterationResult | None = None
    last_result: LoopIterationResult | None = None
    stagnation_rounds: int = 0
    duplicate_baseline_plateau_rounds: int = 0

    def __post_init__(self) -> None:
        if self.remaining_budget is None:
            object.__setattr__(self, "remaining_budget", max(0, self.study_budget))

    def record_iteration(self, result: LoopIterationResult) -> ResearchScratchpad:
        completed_runs = list(self.completed_runs)
        completed_runs.extend(result.run_ids)

        promoted_runs = list(self.promoted_runs)
        promoted_runs.extend(result.promoted_run_ids)

        failed_gates = dict(self.failed_gates)
        for gate_name in result.failed_gates:
            failed_gates[gate_name] = failed_gates.get(gate_name, 0) + 1

        failure_taxonomy_counts = dict(self.failure_taxonomy_counts)
        for taxonomy_label in result.failure_taxonomy:
            failure_taxonomy_counts[taxonomy_label] = failure_taxonomy_counts.get(taxonomy_label, 0) + 1

        repeated_regime_failure_counts = dict(self.repeated_regime_failure_counts)
        for regime_label in result.regime_failure_labels:
            repeated_regime_failure_counts[regime_label] = repeated_regime_failure_counts.get(regime_label, 0) + 1

        repeated_scenario_failure_counts = dict(self.repeated_scenario_failure_counts)
        for scenario_name in result.scenario_failure_names:
            repeated_scenario_failure_counts[scenario_name] = repeated_scenario_failure_counts.get(scenario_name, 0) + 1

        best_result = self.best_result
        if _is_better_result(result, best_result):
            best_result = result

        stagnation_rounds = 0 if best_result is result else self.stagnation_rounds + 1
        duplicate_baseline_plateau_rounds = _next_duplicate_baseline_plateau_rounds(self.last_result, result, self)

        return replace(
            self,
            iteration_index=result.iteration,
            remaining_budget=max(0, int(self.remaining_budget or 0) - len(result.run_ids)),
            completed_runs=completed_runs,
            promoted_runs=promoted_runs,
            failed_gates=failed_gates,
            failure_taxonomy_counts=failure_taxonomy_counts,
            repeated_regime_failure_counts=repeated_regime_failure_counts,
            repeated_scenario_failure_counts=repeated_scenario_failure_counts,
            next_hypotheses=list(result.next_hypotheses),
            best_result=best_result,
            last_result=result,
            stagnation_rounds=stagnation_rounds,
            duplicate_baseline_plateau_rounds=duplicate_baseline_plateau_rounds,
        )

    def resolve_stop_reason(self) -> str | None:
        if self.iteration_index >= self.max_iterations:
            return "max_iterations_reached"
        if int(self.remaining_budget or 0) <= 0:
            return "run_budget_exhausted"
        if self.stop_reason is not None:
            return self.stop_reason
        if self.loop_mode == "karpathy":
            return None
        if self.stagnation_rounds >= self.max_stagnation_rounds:
            return "no_improvement_plateau"
        if self.duplicate_baseline_plateau_rounds >= self.max_duplicate_baseline_plateau_rounds:
            return "duplicate_baseline_plateau"
        taxonomy_stop_reason = _failure_taxonomy_stop_reason(self)
        if taxonomy_stop_reason is not None:
            return taxonomy_stop_reason
        if _max_count(self.repeated_regime_failure_counts) >= self.max_repeated_regime_failures:
            return "repeated_regime_failures"
        if _max_count(self.repeated_scenario_failure_counts) >= self.max_repeated_scenario_failures:
            return "repeated_scenario_failures"
        return None

    def to_payload(self) -> dict[str, object]:
        return {
            "objective": self.objective,
            "study_budget": self.study_budget,
            "max_iterations": self.max_iterations,
            "loop_mode": self.loop_mode,
            "iteration_index": self.iteration_index,
            "remaining_budget": self.remaining_budget,
            "completed_runs": list(self.completed_runs),
            "promoted_runs": list(self.promoted_runs),
            "failed_gates": dict(self.failed_gates),
            "failure_taxonomy_counts": dict(self.failure_taxonomy_counts),
            "repeated_regime_failure_counts": dict(self.repeated_regime_failure_counts),
            "repeated_scenario_failure_counts": dict(self.repeated_scenario_failure_counts),
            "next_hypotheses": list(self.next_hypotheses),
            "event_log": list(self.event_log),
            "latest_memory_summary": dict(self.latest_memory_summary),
            "stop_reason": self.resolve_stop_reason(),
            "best_result": self.best_result.to_payload() if self.best_result is not None else None,
            "last_result": self.last_result.to_payload() if self.last_result is not None else None,
            "stagnation_rounds": self.stagnation_rounds,
            "duplicate_baseline_plateau_rounds": self.duplicate_baseline_plateau_rounds,
        }


def _is_better_result(result: LoopIterationResult, best_result: LoopIterationResult | None) -> bool:
    if best_result is None:
        return True
    current_score = result.objective_score
    best_score = best_result.objective_score
    if current_score is None:
        return False
    if best_score is None:
        return True
    return current_score > best_score


def _next_duplicate_baseline_plateau_rounds(
    previous_result: LoopIterationResult | None,
    result: LoopIterationResult,
    scratchpad: ResearchScratchpad,
) -> int:
    if previous_result is None:
        return 0
    if result.duplicate_baseline_score is None:
        return 0
    if previous_result.duplicate_baseline_score != result.duplicate_baseline_score:
        return 0
    return scratchpad.duplicate_baseline_plateau_rounds + 1


def _max_count(counts: dict[str, int]) -> int:
    return max(counts.values(), default=0)


def _failure_taxonomy_stop_reason(scratchpad: ResearchScratchpad) -> str | None:
    if int(scratchpad.failure_taxonomy_counts.get("resource_license_risk", 0)) >= 1:
        return "resource_license_risk"
    if int(scratchpad.failure_taxonomy_counts.get("upstream_provenance_gap", 0)) >= 1:
        return "upstream_provenance_gap"
    data_contract_failures = int(scratchpad.failure_taxonomy_counts.get("data_quality_failure", 0)) + int(
        scratchpad.failure_taxonomy_counts.get("venue_profile_gap", 0)
    )
    if data_contract_failures >= 2:
        return "repeated_data_contract_failures"
    if int(scratchpad.failure_taxonomy_counts.get("holdout_failure", 0)) >= 2:
        return "repeated_holdout_failures"
    if int(scratchpad.failure_taxonomy_counts.get("stress_failure", 0)) >= scratchpad.max_repeated_scenario_failures:
        return "repeated_stress_failures"
    return None
