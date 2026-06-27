from __future__ import annotations

from dataclasses import asdict, dataclass

from engine.learning.model_registry import ModelRegistry


@dataclass(frozen=True)
class ModelRollbackPlan:
    allowed: bool
    model_id: str
    rollback_model_id: str | None
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_model_rollback_plan(registry: ModelRegistry, *, model_id: str, reason: str) -> ModelRollbackPlan:
    card = registry.get_card(model_id)
    rollback_model_id = card.rollback_model_id if card else None
    return ModelRollbackPlan(
        allowed=bool(rollback_model_id),
        model_id=model_id,
        rollback_model_id=rollback_model_id,
        reason=reason,
    )
