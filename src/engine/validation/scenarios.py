from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from engine.config.models import BacktestResult, DataSnapshot, StressMetrics

if TYPE_CHECKING:
    from engine.validation.hawkes import HawkesKernelParams
    from engine.validation.jump_diffusion import JumpDiffusionParams


@dataclass(frozen=True)
class StressScenario:
    name: str
    severity: float
    description: str
    funding_multiplier: float = 1.0
    liquidity_penalty_bps: float = 0.0
    spread_multiplier: float = 1.0
    depth_multiplier: float = 1.0
    latency_multiplier: float = 1.0
    latency_delta_bars: int = 0
    drawdown_multiplier: float = 1.0
    mark_premium_bps: float = 0.0
    index_basis_bps: float = 0.0
    premium_spike_bars: int = 0
    open_interest_multiplier: float = 1.0
    liquidation_multiplier: float = 1.0
    volatility_multiplier: float = 1.0
    target_regimes: tuple[str, ...] = ()
    # Phase 14 empirical calibration fields default to neutral values.
    calibration_mode: str = "static"  # "static" | "calibrated"
    hawkes_cascade_multiplier: float = 1.0
    jump_severity_factor: float = 1.0


@dataclass(frozen=True)
class ScenarioResult:
    scenario_name: str
    severity: float
    passed: bool
    failure_reasons: list[str]
    result: BacktestResult
    resolved_profile: dict[str, float | int | str] | None = None
    stress_metrics: StressMetrics | None = None


@dataclass(frozen=True)
class ScenarioEvaluationReport:
    total_scenarios: int
    passed_scenarios: int
    pass_rate: float
    results: list[ScenarioResult]
    stress_liquidity_metrics: dict[str, float | int] = field(default_factory=dict)
    regime_scenario_pass_matrix: dict[str, dict[str, bool]] = field(default_factory=dict)


DEFAULT_SCENARIOS = [
    StressScenario("funding_basis_shock", 0.65, "Funding and basis dislocation stress.", funding_multiplier=1.8, mark_premium_bps=120.0, volatility_multiplier=1.1, target_regimes=("bull", "bear")),
    StressScenario("joint_crypto_dislocation", 0.92, "Joint crypto dislocation with price, funding, liquidation, microstructure, and mark/index stress.", funding_multiplier=1.8, liquidity_penalty_bps=36.0, spread_multiplier=1.8, depth_multiplier=0.45, latency_multiplier=1.6, drawdown_multiplier=1.55, mark_premium_bps=180.0, index_basis_bps=120.0, premium_spike_bars=4, open_interest_multiplier=1.25, liquidation_multiplier=2.4, volatility_multiplier=1.3, target_regimes=("crash", "liquidity_stress", "short_squeeze")),
    StressScenario("liquidation_cascade", 0.9, "Reflexive liquidation spiral stress.", liquidity_penalty_bps=45.0, drawdown_multiplier=1.5, mark_premium_bps=180.0, open_interest_multiplier=1.25, liquidation_multiplier=2.2, volatility_multiplier=1.3, target_regimes=("crash", "liquidity_stress", "short_squeeze")),
    StressScenario("liquidity_withdrawal", 0.8, "Depth thins and slippage assumptions steepen.", liquidity_penalty_bps=35.0, latency_delta_bars=1, drawdown_multiplier=1.25, mark_premium_bps=90.0, open_interest_multiplier=1.1, liquidation_multiplier=1.4, target_regimes=("liquidity_stress", "crash")),
    StressScenario("mark_index_dislocation", 0.75, "Mark and index references diverge under venue stress.", liquidity_penalty_bps=16.0, drawdown_multiplier=1.2, mark_premium_bps=140.0, index_basis_bps=85.0, premium_spike_bars=3, volatility_multiplier=1.1, target_regimes=("liquidity_stress", "crash", "short_squeeze")),
    StressScenario("attention_burst", 0.6, "Retail-attention burst with elevated volatility.", funding_multiplier=1.3, liquidity_penalty_bps=12.0, drawdown_multiplier=1.1, mark_premium_bps=40.0, volatility_multiplier=1.35, target_regimes=("bull", "sideways")),
    StressScenario("short_squeeze", 0.85, "Short-side reflexive squeeze stress.", funding_multiplier=1.6, liquidity_penalty_bps=28.0, drawdown_multiplier=1.3, mark_premium_bps=220.0, open_interest_multiplier=1.2, liquidation_multiplier=2.0, volatility_multiplier=1.2, target_regimes=("short_squeeze", "liquidity_stress")),
    StressScenario("venue_outage", 0.9, "Venue disruption inspired by outage literature.", liquidity_penalty_bps=55.0, latency_delta_bars=2, drawdown_multiplier=1.4, mark_premium_bps=160.0, volatility_multiplier=1.15, target_regimes=("liquidity_stress", "crash")),
]

