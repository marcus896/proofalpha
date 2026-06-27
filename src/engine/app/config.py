from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path

from engine.config.models import (
    BacktestResult,
    BootstrapReport,
    CandidateEvaluation,
    DataSnapshot,
    ParameterRange,
    PromotionDecision,
    SnapshotQualityReport,
    StrategyGraph,
    VenueProfile,
)
from engine.data.schema import Candle
from engine.strategy.catalog import resolve_layer_names
from engine.validation.scenarios import StressScenario


VENUE_RUNTIME_PRESETS: dict[str, dict[str, object]] = {
    "binance": {
        "liquidation_mark_price_weight": 0.35,
        "liquidation_mark_premium_bps": 12.0,
        "maintenance_margin_schedule": [
            {"max_leverage": 5.0, "maintenance_margin_ratio": 0.01},
            {"max_leverage": 20.0, "maintenance_margin_ratio": 0.025},
            {"max_leverage": 50.0, "maintenance_margin_ratio": 0.05},
        ],
        "liquidation_fee_schedule": [
            {"max_leverage": 5.0, "liquidation_fee_bps": 0.0},
            {"max_leverage": 20.0, "liquidation_fee_bps": 40.0},
            {"max_leverage": 50.0, "liquidation_fee_bps": 75.0},
        ],
    }
}


@dataclass(frozen=True)
class RuntimeSettings:
    slippage_bps: float = 5.0
    latency_bars: int = 0
    parameter_search_mode: str = "grid"
    optuna_trials: int = 16
    optuna_seed_warm_start_limit: int = 5
    optuna_sampler: str = "tpe"
    optuna_pruner_enabled: bool = True
    optuna_startup_trials: int = 2
    optuna_warm_start_trials: int = 5
    optuna_trial_budget: int = 16
    position_side: str = "long"
    position_leverage: float = 1.0
    maintenance_margin_ratio: float = 0.01
    liquidation_fee_bps: float = 0.0
    liquidation_mark_price_weight: float = 0.0
    partial_liquidation_ratio: float = 1.0
    liquidation_cooldown_bars: int = 0
    liquidation_step_schedule: list[float] = field(default_factory=list)
    liquidation_mark_premium_bps: float = 0.0
    maintenance_margin_schedule: list[dict[str, float]] = field(default_factory=list)
    liquidation_fee_schedule: list[dict[str, float]] = field(default_factory=list)
    min_oos_trades: int | None = None
    fail_on_quality_flags: bool = False
    max_parameter_permutations: int = 64
    search_summary_limit: int = 3
    bootstrap_samples: int = 8
    bootstrap_block_size: int | None = None
    bootstrap_method: str = "moving_block"
    bootstrap_spread_multiplier: float = 1.0
    bootstrap_depth_multiplier: float = 1.0
    bootstrap_latency_multiplier: float = 1.0
    permutation_count: int = 1000
    permutation_pvalue_threshold: float = 0.01
    walk_forward_relaxed_pvalue_threshold: float = 0.05
    regime_model: str = "deterministic"
    regime_n_states: int = 4
    deflated_sharpe_ratio_threshold: float = 0.95
    gate_probabilistic_sharpe_ratio: bool = False
    gate_min_backtest_length: bool = False
    probabilistic_sharpe_ratio_threshold: float = 0.95
    holdout_sharpe_floor: float = 1.0
    holdout_drawdown_cap: float = -0.20
    scenario_severity_multiplier: float = 1.0
    slippage_model: str = "flat"  # Phase 12: "flat" | "dynamic"


@dataclass(frozen=True)
class StudyConfig:
    run_id: str
    seed: int
    runtime_mode: str
    runtime_settings: RuntimeSettings
    research_lineage: dict[str, object]
    layer_parameters: dict[str, dict[str, float | int]]
    parameter_grids: dict[str, dict[str, ParameterRange]]
    snapshot: DataSnapshot
    incumbent: StrategyGraph
    directional_layers: list
    known_good_filters: list
    custom_filters: list
    exit_layers: list
    evaluations: dict[str, CandidateEvaluation]
    scenarios: list[StressScenario]
    scenario_results: dict[str, BacktestResult]
    holdout_decision: PromotionDecision


