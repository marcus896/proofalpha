import unittest

from engine.validation.overfitting import (
    compute_benjamini_hochberg_fdr,
    compute_cscv_pbo,
)


class OverfittingTests(unittest.TestCase):
    def test_compute_benjamini_hochberg_fdr_adjusts_and_rejects_expected_values(self) -> None:
        adjusted = compute_benjamini_hochberg_fdr([0.01, 0.02, 0.20], alpha=0.05)
        expected_adjusted = [0.03, 0.03, 0.2]
        for observed, expected in zip(adjusted["adjusted_pvalues"], expected_adjusted, strict=True):
            self.assertAlmostEqual(observed, expected)
        self.assertEqual(adjusted["rejected"], [True, True, False])

    def test_compute_cscv_pbo_is_low_for_consistent_winner(self) -> None:
        perf_matrix = [
            [0.60, 0.55, 0.10],
            [0.58, 0.57, 0.12],
            [0.62, 0.56, 0.09],
            [0.61, 0.54, 0.11],
        ]
        report = compute_cscv_pbo(perf_matrix, S=4)
        self.assertIn("pbo", report)
        self.assertLessEqual(report["pbo"], 0.30)

    def test_compute_cscv_pbo_is_high_when_in_sample_winner_flips_oos(self) -> None:
        perf_matrix = [
            [0.90, 0.10, 0.20],
            [0.88, 0.11, 0.19],
            [0.05, 0.70, 0.60],
            [0.06, 0.72, 0.58],
        ]
        report = compute_cscv_pbo(perf_matrix, S=4)
        self.assertGreater(report["pbo"], 0.30)

    def test_compute_cscv_pbo_rejects_oversized_matrix_without_truncation(self) -> None:
        perf_matrix = [
            [0.60, 0.55, 0.10],
            [0.58, 0.57, 0.12],
            [0.62, 0.56, 0.09],
            [0.61, 0.54, 0.11],
            [0.59, 0.53, 0.13],
            [0.57, 0.58, 0.14],
        ]

        with self.assertRaises(ValueError):
            compute_cscv_pbo(perf_matrix, S=4)


if __name__ == "__main__":
    unittest.main()
