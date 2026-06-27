from __future__ import annotations

from dataclasses import asdict, dataclass


MODEL_FAMILIES = {
    "SlippageModel",
    "ImpactModel",
    "FillProbabilityModel",
    "QueuePositionModel",
    "FundingRiskModel",
    "LiquidityRegimeModel",
    "CorrelationModel",
    "StrategyHealthModel",
    "ExecutionPolicyModel",
    "CapacityModel",
}


@dataclass(frozen=True)
class ModelCard:
    model_id: str
    parent_model_id: str | None
    family: str
    training_window: str
    symbols_used: list[str]
    features_used: list[str]
    target: str
    validation_metric: dict[str, float]
    shadow_result: dict[str, object]
    paper_result: dict[str, object]
    approved_modes: list[str]
    known_failures: list[str]
    rollback_model_id: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ModelCardValidation:
    passed: bool
    issues: list[str]


def validate_model_card(card: ModelCard) -> ModelCardValidation:
    issues: list[str] = []
    for field_name in ("model_id", "family", "training_window", "target"):
        if not getattr(card, field_name):
            issues.append(f"missing_{field_name}")
    if card.family not in MODEL_FAMILIES:
        issues.append("unknown_model_family")
    if not card.symbols_used:
        issues.append("missing_symbols_used")
    if not card.features_used:
        issues.append("missing_features_used")
    if not card.validation_metric:
        issues.append("missing_validation_metric")
    if card.shadow_result.get("passed") is not True:
        issues.append("shadow_validation_not_passed")
    if "paper" in card.approved_modes and card.paper_result.get("passed") is not True:
        issues.append("paper_validation_not_passed")
    if not card.rollback_model_id:
        issues.append("missing_rollback_model_id")
    return ModelCardValidation(not issues, issues)
