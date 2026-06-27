from __future__ import annotations

import logging
from collections.abc import Callable
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from engine.app.config import StudyConfig
from engine.agent.optuna_advisor import build_optuna_plan
from engine.backtest.simulator import _compute_funding_event_counts, simulate_strategy
from engine.backtest.simulator_numba import (
    BatchSimResult,
    is_numba_available,
    simulate_strategy_batch,
)
from engine.backtest.indicators import (
    atr as _ind_atr,
    ema as _ind_ema,
    hma as _ind_hma,
    kama as _ind_kama,
    rsi as _ind_rsi,
    zscore as _ind_zscore,
)

_logger = logging.getLogger(__name__)
from engine.config.models import (
    BacktestResult,
    BootstrapReport,
    CandidateEvaluation,
    DataSnapshot,
    LayerFamily,
    LayerSpec,
    PromotionDecision,
    StressMetrics,
    StrategyGraph,
)
from engine.data.schema import Candle
from engine.data.snapshots import clone_snapshot
from engine.memory.query import query_bayesian_seed_trials
from engine.optimizer.promotion import evaluate_candidate
from engine.optimizer.grid import expand_parameter_grid
from engine.validation.bootstrap import (
    bootstrap_indices_for_method,
    clone_snapshot_with_bootstrap_indices,
    dependent_wild_bootstrap_snapshot,
)
from engine.validation.protocol import legacy_validation_protocol, run_validation_protocol, validation_trial_count
from engine.validation.regimes import RegimeAnalysis, analyze_regimes
from engine.validation.scenarios import StressScenario, resolve_scenario_profile
from engine.validation.splits import build_split_pack
from engine.validation.statistics import compute_deflated_sharpe_ratio, compute_minimum_backtest_length


Evaluator = Callable[[StrategyGraph, LayerSpec], CandidateEvaluation]
ScenarioEvaluator = Callable[[StrategyGraph, StressScenario], BacktestResult]
ValidationExecutor = Callable[[StrategyGraph, list], object]


@dataclass(frozen=True)
class BatchGridResult:
    train_results: dict[int, BacktestResult]
    oos_results: dict[int, BacktestResult]
    telemetry: dict[str, object]

    def __iter__(self):
        yield self.train_results
        yield self.oos_results


