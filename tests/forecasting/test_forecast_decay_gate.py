from __future__ import annotations

import unittest

from engine.forecasting.forecast_decay_gate import ForecastDecayGate
from engine.forecasting.drift_monitor import ForecastDriftMonitor


class ForecastDecayGateTests(unittest.TestCase):
    def test_forecast_decay_can_disable_features_without_order_changes(self) -> None:
        gate = ForecastDecayGate(
            min_baseline_edge=0.02,
            max_calibration_error=0.05,
            max_directional_decay=0.2,
            max_staleness=300,
            min_symbol_coverage=0.8,
        )

        result = gate.evaluate(
            baseline_edge=0.01,
            calibration_error=0.08,
            directional_decay=0.3,
            staleness_seconds=400,
            symbol_coverage=0.7,
        )

        self.assertEqual(result.state, "DISABLED")
        self.assertEqual(result.action, "disable_research_feature")
        self.assertFalse(result.direct_order_change)
        self.assertIn("baseline_edge_below_min", result.reasons)

    def test_drift_monitor_marks_decaying_before_disable_threshold(self) -> None:
        monitor = ForecastDriftMonitor(max_directional_decay=0.3)

        result = monitor.evaluate(previous_directional_accuracy=0.62, current_directional_accuracy=0.4)

        self.assertEqual(result.status, "DECAYING")
        self.assertFalse(result.direct_order_change)


if __name__ == "__main__":
    unittest.main()
