from __future__ import annotations

from engine.mcp.config import MCPProfile, MCPSettings
from engine.mcp.settings import build_discovery_settings, build_launcher_settings, build_read_only_settings

FORBIDDEN_MCP_TOOLS = {
    "raw_shell",
    "raw_python",
    "raw_sql_mutation",
    "place_order",
    "live_exchange_trade",
    "change_risk_limit",
    "direct_promotion",
    "approve_symbol_for_paper",
    "disable_circuit_breaker",
    "enable_live",
}

_PROFILE_MAP: dict[MCPProfile, MCPSettings] = {
    MCPProfile.READ_ONLY: build_read_only_settings(),
    MCPProfile.LAUNCHER: build_launcher_settings(),
    MCPProfile.DISCOVERY: build_discovery_settings(),
}


def get_profile_settings(profile: MCPProfile) -> MCPSettings:
    return _PROFILE_MAP[profile]


def list_profile_names() -> list[str]:
    return sorted(profile.value for profile in MCPProfile)


def is_tool_allowed_for_profile(profile: MCPProfile, tool_name: str) -> bool:
    if tool_name in FORBIDDEN_MCP_TOOLS:
        return False
    from engine.mcp.discovery import get_tools_for_profile

    return tool_name in {str(tool["name"]) for tool in get_tools_for_profile(profile)}
