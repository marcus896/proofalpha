from __future__ import annotations

import unittest

from engine.validation.min_sample_gate import MinSampleGate


class MinSampleGateTests(unittest.TestCase):
    def test_min_sample_gate_rejects_non_finite_regime_coverage(self) -> None:
        gate = MinSampleGate(min_oos_trades=100, min_final_holdout_trades=50, min_regime_coverage=0.8)

        result = gate.evaluate(oos_trades=100, final_holdout_trades=50, regime_coverage=float("nan"))

        self.assertFalse(result.passed)
        self.assertIn("regime_coverage_non_finite", result.reasons)


if __name__ == "__main__":
    unittest.main()
