from __future__ import annotations

import unittest

from engine.agent.no_trade_policy_enforcer import enforce_no_trade_authority


class NoDirectPromotionTests(unittest.TestCase):
    def test_agent_cannot_promote_artifacts_directly(self) -> None:
        result = enforce_no_trade_authority(["PromoteArtifactDirectly"])

        self.assertFalse(result.allowed)
        self.assertIn("forbidden_action:PromoteArtifactDirectly", result.reasons)


if __name__ == "__main__":
    unittest.main()