SCENARIO_ALIASES = {
    "attention-burst": "attention_burst",
    "joint-crypto-dislocation": "joint_crypto_dislocation",
    "liquidity-withdrawal": "liquidity_withdrawal",
    "mark-index-dislocation": "mark_index_dislocation",
    "outage-shock": "venue_outage",
    "short-squeeze": "short_squeeze",
}

SCENARIO_PRESETS = {
    "funding_basis_shock": {
        "funding_multiplier": 2.1,
        "mark_premium_bps": 160.0,
        "volatility_multiplier": 1.15,
        "spread_multiplier": 1.1,
        "depth_multiplier": 0.95,
    },
    "joint_crypto_dislocation": {
        "funding_multiplier": 2.0,
        "liquidity_penalty_bps": 42.0,
        "spread_multiplier": 2.0,
        "depth_multiplier": 0.4,
        "latency_multiplier": 1.75,
        "drawdown_multiplier": 1.7,
        "mark_premium_bps": 210.0,
        "index_basis_bps": 135.0,
        "premium_spike_bars": 4,
        "open_interest_multiplier": 1.3,
        "liquidation_multiplier": 2.7,
        "volatility_multiplier": 1.35,
    },
    "liquidation_cascade": {
        "liquidity_penalty_bps": 52.0,
        "spread_multiplier": 1.8,
        "depth_multiplier": 0.55,
        "latency_multiplier": 1.4,
        "drawdown_multiplier": 1.6,
        "mark_premium_bps": 220.0,
        "open_interest_multiplier": 1.3,
        "liquidation_multiplier": 2.6,
    },
    "attention_burst": {
        "funding_multiplier": 1.3,
        "liquidity_penalty_bps": 12.0,
        "spread_multiplier": 1.15,
        "depth_multiplier": 0.9,
        "latency_multiplier": 1.1,
        "drawdown_multiplier": 1.1,
        "mark_premium_bps": 40.0,
        "volatility_multiplier": 1.35,
    },
    "liquidity_withdrawal": {
        "liquidity_penalty_bps": 35.0,
        "spread_multiplier": 2.0,
        "depth_multiplier": 0.4,
        "latency_multiplier": 1.8,
        "latency_delta_bars": 1,
        "drawdown_multiplier": 1.25,
        "mark_premium_bps": 90.0,
        "open_interest_multiplier": 1.1,
        "liquidation_multiplier": 1.4,
    },
    "mark_index_dislocation": {
        "liquidity_penalty_bps": 18.0,
        "drawdown_multiplier": 1.25,
        "mark_premium_bps": 150.0,
        "index_basis_bps": 90.0,
        "premium_spike_bars": 3,
        "volatility_multiplier": 1.1,
    },
    "venue_outage": {
        "liquidity_penalty_bps": 55.0,
        "spread_multiplier": 2.5,
        "depth_multiplier": 0.3,
        "latency_multiplier": 2.5,
        "latency_delta_bars": 2,
        "drawdown_multiplier": 1.4,
        "mark_premium_bps": 160.0,
    },
    "short_squeeze": {
        "funding_multiplier": 1.6,
        "liquidity_penalty_bps": 28.0,
        "spread_multiplier": 1.5,
        "depth_multiplier": 0.6,
        "latency_multiplier": 1.3,
        "drawdown_multiplier": 1.3,
        "mark_premium_bps": 220.0,
        "open_interest_multiplier": 1.2,
        "liquidation_multiplier": 2.0,
    },
}

