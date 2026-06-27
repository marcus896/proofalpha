"""Tests for engine.mcp.discovery tool discovery and category activation."""
from __future__ import annotations

import unittest

from engine.mcp.config import MCPProfile
from engine.mcp.discovery import (
    activate_categories,
    discover_tools,
    get_tools_for_profile,
    list_categories,
)
from engine.mcp.settings import build_launcher_settings, build_read_only_settings


class TestListCategories(unittest.TestCase):
    def test_returns_expected_categories(self) -> None:
        cats = list_categories()
        for expected in ("memory", "schema", "validation", "reporting", "launcher"):
            assert expected in cats

    def test_sorted(self) -> None:
        cats = list_categories()
        assert cats == sorted(cats)


class TestDiscoverTools(unittest.TestCase):
    def test_read_only_has_no_launcher_tools(self) -> None:
        settings = build_read_only_settings()
        tools = discover_tools(settings)
        categories = {t["category"] for t in tools}
        assert "launcher" not in categories

    def test_launcher_profile_has_launcher_tools(self) -> None:
        settings = build_launcher_settings()
        tools = discover_tools(settings)
        categories = {t["category"] for t in tools}
        assert "launcher" in categories

    def test_all_tools_have_required_fields(self) -> None:
        settings = build_launcher_settings()
        tools = discover_tools(settings)
        for tool in tools:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool missing 'description': {tool}"
            assert "category" in tool, f"Tool missing 'category': {tool}"

    def test_no_duplicate_names_within_read_only(self) -> None:
        settings = build_read_only_settings()
        tools = discover_tools(settings)
        names = [t["name"] for t in tools]
        assert len(names) == len(set(names)), "Duplicate tool names found"

    def test_discovery_empty_by_default(self) -> None:
        from engine.mcp.settings import build_discovery_settings

        settings = build_discovery_settings()
        tools = discover_tools(settings)
        assert tools == []


class TestActivateCategories(unittest.TestCase):
    def test_allowed_categories_return_tools(self) -> None:
        settings = build_read_only_settings()
        tools, rejected = activate_categories(["memory"], settings)
        assert len(tools) > 0
        assert rejected == []

    def test_disallowed_category_rejected(self) -> None:
        settings = build_read_only_settings()
        tools, rejected = activate_categories(["launcher"], settings)
        assert "launcher" in rejected
        assert len(tools) == 0

    def test_mixed_categories(self) -> None:
        settings = build_read_only_settings()
        tools, rejected = activate_categories(["memory", "launcher"], settings)
        assert "launcher" in rejected
        categories = {t["category"] for t in tools}
        assert "memory" in categories

    def test_empty_request(self) -> None:
        settings = build_read_only_settings()
        tools, rejected = activate_categories([], settings)
        assert tools == []
        assert rejected == []


class TestGetToolsForProfile(unittest.TestCase):
    def test_read_only_tools_non_empty(self) -> None:
        tools = get_tools_for_profile(MCPProfile.READ_ONLY)
        assert len(tools) > 0

    def test_launcher_tools_more_than_read_only(self) -> None:
        ro_tools = get_tools_for_profile(MCPProfile.READ_ONLY)
        la_tools = get_tools_for_profile(MCPProfile.LAUNCHER)
        assert len(la_tools) > len(ro_tools)

    def test_discovery_profile_empty(self) -> None:
        tools = get_tools_for_profile(MCPProfile.DISCOVERY)
        assert tools == []


if __name__ == "__main__":
    unittest.main()
