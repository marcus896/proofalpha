from __future__ import annotations

import unittest

from engine.validation.bundle import compare_validation_bundles, failed_validation_gate_names, normalize_validation_bundle


class ValidationBundleTests(unittest.TestCase):
    def test_failed_validation_gate_names_returns_sorted_failed_gates(self) -> None:
        self.assertEqual(
            failed_validation_gate_names(
                {
                    "spa": False,
                    "deflated_sharpe_ratio": False,
                    "pbo": False,
                    "final_holdout_excellence": True,
                }
            ),
            ["deflated_sharpe_ratio", "pbo", "spa"],
        )

    def test_normalize_validation_bundle_extracts_phase2_headline_fields(self) -> None:
        payload = normalize_validation_bundle(
            {
                "status": "failed",
                "deflated_sharpe_ratio": 0.91,
                "probabilistic_sharpe_ratio": 0.88,
                "pbo_score": 0.27,
                "spa_pvalue": 0.12,
                "purge_bars": 7,
                "embargo_bars": 2,
                "n_blocks": 12,
                "n_test_blocks": 3,
                "cpcv_config": {
                    "method": "combinatorial_purged_cv",
                    "purge_bars": 7,
                    "embargo_bars": 2,
                    "n_blocks": 12,
                    "n_test_blocks": 3,
                },
                "in_sample_summary": {"trade_count": 17, "sharpe": 5.0},
                "selection_oos_summary": {"trade_count": 5, "sharpe": 4.0},
                "holdout_summary": {"trade_count": 5, "sharpe": 3.0},
                "validation_gate_results": {
                    "deflated_sharpe_ratio": False,
                    "pbo": False,
                    "spa": False,
                    "final_holdout_excellence": True,
                },
            }
        )

        self.assertEqual(
            payload,
            {
                "status": "failed",
                "deflated_sharpe_ratio": 0.91,
                "probabilistic_sharpe_ratio": 0.88,
                "pbo_score": 0.27,
                "spa_pvalue": 0.12,
                "purge_bars": 7,
                "embargo_bars": 2,
                "n_blocks": 12,
                "n_test_blocks": 3,
                "cpcv_config": {
                    "method": "combinatorial_purged_cv",
                    "purge_bars": 7,
                    "embargo_bars": 2,
                    "n_blocks": 12,
                    "n_test_blocks": 3,
                },
                "in_sample_summary": {"trade_count": 17, "sharpe": 5.0},
                "selection_oos_summary": {"trade_count": 5, "sharpe": 4.0},
                "holdout_summary": {"trade_count": 5, "sharpe": 3.0},
                "failed_gates": ["deflated_sharpe_ratio", "pbo", "spa"],
            },
        )

    def test_normalize_validation_bundle_allows_metric_overrides(self) -> None:
        payload = normalize_validation_bundle(
            {
                "status": "failed",
                "deflated_sharpe_ratio": 0.70,
                "probabilistic_sharpe_ratio": 0.71,
                "pbo_score": 0.27,
                "spa_pvalue": 0.12,
                "validation_gate_results": {"pbo": False},
            },
            dsr_override=0.91,
            psr_override=0.88,
        )

        self.assertEqual(payload["deflated_sharpe_ratio"], 0.91)
        self.assertEqual(payload["probabilistic_sharpe_ratio"], 0.88)
        self.assertEqual(payload["failed_gates"], ["pbo"])

    def test_normalize_validation_bundle_returns_empty_for_non_dict(self) -> None:
        self.assertEqual(normalize_validation_bundle(None), {})

    def test_compare_validation_bundles_returns_canonical_left_right_and_changed_fields(self) -> None:
        payload = compare_validation_bundles(
            {
                "status": "failed",
                "deflated_sharpe_ratio": 0.91,
                "probabilistic_sharpe_ratio": 0.88,
                "pbo_score": 0.27,
                "spa_pvalue": 0.12,
                "validation_gate_results": {
                    "deflated_sharpe_ratio": False,
                    "pbo": False,
                    "spa": False,
                },
            },
            {
                "status": "passed",
                "deflated_sharpe_ratio": 0.95,
                "probabilistic_sharpe_ratio": 0.93,
                "pbo_score": 0.08,
                "spa_pvalue": 0.02,
                "validation_gate_results": {
                    "deflated_sharpe_ratio": True,
                    "pbo": True,
                    "spa": True,
                },
            },
        )

        self.assertEqual(payload["left"]["status"], "failed")
        self.assertEqual(payload["right"]["status"], "passed")
        self.assertEqual(
            payload["changed_fields"]["failed_gates"],
            {"left": ["deflated_sharpe_ratio", "pbo", "spa"], "right": []},
        )
        self.assertEqual(
            payload["changed_fields"]["pbo_score"],
            {"left": 0.27, "right": 0.08},
        )


if __name__ == "__main__":
    unittest.main()
