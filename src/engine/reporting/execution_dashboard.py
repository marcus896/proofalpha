from __future__ import annotations

from collections.abc import Mapping


REQUIRED_EXECUTION_DASHBOARD_FIELDS = (
    "pending_intents",
    "risk_approvals",
    "risk_rejections",
    "translated_orders",
    "open_orders",
    "fills",
    "partial_fills",
    "slippage",
    "fees",
    "funding",
    "markouts",
    "client_order_ids",
    "websocket_freshness",
    "reconciliation_status",
    "risk_state",
    "circuit_breakers",
)


def _get(state: Mapping[str, object], key: str, default: object) -> object:
    value = state.get(key, default)
    return default if value is None else value


def build_execution_dashboard(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "page": "Execution Desk",
        "pending_intents": list(_get(state, "pending_intents", [])),
        "risk_approvals": list(_get(state, "risk_approvals", [])),
        "risk_rejections": list(_get(state, "risk_rejections", [])),
        "translated_orders": list(_get(state, "translated_orders", [])),
        "open_orders": list(_get(state, "open_orders", [])),
        "fills": list(_get(state, "fills", [])),
        "partial_fills": list(_get(state, "partial_fills", [])),
        "slippage": dict(_get(state, "slippage", {})),
        "fees": dict(_get(state, "fees", {})),
        "funding": dict(_get(state, "funding", {})),
        "markouts": dict(_get(state, "markouts", {})),
        "client_order_ids": list(_get(state, "client_order_ids", [])),
        "websocket_freshness": dict(_get(state, "websocket_freshness", {})),
        "reconciliation_status": str(_get(state, "reconciliation_status", "UNKNOWN")),
        "risk_state": str(_get(state, "risk_state", "UNKNOWN")),
        "circuit_breakers": dict(_get(state, "circuit_breakers", {})),
    }
