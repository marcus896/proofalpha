from __future__ import annotations

from pathlib import Path

from engine.mcp.config import MCPProfile, MCPSettings
from engine.mcp.profiles import get_profile_settings
from engine.mcp.tools_launcher import LAUNCHER_TOOL_CATALOG
from engine.mcp.tools_memory import MEMORY_TOOL_CATALOG
from engine.mcp.tools_reporting import REPORTING_TOOL_CATALOG
from engine.mcp.tools_schema import SCHEMA_TOOL_CATALOG
from engine.mcp.tools_validation import VALIDATION_TOOL_CATALOG

_CATEGORY_CATALOGS: dict[str, list[dict[str, object]]] = {
    "memory": MEMORY_TOOL_CATALOG,
    "schema": SCHEMA_TOOL_CATALOG,
    "validation": VALIDATION_TOOL_CATALOG,
    "reporting": REPORTING_TOOL_CATALOG,
    "launcher": LAUNCHER_TOOL_CATALOG,
}


def discover_tools(settings: MCPSettings) -> list[dict[str, object]]:
    """Return tool descriptors for all categories enabled in *settings*."""
    active_categories = settings.default_tool_categories
    tools: list[dict[str, object]] = []
    for category in active_categories:
        catalog = _CATEGORY_CATALOGS.get(category, [])
        for tool in catalog:
            tools.append({**tool, "category": category})
    return tools


def activate_categories(
    categories: list[str],
    settings: MCPSettings,
) -> tuple[list[dict[str, object]], list[str]]:
    """
    Selectively activate a subset of categories from the profile's *allowed* list.

    Returns:
        (tool_list, rejected_categories)
    """
    allowed = set(settings.allowed_tool_categories)
    activated: list[dict[str, object]] = []
    rejected: list[str] = []
    for category in categories:
        if category not in allowed:
            rejected.append(category)
            continue
        catalog = _CATEGORY_CATALOGS.get(category, [])
        for tool in catalog:
            activated.append({**tool, "category": category})
    return activated, rejected


def get_tools_for_profile(profile: MCPProfile) -> list[dict[str, object]]:
    settings = get_profile_settings(profile)
    return discover_tools(settings)


def list_categories() -> list[str]:
    return sorted(_CATEGORY_CATALOGS.keys())
