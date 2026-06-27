from __future__ import annotations

import unittest

from engine.validation.cpcv import build_cpcv_path_metrics


class Phase3CpcvPathMetricsTests(unittest.TestCase):
    def test_cpcv_path_metrics_use_path_distribution_not_naive_average(self) -> None:
        fold_returns = [
            [0.01, 0.02, 0.01, 0.02],
            [0.02, 0.03, 0.02, 0.03],
            [0.01, -0.01, 0.01, -0.01],
            [0.03, 0.04, 0.03, 0.04],
            [0.02, 0.01, 0.02, 0.01],
            [0.01, 0.01, 0.02, 0.02],
            [0.04, 0.03, 0.04, 0.03],
            [0.01, 0.03, 0.01, 0.03],
        ]

        metrics = build_cpcv_path_metrics(fold_returns, n_blocks=8, n_test_blocks=2)

        self.assertEqual(metrics["method"], "combinatorial_purged_cv")
        self.assertEqual(metrics["path_count"], 28)
        self.assertEqual(len(metrics["path_sharpes"]), 28)
        self.assertGreater(metrics["median_sharpe"], metrics["p10_sharpe"])

    def test_cpcv_rejects_non_v3_block_shapes(self) -> None:
        with self.assertRaises(ValueError):
            build_cpcv_path_metrics([[0.01, 0.02]] * 6, n_blocks=6, n_test_blocks=2)
        with self.assertRaises(ValueError):
            build_cpcv_path_metrics([[0.01, 0.02]] * 8, n_blocks=8, n_test_blocks=4)


if __name__ == "__main__":
    unittest.main()
