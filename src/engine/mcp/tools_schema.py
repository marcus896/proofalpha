from __future__ import annotations

from pathlib import Path

from engine.app.schema import build_study_schema
from engine.config.models import LayerFamily
from engine.mcp.config import MCPSettings
from engine.strategy.catalog import catalog_by_family, get_layer_by_name


def tool_list_layer_families(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    return {"families": [family.value for family in LayerFamily]}


def tool_list_layers(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    family_filter = params.get("family")
    catalog = catalog_by_family()
    layers = [layer for values in catalog.values() for layer in values]
    if isinstance(family_filter, str):
        mapped_family = _normalize_family_filter(family_filter)
        if mapped_family is None:
            return {"layers": []}
        layers = list(catalog.get(mapped_family, []))
    return {"layers": layers}


def tool_get_layer(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    name = params.get("name")
    if not isinstance(name, str):
        return {"error": "name is required"}
    try:
        layer = get_layer_by_name(name)
        return {
            "name": layer.name,
            "family": layer.family.value,
            "parameters": {
                parameter_name: {
                    "minimum": parameter_range.minimum,
                    "maximum": parameter_range.maximum,
                    "step": parameter_range.step,
                }
                for parameter_name, parameter_range in layer.parameters.items()
            },
            "eligibility_rules": dict(layer.eligibility_rules),
        }
    except KeyError:
        return {"error": f"unknown layer '{name}'"}


def tool_get_runtime_schema(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    schema = build_study_schema()
    runtime_schema = schema.get("properties", {}).get("runtime", {})
    return dict(runtime_schema)


def tool_get_scenario_schema(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    schema = build_study_schema()
    scenario_schema = schema.get("properties", {}).get("scenarios", {})
    return dict(scenario_schema)


def tool_get_study_template(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    return {
        "run_id": "my-study",
        "seed": 7,
        "snapshot": {
            "snapshot_id": "snap-01",
            "symbol": "BTCUSDT",
            "venue": "binance",
            "timeframe": "1h",
            "candles": [],
            "funding_rates": [],
            "open_interest": [],
            "liquidation_notional": [],
            "maker_fee_bps": 2.0,
            "taker_fee_bps": 5.0,
        },
        "incumbent": {"backbone": "momentum_backbone"},
        "directional_layers": [],
        "known_good_filters": [],
        "custom_filters": [],
        "exit_layers": [],
        "scenarios": [],
    }


SCHEMA_TOOL_CATALOG: list[dict[str, object]] = [
    {
        "name": "list_layer_families",
        "description": "List all known layer family names.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_layers",
        "description": "List layers, optionally filtered by family.",
        "parameters": {
            "type": "object",
            "properties": {"family": {"type": "string"}},
        },
    },
    {
        "name": "get_layer",
        "description": "Get details for a specific layer by name.",
        "parameters": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
    },
    {
        "name": "get_runtime_schema",
        "description": "Return the runtime settings JSON schema.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_scenario_schema",
        "description": "Return the scenario definition JSON schema.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_study_template",
        "description": "Return a minimal skeleton study config payload ready to be populated.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def _normalize_family_filter(raw: str) -> str | None:
    normalized = raw.strip().lower()
    alias_map = {
        LayerFamily.BACKBONE.value: "backbones",
        LayerFamily.DIRECTIONAL_FILTER.value: "directional_layers",
        LayerFamily.KNOWN_GOOD_FLAT_FILTER.value: "known_good_filters",
        LayerFamily.CUSTOM_FLAT_FILTER.value: "custom_filters",
        LayerFamily.EXIT.value: "exit_layers",
        "backbones": "backbones",
        "directional_layers": "directional_layers",
        "known_good_filters": "known_good_filters",
        "custom_filters": "custom_filters",
        "exit_layers": "exit_layers",
    }
    return alias_map.get(normalized)