SCENARIO_VENUE_PRESETS = {
    "binance": {
        "funding_basis_shock": {
            "funding_multiplier": 2.3,
            "mark_premium_bps": 180.0,
            "spread_multiplier": 1.15,
            "depth_multiplier": 0.9,
        },
        "joint_crypto_dislocation": {
            "funding_multiplier": 2.3,
            "liquidity_penalty_bps": 50.0,
            "spread_multiplier": 2.4,
            "depth_multiplier": 0.3,
            "latency_multiplier": 2.0,
            "drawdown_multiplier": 1.85,
            "mark_premium_bps": 260.0,
            "index_basis_bps": 180.0,
            "premium_spike_bars": 5,
            "open_interest_multiplier": 1.4,
            "liquidation_multiplier": 3.2,
            "volatility_multiplier": 1.45,
        },
        "liquidation_cascade": {
            "liquidity_penalty_bps": 65.0,
            "spread_multiplier": 2.1,
            "depth_multiplier": 0.45,
            "latency_multiplier": 1.6,
            "mark_premium_bps": 260.0,
            "open_interest_multiplier": 1.4,
            "liquidation_multiplier": 3.0,
        },
        "attention_burst": {
            "liquidity_penalty_bps": 15.0,
            "spread_multiplier": 1.2,
            "depth_multiplier": 0.85,
            "latency_multiplier": 1.15,
            "mark_premium_bps": 55.0,
        },
        "liquidity_withdrawal": {
            "liquidity_penalty_bps": 42.0,
            "spread_multiplier": 2.4,
            "depth_multiplier": 0.25,
            "latency_multiplier": 2.2,
            "latency_delta_bars": 2,
            "mark_premium_bps": 110.0,
        },
        "mark_index_dislocation": {
            "liquidity_penalty_bps": 22.0,
            "drawdown_multiplier": 1.3,
            "mark_premium_bps": 180.0,
            "index_basis_bps": 120.0,
            "premium_spike_bars": 4,
            "volatility_multiplier": 1.15,
        },
        "venue_outage": {
            "liquidity_penalty_bps": 65.0,
            "spread_multiplier": 3.0,
            "depth_multiplier": 0.15,
            "latency_multiplier": 3.0,
            "latency_delta_bars": 3,
            "drawdown_multiplier": 1.5,
            "mark_premium_bps": 210.0,
        },
        "short_squeeze": {
            "funding_multiplier": 1.8,
            "liquidity_penalty_bps": 34.0,
            "spread_multiplier": 1.7,
            "depth_multiplier": 0.5,
            "latency_multiplier": 1.5,
            "mark_premium_bps": 260.0,
            "liquidation_multiplier": 2.2,
        },
    }
}


def resolve_scenario_profile(scenario: StressScenario, venue: str | None = None) -> StressScenario:
    resolved = replace(scenario, name=_canonical_scenario_name(scenario.name))
    for preset in _scenario_presets_for(scenario.name, venue):
        for key, default_value in preset.items():
            current_value = getattr(resolved, key)
            if current_value == _scenario_field_default(key):
                resolved = replace(resolved, **{key: default_value})
    return resolved