def build_study_signature_from_payload(payload: dict[str, object]) -> str:
    canonical = _canonicalize_signature_payload(payload)
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def load_study_config(path: Path) -> StudyConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    runtime_mode = payload.get("runtime", {}).get("mode")
    if runtime_mode is None:
        runtime_mode = "fixture" if payload.get("evaluations") or payload.get("scenario_results") else "builtin"
    snapshot = _parse_snapshot(payload["snapshot"])
    runtime_settings = _parse_runtime_settings(payload.get("runtime", {}), venue=snapshot.venue)
    return StudyConfig(
        run_id=payload["run_id"],
        seed=payload["seed"],
        runtime_mode=runtime_mode,
        runtime_settings=runtime_settings,
        research_lineage=dict(payload.get("research_lineage", {})),
        layer_parameters={name: dict(values) for name, values in payload.get("layer_parameters", {}).items()},
        parameter_grids={
            layer_name: {
                parameter_name: ParameterRange(**grid_spec)
                for parameter_name, grid_spec in parameters.items()
            }
            for layer_name, parameters in payload.get("parameter_grids", {}).items()
        },
        snapshot=snapshot,
        incumbent=StrategyGraph(
            backbone=payload["incumbent"]["backbone"],
            layers=resolve_layer_names(payload.get("incumbent", {}).get("layers", [])),
        ),
        directional_layers=resolve_layer_names(payload.get("directional_layers", [])),
        known_good_filters=resolve_layer_names(payload.get("known_good_filters", [])),
        custom_filters=resolve_layer_names(payload.get("custom_filters", [])),
        exit_layers=resolve_layer_names(payload.get("exit_layers", [])),
        evaluations={name: _parse_evaluation(name, raw) for name, raw in payload.get("evaluations", {}).items()},
        scenarios=[_parse_scenario(scenario) for scenario in payload.get("scenarios", [])],
        scenario_results={name: _parse_backtest_result(raw) for name, raw in payload.get("scenario_results", {}).items()},
        holdout_decision=PromotionDecision(**payload.get("holdout_decision", {"decision": "accept", "reasons": []})),
    )


def _parse_scenario(raw: dict) -> StressScenario:
    allowed = StressScenario.__dataclass_fields__.keys()
    return StressScenario(**{key: value for key, value in raw.items() if key in allowed})


