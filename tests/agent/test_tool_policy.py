from __future__ import annotations

import unittest

from engine.agent.tool_policy import AgentToolPolicy


class AgentToolPolicyTests(unittest.TestCase):
    def test_agent_tool_policy_denies_trade_and_risk_mutation_tools(self) -> None:
        policy = AgentToolPolicy.default_research_profile()

        self.assertFalse(policy.is_allowed("place_order"))
        self.assertFalse(policy.is_allowed("set_leverage"))
        self.assertFalse(policy.is_allowed("promote_artifact_direct"))
        self.assertTrue(policy.is_allowed("list_layers"))
        self.assertIn("request_model_promotion", policy.human_approval_required_tools)


if __name__ == "__main__":
    unittest.main()
