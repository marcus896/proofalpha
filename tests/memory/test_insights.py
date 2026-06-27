import unittest

from engine.memory.insights import build_memory_summary


class MemoryInsightsTests(unittest.TestCase):
    def test_build_memory_summary_surfaces_validation_failures_and_regime_coverage_gaps(self) -> None:
        rows = [
            {
                "decision": "blocked",
                "accepted_layers": [],
                "rejected_layers": ["time_stop"],
                "accepted_duplicate_match_run_id": None,
                "scenario_profiles": {},
                "runtime_settings": {"slippage_bps": 4.0},
                "selected_parameters": {},
                "validation_gate_results": {
                    "walk_forward_permutation": False,
                    "deflated_sharpe_ratio": False,
                    "final_holdout": True,
                },
                "regime_summary": {"regime_coverage": {"bull": 0.45, "short_squeeze": 0.02}},
            },
            {
                "decision": "promoted",
                "accepted_layers": ["ema"],
                "rejected_layers": [],
                "accepted_duplicate_match_run_id": "baseline-a",
                "scenario_profiles": {
                    "short-squeeze": {"name": "short-squeeze", "severity": 0.8, "description": "Short squeeze"}
                },
                "runtime_settings": {"slippage_bps": 4.0},
                "selected_parameters": {"ema": {"aggressiveness": 2}},
                "validation_gate_results": {
                    "walk_forward_permutation": True,
                    "deflated_sharpe_ratio": True,
                },
                "regime_summary": {"regime_coverage": {"bull": 0.30, "short_squeeze": 0.04}},
            },
        ]

        summary = build_memory_summary(rows)

        self.assertEqual(summary["validation_failures"][0]["gate_name"], "walk_forward_permutation")
        self.assertEqual(summary["validation_failures"][0]["count"], 1)
        self.assertEqual(summary["validation_failures"][1]["gate_name"], "deflated_sharpe_ratio")
        self.assertEqual(summary["regime_coverage_gaps"][0]["regime_label"], "short_squeeze")
        self.assertAlmostEqual(summary["regime_coverage_gaps"][0]["average_coverage"], 0.03)
        self.assertEqual(summary["runtime_profile_hints"]["profile"]["slippage_bps"], 4.0)


if __name__ == "__main__":
    unittest.main()