def _parse_runtime_settings(raw: dict, venue: str | None = None) -> RuntimeSettings:
    preset = VENUE_RUNTIME_PRESETS.get(str(venue).lower(), {}) if venue else {}
    optuna_trial_budget = raw.get(
        "optuna_trial_budget",
        preset.get("optuna_trial_budget", raw.get("optuna_trials", preset.get("optuna_trials", 16))),
    )
    optuna_warm_start_trials = raw.get(
        "optuna_warm_start_trials",
        preset.get(
            "optuna_warm_start_trials",
            raw.get("optuna_seed_warm_start_limit", preset.get("optuna_seed_warm_start_limit", 5)),
        ),
    )
    return RuntimeSettings(
        slippage_bps=raw.get("slippage_bps", preset.get("slippage_bps", 5.0)),
        latency_bars=raw.get("latency_bars", preset.get("latency_bars", 0)),
        parameter_search_mode=raw.get("parameter_search_mode", preset.get("parameter_search_mode", "grid")),
        optuna_trials=optuna_trial_budget,
        optuna_seed_warm_start_limit=optuna_warm_start_trials,
        optuna_sampler=str(raw.get("optuna_sampler", preset.get("optuna_sampler", "tpe"))),
        optuna_pruner_enabled=bool(raw.get("optuna_pruner_enabled", preset.get("optuna_pruner_enabled", True))),
        optuna_startup_trials=int(raw.get("optuna_startup_trials", preset.get("optuna_startup_trials", 2))),
        optuna_warm_start_trials=int(optuna_warm_start_trials),
        optuna_trial_budget=int(optuna_trial_budget),
        position_side=raw.get("position_side", preset.get("position_side", "long")),
        position_leverage=raw.get("position_leverage", preset.get("position_leverage", 1.0)),
        maintenance_margin_ratio=raw.get("maintenance_margin_ratio", preset.get("maintenance_margin_ratio", 0.01)),
        liquidation_fee_bps=raw.get("liquidation_fee_bps", preset.get("liquidation_fee_bps", 0.0)),
        liquidation_mark_price_weight=raw.get("liquidation_mark_price_weight", preset.get("liquidation_mark_price_weight", 0.0)),
        partial_liquidation_ratio=raw.get("partial_liquidation_ratio", preset.get("partial_liquidation_ratio", 1.0)),
        liquidation_cooldown_bars=raw.get("liquidation_cooldown_bars", preset.get("liquidation_cooldown_bars", 0)),
        liquidation_step_schedule=list(raw.get("liquidation_step_schedule", preset.get("liquidation_step_schedule", []))),
        liquidation_mark_premium_bps=raw.get("liquidation_mark_premium_bps", preset.get("liquidation_mark_premium_bps", 0.0)),
        maintenance_margin_schedule=[dict(item) for item in raw.get("maintenance_margin_schedule", preset.get("maintenance_margin_schedule", []))],
        liquidation_fee_schedule=[dict(item) for item in raw.get("liquidation_fee_schedule", preset.get("liquidation_fee_schedule", []))],
        min_oos_trades=raw.get("min_oos_trades", preset.get("min_oos_trades")),
        fail_on_quality_flags=raw.get("fail_on_quality_flags", preset.get("fail_on_quality_flags", False)),
        max_parameter_permutations=raw.get("max_parameter_permutations", preset.get("max_parameter_permutations", 64)),
        search_summary_limit=raw.get("search_summary_limit", preset.get("search_summary_limit", 3)),
        bootstrap_samples=raw.get("bootstrap_samples", preset.get("bootstrap_samples", 8)),
        bootstrap_block_size=raw.get("bootstrap_block_size", preset.get("bootstrap_block_size")),
        bootstrap_method=raw.get("bootstrap_method", preset.get("bootstrap_method", "moving_block")),
        bootstrap_spread_multiplier=raw.get("bootstrap_spread_multiplier", preset.get("bootstrap_spread_multiplier", 1.0)),
        bootstrap_depth_multiplier=raw.get("bootstrap_depth_multiplier", preset.get("bootstrap_depth_multiplier", 1.0)),
        bootstrap_latency_multiplier=raw.get("bootstrap_latency_multiplier", preset.get("bootstrap_latency_multiplier", 1.0)),
        permutation_count=raw.get("permutation_count", preset.get("permutation_count", 1000)),
        permutation_pvalue_threshold=raw.get("permutation_pvalue_threshold", preset.get("permutation_pvalue_threshold", 0.01)),
        walk_forward_relaxed_pvalue_threshold=raw.get(
            "walk_forward_relaxed_pvalue_threshold",
            preset.get("walk_forward_relaxed_pvalue_threshold", 0.05),
        ),
        regime_model=str(raw.get("regime_model", preset.get("regime_model", "deterministic"))),
        regime_n_states=int(raw.get("regime_n_states", preset.get("regime_n_states", 4))),
        deflated_sharpe_ratio_threshold=raw.get(
            "deflated_sharpe_ratio_threshold",
            preset.get("deflated_sharpe_ratio_threshold", 0.95),
        ),
        gate_probabilistic_sharpe_ratio=raw.get(
            "gate_probabilistic_sharpe_ratio",
            preset.get("gate_probabilistic_sharpe_ratio", False),
        ),
        gate_min_backtest_length=raw.get(
            "gate_min_backtest_length",
            preset.get("gate_min_backtest_length", False),
        ),
        probabilistic_sharpe_ratio_threshold=raw.get(
            "probabilistic_sharpe_ratio_threshold",
            preset.get("probabilistic_sharpe_ratio_threshold", 0.95),
        ),
        holdout_sharpe_floor=raw.get("holdout_sharpe_floor", preset.get("holdout_sharpe_floor", 1.0)),
        holdout_drawdown_cap=raw.get("holdout_drawdown_cap", preset.get("holdout_drawdown_cap", -0.20)),
        scenario_severity_multiplier=raw.get("scenario_severity_multiplier", preset.get("scenario_severity_multiplier", 1.0)),
        slippage_model=raw.get("slippage_model", preset.get("slippage_model", "flat")),
    )


