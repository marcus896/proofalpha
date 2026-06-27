from __future__ import annotations

from collections.abc import Mapping


REQUIRED_AUTORESEARCH_DASHBOARD_FIELDS = (
    "research",
    "artifacts",
    "autoresearch",
    "journal",
    "loop_mode",
    "proposed_studies",
    "running_studies",
    "stopped_campaigns",
    "action_schema",
    "mcp_profile",
    "authority_boundary",
)


def _get(state: Mapping[str, object], key: str, default: object) -> object:
    value = state.get(key, default)
    return default if value is None else value


def build_autoresearch_dashboard(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "page": "Autoresearch",
        "research": dict(_get(state, "research", {})),
        "artifacts": dict(_get(state, "artifacts", {})),
        "autoresearch": dict(_get(state, "autoresearch", {})),
        "journal": list(_get(state, "journal", [])),
        "loop_mode": str(_get(state, "loop_mode", "STOP")),
        "proposed_studies": list(_get(state, "proposed_studies", [])),
        "running_studies": list(_get(state, "running_studies", [])),
        "stopped_campaigns": list(_get(state, "stopped_campaigns", [])),
        "action_schema": dict(_get(state, "action_schema", {})),
        "mcp_profile": str(_get(state, "mcp_profile", "read_only")),
        "authority_boundary": {
            "trade_authority": False,
            "direct_promotion": False,
            "risk_limit_mutation": False,
            **dict(_get(state, "authority_boundary", {})),
        },
    }
