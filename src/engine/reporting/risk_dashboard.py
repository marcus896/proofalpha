from __future__ import annotations

from collections.abc import Mapping


REQUIRED_RISK_DASHBOARD_FIELDS = (
    "risk_state",
    "approvals",
    "rejections",
    "circuit_breakers",
    "funding_guard",
    "liquidation_guard",
    "margin_leverage",
    "reconciliation_status",
)


def _get(state: Mapping[str, object], key: str, default: object) -> object:
    value = state.get(key, default)
    return default if value is None else value


def build_risk_dashboard(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "page": "Risk",
        "risk_state": str(_get(state, "risk_state", "UNKNOWN")),
        "approvals": list(_get(state, "approvals", [])),
        "rejections": list(_get(state, "rejections", [])),
        "circuit_breakers": dict(_get(state, "circuit_breakers", {})),
        "funding_guard": dict(_get(state, "funding_guard", {})),
        "liquidation_guard": dict(_get(state, "liquidation_guard", {})),
        "margin_leverage": dict(_get(state, "margin_leverage", {})),
        "reconciliation_status": str(_get(state, "reconciliation_status", "UNKNOWN")),
    }