def _parse_snapshot(raw: dict) -> DataSnapshot:
    return DataSnapshot(
        snapshot_id=raw["snapshot_id"],
        symbol=raw["symbol"],
        venue=raw["venue"],
        timeframe=raw["timeframe"],
        contract_type=raw.get("contract_type", "perpetual"),
        candles=[
            Candle(
                timestamp=datetime.fromisoformat(candle["timestamp"]),
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
                trade_count=int(candle.get("trade_count", 0)),
            )
            for candle in raw["candles"]
        ],
        funding_rates=list(raw["funding_rates"]),
        open_interest=list(raw["open_interest"]),
        liquidation_notional=list(raw["liquidation_notional"]),
        maker_fee_bps=raw["maker_fee_bps"],
        taker_fee_bps=raw["taker_fee_bps"],
        mark_price=list(raw.get("mark_price", [])),
        index_price=list(raw.get("index_price", [])),
        next_funding_ts=list(raw.get("next_funding_ts", [])),
        open_interest_usd=list(raw.get("open_interest_usd", [])),
        basis_bps=list(raw.get("basis_bps", [])),
        liq_long_usd=list(raw.get("liq_long_usd", [])),
        liq_short_usd=list(raw.get("liq_short_usd", [])),
        spread_bps=list(raw.get("spread_bps", [])),
        depth_bid_1bp_usd=list(raw.get("depth_bid_1bp_usd", [])),
        depth_ask_1bp_usd=list(raw.get("depth_ask_1bp_usd", [])),
        latency_proxy_ms=list(raw.get("latency_proxy_ms", [])),
        ret_1=list(raw.get("ret_1", [])),
        ret_24=list(raw.get("ret_24", [])),
        rv_24h=list(raw.get("rv_24h", [])),
        funding_z=list(raw.get("funding_z", [])),
        d_oi=list(raw.get("d_oi", [])),
        d_oi_z=list(raw.get("d_oi_z", [])),
        liq_intensity_z=list(raw.get("liq_intensity_z", [])),
        vol_regime=list(raw.get("vol_regime", [])),
        regime_id=list(raw.get("regime_id", [])),
        regime_probabilities=[dict(item) for item in raw.get("regime_probabilities", [])],
        quality_flags=list(raw.get("quality_flags", [])),
        venue_profile=_parse_venue_profile(raw.get("venue_profile")),
        quality_report=_parse_quality_report(raw.get("quality_report")),
        provenance=dict(raw.get("provenance", {})),
    )