def _scenario_presets_for(scenario_name: str, venue: str | None) -> list[dict[str, float | int]]:
    presets: list[dict[str, float | int]] = []
    canonical_name = _canonical_scenario_name(scenario_name)
    base = SCENARIO_PRESETS.get(canonical_name)
    if base:
        presets.append(base)
    venue_presets = SCENARIO_VENUE_PRESETS.get((venue or "").lower(), {})
    venue_override = venue_presets.get(canonical_name)
    if venue_override:
        presets.append(venue_override)
    return presets


def _scenario_field_default(field_name: str) -> float | int:
    defaults: dict[str, float | int] = {
        "funding_multiplier": 1.0,
        "liquidity_penalty_bps": 0.0,
        "spread_multiplier": 1.0,
        "depth_multiplier": 1.0,
        "latency_multiplier": 1.0,
        "latency_delta_bars": 0,
        "drawdown_multiplier": 1.0,
        "mark_premium_bps": 0.0,
        "index_basis_bps": 0.0,
        "premium_spike_bars": 0,
        "open_interest_multiplier": 1.0,
        "liquidation_multiplier": 1.0,
        "volatility_multiplier": 1.0,
    }
    return defaults[field_name]


def _canonical_scenario_name(scenario_name: str) -> str:
    return SCENARIO_ALIASES.get(scenario_name, scenario_name)


def apply_calibration(
    scenario: StressScenario,
    hawkes_params: "HawkesKernelParams",
    jump_params: "JumpDiffusionParams",
    oi_concentration: float = 0.5,
) -> StressScenario:
    from engine.validation.hawkes import hawkes_cascade_multiplier as _hcm

    cascade = _hcm(hawkes_params, oi_concentration)
    jump_signal = jump_params.jump_intensity + abs(jump_params.mean_jump_size) + jump_params.jump_volatility
    jump_factor = max(1.0, min(1.0 + jump_signal, 2.5))

    return replace(
        scenario,
        calibration_mode="calibrated",
        hawkes_cascade_multiplier=round(cascade, 6),
        jump_severity_factor=round(jump_factor, 6),
    )


def calibrate_scenarios(
    scenarios: list[StressScenario],
    hawkes_params: "HawkesKernelParams",
    jump_params: "JumpDiffusionParams",
    oi_concentration: float = 0.5,
) -> list[StressScenario]:
    return [
        apply_calibration(s, hawkes_params, jump_params, oi_concentration)
        if s.name in CALIBRATION_ELIGIBLE_SCENARIOS
        else s
        for s in scenarios
    ]


# Scenarios eligible for empirical calibration: those driven by liquidation
# and funding dynamics which the Hawkes / jump-diff models capture.
CALIBRATION_ELIGIBLE_SCENARIOS: frozenset[str] = frozenset({
    "liquidation_cascade",
    "liquidity_withdrawal",
    "short_squeeze",
    "funding_basis_shock",
    "joint_crypto_dislocation",
})


