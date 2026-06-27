from __future__ import annotations

from dataclasses import dataclass


FORBIDDEN_TOOLS = {"place_order", "set_leverage", "change_margin_mode", "promote_artifact_direct", "disable_circuit_breaker"}


@dataclass(frozen=True)
class ProfilePermissions:
    profile: str
    allowed_tools: set[str]
    denied_tools: set[str]

    @staticmethod
    def paper_execute() -> "ProfilePermissions":
        return ProfilePermissions(
            profile="paper_execute",
            allowed_tools={"get_validation_protocol", "list_layers", "list_artifacts"},
            denied_tools=set(FORBIDDEN_TOOLS),
        )

    def is_tool_allowed(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools and tool_name not in self.denied_tools
