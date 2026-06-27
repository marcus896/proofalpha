from __future__ import annotations

import unittest

from engine.learning.shadow_validation import run_shadow_validation


class ShadowValidationTests(unittest.TestCase):
    def test_shadow_validation_compares_candidate_to_incumbent_without_promoting(self) -> None:
        report = run_shadow_validation(
            candidate_model_id="slippage-v2",
            incumbent_model_id="slippage-v1",
            candidate_errors=[1.0, 1.2, 1.1],
            incumbent_errors=[2.0, 2.1, 1.9],
            min_improvement_ratio=0.20,
        )

        self.assertTrue(report.passed)
        self.assertFalse(report.promotes_model)


if __name__ == "__main__":
    unittest.main()
