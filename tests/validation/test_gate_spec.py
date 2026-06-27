from __future__ import annotations

import unittest

from engine.validation.gate_spec import ValidationGateResult, ValidationGateSpec


class ValidationGateSpecTests(unittest.TestCase):
    def test_prd_safe_defaults_are_hard_gates(self) -> None:
        spec = ValidationGateSpec.prd_safe()

        self.assertEqual(spec.holdout_sharpe_floor, 1.0)
        self.assertEqual(spec.final_holdout_calmar_floor, 0.75)
        self.assertEqual(spec.holdout_drawdown_cap, -0.20)
        self.assertEqual(spec.capacity_5x_max_edge_degradation, 0.25)
        self.assertTrue(spec.turnover_budget_required)
        self.assertTrue(spec.min_oos_trades_required)
        self.assertEqual(spec.min_oos_trades, 120)
        self.assertTrue(spec.scenario_pass_matrix_required)
        self.assertTrue(spec.regime_pass_matrix_required)

    def test_gate_result_serializes_evidence_refs(self) -> None:
        result = ValidationGateResult(
            name="final_holdout_calmar",
            passed=False,
            actual=0.50,
            threshold=0.75,
            severity="hard",
            reason="final_holdout_calmar_below_floor",
            evidence_refs=("holdout_summary",),
        )

        self.assertEqual(
            result.to_dict(),
            {
                "name": "final_holdout_calmar",
                "passed": False,
                "actual": 0.50,
                "threshold": 0.75,
                "severity": "hard",
                "reason": "final_holdout_calmar_below_floor",
                "evidence_refs": ["holdout_summary"],
            },
        )


if __name__ == "__main__":
    unittest.main()
