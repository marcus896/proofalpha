from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from engine.strategy.catalog import BACKBONES, approved_layer_names, get_layer_by_name


ALLOWED_FAMILIES = {
    "momentum",
    "breakout",
    "carry",
    "mean_reversion",
    "regime_overlay",
}

ALLOWED_FEATURE_CONTRACTS = {
    "ohlcv",
    "funding",
    "forecast_feature",
    "open_interest",
    "liquidation",
    "mark_price",
    "index_price",
    "premium_index",
    "spread",
    "depth",
    "regime_labels",
}

ALLOWED_RISK_HOOKS = {
    "max_drawdown",
    "funding_shock",
    "liquidation_guard",
    "venue_profile_guard",
    "regime_scope",
    "stale_data_pause",
}

ALLOWED_EXECUTION_POLICY_FIELDS = {
    "venue",
    "signal_tf",
    "execution_tf",
    "order_style",
    "post_only",
    "reduce_only",
}
ALLOWED_SIGNAL_TIMEFRAMES = {"1m", "15m", "1h"}
ALLOWED_EXECUTION_TIMEFRAMES = {"1m", "15m"}

ALLOWED_FORECAST_FEATURE_CONFIG_FIELDS = {
    "provider",
    "model_id",
    "feature_fields",
    "horizon",
    "context_length",
    "config_checksum",
}

ALLOWED_FORECAST_FEATURE_FIELDS = {
    "timesfm_q50_return",
    "timesfm_direction",
    "timesfm_interval_width",
    "timesfm_uncertainty_ratio",
    "timesfm_skew",
    "timesfm_confidence_bucket",
}

PROHIBITED_FORECAST_EXECUTION_FIELDS = {
    "raw_forecast_order",
    "forecast_order",
    "forecast_trade_action",
    "emit_buy_sell_size",
}

PROHIBITED_FREE_FORM_FIELDS = {
    "python_code",
    "source_code",
    "script",
    "code",
    "raw_order_logic",
    "raw_signal_logic",
}

ALLOWED_STRUCTURE_FIELDS = {
    "backbone",
    "directional_layers",
    "known_good_filters",
    "custom_filters",
    "exit_layers",
}

BACKBONE_TO_FAMILY = {
    "mom_squeeze": "momentum",
    "kama_hma": "momentum",
    "keltner_fade": "mean_reversion",
}


@dataclass(frozen=True)
class BoundedStrategyValidation:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    identity_hash: str | None = None
    normalized_spec: dict[str, object] = field(default_factory=dict)