def build_calibrated_scenario_profile(
    snapshot: DataSnapshot,
    scenario: StressScenario,
    *,
    seed: int = 0,
) -> dict[str, object]:
    from engine.validation.hawkes import (
        compute_oi_concentration,
        fit_hawkes_intensity,
        hawkes_cascade_multiplier,
    )
    from engine.validation.jump_diffusion import (
        estimate_jump_params,
        extract_returns_from_snapshot,
        generate_jump_stress_path,
    )

    resolved = resolve_scenario_profile(scenario, venue=snapshot.venue)
    baseline_path = [candle.close for candle in snapshot.candles]
    if scenario.calibration_mode != "calibrated":
        return {
            "resolved_scenario": resolved,
            "calibrated_scenario": resolved,
            "jump_params": None,
            "hawkes_params": None,
            "stressed_path": baseline_path,
            "calibrated_overrides": {},
        }

    jump_params = estimate_jump_params(extract_returns_from_snapshot(snapshot.candles))
    event_pairs = [
        (float(index), float(notional))
        for index, notional in enumerate(snapshot.liquidation_notional)
        if float(notional) > 0.0
    ]
    hawkes_params = fit_hawkes_intensity(
        [event_time for event_time, _ in event_pairs],
        [event_size for _, event_size in event_pairs],
    )
    oi_concentration = compute_oi_concentration(snapshot.open_interest)
    cascade_multiplier = hawkes_cascade_multiplier(hawkes_params, oi_concentration)

    start_price = snapshot.candles[0].close if snapshot.candles else 1.0
    stressed_path = generate_jump_stress_path(
        jump_params,
        n_bars=len(snapshot.candles),
        seed=seed,
        start_price=start_price,
    )
    path_reference = max(start_price, 1.0)
    path_range = (max(stressed_path) - min(stressed_path)) / path_reference if stressed_path else 0.0
    funding_level = max((abs(value) for value in snapshot.funding_rates), default=0.0)

    calibrated = apply_calibration(resolved, hawkes_params, jump_params, oi_concentration)
    calibrated_overrides: dict[str, float] = {
        "severity": round(
            max(
                resolved.severity,
                min(0.99, resolved.severity + jump_params.jump_intensity + (abs(jump_params.mean_jump_size) * 2.0)),
            ),
            6,
        ),
        "drawdown_multiplier": round(
            max(resolved.drawdown_multiplier, resolved.drawdown_multiplier * (1.0 + path_range)),
            6,
        ),
        "volatility_multiplier": round(
            max(resolved.volatility_multiplier, 1.0 + (jump_params.jump_volatility * 5.0)),
            6,
        ),
    }

    if resolved.name == "liquidation_cascade":
        calibrated_overrides["liquidation_multiplier"] = round(
            max(
                resolved.liquidation_multiplier,
                resolved.liquidation_multiplier * max(1.0, cascade_multiplier),
            ),
            6,
        )
        calibrated_overrides["open_interest_multiplier"] = round(
            max(resolved.open_interest_multiplier, 1.0 + oi_concentration),
            6,
        )
    elif resolved.name in {"funding_basis_shock", "short_squeeze"}:
        calibrated_overrides["funding_multiplier"] = round(
            max(resolved.funding_multiplier, 1.0 + (funding_level * 100.0)),
            6,
        )
    elif resolved.name == "joint_crypto_dislocation":
        calibrated_overrides["funding_multiplier"] = round(
            max(
                resolved.funding_multiplier,
                resolved.funding_multiplier * (1.0 + min(funding_level * 10.0, 0.35)),
            ),
            6,
        )
        calibrated_overrides["liquidation_multiplier"] = round(
            max(resolved.liquidation_multiplier, resolved.liquidation_multiplier * max(1.0, cascade_multiplier)),
            6,
        )
        calibrated_overrides["open_interest_multiplier"] = round(
            max(resolved.open_interest_multiplier, 1.0 + oi_concentration),
            6,
        )
        calibrated_overrides["spread_multiplier"] = round(
            max(resolved.spread_multiplier, resolved.spread_multiplier * (1.0 + min(path_range, 0.6))),
            6,
        )
        calibrated_overrides["depth_multiplier"] = round(
            min(resolved.depth_multiplier, max(0.1, resolved.depth_multiplier * (1.0 - min(path_range * 0.5, 0.35)))),
            6,
        )
        calibrated_overrides["latency_multiplier"] = round(
            max(resolved.latency_multiplier, resolved.latency_multiplier + (jump_params.jump_intensity * 5.0) + (oi_concentration * 0.5)),
            6,
        )
        calibrated_overrides["mark_premium_bps"] = round(
            max(resolved.mark_premium_bps, resolved.mark_premium_bps * max(1.0, cascade_multiplier)),
            6,
        )
        calibrated_overrides["index_basis_bps"] = round(
            max(resolved.index_basis_bps, resolved.index_basis_bps * (1.0 + min(path_range, 0.5))),
            6,
        )
        calibrated_overrides["premium_spike_bars"] = max(
            resolved.premium_spike_bars,
            int(round(2 + min(path_range * 10.0, 4.0))),
        )

    calibrated = replace(calibrated, **calibrated_overrides)
    return {
        "resolved_scenario": resolved,
        "calibrated_scenario": calibrated,
        "jump_params": jump_params,
        "hawkes_params": hawkes_params,
        "stressed_path": stressed_path,
        "calibrated_overrides": calibrated_overrides,
    }


