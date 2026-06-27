from __future__ import annotations

from dataclasses import asdict, dataclass


REQUIRED_FORBIDDEN_USES = {
    "orders",
    "position_size",
    "leverage",
    "stops",
    "execution_urgency",
    "artifact_promotion",
}
ALLOWED_FORECAST_MODES = {"research", "validation", "shadow", "paper_observation"}


@dataclass(frozen=True)
class ForecastModelCard:
    forecast_model_id: str
    parent_model_id: str | None
    model_type: str
    training_window: dict[str, object]
    symbols: list[str]
    horizon: int
    quantiles: list[str]
    calibration_metrics: dict[str, object]
    baseline_comparison: dict[str, object]
    decay_status: str
    allowed_modes: list[str]
    forbidden_uses: list[str]
    rollback_model_id: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ForecastModelCardValidation:
    passed: bool
    reasons: list[str]


def validate_forecast_model_card(card: ForecastModelCard) -> ForecastModelCardValidation:
    reasons: list[str] = []
    if not card.forecast_model_id:
        reasons.append("missing_forecast_model_id")
    if not card.model_type:
        reasons.append("missing_model_type")
    if card.horizon <= 0:
        reasons.append("horizon_must_be_positive")
    if not card.symbols:
        reasons.append("missing_symbols")
    if "q50" not in set(card.quantiles):
        reasons.append("missing_required_quantile:q50")
    for mode in card.allowed_modes:
        if mode not in ALLOWED_FORECAST_MODES:
            reasons.append(f"allowed_mode_not_forecast_safe:{mode}")
    forbidden = set(card.forbidden_uses)
    for use in sorted(REQUIRED_FORBIDDEN_USES - forbidden):
        reasons.append(f"missing_forbidden_use:{use}")
    return ForecastModelCardValidation(not reasons, reasons)
