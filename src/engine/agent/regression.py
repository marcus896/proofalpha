from __future__ import annotations

from dataclasses import asdict, dataclass


PHASE5_REQUIRED_CASES = (
    "duplicate_suppression",
    "dirty_snapshot",
    "blocked_resources",
    "repeated_stress_failure",
    "repeated_regime_failure",
    "plateau",
    "queue_handoff",
    "karpathy_keep_discard",
    "crash_recovery",
)


@dataclass(frozen=True)
class AgentLoopPolicyVariant:
    variant_id: str
    planner_refinement_heuristic: str
    memory_selection: str
    duplicate_ranking: str
    stop_policy: str
    karpathy_decision_policy: str
    crash_recovery: str = "event-sourced"
    split_brain_loop: str = "llm-structure-optimizer-parameters-walk-forward-keep-revert"
    immutable_eval: bool = True
    fixed_budget: bool = True
    parseable_result_contract: bool = True
    one_mechanism_per_candidate: bool = True
    holdout_leakage_guard: bool = True
    benchmark_execution_guard: bool = True

    @classmethod
    def baseline(cls) -> "AgentLoopPolicyVariant":
        return cls(
            variant_id="baseline",
            planner_refinement_heuristic="single-mechanism",
            memory_selection="quality-aware",
            duplicate_ranking="canonical-and-near-duplicate",
            stop_policy="budget-aware",
            karpathy_decision_policy="keep-discard",
        )


@dataclass(frozen=True)
class AgentLoopRegressionResult:
    variant: AgentLoopPolicyVariant
    case_results: dict[str, bool]
    score: float

    @property
    def passed(self) -> int:
        return sum(1 for value in self.case_results.values() if value)

    @property
    def failed(self) -> int:
        return len(self.case_results) - self.passed

    @property
    def failed_cases(self) -> list[str]:
        return [case for case, passed in self.case_results.items() if not passed]

    def acceptable_against(self, incumbent: "AgentLoopRegressionResult | None") -> bool:
        if self.failed:
            return False
        if incumbent is None:
            return True
        return self.score >= incumbent.score

    def to_payload(self) -> dict[str, object]:
        return {
            "variant_id": self.variant.variant_id,
            "variant": asdict(self.variant),
            "case_results": dict(self.case_results),
            "passed": self.passed,
            "failed": self.failed,
            "failed_cases": self.failed_cases,
            "score": self.score,
        }


def run_agent_loop_regression(variant: AgentLoopPolicyVariant) -> AgentLoopRegressionResult:
    case_results = {
        "duplicate_suppression": variant.duplicate_ranking == "canonical-and-near-duplicate",
        "dirty_snapshot": variant.memory_selection in {"quality-aware", "clean-only"},
        "blocked_resources": variant.memory_selection == "quality-aware",
        "repeated_stress_failure": variant.stop_policy == "budget-aware",
        "repeated_regime_failure": variant.stop_policy == "budget-aware",
        "plateau": variant.planner_refinement_heuristic == "single-mechanism",
        "queue_handoff": variant.split_brain_loop == "llm-structure-optimizer-parameters-walk-forward-keep-revert",
        "karpathy_keep_discard": variant.karpathy_decision_policy == "keep-discard",
        "crash_recovery": variant.crash_recovery == "event-sourced",
    }
    guard_results = {
        "immutable_eval": variant.immutable_eval,
        "fixed_budget": variant.fixed_budget,
        "parseable_result_contract": variant.parseable_result_contract,
        "one_mechanism_per_candidate": variant.one_mechanism_per_candidate,
        "holdout_leakage_guard": variant.holdout_leakage_guard,
        "benchmark_execution_guard": variant.benchmark_execution_guard,
    }
    total_checks = len(case_results) + len(guard_results)
    score = (sum(case_results.values()) + sum(guard_results.values())) / total_checks
    return AgentLoopRegressionResult(variant=variant, case_results=case_results, score=round(score, 6))


def build_frontier_artifact(results: list[AgentLoopRegressionResult]) -> dict[str, object]:
    ranked = sorted(results, key=lambda result: (-result.score, -result.passed, result.variant.variant_id))
    return {
        "artifact_type": "agent_loop_frontier",
        "frontier": [result.to_payload() for result in ranked],
        "minimum_acceptance_rule": "new score must preserve or improve incumbent and pass all deterministic cases",
    }


def build_evolution_summary(results: list[AgentLoopRegressionResult]) -> dict[str, object]:
    ranked = sorted(results, key=lambda result: (-result.score, -result.passed, result.variant.variant_id))
    best = ranked[0] if ranked else None
    return {
        "artifact_type": "agent_loop_evolution_summary",
        "best_variant_id": best.variant.variant_id if best is not None else None,
        "best_score": best.score if best is not None else None,
        "variants_seen": [result.variant.variant_id for result in results],
        "score_by_variant": {result.variant.variant_id: result.score for result in results},
        "failed_cases_by_variant": {result.variant.variant_id: result.failed_cases for result in results},
    }


def build_controller_policy_variant(
    *,
    variant_id: str,
    memory_quality_policy: str,
) -> AgentLoopPolicyVariant:
    memory_selection = "quality-aware" if memory_quality_policy == "clean-only" else "all-memory"
    return AgentLoopPolicyVariant(
        variant_id=variant_id,
        planner_refinement_heuristic="single-mechanism",
        memory_selection=memory_selection,
        duplicate_ranking="canonical-and-near-duplicate",
        stop_policy="budget-aware",
        karpathy_decision_policy="keep-discard",
    )
