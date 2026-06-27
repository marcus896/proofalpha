"""Tests for engine.mcp.profiles and engine.mcp.settings."""
from __future__ import annotations

from engine.mcp.config import MCPProfile, MCPSettings
from engine.mcp.profiles import get_profile_settings, list_profile_names
from engine.mcp.settings import (
    build_discovery_settings,
    build_launcher_settings,
    build_read_only_settings,
)


class TestProfileNames:
    def test_all_three_profiles_listed(self) -> None:
        names = list_profile_names()
        assert "read_only" in names
        assert "launcher" in names
        assert "discovery" in names

    def test_sorted(self) -> None:
        names = list_profile_names()
        assert names == sorted(names)


class TestReadOnlySettings:
    def test_launcher_disabled(self) -> None:
        s = build_read_only_settings()
        assert not s.launcher_enabled

    def test_launcher_not_in_categories(self) -> None:
        s = build_read_only_settings()
        assert "launcher" not in s.default_tool_categories
        assert "launcher" not in s.allowed_tool_categories

    def test_core_categories_present(self) -> None:
        s = build_read_only_settings()
        for cat in ("memory", "schema", "validation", "reporting"):
            assert cat in s.default_tool_categories


class TestLauncherSettings:
    def test_launcher_enabled(self) -> None:
        s = build_launcher_settings()
        assert s.launcher_enabled

    def test_launcher_in_categories(self) -> None:
        s = build_launcher_settings()
        assert "launcher" in s.default_tool_categories
        assert "launcher" in s.allowed_tool_categories


class TestDiscoverySettings:
    def test_discovery_enabled(self) -> None:
        s = build_discovery_settings()
        assert s.enable_tool_discovery

    def test_default_categories_empty(self) -> None:
        # Discovery profile starts with nothing active — agent must opt-in
        s = build_discovery_settings()
        assert s.default_tool_categories == []

    def test_all_categories_allowed(self) -> None:
        s = build_discovery_settings()
        for cat in ("memory", "schema", "validation", "reporting", "launcher"):
            assert cat in s.allowed_tool_categories


class TestGetProfileSettings:
    def test_read_only_returns_settings(self) -> None:
        s = get_profile_settings(MCPProfile.READ_ONLY)
        assert isinstance(s, MCPSettings)
        assert not s.launcher_enabled

    def test_launcher_returns_settings(self) -> None:
        s = get_profile_settings(MCPProfile.LAUNCHER)
        assert isinstance(s, MCPSettings)
        assert s.launcher_enabled

    def test_discovery_returns_settings(self) -> None:
        s = get_profile_settings(MCPProfile.DISCOVERY)
        assert isinstance(s, MCPSettings)
        assert s.enable_tool_discovery
