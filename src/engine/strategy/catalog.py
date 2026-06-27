from __future__ import annotations

from engine.config.models import LayerFamily, LayerSpec, ParameterRange

BACKBONES: list[LayerSpec] = [
    LayerSpec("mom_squeeze", LayerFamily.BACKBONE, {"entry_stride": ParameterRange(2, 10, 1)}),
    LayerSpec("kama_hma", LayerFamily.BACKBONE, {
        "n": ParameterRange(6, 20, 2),
        "f": ParameterRange(2, 5, 1),
        "s": ParameterRange(20, 50, 5),
        "theta_trend": ParameterRange(0.45, 0.75, 0.05),
        "theta_flat": ParameterRange(0.15, 0.35, 0.05),
        "n_hma": ParameterRange(9, 55, 5),
        "p_atr": ParameterRange(10, 21, 1),
        "k_stop": ParameterRange(1.5, 3.5, 0.5),
    }, eligibility_rules={"constraint": "theta_flat < theta_trend - 0.10"}),
    LayerSpec("keltner_fade", LayerFamily.BACKBONE, {
        "p_ema": ParameterRange(14, 55, 5),
        "p_atr": ParameterRange(10, 21, 1),
        "m": ParameterRange(1.5, 3.5, 0.5),
        "p_rsi": ParameterRange(7, 21, 2),
        "theta_os": ParameterRange(20, 35, 5),
        "theta_ob": ParameterRange(65, 80, 5),
        "k_stop": ParameterRange(1.0, 2.5, 0.5),
        "t_bars": ParameterRange(5, 25, 5),
        "z_threshold": ParameterRange(1.5, 3.0, 0.5),
    }),
]

DIRECTIONAL_FILTERS: list[LayerSpec] = [
    LayerSpec("ema", LayerFamily.DIRECTIONAL_FILTER, {"len": ParameterRange(10, 60, 10)}),
    LayerSpec("kama", LayerFamily.DIRECTIONAL_FILTER, {"len": ParameterRange(10, 60, 10)}),
    LayerSpec("hull", LayerFamily.DIRECTIONAL_FILTER, {"len": ParameterRange(10, 60, 10)}),
]

KNOWN_GOOD_FLAT_FILTERS: list[LayerSpec] = [
    LayerSpec("flat9", LayerFamily.KNOWN_GOOD_FLAT_FILTER),
    LayerSpec("flat11", LayerFamily.KNOWN_GOOD_FLAT_FILTER),
    LayerSpec("flat12", LayerFamily.KNOWN_GOOD_FLAT_FILTER),
    LayerSpec("flat13", LayerFamily.KNOWN_GOOD_FLAT_FILTER),
    LayerSpec("flat14", LayerFamily.KNOWN_GOOD_FLAT_FILTER),
]

CUSTOM_FLAT_FILTERS: list[LayerSpec] = [
    LayerSpec("adx_weak", LayerFamily.CUSTOM_FLAT_FILTER),
    LayerSpec("choppiness", LayerFamily.CUSTOM_FLAT_FILTER),
    LayerSpec("volume_dead", LayerFamily.CUSTOM_FLAT_FILTER),
]

EXIT_LAYERS: list[LayerSpec] = [
    LayerSpec("time_stop", LayerFamily.EXIT, {"hold_bars": ParameterRange(1, 24, 1)}),
]


def get_layer_by_name(name: str) -> LayerSpec:
    for layer in [*BACKBONES, *DIRECTIONAL_FILTERS, *KNOWN_GOOD_FLAT_FILTERS, *CUSTOM_FLAT_FILTERS, *EXIT_LAYERS]:
        if layer.name == name:
            return layer
    raise KeyError(f"unknown layer: {name}")


def resolve_layer_names(names: list[str]) -> list[LayerSpec]:
    return [get_layer_by_name(name) for name in names]


def catalog_by_family() -> dict[str, list[str]]:
    return {
        "backbones": [layer.name for layer in BACKBONES],
        "directional_layers": [layer.name for layer in DIRECTIONAL_FILTERS],
        "known_good_filters": [layer.name for layer in KNOWN_GOOD_FLAT_FILTERS],
        "custom_filters": [layer.name for layer in CUSTOM_FLAT_FILTERS],
        "exit_layers": [layer.name for layer in EXIT_LAYERS],
    }


def approved_layer_names() -> set[str]:
    names: set[str] = set()
    for values in catalog_by_family().values():
        names.update(values)
    return names
