from __future__ import annotations

from dataclasses import dataclass


DENIED_AGENT_TOOLS = {
    "place_order",
    "submit_order",
    "set_leverage",
    "change_margin_mode",
    "change_position_mode",
    "promote_artifact_direct",
    "approve_symbol_direct",
    "disable_circuit_breaker",
}


@dataclass(frozen=True)
class AgentToolPolicy:
    profile: str
    allowed_tools: set[str]
    denied_tools: set[str]
    human_approval_required_tools: set[str]
    audit_log_required: bool

    @staticmethod
    def default_research_profile() -> "AgentToolPolicy":
        return AgentToolPolicy(
            profile="research",
            allowed_tools={"list_layers", "get_validation_protocol", "compare_validation_results"},
            denied_tools=set(DENIED_AGENT_TOOLS),
            human_approval_required_tools={"request_artifact_promotion", "request_model_promotion"},
            audit_log_required=True,
        )

    def is_allowed(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools and tool_name not in self.denied_tools