def build_runtime_functions(study: StudyConfig) -> tuple[Evaluator, ScenarioEvaluator, ValidationExecutor]:
    if study.runtime_mode == "fixture":
        return (
            lambda _graph, layer: study.evaluations[layer.name],
            lambda _strategy, scenario: study.scenario_results[scenario.name],
            lambda _strategy, _phase_records: legacy_validation_protocol(study.holdout_decision),
        )

    split_pack = build_split_pack(study.snapshot)
    validation_candidate_return_series_by_layer: dict[str, list[list[float]]] = {}

    def evaluator(graph: StrategyGraph, layer: LayerSpec) -> CandidateEvaluation:
        incumbent_strategy, candidate_strategy = _resolve_strategies(graph, layer)
        incumbent_train = _evaluate_strategy_with_settings(
            split_pack.in_sample.snapshot,
            incumbent_strategy,
            layer_parameters=study.layer_parameters,
            slippage_bps=study.runtime_settings.slippage_bps,
            latency_bars=study.runtime_settings.latency_bars,
            position_side=study.runtime_settings.position_side,
            position_leverage=study.runtime_settings.position_leverage,
            maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
            liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
            liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
            partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
            liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
            liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
            liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
            maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
            liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
            slippage_model=study.runtime_settings.slippage_model,
        )
        incumbent_oos = _evaluate_strategy_with_settings(
            split_pack.selection_oos.snapshot,
            incumbent_strategy,
            layer_parameters=study.layer_parameters,
            slippage_bps=study.runtime_settings.slippage_bps,
            latency_bars=study.runtime_settings.latency_bars,
            position_side=study.runtime_settings.position_side,
            position_leverage=study.runtime_settings.position_leverage,
            maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
            liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
            liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
            partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
            liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
            liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
            liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
            maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
            liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
            slippage_model=study.runtime_settings.slippage_model,
        )

        min_oos_trades = (
            study.runtime_settings.min_oos_trades
            if study.runtime_settings.min_oos_trades is not None
            else min(100, max(3, len(split_pack.selection_oos.candles) // 8))
        )

        parameter_grid = study.parameter_grids.get(layer.name, {})
        parameter_sets = [{}]
        search_summaries: list[dict[str, object]] = []
        candidate_trials: list[dict[str, object]] = []
        optuna_candidate_returns: list[list[float]] = []
        seed_evidence = _build_search_seed_evidence(
            study=study,
            layer_name=layer.name,
            search_mode=study.runtime_settings.parameter_search_mode,
            source="parameter_grid",
            regime_coverage=split_pack.regime_coverage,
        )
        if parameter_grid:
            if study.runtime_settings.parameter_search_mode == "optuna":
                warm_start_trials, seed_evidence = _resolve_optuna_warm_start_context(study, layer.name)

                optuna_plan = build_optuna_plan(
                    layer_name=layer.name,
                    parameter_grid=_parameter_grid_to_optuna_ranges(parameter_grid),
                    warm_start_trials=warm_start_trials,
                    objective=lambda params: _score_parameter_set_for_optuna(
                        study=study,
                        split_pack=split_pack,
                        candidate_strategy=candidate_strategy,
                        layer_name=layer.name,
                        parameter_set=params,
                        out_returns=optuna_candidate_returns,
                    ),
                    n_trials=study.runtime_settings.optuna_trial_budget,
                    seed=study.seed,
                    sampler_name=study.runtime_settings.optuna_sampler,
                    pruner_enabled=study.runtime_settings.optuna_pruner_enabled,
                    startup_trials=study.runtime_settings.optuna_startup_trials,
                )
                parameter_sets = [dict(optuna_plan["best_parameters"])]
                optuna_trials = [
                    _annotate_candidate_trial(
                        dict(candidate),
                        search_source="optuna",
                        seed_evidence=seed_evidence,
                    )
                    for candidate in optuna_plan.get("search_summary", [])
                    if isinstance(candidate, dict)
                ]
                candidate_trials.extend(optuna_trials)
                search_summaries.extend(optuna_trials)
            else:
                parameter_sets, _ = expand_parameter_grid(
                    parameter_grid,
                    max_permutations=study.runtime_settings.max_parameter_permutations,
                )

        best_candidate: CandidateEvaluation | None = None
        candidate_return_series: list[list[float]] = []
        if study.runtime_settings.parameter_search_mode == "optuna":
            candidate_return_series.extend(optuna_candidate_returns)

        # Phase 11: attempt batch JIT sweep when numba is available and the
        # parameter grid has more than one set to evaluate.  Falls back to the
        # sequential path automatically on any error.
        batch_train_results: dict[int, BacktestResult] = {}
        batch_oos_results: dict[int, BacktestResult] = {}
        # Batch sweep supports flat, dynamic, and realistic slippage. Realistic
        # still requires typed microstructure because it can throttle fills.
        slippage_model = str(study.runtime_settings.slippage_model).strip().lower()
        batch_simulator_metadata: dict[str, object] | None = None
        if (
            is_numba_available()
            and len(parameter_sets) > 1
            and (
                slippage_model in {"flat", "dynamic"}
                or (
                    slippage_model == "realistic"
                    and _snapshot_supports_realistic_batch_sim(split_pack.in_sample.snapshot)
                    and _snapshot_supports_realistic_batch_sim(split_pack.selection_oos.snapshot)
                )
            )
        ):
            batch_grid_result = _run_grid_with_batch_sim(
                in_sample_snapshot=split_pack.in_sample.snapshot,
                oos_snapshot=split_pack.selection_oos.snapshot,
                candidate_strategy=candidate_strategy,
                parameter_sets=parameter_sets,
                layer_name=layer.name,
                base_layer_parameters=study.layer_parameters,
                position_side=study.runtime_settings.position_side,
                position_leverage=study.runtime_settings.position_leverage,
                maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
                liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
                liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
                liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
                maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
                liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
                taker_fee_bps=split_pack.in_sample.snapshot.taker_fee_bps,
                slippage_bps=study.runtime_settings.slippage_bps,
                latency_bars=study.runtime_settings.latency_bars,
                slippage_model=study.runtime_settings.slippage_model,
            )
            if isinstance(batch_grid_result, BatchGridResult):
                batch_train_results = batch_grid_result.train_results
                batch_oos_results = batch_grid_result.oos_results
                batch_simulator_metadata = dict(batch_grid_result.telemetry)
            else:
                batch_train_results, batch_oos_results = batch_grid_result
                batch_simulator_metadata = _build_batch_simulator_metadata(
                    attempted=True,
                    parameter_set_count=len(parameter_sets),
                    fallback_reason=None if batch_train_results else "batch_results_empty",
                    fallback_count=0 if batch_train_results else 1,
                    numba_used=bool(batch_train_results),
                )
            if batch_train_results:
                _logger.debug(
                    "numba batch sweep: %d param sets processed for layer %s",
                    len(batch_train_results),
                    layer.name,
                )

        for param_index, parameter_set in enumerate(parameter_sets):
            merged_layer_parameters = _merge_layer_parameters(study.layer_parameters, layer.name, parameter_set)

            # Use pre-computed batch result when available; otherwise evaluate
            # with the full simulator (which handles tiered margins, step
            # liquidations, and all other advanced features).
            if param_index in batch_train_results:
                candidate_train = batch_train_results[param_index]
            else:
                candidate_train = _evaluate_strategy_with_settings(
                    split_pack.in_sample.snapshot,
                    candidate_strategy,
                    layer_parameters=merged_layer_parameters,
                    slippage_bps=study.runtime_settings.slippage_bps,
                    latency_bars=study.runtime_settings.latency_bars,
                    position_side=study.runtime_settings.position_side,
                    position_leverage=study.runtime_settings.position_leverage,
                    maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
                    liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
                    liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
                    partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
                    liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
                    liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
                    liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
                    maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
                    liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
                    slippage_model=study.runtime_settings.slippage_model,
                )

            if param_index in batch_oos_results:
                candidate_oos = batch_oos_results[param_index]
            else:
                candidate_oos = _evaluate_strategy_with_settings(
                    split_pack.selection_oos.snapshot,
                    candidate_strategy,
                    layer_parameters=merged_layer_parameters,
                    slippage_bps=study.runtime_settings.slippage_bps,
                    latency_bars=study.runtime_settings.latency_bars,
                    position_side=study.runtime_settings.position_side,
                    position_leverage=study.runtime_settings.position_leverage,
                    maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
                    liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
                    liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
                    partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
                    liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
                    liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
                    liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
                    maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
                    liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
                    slippage_model=study.runtime_settings.slippage_model,
                )

            fast_screen = _run_fast_screen_gates(
                candidate_train=candidate_train,
                candidate_oos=candidate_oos,
                min_oos_trades=min_oos_trades,
                gate_min_backtest_length=study.runtime_settings.gate_min_backtest_length,
            )
            bootstrap_report = _bootstrap_strategy_with_settings(
                split_pack.bootstrap_source.snapshot,
                candidate_strategy,
                layer_parameters=merged_layer_parameters,
                slippage_bps=study.runtime_settings.slippage_bps,
                latency_bars=study.runtime_settings.latency_bars,
                position_side=study.runtime_settings.position_side,
                position_leverage=study.runtime_settings.position_leverage,
                maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
                liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
                liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
                partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
                liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
                liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
                liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
                maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
                liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
                slippage_model=study.runtime_settings.slippage_model,
                bootstrap_samples=study.runtime_settings.bootstrap_samples,
                bootstrap_block_size=study.runtime_settings.bootstrap_block_size,
                bootstrap_method=study.runtime_settings.bootstrap_method,
                bootstrap_spread_multiplier=study.runtime_settings.bootstrap_spread_multiplier,
                bootstrap_depth_multiplier=study.runtime_settings.bootstrap_depth_multiplier,
                bootstrap_latency_multiplier=study.runtime_settings.bootstrap_latency_multiplier,
            )

            decision = evaluate_candidate(
                incumbent_train=incumbent_train,
                incumbent_oos=incumbent_oos,
                candidate_train=candidate_train,
                candidate_oos=candidate_oos,
                bootstrap_report=bootstrap_report,
                min_oos_trades=min_oos_trades,
                position_leverage=study.runtime_settings.position_leverage,
            )
            if not fast_screen["passed"]:
                decision = _merge_fast_screen_decision(decision, list(fast_screen["reasons"]))
            search_source = "optuna_final" if study.runtime_settings.parameter_search_mode == "optuna" else "grid"
            trial_payload = _annotate_candidate_trial(
                {
                    "parameters": dict(parameter_set),
                    "decision": decision.decision,
                    "oos_sharpe": candidate_oos.sharpe,
                    "bootstrap_worst_drawdown": bootstrap_report.worst_case_drawdown,
                    "oos_net_pnl": candidate_oos.net_pnl,
                    "execution_pressure_summary": dict(candidate_oos.execution_pressure_summary or {}),
                    "fast_screen": fast_screen,
                },
                search_source=search_source,
                seed_evidence=seed_evidence,
            )
            if batch_simulator_metadata is not None:
                trial_payload["batch_simulator"] = dict(batch_simulator_metadata)
            candidate = CandidateEvaluation(
                layer_name=layer.name,
                decision=decision,
                train_result=candidate_train,
                oos_result=candidate_oos,
                bootstrap_report=bootstrap_report,
                selected_parameters=dict(parameter_set),
                permutation_count=study.runtime_settings.optuna_trial_budget if study.runtime_settings.parameter_search_mode == "optuna" else len(parameter_sets),
            )
            candidate_trials.append(trial_payload)
            search_summaries.append(trial_payload)
            if study.runtime_settings.parameter_search_mode != "optuna":
                candidate_return_series.append(_equity_return_series(candidate_oos))
            if best_candidate is None or _is_better_candidate(candidate, best_candidate):
                best_candidate = candidate

        if best_candidate is None:
            raise ValueError(f"no candidate evaluation produced for layer {layer.name}")

        final_train = _evaluate_strategy_with_settings(
            split_pack.in_sample.snapshot,
            candidate_strategy,
            layer_parameters=_merge_layer_parameters(study.layer_parameters, layer.name, best_candidate.selected_parameters),
            slippage_bps=study.runtime_settings.slippage_bps,
            latency_bars=study.runtime_settings.latency_bars,
            position_side=study.runtime_settings.position_side,
            position_leverage=study.runtime_settings.position_leverage,
            maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
            liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
            liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
            partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
            liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
            liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
            liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
            maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
            liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
            slippage_model=study.runtime_settings.slippage_model,
        )
        final_oos = _evaluate_strategy_with_settings(
            split_pack.selection_oos.snapshot,
            candidate_strategy,
            layer_parameters=_merge_layer_parameters(study.layer_parameters, layer.name, best_candidate.selected_parameters),
            slippage_bps=study.runtime_settings.slippage_bps,
            latency_bars=study.runtime_settings.latency_bars,
            position_side=study.runtime_settings.position_side,
            position_leverage=study.runtime_settings.position_leverage,
            maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
            liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
            liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
            partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
            liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
            liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
            liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
            maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
            liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
            slippage_model=study.runtime_settings.slippage_model,
        )
        best_candidate = CandidateEvaluation(
            layer_name=best_candidate.layer_name,
            decision=best_candidate.decision,
            train_result=final_train,
            oos_result=final_oos,
            bootstrap_report=best_candidate.bootstrap_report,
            selected_parameters=dict(best_candidate.selected_parameters),
            permutation_count=best_candidate.permutation_count,
            candidate_trials=list(best_candidate.candidate_trials),
        )

        sorted_summaries = sorted(
            search_summaries,
            key=lambda summary: (
                _decision_rank(str(summary.get("decision", "accept"))),
                float(summary.get("oos_sharpe", summary.get("score", 0.0))),
                float(summary.get("bootstrap_worst_drawdown", -999.0)),
                float(summary.get("oos_net_pnl", summary.get("score", 0.0))),
            ),
            reverse=True,
        )
        limit = max(1, study.runtime_settings.search_summary_limit)
        validation_candidate_return_series_by_layer[layer.name] = candidate_return_series
        return CandidateEvaluation(
            layer_name=best_candidate.layer_name,
            decision=best_candidate.decision,
            train_result=best_candidate.train_result,
            oos_result=best_candidate.oos_result,
            bootstrap_report=best_candidate.bootstrap_report,
            selected_parameters=dict(best_candidate.selected_parameters),
            permutation_count=(
                study.runtime_settings.optuna_trial_budget
                if study.runtime_settings.parameter_search_mode == "optuna"
                else len(parameter_sets)
            ),
            search_summary=sorted_summaries[:limit],
            candidate_trials=list(candidate_trials),
        )

    def scenario_evaluator(strategy: StrategyGraph, scenario: StressScenario) -> BacktestResult:
        active_snapshot, active_scenario = _resolve_scenario_runtime_inputs(
            split_pack.selection_oos.snapshot,
            scenario,
            seed=study.seed,
        )
        baseline = _apply_scenario_execution_overlay(
            snapshot=active_snapshot,
            strategy=strategy,
            scenario=active_scenario,
            layer_parameters=study.layer_parameters,
            slippage_bps=study.runtime_settings.slippage_bps,
            latency_bars=study.runtime_settings.latency_bars,
            position_side=study.runtime_settings.position_side,
            position_leverage=study.runtime_settings.position_leverage,
            maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
            liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
            liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
            partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
            liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
            liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
            liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
            maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
            liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
        )
        return _apply_scenario_stress(
            baseline,
            active_scenario,
            active_scenario.severity * study.runtime_settings.scenario_severity_multiplier,
            study.runtime_settings.position_side,
            active_snapshot,
        )

    def validation_executor(strategy: StrategyGraph, phase_records: list) -> object:
        def evaluate_strategy(snapshot: DataSnapshot, fixed_strategy: StrategyGraph) -> BacktestResult:
            return _evaluate_strategy_with_settings(
                snapshot,
                fixed_strategy,
                layer_parameters=study.layer_parameters,
                slippage_bps=study.runtime_settings.slippage_bps,
                latency_bars=study.runtime_settings.latency_bars,
                position_side=study.runtime_settings.position_side,
                position_leverage=study.runtime_settings.position_leverage,
                maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
                liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
                liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
                partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
                liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
                liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
                liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
                maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
                liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
                slippage_model=study.runtime_settings.slippage_model,
            )

        return run_validation_protocol(
            split_pack=split_pack,
            strategy=strategy,
            evaluate_strategy=evaluate_strategy,
            trial_count=validation_trial_count(phase_records),
            candidate_return_series=_candidate_return_series_from_phase_records(
                phase_records,
                validation_candidate_return_series_by_layer,
            ),
            permutation_count=study.runtime_settings.permutation_count,
            permutation_pvalue_threshold=study.runtime_settings.permutation_pvalue_threshold,
            walk_forward_relaxed_pvalue_threshold=study.runtime_settings.walk_forward_relaxed_pvalue_threshold,
            deflated_sharpe_ratio_threshold=study.runtime_settings.deflated_sharpe_ratio_threshold,
            gate_probabilistic_sharpe_ratio=study.runtime_settings.gate_probabilistic_sharpe_ratio,
            gate_min_backtest_length=study.runtime_settings.gate_min_backtest_length,
            probabilistic_sharpe_ratio_threshold=study.runtime_settings.probabilistic_sharpe_ratio_threshold,
            holdout_sharpe_floor=study.runtime_settings.holdout_sharpe_floor,
            holdout_drawdown_cap=study.runtime_settings.holdout_drawdown_cap,
            seed=study.seed,
        )

    return evaluator, scenario_evaluator, validation_executor


def _resolve_strategies(graph: StrategyGraph, layer: LayerSpec) -> tuple[StrategyGraph, StrategyGraph]:
    existing_names = {existing_layer.name for existing_layer in graph.layers}
    if layer.name == graph.backbone and not graph.layers:
        return graph, graph
    if layer.name in existing_names:
        previous_layers = graph.layers[:-1] if graph.layers else []
        return StrategyGraph(backbone=graph.backbone, layers=previous_layers, risk_guards=graph.risk_guards), graph
    return graph, graph.with_layer(layer)


def _evaluate_strategy(snapshot: DataSnapshot, strategy: StrategyGraph) -> BacktestResult:
    return _evaluate_strategy_with_settings(
        snapshot,
        strategy,
        layer_parameters={},
        slippage_bps=5.0,
        latency_bars=0,
        position_side="long",
        position_leverage=1.0,
        maintenance_margin_ratio=0.01,
        liquidation_fee_bps=0.0,
        liquidation_mark_price_weight=0.0,
        partial_liquidation_ratio=1.0,
        liquidation_cooldown_bars=0,
        liquidation_step_schedule=[],
        liquidation_mark_premium_bps=0.0,
        maintenance_margin_schedule=[],
        liquidation_fee_schedule=[],
    )


def _candidate_return_series_from_phase_records(
    phase_records: list,
    candidate_return_series_by_layer: dict[str, list[list[float]]],
) -> list[list[float]]:
    for record in reversed(list(phase_records)):
        layer_name = getattr(record, "layer_name", None)
        if not isinstance(layer_name, str):
            continue
        candidate_series = candidate_return_series_by_layer.get(layer_name, [])
        usable_series = [list(series) for series in candidate_series if len(series) >= 2]
        if len(usable_series) >= 2:
            return usable_series
    return []


def _run_fast_screen_gates(
    *,
    candidate_train: BacktestResult,
    candidate_oos: BacktestResult,
    min_oos_trades: int,
    gate_min_backtest_length: bool,
) -> dict[str, object]:
    returns = _equity_return_series(candidate_oos)
    min_btl = compute_minimum_backtest_length(returns, target_psr=0.95)
    liquidation_count = len(candidate_train.liquidation_events) + len(candidate_oos.liquidation_events)
    funding_drag_ratio = _funding_drag_ratio(candidate_oos)
    reasons: list[str] = []
    if candidate_oos.trade_count < min_oos_trades:
        reasons.append("fast_screen_min_oos_trades")
    if gate_min_backtest_length and returns and len(returns) < min_btl:
        reasons.append("fast_screen_minimum_backtest_length")
    if liquidation_count:
        reasons.append("fast_screen_liquidation_events")
    if funding_drag_ratio >= 0.50:
        reasons.append("fast_screen_excessive_funding_drag")
    return {
        "stage": "fast_screen",
        "passed": not reasons,
        "reasons": reasons,
        "metrics": {
            "sample_count": len(returns),
            "minimum_backtest_length": min_btl,
            "minimum_backtest_length_enforced": bool(gate_min_backtest_length),
            "min_oos_trades": int(min_oos_trades),
            "oos_trade_count": int(candidate_oos.trade_count),
            "liquidation_event_count": liquidation_count,
            "funding_drag_ratio": funding_drag_ratio,
        },
    }


def _merge_fast_screen_decision(decision: PromotionDecision, reasons: list[str]) -> PromotionDecision:
    merged_reasons = list(decision.reasons)
    for reason in reasons:
        if reason not in merged_reasons:
            merged_reasons.append(reason)
    return PromotionDecision("reject", merged_reasons)


def _funding_drag_ratio(result: BacktestResult) -> float:
    denominator = abs(float(result.gross_pnl)) + abs(float(result.fee_spend)) + 1e-9
    return abs(float(result.funding_spend)) / denominator


def _equity_return_series(result: BacktestResult) -> list[float]:
    if len(result.equity_curve) < 2:
        return []
    return [
        result.equity_curve[index] - result.equity_curve[index - 1]
        for index in range(1, len(result.equity_curve))
    ]


def _evaluate_strategy_with_settings(
    snapshot: DataSnapshot,
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
    slippage_bps: float,
    latency_bars: int,
    position_side: str,
    position_leverage: float,
    maintenance_margin_ratio: float,
    liquidation_fee_bps: float,
    liquidation_mark_price_weight: float,
    partial_liquidation_ratio: float,
    liquidation_cooldown_bars: int,
    liquidation_step_schedule: list[float],
    liquidation_mark_premium_bps: float,
    maintenance_margin_schedule: list[dict[str, float]],
    liquidation_fee_schedule: list[dict[str, float]],
    slippage_model: str = "flat",
) -> BacktestResult:
    if len(snapshot.candles) < 3:
        return BacktestResult(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [], [])

    entry_signals, exit_signals = _build_signals(snapshot, strategy, layer_parameters, position_side)
    raw = simulate_strategy(
        snapshot,
        entry_signals,
        exit_signals,
        slippage_bps=slippage_bps,
        latency_bars=latency_bars,
        position_side=position_side,
        position_leverage=position_leverage,
        maintenance_margin_ratio=maintenance_margin_ratio,
        liquidation_fee_bps=liquidation_fee_bps,
        liquidation_mark_price_weight=liquidation_mark_price_weight,
        partial_liquidation_ratio=partial_liquidation_ratio,
        liquidation_cooldown_bars=liquidation_cooldown_bars,
        liquidation_step_schedule=liquidation_step_schedule,
        liquidation_mark_premium_bps=liquidation_mark_premium_bps,
        maintenance_margin_schedule=maintenance_margin_schedule,
        liquidation_fee_schedule=liquidation_fee_schedule,
        slippage_model=slippage_model,
    )
    normalized = _normalize_result(raw, snapshot)
    return _apply_layer_adjustments(normalized, strategy, layer_parameters, position_side)


def _apply_scenario_execution_overlay(
    snapshot: DataSnapshot,
    strategy: StrategyGraph,
    scenario: StressScenario,
    layer_parameters: dict[str, dict[str, float | int]],
    slippage_bps: float,
    latency_bars: int,
    position_side: str,
    position_leverage: float,
    maintenance_margin_ratio: float,
    liquidation_fee_bps: float,
    liquidation_mark_price_weight: float,
    partial_liquidation_ratio: float,
    liquidation_cooldown_bars: int,
    liquidation_step_schedule: list[float],
    liquidation_mark_premium_bps: float,
    maintenance_margin_schedule: list[dict[str, float]],
    liquidation_fee_schedule: list[dict[str, float]],
    slippage_model: str = "flat",
) -> BacktestResult:
    scenario = resolve_scenario_profile(scenario, venue=snapshot.venue)
    dislocation_premium_bps = _scenario_dislocation_premium_bps(scenario)
    dislocation_liquidity_bps = _scenario_dislocation_liquidity_penalty_bps(scenario)
    return _evaluate_strategy_with_settings(
        snapshot=snapshot,
        strategy=strategy,
        layer_parameters=layer_parameters,
        slippage_bps=slippage_bps + scenario.liquidity_penalty_bps + dislocation_liquidity_bps,
        latency_bars=max(0, latency_bars + scenario.latency_delta_bars),
        position_side=position_side,
        position_leverage=position_leverage,
        maintenance_margin_ratio=maintenance_margin_ratio,
        liquidation_fee_bps=liquidation_fee_bps,
        liquidation_mark_price_weight=liquidation_mark_price_weight,
        partial_liquidation_ratio=partial_liquidation_ratio,
        liquidation_cooldown_bars=liquidation_cooldown_bars,
        liquidation_step_schedule=liquidation_step_schedule,
        liquidation_mark_premium_bps=liquidation_mark_premium_bps + dislocation_premium_bps,
        maintenance_margin_schedule=maintenance_margin_schedule,
        liquidation_fee_schedule=liquidation_fee_schedule,
        slippage_model=slippage_model,
    )


def _build_signals(
    snapshot: DataSnapshot,
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
    position_side: str,
) -> tuple[list[bool], list[bool]]:
    """Dispatch to backbone-specific signal generator."""
    candles = snapshot.candles
    closes = [c.close for c in candles]
    highs  = [c.high  for c in candles]
    lows   = [c.low   for c in candles]
    n = len(candles)
    entry_signals = [False] * n
    exit_signals  = [False] * n

    if strategy.backbone == "kama_hma":
        return _build_kama_hma_signals(
            closes, highs, lows, entry_signals, exit_signals,
            strategy, layer_parameters, position_side,
        )
    if strategy.backbone == "keltner_fade":
        return _build_keltner_fade_signals(
            closes, highs, lows, entry_signals, exit_signals,
            strategy, layer_parameters, position_side,
        )
    # Default: mom_squeeze — strided close-vs-prior momentum logic
    return _build_mom_squeeze_signals(
        candles, closes, highs, lows, entry_signals, exit_signals,
        strategy, layer_parameters, position_side,
    )


def _build_mom_squeeze_signals(
    candles: list,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    entry_signals: list[bool],
    exit_signals: list[bool],
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
    position_side: str,
) -> tuple[list[bool], list[bool]]:
    """Original strided close-vs-prior momentum backbone (mom_squeeze)."""
    filter_emas = _precompute_filter_emas(closes, strategy, layer_parameters)

    hold_bars = _resolve_time_stop_bars(strategy, layer_parameters, default=3)

    stride = int(_get_layer_parameter(
        layer_parameters, strategy.backbone, "entry_stride",
        max(2, 5 - min(len(strategy.layers), 2)),
    ))
    if any(layer.family is LayerFamily.DIRECTIONAL_FILTER for layer in strategy.layers):
        stride = max(2, stride - 1)

    open_index: int | None = None
    for index in range(1, len(candles)):
        if open_index is None:
            if position_side == "short":
                should_enter = index % stride == 1 and closes[index] < closes[index - 1]
            else:
                should_enter = index % stride == 1 and closes[index] > closes[index - 1]
            if should_enter and _passes_filters(
                closes, index, strategy, layer_parameters, position_side, filter_emas
            ):
                entry_signals[index] = True
                open_index = index
        else:
            if index - open_index >= hold_bars:
                exit_signals[index] = True
                open_index = None

    if open_index is not None:
        exit_signals[-1] = True

    return entry_signals, exit_signals


def _build_kama_hma_signals(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    entry_signals: list[bool],
    exit_signals: list[bool],
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
    position_side: str,
) -> tuple[list[bool], list[bool]]:
    """KAMA-HMA Adaptive Regime Separation backbone.

    Uses KAMA's Efficiency Ratio (ER) as a continuous-state regime gate.
    HMA directional signals are only activated inside confirmed trending
    regimes.  An ATR trailing stop provides intra-bar risk control.

    Hysteresis gap (theta_flat < theta_trend - 0.10) prevents oscillation
    in the dead-band between the two thresholds.
    """
    p = layer_parameters.get(strategy.backbone, {})
    n_er        = int(p.get("n",           10))
    f_fast      = int(p.get("f",            2))
    s_slow      = int(p.get("s",           30))
    theta_trend = float(p.get("theta_trend", 0.60))
    theta_flat  = float(p.get("theta_flat",  0.25))
    n_hma       = int(p.get("n_hma",        20))
    p_atr       = int(p.get("p_atr",        14))
    k_stop      = float(p.get("k_stop",      2.0))
    max_hold    = _resolve_time_stop_bars(strategy, layer_parameters, default=24)

    _kama_vals, er_series = _ind_kama(closes, n=n_er, f=f_fast, s=s_slow)
    hma_vals = _ind_hma(closes, n_hma)
    atr_vals = _ind_atr(highs, lows, closes, p_atr)
    filter_emas = _precompute_filter_emas(closes, strategy, layer_parameters)

    in_trend = False
    open_index: int | None = None
    entry_price = 0.0
    atr_at_entry = 0.0

    for i in range(1, len(closes)):
        er = er_series[i]

        # Hysteresis state machine — only flip outside the dead-band
        if er >= theta_trend:
            in_trend = True
        elif er <= theta_flat:
            in_trend = False
        # Between theta_flat and theta_trend: hold current state

        if open_index is not None:
            # ATR trailing stop
            stop_dist = k_stop * atr_at_entry
            if position_side == "long" and closes[i] < entry_price - stop_dist:
                exit_signals[i] = True
                open_index = None
                continue
            if position_side == "short" and closes[i] > entry_price + stop_dist:
                exit_signals[i] = True
                open_index = None
                continue
            # Safety cap on hold length
            if i - open_index >= max_hold:
                exit_signals[i] = True
                open_index = None
            continue

        # Regime gate: only enter in confirmed trending state
        if not in_trend:
            continue

        # HMA slope: rising for long, falling for short
        if position_side == "long" and not (hma_vals[i] > hma_vals[i - 1]):
            continue
        if position_side == "short" and not (hma_vals[i] < hma_vals[i - 1]):
            continue

        # Additional directional filter layers
        if not _passes_filters(closes, i, strategy, layer_parameters, position_side, filter_emas):
            continue

        entry_signals[i] = True
        open_index = i
        entry_price = closes[i]
        atr_at_entry = max(atr_vals[i], 1e-9)

    if open_index is not None:
        exit_signals[-1] = True

    return entry_signals, exit_signals


def _build_keltner_fade_signals(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    entry_signals: list[bool],
    exit_signals: list[bool],
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
    position_side: str,
) -> tuple[list[bool], list[bool]]:
    """Keltner Channel Volatility-Adjusted Mean Reversion backbone.

    Fades price exhaustion at channel extremes when RSI and Z-score
    simultaneously confirm the tail move.  Exits via ATR trailing stop
    or a fixed t_bars time stop, whichever triggers first.
    """
    p = layer_parameters.get(strategy.backbone, {})
    p_ema       = int(p.get("p_ema",        20))
    p_atr       = int(p.get("p_atr",        14))
    m           = float(p.get("m",            2.0))
    p_rsi       = int(p.get("p_rsi",        14))
    theta_os    = float(p.get("theta_os",    30.0))
    theta_ob    = float(p.get("theta_ob",    70.0))
    k_stop      = float(p.get("k_stop",      1.5))
    t_bars      = int(p.get("t_bars",       10))
    t_bars      = _resolve_time_stop_bars(strategy, layer_parameters, default=t_bars)
    z_threshold = float(p.get("z_threshold", 2.0))

    ema_mid  = _ind_ema(closes, p_ema)
    atr_vals = _ind_atr(highs, lows, closes, p_atr)
    rsi_vals = _ind_rsi(closes, p_rsi)
    z_vals   = _ind_zscore(closes, p_ema)

    open_index: int | None = None
    entry_price = 0.0
    atr_at_entry = 0.0

    for i in range(1, len(closes)):
        upper = ema_mid[i] + m * atr_vals[i]
        lower = ema_mid[i] - m * atr_vals[i]

        if open_index is not None:
            # ATR trailing stop
            stop_dist = k_stop * atr_at_entry
            if position_side == "long" and closes[i] < entry_price - stop_dist:
                exit_signals[i] = True
                open_index = None
                continue
            if position_side == "short" and closes[i] > entry_price + stop_dist:
                exit_signals[i] = True
                open_index = None
                continue
            # Time stop
            if i - open_index >= t_bars:
                exit_signals[i] = True
                open_index = None
            continue

        # Entry: fade down (long) — below lower band, RSI oversold, Z deeply negative
        if position_side == "long" and (
            closes[i] < lower
            and rsi_vals[i] < theta_os
            and z_vals[i] < -z_threshold
        ):
            entry_signals[i] = True
            open_index = i
            entry_price = closes[i]
            atr_at_entry = max(atr_vals[i], 1e-9)
            continue

        # Entry: fade up (short) — above upper band, RSI overbought, Z deeply positive
        if position_side == "short" and (
            closes[i] > upper
            and rsi_vals[i] > theta_ob
            and z_vals[i] > z_threshold
        ):
            entry_signals[i] = True
            open_index = i
            entry_price = closes[i]
            atr_at_entry = max(atr_vals[i], 1e-9)

    if open_index is not None:
        exit_signals[-1] = True

    return entry_signals, exit_signals


def _precompute_filter_emas(
    closes: list[float],
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
) -> dict[str, list[float]]:
    """Pre-compute EMA series for every DIRECTIONAL_FILTER layer.

    Uses each layer's actual ``len`` parameter so the filter lookback
    matches the catalogued period, rather than the previous hardcoded
    5-bar window.
    """
    result: dict[str, list[float]] = {}
    for layer in strategy.layers:
        if layer.family is LayerFamily.DIRECTIONAL_FILTER:
            filter_len = int(_get_layer_parameter(layer_parameters, layer.name, "len", 20))
            result[layer.name] = _ind_ema(closes, filter_len)
    return result


def _resolve_time_stop_bars(
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
    *,
    default: int,
) -> int:
    for layer in strategy.layers:
        if layer.family is LayerFamily.EXIT and layer.name == "time_stop":
            return int(_get_layer_parameter(layer_parameters, layer.name, "hold_bars", default))
    return default


def _passes_filters(
    closes: list[float],
    index: int,
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
    position_side: str,
    filter_emas: dict[str, list[float]] | None = None,
) -> bool:
    """Gate an entry bar through all non-backbone filter layers.

    Directional filters compare close to their pre-computed EMA (real
    indicator period, not a 5-bar average).  Flat filters block entries
    when the recent 10-bar range is below the configured threshold.
    """
    if filter_emas is None:
        filter_emas = {}

    recent = closes[max(0, index - 10) : index + 1]
    recent_range = max(recent) - min(recent) if len(recent) > 1 else 0.0

    for layer in strategy.layers:
        if layer.family is LayerFamily.DIRECTIONAL_FILTER:
            ema_series = filter_emas.get(layer.name)
            if ema_series and index < len(ema_series):
                filter_ema = ema_series[index]
            else:
                window = closes[max(0, index - 20) : index + 1]
                filter_ema = sum(window) / max(1, len(window))
            if position_side == "short":
                if closes[index] > filter_ema:
                    return False
            else:
                if closes[index] < filter_ema:
                    return False

        if layer.family in {LayerFamily.KNOWN_GOOD_FLAT_FILTER, LayerFamily.CUSTOM_FLAT_FILTER}:
            # Normalise range to percentage of current price so the threshold
            # works across all price levels (BTC at $60k, alts at $0.05, etc.).
            current_price = max(closes[index], 1e-9)
            recent_range_pct = recent_range / current_price
            flat_threshold = float(_get_layer_parameter(
                layer_parameters, layer.name, "flat_range_threshold", 0.003
            ))
            if recent_range_pct < flat_threshold:
                return False

    return True


def _apply_layer_adjustments(
    result: BacktestResult,
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
    position_side: str,
) -> BacktestResult:
    """Pass-through: returns backtest result unchanged.

    The previous implementation applied synthetic Sharpe/PnL/drawdown
    multipliers post-simulation, causing the validation pipeline to
    operate on fabricated numbers (~85\u0025 Sharpe inflation observed).
    All layer effects are now captured directly in _build_signals signal
    generation, so no post-hoc adjustment is correct or needed.
    """
    return result



def _apply_scenario_stress(
    baseline: BacktestResult,
    scenario: StressScenario,
    effective_severity: float,
    position_side: str,
    snapshot: DataSnapshot,
) -> BacktestResult:
    scenario = resolve_scenario_profile(scenario, venue=snapshot.venue)
    severity_factor = max(0.1, 1.0 - effective_severity * 0.65)
    drawdown_multiplier = (1.0 + effective_severity * 1.7) * max(0.1, scenario.drawdown_multiplier)
    funding_multiplier = (1.0 + effective_severity) * max(0.1, scenario.funding_multiplier)
    liquidation_events = list(baseline.liquidation_events)
    extra_liquidity_cost = abs(baseline.gross_pnl) * (
        max(0.0, scenario.liquidity_penalty_bps)
        + _scenario_dislocation_liquidity_penalty_bps(scenario)
    ) / 10_000.0
    dislocation_premium_bps = _scenario_dislocation_premium_bps(scenario)
    if dislocation_premium_bps > 0:
        drawdown_multiplier *= 1.0 + (dislocation_premium_bps / 10_000.0)
        if effective_severity >= 0.7:
            liquidation_events = [*liquidation_events, f"{scenario.name}:synthetic-mark-pressure"]

    if position_side == "short":
        average_open_interest = sum(snapshot.open_interest) / max(1, len(snapshot.open_interest))
        average_liquidation = sum(snapshot.liquidation_notional) / max(1, len(snapshot.liquidation_notional))
        average_funding = sum(snapshot.funding_rates) / max(1, len(snapshot.funding_rates))
        squeeze_pressure = min(0.35, average_liquidation / max(average_open_interest, 1.0))
        funding_pressure = min(0.20, max(0.0, average_funding) * 20.0)
        liquidation_pressure = max(1.0, scenario.liquidation_multiplier)
        severity_factor = max(
            0.05,
            severity_factor * (1.0 - squeeze_pressure * 0.55 * liquidation_pressure - funding_pressure * 0.35),
        )
        drawdown_multiplier += squeeze_pressure * 1.4 * liquidation_pressure + funding_pressure * 0.6
        funding_multiplier += funding_pressure * 3.0
        if effective_severity + squeeze_pressure >= 0.85:
            liquidation_events = [*liquidation_events, f"{scenario.name}:synthetic-short-squeeze"]
    elif effective_severity >= 0.85:
        liquidation_events = [*liquidation_events, f"{scenario.name}:synthetic-liquidation"]

    average_open_interest = sum(snapshot.open_interest) / max(1, len(snapshot.open_interest))
    average_liquidation = sum(snapshot.liquidation_notional) / max(1, len(snapshot.liquidation_notional))
    leverage_pressure = min(0.35, average_liquidation / max(average_open_interest, 1.0))
    severity_factor = max(
        0.05,
        severity_factor
        * (1.0 - max(0.0, scenario.volatility_multiplier - 1.0) * 0.18)
        * (1.0 - max(0.0, scenario.open_interest_multiplier - 1.0) * leverage_pressure * 0.5),
    )
    drawdown_multiplier *= 1.0 + max(0.0, scenario.volatility_multiplier - 1.0) * 0.5
    drawdown_multiplier *= 1.0 + max(0.0, scenario.open_interest_multiplier - 1.0) * leverage_pressure

    # Phase 14: apply empirical calibration multipliers when the scenario was
    # calibrated via Hawkes / jump-diffusion estimation.
    if scenario.calibration_mode == "calibrated":
        # Cascade multiplier amplifies the drawdown further (≥1.0 by construction).
        drawdown_multiplier *= max(1.0, scenario.hawkes_cascade_multiplier)
        # Jump severity factor tightens the PnL severity (higher jump risk → worse outcomes).
        severity_factor = max(0.01, severity_factor / max(1.0, scenario.jump_severity_factor))

    stressed_gross_pnl = baseline.gross_pnl * severity_factor
    stressed_fee_spend = baseline.fee_spend + extra_liquidity_cost
    stressed_funding_spend = _stress_funding_spend(baseline.funding_spend, funding_multiplier)

    return BacktestResult(
        trade_count=baseline.trade_count,
        win_rate=max(0.0, baseline.win_rate * severity_factor),
        gross_pnl=stressed_gross_pnl,
        net_pnl=stressed_gross_pnl - stressed_fee_spend - stressed_funding_spend,
        fee_spend=stressed_fee_spend,
        funding_spend=stressed_funding_spend,
        sharpe=baseline.sharpe * max(0.15, 1.0 - effective_severity * 0.8),
        sortino=baseline.sortino * max(0.15, 1.0 - effective_severity * 0.75),
        max_drawdown=-abs(baseline.max_drawdown) * drawdown_multiplier,
        equity_curve=list(baseline.equity_curve),
        liquidation_events=liquidation_events,
    )


def _derive_stress_metrics(
    baseline: BacktestResult,
    stressed: BacktestResult,
    scenario: StressScenario,
    snapshot: DataSnapshot,
) -> StressMetrics:
    resolved = resolve_scenario_profile(scenario, venue=snapshot.venue)
    average_open_interest = sum(snapshot.open_interest) / max(1, len(snapshot.open_interest))
    average_liquidation = sum(snapshot.liquidation_notional) / max(1, len(snapshot.liquidation_notional))
    average_funding = sum(abs(value) for value in snapshot.funding_rates) / max(1, len(snapshot.funding_rates))
    liquidation_ratio = min(1.0, average_liquidation / max(average_open_interest, 1.0))
    fee_delta = max(0.0, stressed.fee_spend - baseline.fee_spend)
    pnl_scale = max(abs(baseline.gross_pnl), abs(stressed.gross_pnl), 1.0)

    stress_slippage_quantile = min(
        1.0,
        (fee_delta / pnl_scale) + (max(0.0, resolved.liquidity_penalty_bps) / 10_000.0),
    )
    stress_tail_slippage = min(
        1.0,
        stress_slippage_quantile * (1.0 + resolved.severity + liquidation_ratio * max(1.0, resolved.volatility_multiplier)),
    )
    liquidity_stress_score = min(
        1.0,
        (max(0.0, resolved.liquidity_penalty_bps) / 100.0)
        + liquidation_ratio * 0.35
        + max(0.0, resolved.spread_multiplier - 1.0) * 0.08
        + max(0.0, 1.0 - resolved.depth_multiplier) * 0.2
        + max(0.0, resolved.latency_multiplier - 1.0) * 0.03
        + max(0.0, resolved.latency_delta_bars) * 0.05,
    )
    basis_stress_score = min(
        1.0,
        average_funding * max(1.0, resolved.funding_multiplier) * 18.0
        + (max(0.0, _scenario_dislocation_premium_bps(resolved)) / 1_000.0),
    )
    cascade_liquidation_count = max(
        0,
        len(stressed.liquidation_events) - len(baseline.liquidation_events),
    )
    if resolved.name == "liquidation_cascade":
        cascade_liquidation_count = max(
            cascade_liquidation_count,
            int(round(liquidation_ratio * max(1.0, resolved.liquidation_multiplier))),
        )

    return StressMetrics(
        stress_slippage_quantile=round(stress_slippage_quantile, 6),
        stress_tail_slippage=round(stress_tail_slippage, 6),
        liquidity_stress_score=round(liquidity_stress_score, 6),
        basis_stress_score=round(basis_stress_score, 6),
        cascade_liquidation_count=int(cascade_liquidation_count),
    )


def _normalize_result(result: BacktestResult, snapshot: DataSnapshot) -> BacktestResult:
    # max_drawdown from risk.py is already a fraction of equity (e.g. -0.15).
    # Do NOT divide by average_close * trade_count — that would convert a
    # dimensionless ratio into a near-zero value and silently disable every
    # downstream drawdown gate (bootstrap kill-switch, promotion cap, etc.).
    return BacktestResult(
        trade_count=result.trade_count,
        win_rate=result.win_rate,
        gross_pnl=result.gross_pnl,
        net_pnl=result.net_pnl,
        fee_spend=result.fee_spend,
        funding_spend=result.funding_spend,
        sharpe=result.sharpe,
        sortino=result.sortino,
        max_drawdown=result.max_drawdown,
        equity_curve=result.equity_curve,
        liquidation_events=result.liquidation_events,
        execution_pressure_summary=dict(result.execution_pressure_summary or {}),
    )


def _stress_funding_spend(baseline_funding_spend: float, funding_multiplier: float) -> float:
    if baseline_funding_spend >= 0.0:
        return baseline_funding_spend * funding_multiplier
    return baseline_funding_spend + abs(baseline_funding_spend) * max(0.0, funding_multiplier - 1.0)


def _resolve_scenario_runtime_inputs(
    snapshot: DataSnapshot,
    scenario: StressScenario,
    *,
    seed: int = 0,
) -> tuple[DataSnapshot, StressScenario]:
    resolved = resolve_scenario_profile(scenario, venue=snapshot.venue)
    if resolved.calibration_mode != "calibrated":
        active_snapshot = _snapshot_with_stressed_microstructure(snapshot, resolved, scenario_name=resolved.name)
        active_snapshot = _snapshot_with_mark_index_dislocation(
            active_snapshot,
            resolved,
            scenario_name=resolved.name,
        )
        active_snapshot = _snapshot_with_scenario_execution_overlay_summary(
            active_snapshot,
            resolved,
            scenario_name=resolved.name,
        )
        return active_snapshot, resolved

    try:
        from engine.validation.scenarios import build_calibrated_scenario_profile
    except ImportError:
        active_snapshot = _snapshot_with_stressed_microstructure(snapshot, resolved, scenario_name=resolved.name)
        active_snapshot = _snapshot_with_mark_index_dislocation(
            active_snapshot,
            resolved,
            scenario_name=resolved.name,
        )
        active_snapshot = _snapshot_with_scenario_execution_overlay_summary(
            active_snapshot,
            resolved,
            scenario_name=resolved.name,
        )
        return active_snapshot, resolved

    profile = build_calibrated_scenario_profile(snapshot, resolved, seed=seed)
    active_scenario = profile.get("calibrated_scenario", resolved)
    stressed_path = profile.get("stressed_path", [])
    if not isinstance(active_scenario, StressScenario):
        active_scenario = resolved
    active_snapshot = _snapshot_with_stressed_path(snapshot, stressed_path, scenario_name=resolved.name)
    active_snapshot = _snapshot_with_stressed_microstructure(
        active_snapshot,
        active_scenario,
        scenario_name=resolved.name,
    )
    active_snapshot = _snapshot_with_mark_index_dislocation(
        active_snapshot,
        active_scenario,
        scenario_name=resolved.name,
    )
    active_snapshot = _snapshot_with_scenario_execution_overlay_summary(
        active_snapshot,
        active_scenario,
        scenario_name=resolved.name,
    )

    if active_scenario.calibration_mode == "calibrated":
        _logger.debug(
            "scenario=%s calibrated: hawkes_cascade=%.3f jump_factor=%.3f path_bars=%d",
            resolved.name,
            active_scenario.hawkes_cascade_multiplier,
            active_scenario.jump_severity_factor,
            len(active_snapshot.candles),
        )
    return active_snapshot, active_scenario


def _snapshot_with_stressed_path(
    snapshot: DataSnapshot,
    stressed_path: object,
    *,
    scenario_name: str,
) -> DataSnapshot:
    if not isinstance(stressed_path, list) or len(stressed_path) != len(snapshot.candles):
        return snapshot

    stressed_candles: list[Candle] = []
    for index, (candle, stressed_close_raw) in enumerate(zip(snapshot.candles, stressed_path)):
        stressed_close = float(stressed_close_raw)
        if stressed_close <= 0.0:
            return snapshot
        scale = stressed_close / max(float(candle.close), 1e-9)
        stressed_open = max(float(candle.open) * scale, 1e-9)
        stressed_high = max(float(candle.high) * scale, stressed_open, stressed_close)
        stressed_low = min(float(candle.low) * scale, stressed_open, stressed_close)
        stressed_candles.append(
            Candle(
                timestamp=candle.timestamp,
                open=round(stressed_open, 8),
                high=round(stressed_high, 8),
                low=round(max(stressed_low, 1e-9), 8),
                close=round(stressed_close, 8),
                volume=candle.volume,
            )
        )

    return clone_snapshot(
        snapshot,
        snapshot_id=f"{snapshot.snapshot_id}:calibrated:{scenario_name}",
        candles=stressed_candles,
        provenance_updates={
            "transformation": "scenario_calibration",
            "scenario_name": scenario_name,
        },
    )


def _snapshot_with_stressed_microstructure(
    snapshot: DataSnapshot,
    scenario: StressScenario,
    *,
    scenario_name: str,
) -> DataSnapshot:
    spread_multiplier = max(float(scenario.spread_multiplier), 0.0)
    depth_multiplier = max(float(scenario.depth_multiplier), 0.0)
    latency_multiplier = max(float(scenario.latency_multiplier), 0.0)
    if (
        spread_multiplier == 1.0
        and depth_multiplier == 1.0
        and latency_multiplier == 1.0
    ):
        return snapshot
    if not (
        snapshot.spread_bps
        and snapshot.depth_bid_1bp_usd
        and snapshot.depth_ask_1bp_usd
        and snapshot.latency_proxy_ms
    ):
        return snapshot

    stressed_spread = [round(max(0.0, float(value) * spread_multiplier), 8) for value in snapshot.spread_bps]
    stressed_bid_depth = [
        round(max(0.0, float(value) * depth_multiplier), 8)
        for value in snapshot.depth_bid_1bp_usd
    ]
    stressed_ask_depth = [
        round(max(0.0, float(value) * depth_multiplier), 8)
        for value in snapshot.depth_ask_1bp_usd
    ]
    stressed_latency = [
        round(max(0.0, float(value) * latency_multiplier), 8)
        for value in snapshot.latency_proxy_ms
    ]
    return clone_snapshot(
        snapshot,
        snapshot_id=(
            snapshot.snapshot_id
            if snapshot.snapshot_id.endswith(f":microstructure:{scenario_name}")
            else f"{snapshot.snapshot_id}:microstructure:{scenario_name}"
        ),
        spread_bps=stressed_spread,
        depth_bid_1bp_usd=stressed_bid_depth,
        depth_ask_1bp_usd=stressed_ask_depth,
        latency_proxy_ms=stressed_latency,
        provenance_updates={
            "transformation": "scenario_microstructure_stress",
            "scenario_name": scenario_name,
            "spread_multiplier": spread_multiplier,
            "depth_multiplier": depth_multiplier,
            "latency_multiplier": latency_multiplier,
        },
    )


def _snapshot_with_mark_index_dislocation(
    snapshot: DataSnapshot,
    scenario: StressScenario,
    *,
    scenario_name: str,
) -> DataSnapshot:
    summary = _scenario_dislocation_summary(scenario)
    if not summary:
        return snapshot
    return clone_snapshot(
        snapshot,
        snapshot_id=(
            snapshot.snapshot_id
            if snapshot.snapshot_id.endswith(f":dislocation:{scenario_name}")
            else f"{snapshot.snapshot_id}:dislocation:{scenario_name}"
        ),
        provenance_updates={
            "transformation": "scenario_mark_index_dislocation",
            "scenario_name": scenario_name,
            "dislocation_summary": summary,
        },
    )


def _snapshot_with_scenario_execution_overlay_summary(
    snapshot: DataSnapshot,
    scenario: StressScenario,
    *,
    scenario_name: str,
) -> DataSnapshot:
    summary = _scenario_execution_overlay_summary(scenario)
    if not summary:
        return snapshot
    summary["scenario_name"] = scenario_name
    return clone_snapshot(
        snapshot,
        snapshot_id=snapshot.snapshot_id,
        provenance_updates={
            "scenario_execution_overlay": summary,
        },
    )


def _scenario_dislocation_summary(scenario: StressScenario) -> dict[str, float | int]:
    summary = {
        "mark_premium_bps": round(max(0.0, float(scenario.mark_premium_bps)), 6),
        "index_basis_bps": round(max(0.0, float(scenario.index_basis_bps)), 6),
        "premium_spike_bars": max(0, int(scenario.premium_spike_bars)),
    }
    if not any(summary.values()):
        return {}
    return summary


def _scenario_dislocation_premium_bps(scenario: StressScenario) -> float:
    summary = _scenario_dislocation_summary(scenario)
    if not summary:
        return 0.0
    spike_bonus_bps = min(int(summary["premium_spike_bars"]), 6) * 10.0
    return float(summary["mark_premium_bps"]) + float(summary["index_basis_bps"]) + spike_bonus_bps


def _scenario_dislocation_liquidity_penalty_bps(scenario: StressScenario) -> float:
    summary = _scenario_dislocation_summary(scenario)
    if not summary:
        return 0.0
    basis_component = float(summary["index_basis_bps"]) * 0.1
    spike_component = min(int(summary["premium_spike_bars"]), 6) * 2.0
    return min(40.0, basis_component + spike_component)


def _snapshot_dislocation_summary(snapshot: DataSnapshot) -> dict[str, float | int]:
    provenance = getattr(snapshot, "provenance", {}) or {}
    summary = provenance.get("dislocation_summary")
    if not isinstance(summary, dict):
        return {}
    normalized = {
        "mark_premium_bps": round(max(0.0, float(summary.get("mark_premium_bps", 0.0))), 6),
        "index_basis_bps": round(max(0.0, float(summary.get("index_basis_bps", 0.0))), 6),
        "premium_spike_bars": max(0, int(summary.get("premium_spike_bars", 0))),
    }
    if not any(normalized.values()):
        return {}
    return normalized


def _snapshot_dislocation_premium_bps(snapshot: DataSnapshot) -> float:
    summary = _snapshot_dislocation_summary(snapshot)
    if not summary:
        return 0.0
    spike_bonus_bps = min(int(summary["premium_spike_bars"]), 6) * 10.0
    return float(summary["mark_premium_bps"]) + float(summary["index_basis_bps"]) + spike_bonus_bps


def _snapshot_dislocation_liquidity_penalty_bps(snapshot: DataSnapshot) -> float:
    summary = _snapshot_dislocation_summary(snapshot)
    if not summary:
        return 0.0
    basis_component = float(summary["index_basis_bps"]) * 0.1
    spike_component = min(int(summary["premium_spike_bars"]), 6) * 2.0
    return min(40.0, basis_component + spike_component)


def _scenario_execution_overlay_summary(scenario: StressScenario) -> dict[str, float | int | str]:
    summary = {
        "scenario_name": str(scenario.name),
        "liquidity_penalty_bps": round(max(0.0, float(scenario.liquidity_penalty_bps)), 6),
        "latency_delta_bars": max(0, int(scenario.latency_delta_bars)),
    }
    if (
        summary["liquidity_penalty_bps"] == 0.0
        and summary["latency_delta_bars"] == 0
    ):
        return {}
    return summary


def _snapshot_execution_overlay_summary(snapshot: DataSnapshot) -> dict[str, float | int | str]:
    provenance = getattr(snapshot, "provenance", {}) or {}
    summary = provenance.get("scenario_execution_overlay")
    if not isinstance(summary, dict):
        return {}
    normalized = {
        "scenario_name": str(summary.get("scenario_name", "")),
        "liquidity_penalty_bps": round(max(0.0, float(summary.get("liquidity_penalty_bps", 0.0))), 6),
        "latency_delta_bars": max(0, int(summary.get("latency_delta_bars", 0))),
    }
    if normalized["liquidity_penalty_bps"] == 0.0 and normalized["latency_delta_bars"] == 0:
        return {}
    return normalized


def _snapshot_execution_overlay_liquidity_penalty_bps(snapshot: DataSnapshot) -> float:
    summary = _snapshot_execution_overlay_summary(snapshot)
    return float(summary.get("liquidity_penalty_bps", 0.0)) if summary else 0.0


def _snapshot_execution_overlay_latency_delta_bars(snapshot: DataSnapshot) -> int:
    summary = _snapshot_execution_overlay_summary(snapshot)
    return int(summary.get("latency_delta_bars", 0)) if summary else 0


def _resolve_batch_execution_overlays(
    snapshot: DataSnapshot,
    *,
    slippage_bps: float,
    latency_bars: int,
    liquidation_mark_premium_bps: float,
) -> tuple[float, int, float]:
    adjusted_slippage_bps = (
        slippage_bps
        + _snapshot_execution_overlay_liquidity_penalty_bps(snapshot)
        + _snapshot_dislocation_liquidity_penalty_bps(snapshot)
    )
    adjusted_latency_bars = max(
        0,
        latency_bars + _snapshot_execution_overlay_latency_delta_bars(snapshot),
    )
    adjusted_liquidation_mark_premium_bps = (
        liquidation_mark_premium_bps + _snapshot_dislocation_premium_bps(snapshot)
    )
    return (
        adjusted_slippage_bps,
        adjusted_latency_bars,
        adjusted_liquidation_mark_premium_bps,
    )


def _compute_calibration_from_snapshot(
    snapshot: "DataSnapshot",  # noqa: F821
) -> "tuple | None":
    """Compute (HawkesParams, JumpDiffusionParams, oi_concentration) from snapshot.

    Returns None when numpy is unavailable or the snapshot is too thin for a
    meaningful fit (fewer than 10 candles).  The result is intentionally not
    cached so callers can pass in any snapshot without stale state concerns.
    """
    try:
        from engine.validation.hawkes import (
            compute_oi_concentration,
            fit_hawkes_intensity,
        )
        from engine.validation.jump_diffusion import (
            estimate_jump_params,
            extract_returns_from_snapshot,
        )
    except ImportError:
        return None

    candles = snapshot.candles
    if len(candles) < 10:
        return None
    if any(str(flag).startswith("missing_liquidation_notional_count=") for flag in snapshot.quality_flags):
        return None

    # Liquidation event times: bar indices where liquidation_notional > 0
    liq_notional = snapshot.liquidation_notional
    event_times: list[float] = []
    event_sizes: list[float] = []
    for i, notional in enumerate(liq_notional):
        if notional > 0.0:
            event_times.append(float(i))
            event_sizes.append(float(notional))

    hawkes_params = fit_hawkes_intensity(event_times, event_sizes)

    log_returns = extract_returns_from_snapshot(candles)
    jump_params = estimate_jump_params(log_returns)

    oi_concentration = compute_oi_concentration(snapshot.open_interest)

    return hawkes_params, jump_params, oi_concentration


def _bootstrap_strategy(snapshot: DataSnapshot, strategy: StrategyGraph) -> BootstrapReport:
    profits: list[float] = []
    drawdowns: list[float] = []
    return _bootstrap_strategy_with_settings(
        snapshot,
        strategy,
        layer_parameters={},
        slippage_bps=5.0,
        latency_bars=0,
        position_side="long",
        position_leverage=1.0,
        maintenance_margin_ratio=0.01,
        liquidation_fee_bps=0.0,
        liquidation_mark_price_weight=0.0,
        partial_liquidation_ratio=1.0,
        liquidation_cooldown_bars=0,
        liquidation_step_schedule=[],
        liquidation_mark_premium_bps=0.0,
        maintenance_margin_schedule=[],
        liquidation_fee_schedule=[],
        slippage_model="flat",
        bootstrap_samples=8,
        bootstrap_block_size=None,
        bootstrap_method="moving_block",
        bootstrap_spread_multiplier=1.0,
        bootstrap_depth_multiplier=1.0,
        bootstrap_latency_multiplier=1.0,
    )


def _bootstrap_strategy_with_settings(
    snapshot: DataSnapshot,
    strategy: StrategyGraph,
    layer_parameters: dict[str, dict[str, float | int]],
    slippage_bps: float,
    latency_bars: int,
    position_side: str,
    position_leverage: float,
    maintenance_margin_ratio: float,
    liquidation_fee_bps: float,
    liquidation_mark_price_weight: float,
    partial_liquidation_ratio: float,
    liquidation_cooldown_bars: int,
    liquidation_step_schedule: list[float],
    liquidation_mark_premium_bps: float,
    maintenance_margin_schedule: list[dict[str, float]],
    liquidation_fee_schedule: list[dict[str, float]],
    slippage_model: str,
    bootstrap_samples: int,
    bootstrap_block_size: int | None,
    bootstrap_method: str,
    bootstrap_spread_multiplier: float = 1.0,
    bootstrap_depth_multiplier: float = 1.0,
    bootstrap_latency_multiplier: float = 1.0,
) -> BootstrapReport:
    profits: list[float] = []
    drawdowns: list[float] = []
    regime_analyses: list[RegimeAnalysis] = []
    block_size = bootstrap_block_size or max(2, min(8, len(snapshot.candles) // 6))
    for seed in range(bootstrap_samples):
        if str(bootstrap_method) == "dependent_wild":
            resampled_snapshot = dependent_wild_bootstrap_snapshot(
                snapshot,
                block_size=block_size,
                seed=seed,
            )
        else:
            bootstrap_indices = bootstrap_indices_for_method(
                method=bootstrap_method,
                sample_count=len(snapshot.candles),
                block_size=block_size,
                seed=seed,
            )
            resampled_snapshot = clone_snapshot_with_bootstrap_indices(
                snapshot,
                indices=bootstrap_indices,
                snapshot_id=f"{snapshot.snapshot_id}:bootstrap:{seed}",
                provenance_updates={
                    "transformation": "bootstrap",
                    "seed": seed,
                    "bootstrap_method": bootstrap_method,
                    "block_size": block_size,
                },
            )
        resampled_snapshot = _apply_bootstrap_microstructure_overlay(
            resampled_snapshot,
            spread_multiplier=bootstrap_spread_multiplier,
            depth_multiplier=bootstrap_depth_multiplier,
            latency_multiplier=bootstrap_latency_multiplier,
        )
        result = (
            _evaluate_strategy_with_settings(
                resampled_snapshot,
                strategy,
                layer_parameters=layer_parameters,
                slippage_bps=slippage_bps,
                latency_bars=latency_bars,
                position_side=position_side,
                position_leverage=position_leverage,
                maintenance_margin_ratio=maintenance_margin_ratio,
                liquidation_fee_bps=liquidation_fee_bps,
                liquidation_mark_price_weight=liquidation_mark_price_weight,
                partial_liquidation_ratio=partial_liquidation_ratio,
                liquidation_cooldown_bars=liquidation_cooldown_bars,
                liquidation_step_schedule=liquidation_step_schedule,
                liquidation_mark_premium_bps=liquidation_mark_premium_bps,
                maintenance_margin_schedule=maintenance_margin_schedule,
                liquidation_fee_schedule=liquidation_fee_schedule,
                slippage_model=slippage_model,
            )
            if len(resampled_snapshot.candles) >= 3
            else _evaluate_strategy_with_settings(
                snapshot,
                strategy,
                layer_parameters=layer_parameters,
                slippage_bps=slippage_bps,
                latency_bars=latency_bars,
                position_side=position_side,
                position_leverage=position_leverage,
                maintenance_margin_ratio=maintenance_margin_ratio,
                liquidation_fee_bps=liquidation_fee_bps,
                liquidation_mark_price_weight=liquidation_mark_price_weight,
                partial_liquidation_ratio=partial_liquidation_ratio,
                liquidation_cooldown_bars=liquidation_cooldown_bars,
                liquidation_step_schedule=liquidation_step_schedule,
                liquidation_mark_premium_bps=liquidation_mark_premium_bps,
                maintenance_margin_schedule=maintenance_margin_schedule,
                liquidation_fee_schedule=liquidation_fee_schedule,
                slippage_model=slippage_model,
            )
        )
        profits.append(result.net_pnl)
        drawdowns.append(result.max_drawdown)
        regime_analyses.append(analyze_regimes(resampled_snapshot))

    # Scale the drawdown threshold by leverage: at 1x, -25% requires a 25%
    # adverse move (severe crash).  At 10x, -25% is only a 2.5% move
    # (trivially common).  Dividing by leverage keeps the threshold
    # proportional to the actual price move risk.
    dd_threshold = -0.25 / max(position_leverage, 1.0)
    passed = sum(1 for drawdown in drawdowns if drawdown > dd_threshold)
    return BootstrapReport(
        sample_count=len(profits),
        median_net_profit=median(profits),
        median_max_drawdown=median(drawdowns),
        worst_case_net_profit=min(profits),
        worst_case_drawdown=min(drawdowns),
        pass_rate=passed / len(profits),
        bootstrap_method=bootstrap_method,
        block_size=block_size,
        bootstrap_microstructure_overlay=_bootstrap_microstructure_overlay_summary(
            spread_multiplier=bootstrap_spread_multiplier,
            depth_multiplier=bootstrap_depth_multiplier,
            latency_multiplier=bootstrap_latency_multiplier,
        ),
        bootstrap_regime_summary=_summarize_bootstrap_regimes(regime_analyses),
    )


def _bootstrap_microstructure_overlay_summary(
    *,
    spread_multiplier: float,
    depth_multiplier: float,
    latency_multiplier: float,
) -> dict[str, float]:
    if (
        float(spread_multiplier) == 1.0
        and float(depth_multiplier) == 1.0
        and float(latency_multiplier) == 1.0
    ):
        return {}
    return {
        "spread_multiplier": float(spread_multiplier),
        "depth_multiplier": float(depth_multiplier),
        "latency_multiplier": float(latency_multiplier),
    }


def _apply_bootstrap_microstructure_overlay(
    snapshot: DataSnapshot,
    *,
    spread_multiplier: float,
    depth_multiplier: float,
    latency_multiplier: float,
) -> DataSnapshot:
    overlay_summary = _bootstrap_microstructure_overlay_summary(
        spread_multiplier=spread_multiplier,
        depth_multiplier=depth_multiplier,
        latency_multiplier=latency_multiplier,
    )
    if not overlay_summary:
        return snapshot

    has_typed_microstructure = bool(
        snapshot.spread_bps
        or snapshot.depth_bid_1bp_usd
        or snapshot.depth_ask_1bp_usd
        or snapshot.latency_proxy_ms
    )
    if not has_typed_microstructure:
        return snapshot

    next_snapshot_id = f"{snapshot.snapshot_id}:microstructure_overlay"
    return clone_snapshot(
        snapshot,
        snapshot_id=next_snapshot_id,
        spread_bps=[round(max(0.0, float(value) * float(spread_multiplier)), 8) for value in snapshot.spread_bps],
        depth_bid_1bp_usd=[round(max(0.0, float(value) * float(depth_multiplier)), 8) for value in snapshot.depth_bid_1bp_usd],
        depth_ask_1bp_usd=[round(max(0.0, float(value) * float(depth_multiplier)), 8) for value in snapshot.depth_ask_1bp_usd],
        latency_proxy_ms=[round(max(0.0, float(value) * float(latency_multiplier)), 8) for value in snapshot.latency_proxy_ms],
        provenance_updates={
            "bootstrap_microstructure_overlay_applied": True,
            "bootstrap_spread_multiplier": float(spread_multiplier),
            "bootstrap_depth_multiplier": float(depth_multiplier),
            "bootstrap_latency_multiplier": float(latency_multiplier),
        },
    )


def _summarize_bootstrap_regimes(regime_analyses: list[RegimeAnalysis]) -> dict[str, object]:
    if not regime_analyses:
        return {
            "sample_count": 0,
            "average_regime_coverage": {},
            "crisis_sample_frequency": {},
            "dominant_regimes": [],
        }

    sample_count = len(regime_analyses)
    coverage_totals: dict[str, float] = defaultdict(float)
    crisis_presence_totals: dict[str, float] = defaultdict(float)
    dominant_regime_counts: dict[str, int] = defaultdict(int)

    for analysis in regime_analyses:
        for label, coverage in analysis.regime_coverage.items():
            coverage_totals[str(label)] += float(coverage)
        for label, coverage in analysis.crisis_window_coverage.items():
            if float(coverage) > 0.0:
                crisis_presence_totals[str(label)] += 1.0
        if analysis.regime_coverage:
            dominant_label = max(
                analysis.regime_coverage.items(),
                key=lambda item: (float(item[1]), str(item[0])),
            )[0]
            dominant_regime_counts[str(dominant_label)] += 1

    average_regime_coverage = {
        label: total / sample_count
        for label, total in sorted(coverage_totals.items())
    }
    crisis_sample_frequency = {
        label: total / sample_count
        for label, total in sorted(crisis_presence_totals.items())
    }
    dominant_regimes = [
        label
        for label, _count in sorted(
            dominant_regime_counts.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )
    ]
    return {
        "sample_count": sample_count,
        "average_regime_coverage": average_regime_coverage,
        "crisis_sample_frequency": crisis_sample_frequency,
        "dominant_regimes": dominant_regimes,
    }


def _get_layer_parameter(
    layer_parameters: dict[str, dict[str, float | int]],
    layer_name: str,
    key: str,
    default: float | int,
) -> float | int:
    return layer_parameters.get(layer_name, {}).get(key, default)


def _merge_layer_parameters(
    base_layer_parameters: dict[str, dict[str, float | int]],
    layer_name: str,
    parameter_set: dict[str, float | int],
) -> dict[str, dict[str, float | int]]:
    merged = {name: dict(values) for name, values in base_layer_parameters.items()}
    merged.setdefault(layer_name, {})
    merged[layer_name].update(parameter_set)
    return merged


def _parameter_grid_to_optuna_ranges(parameter_grid: dict) -> dict[str, dict[str, float | int]]:
    return {
        name: {
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "step": spec.step,
        }
        for name, spec in parameter_grid.items()
    }


def _build_search_seed_evidence(
    *,
    study: StudyConfig,
    layer_name: str,
    search_mode: str,
    source: str,
    regime_coverage: dict[str, float] | None = None,
) -> dict[str, object]:
    dominant_regime = None
    if regime_coverage:
        dominant_regime = max(
            regime_coverage.items(),
            key=lambda item: (float(item[1]), str(item[0])),
        )[0]
    return {
        "source": source,
        "search_mode": search_mode,
        "layer_name": layer_name,
        "symbol": study.snapshot.symbol,
        "venue": study.snapshot.venue,
        "regime_label": str(dominant_regime) if dominant_regime is not None else None,
        "scenario_names": [scenario.name for scenario in study.scenarios],
        "seed_count": 0,
        "seed_run_ids": [],
        "regime_similarity": {
            "dominant_regime": str(dominant_regime) if dominant_regime is not None else None,
            "candidate_matches": [],
        },
    }


def _annotate_candidate_trial(
    candidate: dict[str, object],
    *,
    search_source: str,
    seed_evidence: dict[str, object],
) -> dict[str, object]:
    annotated = dict(candidate)
    annotated.setdefault("parameters", {})
    annotated["search_source"] = search_source
    annotated["seed_evidence"] = dict(seed_evidence)
    regime_similarity = seed_evidence.get("regime_similarity")
    if isinstance(regime_similarity, dict):
        annotated["regime_similarity"] = dict(regime_similarity)
    return annotated


def _resolve_optuna_warm_start_context(
    study: StudyConfig,
    layer_name: str,
) -> tuple[list[dict[str, float | int]], dict[str, object]]:
    regime_analysis = analyze_regimes(study.snapshot)
    dominant_regime = None
    if regime_analysis.regime_coverage:
        dominant_regime = max(
            regime_analysis.regime_coverage.items(),
            key=lambda item: (float(item[1]), str(item[0])),
        )[0]
    evidence = _build_search_seed_evidence(
        study=study,
        layer_name=layer_name,
        search_mode="optuna",
        source="bayesian_memory_unavailable",
        regime_coverage=regime_analysis.regime_coverage,
    )
    memory_db_path = study.research_lineage.get("memory_db_path")
    if not isinstance(memory_db_path, str) or not memory_db_path:
        return [], evidence
    seed_candidates = query_bayesian_seed_trials(
        Path(memory_db_path),
        layer_name=layer_name,
        symbol=study.snapshot.symbol,
        venue=study.snapshot.venue,
        regime_label=str(dominant_regime) if dominant_regime is not None else None,
        scenario_names=[scenario.name for scenario in study.scenarios],
        limit=study.runtime_settings.optuna_warm_start_trials,
    )
    warm_start_trials = [
        dict(candidate["parameters"])
        for candidate in seed_candidates
        if isinstance(candidate, dict) and isinstance(candidate.get("parameters"), dict)
    ]
    evidence["source"] = "bayesian_memory" if warm_start_trials else "bayesian_memory_empty"
    evidence["memory_db_path"] = memory_db_path
    evidence["seed_count"] = len(warm_start_trials)
    evidence["seed_run_ids"] = [
        str(candidate.get("run_id"))
        for candidate in seed_candidates
        if isinstance(candidate, dict) and candidate.get("run_id") not in (None, "")
    ]
    evidence["regime_similarity"] = {
        "dominant_regime": str(dominant_regime) if dominant_regime is not None else None,
        "candidate_matches": [
            {
                "run_id": str(candidate.get("run_id")),
                "rank_score": float(candidate.get("rank_score", 0.0)),
                "selection_oos_sharpe": float(candidate.get("selection_oos_sharpe", 0.0)),
                "match_details": dict(candidate.get("match_details", {}))
                if isinstance(candidate.get("match_details"), dict)
                else {},
            }
            for candidate in seed_candidates
            if isinstance(candidate, dict)
        ],
    }
    return warm_start_trials, evidence


def _score_parameter_set_for_optuna(
    *,
    study: StudyConfig,
    split_pack,
    candidate_strategy: StrategyGraph,
    layer_name: str,
    parameter_set: dict[str, float | int],
    pruner: Callable[[int, float], bool] | None = None,
    out_returns: list[list[float]] | None = None,
) -> dict[str, float]:
    candidate_train = _evaluate_strategy_with_settings(
        split_pack.in_sample.snapshot,
        candidate_strategy,
        layer_parameters=_merge_layer_parameters(study.layer_parameters, layer_name, parameter_set),
        slippage_bps=study.runtime_settings.slippage_bps,
        latency_bars=study.runtime_settings.latency_bars,
        position_side=study.runtime_settings.position_side,
        position_leverage=study.runtime_settings.position_leverage,
        maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
        liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
        liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
        partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
        liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
        liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
        liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
        maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
        liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
        slippage_model=study.runtime_settings.slippage_model,
    )
    train_returns = [
        candidate_train.equity_curve[index] - candidate_train.equity_curve[index - 1]
        for index in range(1, len(candidate_train.equity_curve))
    ]
    train_score = (
        compute_deflated_sharpe_ratio(
            train_returns,
            trial_count=max(1, study.runtime_settings.optuna_trial_budget),
        )
        if train_returns
        else candidate_train.sharpe
    )
    
    if pruner is not None:
        pruner(0, float(train_score))

    merged_layer_parameters = _merge_layer_parameters(study.layer_parameters, layer_name, parameter_set)
    candidate_oos = _evaluate_strategy_with_settings(
        split_pack.selection_oos.snapshot,
        candidate_strategy,
        layer_parameters=merged_layer_parameters,
        slippage_bps=study.runtime_settings.slippage_bps,
        latency_bars=study.runtime_settings.latency_bars,
        position_side=study.runtime_settings.position_side,
        position_leverage=study.runtime_settings.position_leverage,
        maintenance_margin_ratio=study.runtime_settings.maintenance_margin_ratio,
        liquidation_fee_bps=study.runtime_settings.liquidation_fee_bps,
        liquidation_mark_price_weight=study.runtime_settings.liquidation_mark_price_weight,
        partial_liquidation_ratio=study.runtime_settings.partial_liquidation_ratio,
        liquidation_cooldown_bars=study.runtime_settings.liquidation_cooldown_bars,
        liquidation_step_schedule=study.runtime_settings.liquidation_step_schedule,
        liquidation_mark_premium_bps=study.runtime_settings.liquidation_mark_premium_bps,
        maintenance_margin_schedule=study.runtime_settings.maintenance_margin_schedule,
        liquidation_fee_schedule=study.runtime_settings.liquidation_fee_schedule,
        slippage_model=study.runtime_settings.slippage_model,
    )
    equity_returns = [
        candidate_oos.equity_curve[index] - candidate_oos.equity_curve[index - 1]
        for index in range(1, len(candidate_oos.equity_curve))
    ]
    if equity_returns:
        if out_returns is not None:
            out_returns.append(equity_returns)
        score = compute_deflated_sharpe_ratio(
            equity_returns,
            trial_count=max(1, study.runtime_settings.optuna_trial_budget),
        )
    else:
        score = candidate_oos.sharpe
    return {
        "score": float(score),
        "train_score": float(train_score),
        "oos_sharpe": float(candidate_oos.sharpe),
        "oos_net_pnl": float(candidate_oos.net_pnl),
    }


def _decision_rank(decision: str) -> int:
    if decision == "accept":
        return 2
    if decision == "wash":
        return 1
    return 0


def _is_better_candidate(candidate: CandidateEvaluation, incumbent: CandidateEvaluation) -> bool:
    candidate_rank = _decision_rank(candidate.decision.decision)
    incumbent_rank = _decision_rank(incumbent.decision.decision)
    if candidate_rank != incumbent_rank:
        return candidate_rank > incumbent_rank
    if candidate.oos_result.sharpe != incumbent.oos_result.sharpe:
        return candidate.oos_result.sharpe > incumbent.oos_result.sharpe
    if candidate.bootstrap_report.worst_case_drawdown != incumbent.bootstrap_report.worst_case_drawdown:
        # worst_case_drawdown is negative (e.g. -0.15).  Higher (closer to 0)
        # = shallower drawdown = less tail risk.  When Sharpe is tied, prefer
        # the candidate with less severe worst-case drawdown (conservative).
        return candidate.bootstrap_report.worst_case_drawdown > incumbent.bootstrap_report.worst_case_drawdown
    return candidate.oos_result.net_pnl > incumbent.oos_result.net_pnl


def _snapshot_has_typed_microstructure(snapshot: DataSnapshot) -> bool:
    return bool(
        getattr(snapshot, "spread_bps", [])
        and getattr(snapshot, "depth_bid_1bp_usd", [])
        and getattr(snapshot, "depth_ask_1bp_usd", [])
        and getattr(snapshot, "latency_proxy_ms", [])
    )


def _snapshot_supports_realistic_batch_sim(snapshot: DataSnapshot) -> bool:
    return _snapshot_has_typed_microstructure(snapshot)


# ---------------------------------------------------------------------------
# Phase 11 — Numba batch sweep helper
# ---------------------------------------------------------------------------

def _run_grid_with_batch_sim(
    in_sample_snapshot: DataSnapshot,
    oos_snapshot: DataSnapshot,
    candidate_strategy: StrategyGraph,
    parameter_sets: list[dict],
    layer_name: str,
    base_layer_parameters: dict[str, dict[str, float | int]],
    position_side: str,
    position_leverage: float,
    maintenance_margin_ratio: float,
    liquidation_fee_bps: float,
    liquidation_mark_price_weight: float,
    liquidation_mark_premium_bps: float,
    maintenance_margin_schedule: list[dict[str, float]],
    liquidation_fee_schedule: list[dict[str, float]],
    taker_fee_bps: float,
    slippage_bps: float,
    latency_bars: int,
    slippage_model: str,
) -> BatchGridResult:
    """Pre-build signal matrices for all parameter sets and run a single JIT batch.

    Returns two dicts keyed by parameter-set index:
        train_results[i] -> BacktestResult for in-sample split
        oos_results[i]   -> BacktestResult for OOS split

    On any error returns two empty dicts — callers fall back to sequential evaluation.
    """
    telemetry = _build_batch_simulator_metadata(
        attempted=True,
        parameter_set_count=len(parameter_sets),
        fallback_reason=None,
        fallback_count=0,
        numba_used=False,
    )
    try:
        train_closes = [c.close for c in in_sample_snapshot.candles]
        train_highs = [c.high for c in in_sample_snapshot.candles]
        train_lows = [c.low for c in in_sample_snapshot.candles]
        train_funding = in_sample_snapshot.funding_rates
        train_funding_event_counts = _compute_funding_event_counts(in_sample_snapshot.candles, in_sample_snapshot.venue)
        train_open_interest = in_sample_snapshot.open_interest
        train_liquidation = in_sample_snapshot.liquidation_notional
        train_spread = getattr(in_sample_snapshot, "spread_bps", [])
        train_depth_bid = getattr(in_sample_snapshot, "depth_bid_1bp_usd", [])
        train_depth_ask = getattr(in_sample_snapshot, "depth_ask_1bp_usd", [])
        train_latency_proxy = getattr(in_sample_snapshot, "latency_proxy_ms", [])
        oos_closes = [c.close for c in oos_snapshot.candles]
        oos_highs = [c.high for c in oos_snapshot.candles]
        oos_lows = [c.low for c in oos_snapshot.candles]
        oos_funding = oos_snapshot.funding_rates
        oos_funding_event_counts = _compute_funding_event_counts(oos_snapshot.candles, oos_snapshot.venue)
        oos_open_interest = oos_snapshot.open_interest
        oos_liquidation = oos_snapshot.liquidation_notional
        oos_spread = getattr(oos_snapshot, "spread_bps", [])
        oos_depth_bid = getattr(oos_snapshot, "depth_bid_1bp_usd", [])
        oos_depth_ask = getattr(oos_snapshot, "depth_ask_1bp_usd", [])
        oos_latency_proxy = getattr(oos_snapshot, "latency_proxy_ms", [])

        if len(train_closes) < 3 or len(oos_closes) < 3:
            return BatchGridResult(
                {},
                {},
                _build_batch_simulator_metadata(
                    attempted=True,
                    parameter_set_count=len(parameter_sets),
                    fallback_reason="insufficient_split_length",
                    fallback_count=1,
                    numba_used=False,
                ),
            )

        train_signal_matrix: list[tuple[list[bool], list[bool]]] = []
        oos_signal_matrix: list[tuple[list[bool], list[bool]]] = []

        for parameter_set in parameter_sets:
            merged = _merge_layer_parameters(base_layer_parameters, layer_name, parameter_set)
            t_entry, t_exit = _build_signals(in_sample_snapshot, candidate_strategy, merged, position_side)
            o_entry, o_exit = _build_signals(oos_snapshot, candidate_strategy, merged, position_side)
            train_signal_matrix.append((t_entry, t_exit))
            oos_signal_matrix.append((o_entry, o_exit))

        n_sets = len(parameter_sets)
        (
            train_slippage_bps,
            train_latency_bars,
            train_liquidation_mark_premium_bps,
        ) = _resolve_batch_execution_overlays(
            in_sample_snapshot,
            slippage_bps=slippage_bps,
            latency_bars=latency_bars,
            liquidation_mark_premium_bps=liquidation_mark_premium_bps,
        )
        (
            oos_slippage_bps,
            oos_latency_bars,
            oos_liquidation_mark_premium_bps,
        ) = _resolve_batch_execution_overlays(
            oos_snapshot,
            slippage_bps=slippage_bps,
            latency_bars=latency_bars,
            liquidation_mark_premium_bps=liquidation_mark_premium_bps,
        )
        train_slippage_list = [train_slippage_bps] * n_sets
        oos_slippage_list = [oos_slippage_bps] * n_sets
        train_latency_list = [train_latency_bars] * n_sets
        oos_latency_list = [oos_latency_bars] * n_sets
        from engine.validation.regimes import label_snapshot_regimes
        train_regimes = label_snapshot_regimes(in_sample_snapshot)
        oos_regimes = label_snapshot_regimes(oos_snapshot)

        train_telemetry: dict[str, object] = {}
        oos_telemetry: dict[str, object] = {}
        batch_train = simulate_strategy_batch(
            closes=train_closes,
            highs=train_highs,
            lows=train_lows,
            funding_rates=train_funding,
            open_interest=train_open_interest,
            liquidation_notional=train_liquidation,
            spread_bps=train_spread,
            depth_bid_1bp_usd=train_depth_bid,
            depth_ask_1bp_usd=train_depth_ask,
            latency_proxy_ms=train_latency_proxy,
            stress_regimes=train_regimes,
            funding_event_counts=train_funding_event_counts,
            signal_matrix=train_signal_matrix,
            taker_fee_bps=taker_fee_bps,
            param_slippage_bps=train_slippage_list,
            param_latency_bars=train_latency_list,
            position_side=position_side,
            position_leverage=position_leverage,
            maintenance_margin_ratio=maintenance_margin_ratio,
            liquidation_fee_bps=liquidation_fee_bps,
            liquidation_mark_price_weight=liquidation_mark_price_weight,
            liquidation_mark_premium_bps=train_liquidation_mark_premium_bps,
            maintenance_margin_schedule=maintenance_margin_schedule,
            liquidation_fee_schedule=liquidation_fee_schedule,
            slippage_model=slippage_model,
            telemetry_sink=train_telemetry,
        )
        batch_oos = simulate_strategy_batch(
            closes=oos_closes,
            highs=oos_highs,
            lows=oos_lows,
            funding_rates=oos_funding,
            open_interest=oos_open_interest,
            liquidation_notional=oos_liquidation,
            spread_bps=oos_spread,
            depth_bid_1bp_usd=oos_depth_bid,
            depth_ask_1bp_usd=oos_depth_ask,
            latency_proxy_ms=oos_latency_proxy,
            stress_regimes=oos_regimes,
            funding_event_counts=oos_funding_event_counts,
            signal_matrix=oos_signal_matrix,
            taker_fee_bps=taker_fee_bps,
            param_slippage_bps=oos_slippage_list,
            param_latency_bars=oos_latency_list,
            position_side=position_side,
            position_leverage=position_leverage,
            maintenance_margin_ratio=maintenance_margin_ratio,
            liquidation_fee_bps=liquidation_fee_bps,
            liquidation_mark_price_weight=liquidation_mark_price_weight,
            liquidation_mark_premium_bps=oos_liquidation_mark_premium_bps,
            maintenance_margin_schedule=maintenance_margin_schedule,
            liquidation_fee_schedule=liquidation_fee_schedule,
            slippage_model=slippage_model,
            telemetry_sink=oos_telemetry,
        )

        def _to_backtest_result(r: BatchSimResult, snap: DataSnapshot) -> BacktestResult:
            from engine.backtest.risk import max_drawdown, sharpe_ratio, sortino_ratio
            returns = [
                r.equity_curve[i] - r.equity_curve[i - 1]
                for i in range(1, len(r.equity_curve))
            ]
            raw = BacktestResult(
                trade_count=r.trade_count,
                win_rate=r.win_rate,
                gross_pnl=r.gross_pnl,
                net_pnl=r.net_pnl,
                fee_spend=r.fee_spend,
                funding_spend=r.funding_spend,
                sharpe=sharpe_ratio(returns),
                sortino=sortino_ratio(returns),
                max_drawdown=max_drawdown(r.equity_curve),
                equity_curve=r.equity_curve,
                liquidation_events=[],
                execution_pressure_summary=dict(r.execution_pressure_summary or {}),
            )
            return _normalize_result(raw, snap)

        train_results = {i: _to_backtest_result(batch_train[i], in_sample_snapshot) for i in range(n_sets)}
        oos_results = {i: _to_backtest_result(batch_oos[i], oos_snapshot) for i in range(n_sets)}
        return BatchGridResult(
            train_results,
            oos_results,
            _merge_batch_simulator_telemetry(
                parameter_set_count=len(parameter_sets),
                train_telemetry=train_telemetry,
                oos_telemetry=oos_telemetry,
            ),
        )

    except Exception as exc:
        _logger.warning("Batch sim grid sweep failed (%s); falling back to sequential", exc)
        telemetry["fallback_reason"] = str(exc)
        telemetry["fallback_count"] = 1
        return BatchGridResult({}, {}, telemetry)


def _build_batch_simulator_metadata(
    *,
    attempted: bool,
    parameter_set_count: int,
    fallback_reason: str | None,
    fallback_count: int,
    numba_used: bool,
    kernel_compile_ms: float | None = None,
    python_fallback_ms: float | None = None,
) -> dict[str, object]:
    return {
        "attempted": attempted,
        "parameter_set_count": int(parameter_set_count),
        "numba_used": bool(numba_used),
        "fallback_reason": fallback_reason,
        "fallback_count": int(fallback_count),
        "kernel_compile_ms": kernel_compile_ms,
        "python_fallback_ms": python_fallback_ms,
    }


def _merge_batch_simulator_telemetry(
    *,
    parameter_set_count: int,
    train_telemetry: dict[str, object],
    oos_telemetry: dict[str, object],
) -> dict[str, object]:
    telemetry_rows = [row for row in (train_telemetry, oos_telemetry) if row]
    fallback_reasons = [
        str(row.get("fallback_reason"))
        for row in telemetry_rows
        if row.get("fallback_reason") not in (None, "")
    ]
    fallback_count = sum(int(row.get("fallback_count") or 0) for row in telemetry_rows)
    numba_used = bool(telemetry_rows) and all(bool(row.get("numba_used")) for row in telemetry_rows)
    kernel_compile_values = [
        float(row["kernel_compile_ms"])
        for row in telemetry_rows
        if isinstance(row.get("kernel_compile_ms"), int | float)
    ]
    python_fallback_values = [
        float(row["python_fallback_ms"])
        for row in telemetry_rows
        if isinstance(row.get("python_fallback_ms"), int | float)
    ]
    return _build_batch_simulator_metadata(
        attempted=True,
        parameter_set_count=parameter_set_count,
        fallback_reason="; ".join(fallback_reasons) if fallback_reasons else None,
        fallback_count=fallback_count,
        numba_used=numba_used,
        kernel_compile_ms=round(sum(kernel_compile_values), 6) if kernel_compile_values else None,
        python_fallback_ms=round(sum(python_fallback_values), 6) if python_fallback_values else None,
    )
