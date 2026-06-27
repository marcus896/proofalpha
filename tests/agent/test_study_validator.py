from __future__ import annotations

import unittest

from engine.agent.study_validator import StudyProposal, StudyValidator


class StudyValidatorTests(unittest.TestCase):
    def test_study_validator_checks_layer_feature_scenario_budget_and_duplicate_signature(self) -> None:
        validator = StudyValidator(
            approved_layers={"momentum_v1"},
            feature_contracts={"close", "spread_bps"},
            scenario_packs={"scenario-v1"},
            seen_signatures={"dup"},
            max_search_budget=50,
            required_validation_gate_spec="prd_safe",
        )
        result = validator.validate(
            StudyProposal(
                layer="bad_layer",
                features=["close", "future_return"],
                scenario_pack="missing",
                parameter_ranges={"lookback": (100, 10)},
                signature="dup",
                search_budget=75,
                validation_gate_spec="weak",
            )
        )

        self.assertFalse(result.passed)
        self.assertIn("layer_not_approved", result.reasons)
        self.assertIn("duplicate_signature", result.reasons)
        self.assertIn("validation_gate_spec_mismatch", result.reasons)

    def test_study_validator_rejects_non_positive_budget_and_non_finite_parameter_bounds(self) -> None:
        validator = StudyValidator(
            approved_layers={"momentum_v1"},
            feature_contracts={"close"},
            scenario_packs={"scenario-v1"},
            seen_signatures=set(),
            max_search_budget=50,
            required_validation_gate_spec="prd_safe",
        )
        result = validator.validate(
            StudyProposal(
                layer="momentum_v1",
                features=["close"],
                scenario_pack="scenario-v1",
                parameter_ranges={"lookback": (float("nan"), 20.0), "threshold": (0.1, float("inf"))},
                signature="new",
                search_budget=0,
                validation_gate_spec="prd_safe",
            )
        )

        self.assertFalse(result.passed)
        self.assertIn("search_budget_not_positive", result.reasons)
        self.assertIn("invalid_parameter_range:lookback", result.reasons)
        self.assertIn("invalid_parameter_range:threshold", result.reasons)


if __name__ == "__main__":
    unittest.main()
