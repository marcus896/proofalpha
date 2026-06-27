from __future__ import annotations

from engine.learning.dataset_builder import LearningDataset, build_learning_dataset
from engine.learning.model_card import ModelCard
from engine.learning.model_registry import ModelRegistry


class LearningManager:
    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self.registry = registry or ModelRegistry()

    def build_dataset(self, **kwargs: object) -> LearningDataset:
        return build_learning_dataset(**kwargs)  # type: ignore[arg-type]

    def executor_model(self, model_id: str, *, mode: str) -> ModelCard:
        return self.registry.model_for_executor(model_id, mode=mode)