def evaluate_scenarios(
    scenarios: list[StressScenario],
    results_by_name: dict[str, BacktestResult],
    resolved_profiles_by_name: dict[str, dict[str, float | int | str]] | None = None,
    stress_metrics_by_name: dict[str, StressMetrics] | None = None,
    regime_scenario_pass_matrix: dict[str, dict[str, bool]] | None = None,
    position_leverage: float = 1.0,
) -> ScenarioEvaluationReport:
    evaluated: list[ScenarioResult] = []
    passed = 0
    # Scale drawdown kill-switch by leverage: a 10x strategy tolerates
    # up to -2.5 (= -0.25 * 10) before rejection, matching the
    # simulator's leverage-aware equity dynamics.
    effective_leverage = max(1.0, float(position_leverage))
    drawdown_kill_threshold = -0.25 * effective_leverage

    for scenario in scenarios:
        resolved = resolve_scenario_profile(scenario)
        result = (
            results_by_name.get(resolved.name)
            or results_by_name.get(scenario.name)
        )
        if result is None:
            raise KeyError(resolved.name)
        failure_reasons: list[str] = []
        if result.max_drawdown <= drawdown_kill_threshold:
            failure_reasons.append("drawdown_kill_switch")
        if result.liquidation_events:
            failure_reasons.append("liquidation_events")
        scenario_passed = not failure_reasons
        if scenario_passed:
            passed += 1
        evaluated.append(
            ScenarioResult(
                scenario_name=scenario.name,
                severity=_resolved_profile_severity(
                    (resolved_profiles_by_name or {}).get(scenario.name)
                    or (resolved_profiles_by_name or {}).get(resolved.name),
                    scenario.severity,
                ),
                passed=scenario_passed,
                failure_reasons=failure_reasons,
                result=result,
                resolved_profile=(resolved_profiles_by_name or {}).get(scenario.name) or (resolved_profiles_by_name or {}).get(resolved.name),
                stress_metrics=(stress_metrics_by_name or {}).get(scenario.name) or (stress_metrics_by_name or {}).get(resolved.name),
            )
        )

    total = len(evaluated)
    pass_rate = (passed / total) if total else 0.0
    return ScenarioEvaluationReport(
        total_scenarios=total,
        passed_scenarios=passed,
        pass_rate=pass_rate,
        results=evaluated,
        stress_liquidity_metrics=_summarize_stress_metrics(evaluated),
        regime_scenario_pass_matrix=regime_scenario_pass_matrix or {},
    )


def _summarize_stress_metrics(results: list[ScenarioResult]) -> dict[str, float | int]:
    stress_rows = [result.stress_metrics for result in results if result.stress_metrics is not None]
    if not stress_rows:
        return {}
    return {
        "stress_slippage_quantile": max(metric.stress_slippage_quantile for metric in stress_rows),
        "stress_tail_slippage": max(metric.stress_tail_slippage for metric in stress_rows),
        "liquidity_stress_score": max(metric.liquidity_stress_score for metric in stress_rows),
        "basis_stress_score": max(metric.basis_stress_score for metric in stress_rows),
        "cascade_liquidation_count": max(metric.cascade_liquidation_count for metric in stress_rows),
    }


def _resolved_profile_severity(profile: object, fallback: float) -> float:
    if isinstance(profile, dict):
        value = profile.get("severity")
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return float(fallback)
