import unittest

from engine.agent.regression import (
    PHASE5_REQUIRED_CASES,
    AgentLoopPolicyVariant,
    build_evolution_summary,
    build_frontier_artifact,
    run_agent_loop_regression,
)


class Phase5RegressionHarnessTests(unittest.TestCase):
    def test_baseline_policy_preserves_full_phase5_harness_score(self) -> None:
        result = run_agent_loop_regression(AgentLoopPolicyVariant.baseline())

        self.assertEqual(set(result.case_results), set(PHASE5_REQUIRED_CASES))
        self.assertEqual(result.passed, len(PHASE5_REQUIRED_CASES))
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.score, 1.0)
        self.assertTrue(result.acceptable_against(None))

    def test_policy_must_preserve_or_improve_prior_score(self) -> None:
        baseline = run_agent_loop_regression(AgentLoopPolicyVariant.baseline())
        weaker = run_agent_loop_regression(
            AgentLoopPolicyVariant(
                variant_id="unsafe",
                planner_refinement_heuristic="single-mechanism",
                memory_selection="quality-aware",
                duplicate_ranking="off",
                stop_policy="budget-aware",
                karpathy_decision_policy="keep-discard",
            )
        )

        self.assertLess(weaker.score, baseline.score)
        self.assertFalse(weaker.acceptable_against(baseline))
        self.assertIn("duplicate_suppression", weaker.failed_cases)

    def test_frontier_and_evolution_artifacts_are_parseable_and_ranked(self) -> None:
        baseline = run_agent_loop_regression(AgentLoopPolicyVariant.baseline())
        weaker = run_agent_loop_regression(
            AgentLoopPolicyVariant(
                variant_id="unsafe",
                planner_refinement_heuristic="single-mechanism",
                memory_selection="quality-aware",
                duplicate_ranking="canonical-only",
                stop_policy="budget-aware",
                karpathy_decision_policy="keep-discard",
                crash_recovery="none",
            )
        )

        frontier = build_frontier_artifact([weaker, baseline])
        evolution = build_evolution_summary([weaker, baseline])

        self.assertEqual(frontier["frontier"][0]["variant_id"], "baseline")
        self.assertEqual(frontier["frontier"][0]["score"], 1.0)
        self.assertEqual(evolution["best_variant_id"], "baseline")
        self.assertIn("unsafe", evolution["variants_seen"])
