from __future__ import annotations

from collections.abc import Mapping


REQUIRED_LEARNING_DASHBOARD_FIELDS = (
    "active_models",
    "model_cards",
    "training_windows",
    "validation_errors",
    "shadow_results",
    "promotion_history",
    "rollback_history",
)

MODEL_SLOTS = ("slippage", "fill", "funding", "capacity")


def _get(state: Mapping[str, object], key: str, default: object) -> object:
    value = state.get(key, default)
    return default if value is None else value


def _active_models(state: Mapping[str, object]) -> dict[str, object]:
    raw = _get(state, "active_models", {})
    models = dict(raw) if isinstance(raw, Mapping) else {}
    for slot in MODEL_SLOTS:
        models.setdefault(slot, None)
    return models


def build_learning_dashboard(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "page": "Learning Models",
        "active_models": _active_models(state),
        "model_cards": list(_get(state, "model_cards", [])),
        "training_windows": list(_get(state, "training_windows", [])),
        "validation_errors": list(_get(state, "validation_errors", [])),
        "shadow_results": list(_get(state, "shadow_results", [])),
        "promotion_history": list(_get(state, "promotion_history", [])),
        "rollback_history": list(_get(state, "rollback_history", [])),
    }
