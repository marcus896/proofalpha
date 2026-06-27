from __future__ import annotations

import unittest

from engine.optimizer.experiment_budget import ExperimentBudget
from engine.optimizer.failure_router import FailureRouter
from engine.optimizer.overfit_budget import OverfitBudget


class Phase14OptimizerGovernanceTests(unittest.TestCase):
    def test_overfit_budget_stops_excessive_trials(self) -> None:
        budget = OverfitBudget(
            max_trials=10,
            max_strategy_variants=3,
            max_parameter_reuse=2,
            max_failed_gate_retries=1,
            pbo_ceiling=0.2,
            multiple_testing_penalty_policy="deflated_sharpe",
        )

        result = budget.evaluate(trials=11, strategy_variants=2, parameter_reuse=1, failed_gate_retries=0, pbo=0.1)

        self.assertFalse(result.passed)
        self.assertIn("max_trials_exceeded", result.reasons)

    def test_overfit_budget_rejects_negative_counts_and_non_finite_pbo(self) -> None:
        budget = OverfitBudget(
            max_trials=10,
            max_strategy_variants=3,
            max_parameter_reuse=2,
            max_failed_gate_retries=1,
            pbo_ceiling=0.2,
            multiple_testing_penalty_policy="deflated_sharpe",
        )

        result = budget.evaluate(
            trials=-1,
            strategy_variants=-1,
            parameter_reuse=-1,
            failed_gate_retries=-1,
            pbo=float("nan"),
        )

        self.assertFalse(result.passed)
        self.assertIn("negative_trials", result.reasons)
        self.assertIn("negative_strategy_variants", result.reasons)
        self.assertIn("non_finite_pbo", result.reasons)

    def test_experiment_budget_rejects_negative_usage(self) -> None:
        budget = ExperimentBudget(max_runs=10, max_wall_clock_seconds=60)

        self.assertFalse(budget.within_budget(runs=-1, elapsed_seconds=1))
        self.assertFalse(budget.within_budget(runs=1, elapsed_seconds=-1))

    def test_failure_router_classifies_repeated_gate_failure(self) -> None:
        routed = FailureRouter(failed_gate="holdout_sharpe", repeated_count=3).route()

        self.assertEqual(routed.failure_family, "validation_failures")
        self.assertEqual(routed.recommended_action, "stop")
        self.assertIn("holdout_sharpe", routed.memory_reason)


if __name__ == "__main__":
    unittest.main()
