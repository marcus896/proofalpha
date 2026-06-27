from __future__ import annotations

from dataclasses import dataclass

from engine.learning.model_card import ModelCard, validate_model_card


@dataclass(frozen=True)
class ModelApprovalResult:
    approved: bool
    model_id: str
    reasons: list[str]


class ModelRegistry:
    def __init__(self) -> None:
        self._cards: dict[str, ModelCard] = {}
        self._approved: dict[tuple[str, str], str] = {}

    def register_candidate(self, card: ModelCard) -> None:
        self._cards[card.model_id] = card

    def approve(self, model_id: str, *, mode: str) -> ModelApprovalResult:
        card = self._cards.get(model_id)
        if card is None:
            return ModelApprovalResult(False, model_id, ["missing_model_card"])
        validation = validate_model_card(card)
        reasons = list(validation.issues)
        if mode not in card.approved_modes:
            reasons.append("mode_not_approved")
        if reasons:
            return ModelApprovalResult(False, model_id, reasons)
        self._approved[(model_id, mode)] = model_id
        return ModelApprovalResult(True, model_id, [])

    def model_for_executor(self, model_id: str, *, mode: str) -> ModelCard:
        if self._approved.get((model_id, mode)) != model_id:
            raise ValueError(f"model_not_approved:{model_id}:{mode}")
        return self._cards[model_id]

    def get_card(self, model_id: str) -> ModelCard | None:
        return self._cards.get(model_id)
