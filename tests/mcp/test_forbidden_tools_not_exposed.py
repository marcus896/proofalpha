from __future__ import annotations

import unittest

from engine.mcp.config import MCPProfile
from engine.mcp.discovery import get_tools_for_profile
from engine.mcp.profiles import FORBIDDEN_MCP_TOOLS


class ForbiddenToolsNotExposedTests(unittest.TestCase):
    def test_forbidden_tools_are_not_exposed_by_any_profile(self) -> None:
        for profile in MCPProfile:
            with self.subTest(profile=profile.value):
                names = {str(tool["name"]) for tool in get_tools_for_profile(profile)}
                self.assertTrue(names.isdisjoint(FORBIDDEN_MCP_TOOLS))


if __name__ == "__main__":
    unittest.main()
