from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MCPProfile(str, Enum):
    READ_ONLY = "read_only"
    LAUNCHER = "launcher"
    DISCOVERY = "discovery"


@dataclass(frozen=True)
class MCPSettings:
    default_tool_categories: list[str] = field(
        default_factory=lambda: ["memory", "schema", "validation", "reporting"]
    )
    allowed_tool_categories: list[str] = field(
        default_factory=lambda: ["memory", "schema", "validation", "reporting"]
    )
    enable_tool_discovery: bool = False
    default_skills_dir: str = "skills"
    system_prompt_file: str | None = None
    server_prompts_file: str | None = None
    skills_reload: bool = False
    skills_providers: list[str] = field(default_factory=list)
    launcher_enabled: bool = False
    auth_mode: str = "none"
    pagination_limit: int = 50


@dataclass(frozen=True)
class AgentDescriptor:
    name: str
    streaming: bool = False
    widget_dashboard_search: bool = False
    mcp_tools: bool = True