def _parse_venue_profile(raw: dict | None) -> VenueProfile | None:
    if raw is None:
        return None
    return VenueProfile(
        venue=raw["venue"],
        contract_type=raw.get("contract_type", "perpetual"),
        quote_currency=raw.get("quote_currency"),
        settlement_currency=raw.get("settlement_currency"),
        funding_interval_h=raw.get("funding_interval_h"),
        maker_fee_bps=raw.get("maker_fee_bps"),
        taker_fee_bps=raw.get("taker_fee_bps"),
        fee_schedule_source=raw.get("fee_schedule_source"),
        mark_price_source=raw.get("mark_price_source", "exchange_mark"),
        leverage_tiers=[dict(item) for item in raw.get("leverage_tiers", [])],
        maintenance_margin_schedule=[dict(item) for item in raw.get("maintenance_margin_schedule", [])],
        liquidation_fee_schedule=[dict(item) for item in raw.get("liquidation_fee_schedule", [])],
        liquidation_style=raw.get("liquidation_style", "full"),
        partial_liquidation_ratio=raw.get("partial_liquidation_ratio", 1.0),
        liquidation_cooldown_bars=raw.get("liquidation_cooldown_bars", 0),
        liquidation_mark_price_weight=raw.get("liquidation_mark_price_weight", 0.0),
        liquidation_mark_premium_bps=raw.get("liquidation_mark_premium_bps", 0.0),
        notes=list(raw.get("notes", [])),
    )


def _parse_quality_report(raw: dict | None) -> SnapshotQualityReport | None:
    if raw is None:
        return None
    return SnapshotQualityReport(
        report_id=raw["report_id"],
        snapshot_id=raw["snapshot_id"],
        quality_score=raw.get("quality_score", 1.0),
        passed=raw.get("passed", True),
        issues=list(raw.get("issues", [])),
        metrics=dict(raw.get("metrics", {})),
        source_checks=dict(raw.get("source_checks", {})),
        generated_at=raw.get("generated_at"),
    )


def _parse_backtest_result(raw: dict) -> BacktestResult:
    return BacktestResult(
        trade_count=raw["trade_count"],
        win_rate=raw["win_rate"],
        gross_pnl=raw["gross_pnl"],
        net_pnl=raw["net_pnl"],
        fee_spend=raw["fee_spend"],
        funding_spend=raw["funding_spend"],
        sharpe=raw["sharpe"],
        sortino=raw["sortino"],
        max_drawdown=raw["max_drawdown"],
        equity_curve=list(raw["equity_curve"]),
        liquidation_events=list(raw.get("liquidation_events", [])),
    )


def _parse_bootstrap_report(raw: dict) -> BootstrapReport:
    return BootstrapReport(
        sample_count=raw["sample_count"],
        median_net_profit=raw["median_net_profit"],
        median_max_drawdown=raw["median_max_drawdown"],
        worst_case_net_profit=raw["worst_case_net_profit"],
        worst_case_drawdown=raw["worst_case_drawdown"],
        pass_rate=raw["pass_rate"],
        bootstrap_method=raw.get("bootstrap_method", "moving_block"),
        block_size=raw.get("block_size"),
        bootstrap_microstructure_overlay=dict(raw.get("bootstrap_microstructure_overlay", {})),
        bootstrap_regime_summary=dict(raw.get("bootstrap_regime_summary", {})),
    )


def _parse_evaluation(name: str, raw: dict) -> CandidateEvaluation:
    return CandidateEvaluation(
        layer_name=name,
        decision=PromotionDecision(decision=raw["decision"], reasons=list(raw.get("reasons", []))),
        train_result=_parse_backtest_result(raw["train"]),
        oos_result=_parse_backtest_result(raw["oos"]),
        bootstrap_report=_parse_bootstrap_report(raw["bootstrap"]),
        selected_parameters=dict(raw.get("selected_parameters", {})),
        permutation_count=raw.get("permutation_count", 1),
        search_summary=list(raw.get("search_summary", [])),
    )


def _canonicalize_signature_payload(payload: object) -> object:
    ignored_top_level = {
        "run_id",
        "research_lineage",
        "research_hypotheses",
        "research_variant",
        "parameter_avoidance",
        "advisory_context",
        "advisory_rationale",
    }
    if isinstance(payload, dict):
        return {
            key: _canonicalize_signature_payload(value)
            for key, value in sorted(payload.items())
            if key not in ignored_top_level
        }
    if isinstance(payload, list):
        return [_canonicalize_signature_payload(value) for value in payload]
    return payload
