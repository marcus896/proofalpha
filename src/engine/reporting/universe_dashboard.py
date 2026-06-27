from __future__ import annotations

from collections.abc import Mapping


REQUIRED_UNIVERSE_DASHBOARD_FIELDS = (
    "manifest_state",
    "rings",
    "exposure_caps",
    "admissions",
    "demotions",
    "quarantine",
    "scorecards",
    "discovery",
)


def _get(state: Mapping[str, object], key: str, default: object) -> object:
    value = state.get(key, default)
    return default if value is None else value


def build_universe_dashboard(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "page": "Universe",
        "manifest_state": dict(_get(state, "manifest_state", {})),
        "rings": dict(_get(state, "rings", {})),
        "exposure_caps": dict(_get(state, "exposure_caps", {})),
        "admissions": list(_get(state, "admissions", [])),
        "demotions": list(_get(state, "demotions", [])),
        "quarantine": list(_get(state, "quarantine", [])),
        "scorecards": dict(_get(state, "scorecards", {})),
        "discovery": list(_get(state, "discovery", [])),
    }
