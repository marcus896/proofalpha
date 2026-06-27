"""Tests for engine.mcp.config MCPSettings, MCPProfile, AgentDescriptor."""
from __future__ import annotations

import unittest

from engine.mcp.config import AgentDescriptor, MCPProfile, MCPSettings


class TestMCPProfile(unittest.TestCase):
    def test_values_are_strings(self) -> None:
        for profile in MCPProfile:
            assert isinstance(profile.value, str)

    def test_all_three_profiles_exist(self) -> None:
        names = {profile.value for profile in MCPProfile}
        assert "read_only" in names
        assert "launcher" in names
        assert "discovery" in names

    def test_profile_from_string(self) -> None:
        assert MCPProfile("read_only") == MCPProfile.READ_ONLY
        assert MCPProfile("launcher") == MCPProfile.LAUNCHER
        assert MCPProfile("discovery") == MCPProfile.DISCOVERY

    def test_invalid_profile_raises(self) -> None:
        with self.assertRaises(ValueError):
            MCPProfile("shell_exec")


class TestMCPSettings(unittest.TestCase):
    def test_defaults_exclude_launcher(self) -> None:
        settings = MCPSettings()
        assert not settings.launcher_enabled
        assert "launcher" not in settings.default_tool_categories

    def test_pagination_limit_positive(self) -> None:
        settings = MCPSettings()
        assert settings.pagination_limit > 0

    def test_frozen(self) -> None:
        settings = MCPSettings()
        with self.assertRaises((AttributeError, TypeError)):
            settings.launcher_enabled = True  # type: ignore[misc]

    def test_custom_settings(self) -> None:
        settings = MCPSettings(
            launcher_enabled=True,
            default_tool_categories=["memory"],
            pagination_limit=10,
        )
        assert settings.launcher_enabled
        assert settings.default_tool_categories == ["memory"]
        assert settings.pagination_limit == 10


class TestAgentDescriptor(unittest.TestCase):
    def test_construction(self) -> None:
        desc = AgentDescriptor(name="test-agent")
        assert desc.name == "test-agent"
        assert desc.mcp_tools is True
        assert desc.streaming is False

    def test_frozen(self) -> None:
        desc = AgentDescriptor(name="x")
        with self.assertRaises((AttributeError, TypeError)):
            desc.name = "y"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
