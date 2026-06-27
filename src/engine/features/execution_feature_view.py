from __future__ import annotations

from typing import Any

from engine.features.contracts import EXECUTION_MODES, FeatureContract
from engine.features.feature_ttl import evaluate_feature_ttl
from engine.features.forecast_feature_contracts import (
    is_forecast_authority_field,
    is_forecast_field,
    is_forecast_observation_metadata,
)


def build_execution_feature_view(
    values: dict[str, Any],
    *,
    contracts: dict[str, FeatureContract],
    mode: str,
    now_utc: str,
    observed_at_by_field: dict[str, str],
    allow_forecast_observation_metadata: bool = False,
) -> dict[str, Any]:
    if mode not in EXECUTION_MODES:
        raise ValueError(f"not_execution_mode:{mode}")
    for name in sorted(values):
        if is_forecast_authority_field(name):
            raise ValueError(f"forecast_authority_field:{name}")
        if is_forecast_field(name) and not (
            allow_forecast_observation_metadata and is_forecast_observation_metadata(name)
        ):
            raise ValueError(f"forecast_field_not_execution_safe:{name}")
        contract = contracts.get(name)
        if contract is not None and contract.leakage_risk == "research_only":
            raise ValueError(f"research_only_field:{name}")
    ttl = evaluate_feature_ttl(
        values,
        contracts=contracts,
        mode=mode,
        now_utc=now_utc,
        observed_at_by_field=observed_at_by_field,
    )
    if not ttl.passed:
        raise ValueError(",".join(ttl.issues))
    return {name: values[name] for name in sorted(values)}