def validate_bounded_strategy_spec(spec: dict[str, object]) -> BoundedStrategyValidation:
    reasons: list[str] = []
    if not isinstance(spec, dict):
        return BoundedStrategyValidation(passed=False, reasons=["spec_not_object"])

    if PROHIBITED_FREE_FORM_FIELDS.intersection(spec):
        reasons.append("free_form_code_not_allowed")

    allowed_keys = {
        "family",
        "variant_id",
        "feature_contracts",
        "parameter_schema",
        "risk_hooks",
        "execution_policy",
        "structure",
        "forecast_feature_config",
    }
    for key in spec:
        if key not in allowed_keys and key not in PROHIBITED_FREE_FORM_FIELDS:
            reasons.append(f"unknown_field:{key}")

    family = spec.get("family")
    if family not in ALLOWED_FAMILIES:
        reasons.append("family_not_allowed")

    variant_id = spec.get("variant_id")
    if not isinstance(variant_id, str) or not variant_id.strip():
        reasons.append("missing_variant_id")

    feature_contracts = spec.get("feature_contracts")
    normalized_features = _normalize_string_list(feature_contracts)
    if not normalized_features:
        reasons.append("missing_feature_contracts")
    invalid_features = [item for item in normalized_features if item not in ALLOWED_FEATURE_CONTRACTS]
    if invalid_features:
        reasons.append("feature_contract_not_allowed")

    parameter_schema = spec.get("parameter_schema")
    normalized_parameter_schema = _normalize_parameter_schema(parameter_schema)
    if not normalized_parameter_schema:
        reasons.append("missing_parameter_schema")

    risk_hooks = spec.get("risk_hooks")
    normalized_risk_hooks = _normalize_string_list(risk_hooks)
    invalid_risk_hooks = [item for item in normalized_risk_hooks if item not in ALLOWED_RISK_HOOKS]
    if invalid_risk_hooks:
        reasons.append("risk_hook_not_allowed")

    execution_policy = spec.get("execution_policy")
    normalized_execution_policy, execution_policy_issues = _normalize_execution_policy(execution_policy)
    reasons.extend(execution_policy_issues)
    if not normalized_execution_policy:
        reasons.append("missing_execution_policy")
    else:
        if normalized_execution_policy.get("venue") != "binance":
            reasons.append("venue_not_allowed")
        if normalized_execution_policy.get("signal_tf") not in ALLOWED_SIGNAL_TIMEFRAMES:
            reasons.append("signal_tf_not_allowed")
        if normalized_execution_policy.get("execution_tf") not in ALLOWED_EXECUTION_TIMEFRAMES:
            reasons.append("execution_tf_not_allowed")

    structure = spec.get("structure")
    normalized_structure = _normalize_structure(structure)
    if structure is not None and not normalized_structure:
        reasons.append("invalid_structure")
    elif normalized_structure and normalized_structure.get("backbone") not in {layer.name for layer in BACKBONES}:
        reasons.append("backbone_not_allowed")

    forecast_feature_config = spec.get("forecast_feature_config")
    normalized_forecast_feature_config, forecast_feature_issues = _normalize_forecast_feature_config(
        forecast_feature_config
    )
    reasons.extend(forecast_feature_issues)
    if "forecast_feature" in normalized_features and not normalized_forecast_feature_config:
        reasons.append("missing_forecast_feature_config")
    if forecast_feature_config is not None and "forecast_feature" not in normalized_features:
        reasons.append("forecast_feature_config_without_contract")

    if reasons:
        return BoundedStrategyValidation(passed=False, reasons=reasons)

    normalized_spec = {
        "family": str(family),
        "variant_id": str(variant_id),
        "feature_contracts": normalized_features,
        "parameter_schema": normalized_parameter_schema,
        "risk_hooks": normalized_risk_hooks,
        "execution_policy": normalized_execution_policy,
        "structure": normalized_structure,
        "forecast_feature_config": normalized_forecast_feature_config,
    }
    identity_hash = hashlib.sha256(json.dumps(normalized_spec, sort_keys=True).encode("utf-8")).hexdigest()
    return BoundedStrategyValidation(
        passed=True,
        reasons=[],
        identity_hash=identity_hash,
        normalized_spec=normalized_spec,
    )


