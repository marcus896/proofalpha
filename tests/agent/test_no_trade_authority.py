from __future__ import annotations

import unittest

from engine.agent.no_trade_policy_enforcer import enforce_no_trade_authority


class NoTradeAuthorityTests(unittest.TestCase):
    def test_agent_cannot_place_orders(self) -> None:
        result = enforce_no_trade_authority(["ProposeStudy", "PlaceOrder"])

        self.assertFalse(result.allowed)
        self.assertIn("forbidden_action:PlaceOrder", result.reasons)


if __name__ == "__main__":
    unittest.main()
