from __future__ import annotations

import unittest

from engine.agent.no_trade_policy_enforcer import enforce_no_trade_authority


class NoRiskLimitChangeTests(unittest.TestCase):
    def test_agent_cannot_change_risk_limits(self) -> None:
        result = enforce_no_trade_authority(["ChangeRiskLimit", "DisableCircuitBreaker"])

        self.assertFalse(result.allowed)
        self.assertIn("forbidden_action:ChangeRiskLimit", result.reasons)
        self.assertIn("forbidden_action:DisableCircuitBreaker", result.reasons)


if __name__ == "__main__":
    unittest.main()