def build_bounded_strategy_spec_from_payload(payload: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("payload_not_object")

    incumbent = payload.get("incumbent", {})
    backbone = str(incumbent.get("backbone", "")).strip() if isinstance(incumbent, dict) else ""
    if not backbone:
        backbone = str(payload.get("backbone", "")).strip()
    family = BACKBONE_TO_FAMILY.get(backbone, "momentum")

    snapshot = payload.get("snapshot", {})
    feature_contracts = ["ohlcv"]
    if isinstance(snapshot, dict):
        if snapshot.get("funding_rates") is not None:
            feature_contracts.append("funding")
        if snapshot.get("open_interest") is not None:
            feature_contracts.append("open_interest")
        if snapshot.get("liquidation_notional") is not None:
            feature_contracts.append("liquidation")
        if snapshot.get("mark_price") is not None:
            feature_contracts.append("mark_price")
        if snapshot.get("index_price") is not None:
            feature_contracts.append("index_price")
        if snapshot.get("spread_bps") is not None:
            feature_contracts.append("spread")
        if snapshot.get("depth_bid_1bp_usd") is not None or snapshot.get("depth_ask_1bp_usd") is not None:
            feature_contracts.append("depth")
        if snapshot.get("regime_id") is not None or snapshot.get("vol_regime") is not None:
            feature_contracts.append("regime_labels")
        if snapshot.get("forecast_features") is not None or payload.get("forecast_feature_config") is not None:
            feature_contracts.append("forecast_feature")

    structure = {
        "backbone": backbone,
        "directional_layers": _normalize_string_list(payload.get("directional_layers")),
        "known_good_filters": _normalize_string_list(payload.get("known_good_filters")),
        "custom_filters": _normalize_string_list(payload.get("custom_filters")),
        "exit_layers": _normalize_string_list(payload.get("exit_layers")),
    }
    parameter_schema = _parameter_schema_from_payload(payload, structure)

    risk_hooks = ["max_drawdown", "venue_profile_guard"]
    if "funding" in feature_contracts:
        risk_hooks.append("funding_shock")
    if "liquidation" in feature_contracts:
        risk_hooks.append("liquidation_guard")

    signal_tf = "1h"
    execution_tf = "15m"
    venue = "binance"
    if isinstance(snapshot, dict):
        signal_tf = _normalize_signal_timeframe(snapshot.get("timeframe", "1h"))
        execution_tf = "1m" if signal_tf == "1m" else "15m"
        venue = str(snapshot.get("venue", "binance"))

    spec = {
        "family": family,
        "variant_id": str(payload.get("run_id", "strategy-proposal")),
        "feature_contracts": feature_contracts,
        "parameter_schema": parameter_schema,
        "risk_hooks": risk_hooks,
        "execution_policy": {
            "venue": venue,
            "signal_tf": signal_tf,
            "execution_tf": execution_tf,
        },
        "structure": structure,
    }
    forecast_feature_config = payload.get("forecast_feature_config")
    if forecast_feature_config is not None:
        spec["forecast_feature_config"] = forecast_feature_config
    for field_name in PROHIBITED_FREE_FORM_FIELDS:
        if field_name in payload:
            spec[field_name] = payload[field_name]
    return spec


def _normalize_string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return sorted({str(item) for item in raw if isinstance(item, str) and item.strip()})


def _normalize_signal_timeframe(raw: object) -> str:
    text = str(raw or "1h").strip()
    aliases = {
        "1min": "1m",
        "1minute": "1m",
        "1m": "1m",
        "15min": "15m",
        "15minute": "15m",
        "15m": "15m",
        "1hour": "1h",
        "1h": "1h",
    }
    return aliases.get(text.lower(), text)


def _normalize_parameter_schema(raw: object) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, float]] = {}
    for name, bounds in raw.items():
        if not isinstance(name, str) or not isinstance(bounds, dict):
            continue
        minimum = _to_float(bounds.get("minimum"))
        maximum = _to_float(bounds.get("maximum"))
        step = _to_float(bounds.get("step"))
        if minimum is None or maximum is None or step is None or minimum > maximum or step <= 0:
            continue
        normalized[name] = {
            "minimum": minimum,
            "maximum": maximum,
            "step": step,
        }
    return {key: normalized[key] for key in sorted(normalized)}


def _normalize_execution_policy(raw: object) -> tuple[dict[str, object], list[str]]:
    if not isinstance(raw, dict):
        return {}, []
    normalized: dict[str, object] = {}
    issues: list[str] = []
    for field_name in raw:
        if field_name in PROHIBITED_FORECAST_EXECUTION_FIELDS:
            issues.append(f"execution_policy_field_not_allowed:{field_name}")
            continue
        if field_name not in ALLOWED_EXECUTION_POLICY_FIELDS:
            issues.append(f"execution_policy_field_not_allowed:{field_name}")
            continue
        value = raw[field_name]
        if isinstance(value, (str, bool, int, float)):
            normalized[field_name] = value
    return {key: normalized[key] for key in sorted(normalized)}, issues


