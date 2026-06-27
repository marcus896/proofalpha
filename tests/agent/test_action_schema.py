from __future__ import annotations

import unittest

from engine.agent.action_schema import AgentActionSchema


class AgentActionSchemaTests(unittest.TestCase):
    def test_agent_can_propose_studies_only_from_allowlist(self) -> None:
        self.assertTrue(AgentActionSchema.validate_action("ProposeStudy").allowed)
        self.assertTrue(AgentActionSchema.validate_action("StopCampaign").allowed)
        self.assertFalse(AgentActionSchema.validate_action("PlaceOrder").allowed)
        self.assertFalse(AgentActionSchema.validate_action("EnableLive").allowed)


if __name__ == "__main__":
    unittest.main()
