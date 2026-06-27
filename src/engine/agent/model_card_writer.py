from __future__ import annotations

from engine.learning.model_card import ModelCard


def model_card_from_payload(payload: dict[str, object]) -> ModelCard:
    return ModelCard(
        model_id=str(payload.get("model_id", "")),
        parent_model_id=str(payload.get("parent_model_id")) if payload.get("parent_model_id") else None,
        family=str(payload.get("family", "")),
        training_window=str(payload.get("training_window", "")),
        symbols_used=[str(value) for value in payload.get("symbols_used", []) if isinstance(value, str)],
        features_used=[str(value) for value in payload.get("features_used", []) if isinstance(value, str)],
        target=str(payload.get("target", "")),
        validation_metric=dict(payload.get("validation_metric", {})) if isinstance(payload.get("validation_metric"), dict) else {},
        shadow_result=dict(payload.get("shadow_result", {})) if isinstance(payload.get("shadow_result"), dict) else {},
        paper_result=dict(payload.get("paper_result", {})) if isinstance(payload.get("paper_result"), dict) else {},
        approved_modes=[str(value) for value in payload.get("approved_modes", []) if isinstance(value, str)],
        known_failures=[str(value) for value in payload.get("known_failures", []) if isinstance(value, str)],
        rollback_model_id=str(payload.get("rollback_model_id")) if payload.get("rollback_model_id") else None,
    )
