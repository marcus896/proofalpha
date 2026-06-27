from __future__ import annotations

from collections.abc import Mapping


REQUIRED_PORTFOLIO_DASHBOARD_FIELDS = (
    "target_weights",
    "current_weights",
    "deltas",
    "exposures",
    "btc_beta",
    "eth_beta",
    "cluster_exposure",
    "turnover",
    "funding_budget",
    "pnl_attribution",
)

PNL_ATTRIBUTION_BUCKETS = (
    "btc_beta",
    "eth_beta",
    "symbol_selection",
    "timing",
    "funding",
    "fees",
    "slippage",
    "spread_impact",
    "rebalance_cost",
    "residual_alpha",
)


def _get(state: Mapping[str, object], key: str, default: object) -> object:
    value = state.get(key, default)
    return default if value is None else value


def _pnl_attribution(state: Mapping[str, object]) -> dict[str, object]:
    raw = _get(state, "pnl_attribution", {})
    attribution = dict(raw) if isinstance(raw, Mapping) else {}
    for bucket in PNL_ATTRIBUTION_BUCKETS:
        attribution.setdefault(bucket, 0.0)
    return attribution


def build_portfolio_dashboard(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "page": "Portfolio Targets",
        "target_weights": dict(_get(state, "target_weights", {})),
        "current_weights": dict(_get(state, "current_weights", {})),
        "deltas": dict(_get(state, "deltas", {})),
        "exposures": dict(_get(state, "exposures", {})),
        "btc_beta": float(_get(state, "btc_beta", 0.0)),
        "eth_beta": float(_get(state, "eth_beta", 0.0)),
        "cluster_exposure": dict(_get(state, "cluster_exposure", {})),
        "turnover": float(_get(state, "turnover", 0.0)),
        "funding_budget": dict(_get(state, "funding_budget", {})),
        "pnl_attribution": _pnl_attribution(state),
    }
