from __future__ import annotations

from pathlib import Path
from typing import Callable

from engine.mcp.config import MCPProfile, MCPSettings
from engine.mcp.discovery import discover_tools
from engine.mcp.profiles import get_profile_settings
from engine.mcp.tools_launcher import (
    LAUNCHER_TOOL_CATALOG,
    tool_create_autoresearch,
    tool_create_campaign,
    tool_create_study,
)
from engine.mcp.tools_memory import (
    MEMORY_TOOL_CATALOG,
    tool_query_agent_decisions,
    tool_query_data_snapshots,
    tool_query_meta_policies,
    tool_query_resource_index,
    tool_query_run_resource_links,
    tool_query_stress_runs,
    tool_query_validation_runs,
    tool_get_batch,
    tool_get_campaign,
    tool_get_run,
    tool_list_batches,
    tool_list_campaigns,
    tool_list_runs,
    tool_query_memory_summary,
)
from engine.mcp.tools_reporting import (
    REPORTING_TOOL_CATALOG,
    tool_compare_runs,
    tool_list_artifacts,
    tool_summarize_run,
)
from engine.mcp.tools_schema import (
    SCHEMA_TOOL_CATALOG,
    tool_get_layer,
    tool_get_runtime_schema,
    tool_get_scenario_schema,
    tool_get_study_template,
    tool_list_layer_families,
    tool_list_layers,
)
from engine.mcp.tools_validation import (
    VALIDATION_TOOL_CATALOG,
    tool_compare_validation_results,
    tool_get_regime_coverage,
    tool_get_scenario_matrix,
    tool_get_validation_protocol,
)

# Type alias for tool handler functions
ToolHandler = Callable[
    [dict[str, object]],
    dict[str, object],
]

_TOOL_REGISTRY: dict[str, Callable] = {
    # memory
    "list_runs": tool_list_runs,
    "get_run": tool_get_run,
    "list_batches": tool_list_batches,
    "get_batch": tool_get_batch,
    "list_campaigns": tool_list_campaigns,
    "get_campaign": tool_get_campaign,
    "query_memory_summary": tool_query_memory_summary,
    "query_validation_runs": tool_query_validation_runs,
    "query_stress_runs": tool_query_stress_runs,
    "query_agent_decisions": tool_query_agent_decisions,
    "query_data_snapshots": tool_query_data_snapshots,
    "query_resource_index": tool_query_resource_index,
    "query_run_resource_links": tool_query_run_resource_links,
    "query_meta_policies": tool_query_meta_policies,
    # schema
    "list_layer_families": tool_list_layer_families,
    "list_layers": tool_list_layers,
    "get_layer": tool_get_layer,
    "get_runtime_schema": tool_get_runtime_schema,
    "get_scenario_schema": tool_get_scenario_schema,
    "get_study_template": tool_get_study_template,
    # validation
    "get_validation_protocol": tool_get_validation_protocol,
    "get_regime_coverage": tool_get_regime_coverage,
    "get_scenario_matrix": tool_get_scenario_matrix,
    "compare_validation_results": tool_compare_validation_results,
    # reporting
    "summarize_run": tool_summarize_run,
    "compare_runs": tool_compare_runs,
    "list_artifacts": tool_list_artifacts,
    # launcher
    "create_study": tool_create_study,
    "create_autoresearch": tool_create_autoresearch,
    "create_campaign": tool_create_campaign,
}


class MCPServer:
    """
    Local MCP server — dispatches tool calls from an agent to the correct module.

    All calls are validated against the active profile before dispatch.
    Launcher tools additionally require `settings.launcher_enabled = True`.
    """

    def __init__(
        self,
        *,
        profile: MCPProfile = MCPProfile.READ_ONLY,
        output_dir: Path,
        db_path: Path,
    ) -> None:
        self.profile = profile
        self.settings: MCPSettings = get_profile_settings(profile)
        self.output_dir = output_dir
        self.db_path = db_path
        self._active_tools: dict[str, dict[str, object]] = {
            tool["name"]: tool for tool in discover_tools(self.settings)  # type: ignore[index]
        }

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, object]]:
        """Return the tool catalog for the active profile."""
        return list(self._active_tools.values())

    def call_tool(
        self,
        name: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """
        Dispatch a tool call by name.

        Raises ValueError if the tool is not available in the current profile.
        """
        if name not in self._active_tools:
            return {
                "error": (
                    f"tool '{name}' is not available in profile '{self.profile.value}'. "
                    f"Available tools: {sorted(self._active_tools)}"
                )
            }
        handler = _TOOL_REGISTRY.get(name)
        if handler is None:
            return {"error": f"tool '{name}' has no registered handler"}
        return handler(
            params or {},
            settings=self.settings,
            output_dir=self.output_dir,
            db_path=self.db_path,
        )

    def describe(self) -> dict[str, object]:
        return {
            "profile": self.profile.value,
            "launcher_enabled": self.settings.launcher_enabled,
            "active_categories": self.settings.default_tool_categories,
            "tool_count": len(self._active_tools),
            "tools": self.list_tools(),
        }


def build_mcp_server(
    profile: MCPProfile,
    *,
    output_dir: Path,
    db_path: Path,
) -> MCPServer:
    return MCPServer(profile=profile, output_dir=output_dir, db_path=db_path)
