import unittest

from engine.agent.scratchpad import LoopIterationResult, ResearchScratchpad


class ResearchScratchpadTests(unittest.TestCase):
    def test_record_iteration_updates_budget_and_best_result(self) -> None:
        scratchpad = ResearchScratchpad(objective="maximize_validation_score", study_budget=3, max_iterations=4)
        result = LoopIterationResult(
            iteration=1,
            run_ids=["run-a"],
            promoted_run_ids=["run-a"],
            validation_status="promoted",
            objective_score=3.2,
            failed_gates=["walk_forward_permutation"],
            regime_failure_labels=["short_squeeze"],
            scenario_failure_names=["venue_outage"],
            failure_taxonomy=["multiple_testing_failure", "stress_failure"],
        )

        scratchpad = scratchpad.record_iteration(result)

        self.assertEqual(scratchpad.iteration_index, 1)
        self.assertEqual(scratchpad.remaining_budget, 2)
        self.assertEqual(scratchpad.completed_runs, ["run-a"])
        self.assertEqual(scratchpad.promoted_runs, ["run-a"])
        self.assertEqual(scratchpad.failed_gates["walk_forward_permutation"], 1)
        self.assertEqual(scratchpad.repeated_regime_failure_counts["short_squeeze"], 1)
        self.assertEqual(scratchpad.repeated_scenario_failure_counts["venue_outage"], 1)
        self.assertEqual(scratchpad.failure_taxonomy_counts["multiple_testing_failure"], 1)
        self.assertEqual(scratchpad.failure_taxonomy_counts["stress_failure"], 1)
        self.assertEqual(scratchpad.best_result.objective_score, 3.2)

    def test_to_payload_includes_failure_taxonomy_counts(self) -> None:
        scratchpad = ResearchScratchpad(objective="maximize_validation_score", study_budget=3, max_iterations=4)
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(
                iteration=1,
                run_ids=["run-a"],
                promoted_run_ids=[],
                validation_status="blocked",
                failure_taxonomy=["data_quality_failure", "venue_profile_gap"],
            )
        )

        payload = scratchpad.to_payload()

        self.assertEqual(
            payload["failure_taxonomy_counts"],
            {
                "data_quality_failure": 1,
                "venue_profile_gap": 1,
            },
        )
        self.assertEqual(
            payload["last_result"]["failure_taxonomy"],
            ["data_quality_failure", "venue_profile_gap"],
        )

    def test_resolve_stop_reason_prefers_iteration_cap(self) -> None:
        scratchpad = ResearchScratchpad(
            objective="maximize_validation_score",
            study_budget=3,
            max_iterations=2,
            max_stagnation_rounds=1,
            max_duplicate_baseline_plateau_rounds=1,
            max_repeated_regime_failures=2,
            max_repeated_scenario_failures=2,
        )
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(
                iteration=1,
                run_ids=["run-a"],
                promoted_run_ids=[],
                validation_status="blocked",
                objective_score=1.0,
                failed_gates=["deflated_sharpe_ratio"],
                regime_failure_labels=["crash"],
                scenario_failure_names=["venue_outage"],
                duplicate_baseline_score=5.0,
            )
        )
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(
                iteration=2,
                run_ids=["run-b"],
                promoted_run_ids=[],
                validation_status="blocked",
                objective_score=1.0,
                failed_gates=["deflated_sharpe_ratio"],
                regime_failure_labels=["crash"],
                scenario_failure_names=["venue_outage"],
                duplicate_baseline_score=5.0,
            )
        )

        self.assertEqual(scratchpad.resolve_stop_reason(), "max_iterations_reached")

    def test_karpathy_mode_ignores_plateau_style_auto_stops(self) -> None:
        scratchpad = ResearchScratchpad(
            objective="maximize_validation_score",
            study_budget=5,
            max_iterations=5,
            loop_mode="karpathy",
            max_stagnation_rounds=1,
            max_duplicate_baseline_plateau_rounds=1,
            max_repeated_regime_failures=1,
            max_repeated_scenario_failures=1,
        )
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(
                iteration=1,
                run_ids=["run-a"],
                promoted_run_ids=[],
                validation_status="blocked",
                objective_score=1.0,
                failed_gates=["deflated_sharpe_ratio"],
                regime_failure_labels=["crash"],
                scenario_failure_names=["venue_outage"],
                duplicate_baseline_score=5.0,
            )
        )
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(
                iteration=2,
                run_ids=["run-b"],
                promoted_run_ids=[],
                validation_status="blocked",
                objective_score=1.0,
                failed_gates=["deflated_sharpe_ratio"],
                regime_failure_labels=["crash"],
                scenario_failure_names=["venue_outage"],
                duplicate_baseline_score=5.0,
            )
        )

        self.assertIsNone(scratchpad.resolve_stop_reason())

    def test_resolve_stop_reason_stops_after_repeated_data_contract_failures(self) -> None:
        scratchpad = ResearchScratchpad(objective="maximize_validation_score", study_budget=4, max_iterations=4)
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(iteration=1, run_ids=["run-a"], promoted_run_ids=[], validation_status="blocked", objective_score=1.0, failure_taxonomy=["data_quality_failure"])
        )
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(iteration=2, run_ids=["run-b"], promoted_run_ids=[], validation_status="blocked", objective_score=1.1, failure_taxonomy=["data_quality_failure"])
        )

        self.assertEqual(scratchpad.resolve_stop_reason(), "repeated_data_contract_failures")

    def test_resolve_stop_reason_stops_after_repeated_holdout_failures(self) -> None:
        scratchpad = ResearchScratchpad(
            objective="maximize_validation_score",
            study_budget=4,
            max_iterations=4,
            max_stagnation_rounds=5,
        )
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(iteration=1, run_ids=["run-a"], promoted_run_ids=[], validation_status="blocked", objective_score=1.0, failure_taxonomy=["holdout_failure"])
        )
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(iteration=2, run_ids=["run-b"], promoted_run_ids=[], validation_status="blocked", objective_score=1.1, failure_taxonomy=["holdout_failure"])
        )

        self.assertEqual(scratchpad.resolve_stop_reason(), "repeated_holdout_failures")

    def test_resolve_stop_reason_stops_after_repeated_stress_failures_even_when_scenarios_vary(self) -> None:
        scratchpad = ResearchScratchpad(
            objective="maximize_validation_score",
            study_budget=4,
            max_iterations=4,
            max_stagnation_rounds=5,
            max_repeated_scenario_failures=2,
        )
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(
                iteration=1,
                run_ids=["run-a"],
                promoted_run_ids=[],
                validation_status="blocked",
                objective_score=1.0,
                scenario_failure_names=["venue-outage"],
                failure_taxonomy=["stress_failure"],
            )
        )
        scratchpad = scratchpad.record_iteration(
            LoopIterationResult(
                iteration=2,
                run_ids=["run-b"],
                promoted_run_ids=[],
                validation_status="blocked",
                objective_score=1.1,
                scenario_failure_names=["liquidation-cascade"],
                failure_taxonomy=["stress_failure"],
            )
        )

        self.assertEqual(scratchpad.resolve_stop_reason(), "repeated_stress_failures")