def _normalize_forecast_feature_config(raw: object) -> tuple[dict[str, object], list[str]]:
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return {}, ["invalid_forecast_feature_config"]
    issues: list[str] = []
    for key in raw:
        if key not in ALLOWED_FORECAST_FEATURE_CONFIG_FIELDS:
            issues.append(f"forecast_feature_config_field_not_allowed:{key}")
    provider = raw.get("provider")
    if provider != "timesfm":
        issues.append("forecast_feature_provider_not_allowed")
    model_id = raw.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        issues.append("missing_forecast_feature_model_id")
    horizon = _to_int(raw.get("horizon"))
    if horizon is None or horizon <= 0:
        issues.append("invalid_forecast_feature_horizon")
    context_length = _to_int(raw.get("context_length"))
    if context_length is None or context_length <= 0:
        issues.append("invalid_forecast_feature_context_length")
    config_checksum = raw.get("config_checksum")
    if not isinstance(config_checksum, str) or not config_checksum:
        issues.append("missing_forecast_feature_config_checksum")
    feature_fields = _normalize_string_list(raw.get("feature_fields"))
    if not feature_fields:
        issues.append("missing_forecast_feature_fields")
    if any(field_name not in ALLOWED_FORECAST_FEATURE_FIELDS for field_name in feature_fields):
        issues.append("forecast_feature_field_not_allowed")
    if issues:
        return {}, issues
    return {
        "config_checksum": str(config_checksum),
        "context_length": int(context_length),
        "feature_fields": feature_fields,
        "horizon": int(horizon),
        "model_id": str(model_id),
        "provider": "timesfm",
    }, []


def _normalize_structure(raw: object) -> dict[str, object]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return {}
    normalized = {
        "backbone": str(raw.get("backbone", "")).strip(),
        "directional_layers": _normalize_string_list(raw.get("directional_layers")),
        "known_good_filters": _normalize_string_list(raw.get("known_good_filters")),
        "custom_filters": _normalize_string_list(raw.get("custom_filters")),
        "exit_layers": _normalize_string_list(raw.get("exit_layers")),
    }
    approved = approved_layer_names()
    if normalized["backbone"] not in approved:
        return {}
    for field_name in ("directional_layers", "known_good_filters", "custom_filters", "exit_layers"):
        if any(name not in approved for name in normalized[field_name]):
            return {}
    return {key: normalized[key] for key in sorted(normalized)}


def _parameter_schema_from_payload(payload: dict[str, object], structure: dict[str, object]) -> dict[str, dict[str, float]]:
    parameter_grids = payload.get("parameter_grids")
    normalized: dict[str, dict[str, float]] = {}
    if isinstance(parameter_grids, dict):
        for layer_name, layer_grid in parameter_grids.items():
            if not isinstance(layer_name, str) or not isinstance(layer_grid, dict):
                continue
            for parameter_name, bounds in layer_grid.items():
                if not isinstance(parameter_name, str) or not isinstance(bounds, dict):
                    continue
                minimum = _to_float(bounds.get("minimum"))
                maximum = _to_float(bounds.get("maximum"))
                step = _to_float(bounds.get("step"))
                if minimum is None or maximum is None or step is None or minimum > maximum or step <= 0:
                    continue
                normalized[f"{layer_name}.{parameter_name}"] = {
                    "minimum": minimum,
                    "maximum": maximum,
                    "step": step,
                }
    if normalized:
        return {key: normalized[key] for key in sorted(normalized)}

    layer_names = [structure.get("backbone", "")]
    for field_name in ("directional_layers", "known_good_filters", "custom_filters", "exit_layers"):
        layer_names.extend(structure.get(field_name, []))
    for layer_name in layer_names:
        if not isinstance(layer_name, str) or not layer_name.strip():
            continue
        try:
            layer_spec = get_layer_by_name(layer_name)
        except KeyError:
            continue
        for parameter_name, bounds in layer_spec.parameters.items():
            normalized[f"{layer_name}.{parameter_name}"] = {
                "minimum": float(bounds.minimum),
                "maximum": float(bounds.maximum),
                "step": float(bounds.step),
            }
    return {key: normalized[key] for key in sorted(normalized)}


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
