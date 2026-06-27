from __future__ import annotations

import unittest

from engine.features.train_serve_skew import build_train_serve_skew_report


class TrainServeSkewTests(unittest.TestCase):
    def test_train_serve_skew_report_flags_distribution_drift(self) -> None:
        report = build_train_serve_skew_report(
            train_rows=[{"spread_bps": 1.0}, {"spread_bps": 1.2}, {"spread_bps": 1.1}],
            serve_rows=[{"spread_bps": 4.0}, {"spread_bps": 4.2}, {"spread_bps": 4.1}],
            feature_names=["spread_bps"],
            max_mean_delta=1.0,
        )

        self.assertFalse(report.passed)
        self.assertIn("mean_delta:spread_bps", report.issues)
        self.assertGreater(report.metrics["spread_bps"]["mean_delta"], 1.0)


if __name__ == "__main__":
    unittest.main()
