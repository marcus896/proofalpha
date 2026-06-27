from __future__ import annotations

import unittest

from engine.portfolio.rebalance_policy import RebalancePolicy, evaluate_rebalance_policy


class RebalancePolicyTests(unittest.TestCase):
    def test_scheduled_drift_risk_and_lifecycle_triggers_are_reported(self) -> None:
        decision = evaluate_rebalance_policy(
            RebalancePolicy(interval_seconds=900, drift_bps=50.0, risk_breach=True, lifecycle_event="artifact_expired"),
            last_rebalance_utc="2026-05-07T00:00:00Z",
            now_utc="2026-05-07T00:20:00Z",
        )

        self.assertTrue(decision.should_rebalance)
        self.assertEqual(
            decision.triggers,
            ("scheduled", "drift", "risk", "lifecycle:artifact_expired"),
        )


if __name__ == "__main__":
    unittest.main()
