from __future__ import annotations

import unittest

from engine.mcp.config import MCPProfile
from engine.mcp.profiles import is_tool_allowed_for_profile


class MCPProfileGatingTests(unittest.TestCase):
    def test_mcp_profile_gating_allows_high_level_tools_only(self) -> None:
        self.assertTrue(is_tool_allowed_for_profile(MCPProfile.READ_ONLY, "list_runs"))
        self.assertFalse(is_tool_allowed_for_profile(MCPProfile.READ_ONLY, "create_study"))
        self.assertTrue(is_tool_allowed_for_profile(MCPProfile.LAUNCHER, "create_study"))
        self.assertFalse(is_tool_allowed_for_profile(MCPProfile.LAUNCHER, "raw_shell"))


if __name__ == "__main__":
    unittest.main()
