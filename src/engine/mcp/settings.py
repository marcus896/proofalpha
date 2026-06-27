from __future__ import annotations

from engine.mcp.config import MCPSettings


def build_read_only_settings() -> MCPSettings:
    """Standard read-only profile: memory, schema, validation, reporting only."""
    return MCPSettings(
        default_tool_categories=["memory", "schema", "validation", "reporting"],
        allowed_tool_categories=["memory", "schema", "validation", "reporting"],
        launcher_enabled=False,
        enable_tool_discovery=False,
    )


def build_launcher_settings() -> MCPSettings:
    """Launcher profile: adds launcher category; still no arbitrary shell access."""
    return MCPSettings(
        default_tool_categories=["memory", "schema", "validation", "reporting", "launcher"],
        allowed_tool_categories=["memory", "schema", "validation", "reporting", "launcher"],
        launcher_enabled=True,
        enable_tool_discovery=False,
    )


def build_discovery_settings() -> MCPSettings:
    """Discovery profile: all categories allowed; agent must explicitly activate each one."""
    return MCPSettings(
        default_tool_categories=[],
        allowed_tool_categories=["memory", "schema", "validation", "reporting", "launcher"],
        launcher_enabled=True,
        enable_tool_discovery=True,
    )
