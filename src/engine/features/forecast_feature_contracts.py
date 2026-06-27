from __future__ import annotations

from dataclasses import dataclass


FORECAST_PREFIXES = ("forecast_", "timesfm_")
OBSERVATION_ONLY_PREFIXES = ("forecast_observation_", "forecast_meta_")
FORECAST_AUTHORITY_TERMS = (
    "order",
    "trade",
    "position",
    "leverage",
    "size",
    "stop",
    "urgency",
    "venue_order",
)


@dataclass(frozen=True)
class ForecastFeatureNameValidation:
    passed: bool
    reasons: list[str]


def is_forecast_field(name: str) -> bool:
    return name.startswith(FORECAST_PREFIXES) or name.startswith("timesfm_")


def is_forecast_observation_metadata(name: str) -> bool:
    return name.startswith(OBSERVATION_ONLY_PREFIXES)


def is_forecast_authority_field(name: str) -> bool:
    lowered = name.lower()
    return is_forecast_field(lowered) and any(term in lowered for term in FORECAST_AUTHORITY_TERMS)


def validate_forecast_feature_names(names: list[str]) -> ForecastFeatureNameValidation:
    reasons: list[str] = []
    for name in names:
        if is_forecast_authority_field(name):
            reasons.append(f"forecast_authority_field_not_allowed:{name}")
    return ForecastFeatureNameValidation(not reasons, reasons)
