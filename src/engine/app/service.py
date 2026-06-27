from __future__ import annotations

from dataclasses import replace
import json
import logging
from pathlib import Path
from typing import Callable

from engine.app.runtime import _derive_stress_metrics, _resolve_scenario_runtime_inputs
from engine.config.models import (
    BacktestResult,
    DataSnapshot,
    LayerSpec,
    ResearchCycleExecution,
    StrategyGraph,
)
from engine.io.artifacts import write_json_atomic
from engine.optimizer.phases import Evaluator, OvernightRunner, ValidationExecutor
from engine.reporting.dashboard import build_dashboard_payload
from engine.reporting.runcards import build_runcard, save_runcard
from engine.validation.protocol import legacy_validation_protocol
from engine.validation.scenarios import DEFAULT_SCENARIOS, StressScenario, evaluate_scenarios
from engine.validation.splits import build_split_pack


ScenarioEvaluator = Callable[[StrategyGraph, StressScenario], BacktestResult]
logger = logging.getLogger(__name__)


def execute_research_cycle(
    run_id: str,
    snapshot: DataSnapshot,
    incumbent: StrategyGraph,
    directional_layers: list[LayerSpec],
    known_good_filters: list[LayerSpec],
    custom_filters: list[LayerSpec],
    exit_layers: list[LayerSpec],
    evaluator: Evaluator,
    scenario_evaluator: ScenarioEvaluator,
    output_dir: Path,
    seed: int,
    study_signature: str | None = None,
    runtime_settings: dict[str, object] | None = None,
    validation_executor: ValidationExecutor | None = None,
    scenarios: list[StressScenario] | None = None,
    agent_loop_metadata: dict[str, object] | None = None,
    research_program_version: str | None = None,
) -> ResearchCycleExecution:
    logger.info("Starting research cycle '%s' (seed=%s)", run_id, seed)

    runtime_settings = runtime_settings or {}
    split_pack = build_split_pack(
        snapshot,
        regime_model=str(runtime_settings.get("regime_model", "deterministic")),
        regime_n_states=int(runtime_settings.get("regime_n_states", 4)),
    )
    runner = OvernightRunner(snapshot=snapshot, evaluator=evaluator)
    report = runner.run_pipeline(
        incumbent=incumbent,
        directional_layers=directional_layers,
        known_good_filters=known_good_filters,
        custom_filters=custom_filters,
        exit_layers=exit_layers,
        validation_executor=validation_executor,
    )
    logger.info("Pipeline completed for '%s'", run_id)
    final_evaluation = report.final_evaluation
    if final_evaluation is None:
        raise ValueError("pipeline report did not include a final evaluation")

    scenario_list = list(scenarios or DEFAULT_SCENARIOS)
    active_runtime_inputs = {
        scenario.name: _resolve_scenario_runtime_inputs(
            split_pack.selection_oos.snapshot,
            scenario,
            seed=seed,
        )
        for scenario in scenario_list
    }
    active_scenarios = {
        scenario.name: active_runtime_inputs[scenario.name][1]
        for scenario in scenario_list
    }
    resolved_profiles = {
        scenario.name: _scenario_profile_dict(
            active_scenarios[scenario.name],
            active_runtime_inputs[scenario.name][0],
        )
        for scenario in scenario_list
    }
    scenario_results = {
        scenario.name: scenario_evaluator(report.final_strategy, scenario)
        for scenario in scenario_list
    }
    stress_metrics_by_name = {
        scenario.name: _derive_stress_metrics(
            baseline=final_evaluation.oos_result,
            stressed=scenario_results[scenario.name],
            scenario=active_scenarios[scenario.name],
            snapshot=split_pack.selection_oos.snapshot,
        )
        for scenario in scenario_list
    }
    scenario_report = evaluate_scenarios(
        scenario_list,
        scenario_results,
        resolved_profiles_by_name=resolved_profiles,
        stress_metrics_by_name=stress_metrics_by_name,
        position_leverage=float(runtime_settings.get("position_leverage", 1.0)),
    )
    scenario_report = replace(
        scenario_report,
        regime_scenario_pass_matrix=_build_regime_scenario_pass_matrix(split_pack, scenario_report.results),
    )
    validation_protocol = report.validation_protocol or legacy_validation_protocol(report.holdout_decision)
    holdout_decision = report.holdout_decision or validation_protocol.promotion_decision

    runcard = build_runcard(
        run_id=run_id,
        snapshot=snapshot,
        split_pack=split_pack,
        report=report,
        selection_oos_result=final_evaluation.oos_result,
        scenario_report=scenario_report,
        seed=seed,
        study_signature=study_signature,
        runtime_settings=runtime_settings,
        validation_protocol=validation_protocol,
        agent_loop_metadata=agent_loop_metadata,
    )

    dashboard_payload = build_dashboard_payload(
        runcard=runcard,
        split_pack=split_pack,
        selection_oos_result=final_evaluation.oos_result,
        bootstrap_report=final_evaluation.bootstrap_report,
        strategy=report.final_strategy,
        phase_records=report.phase_records,
        holdout_decision=holdout_decision,
        validation_protocol=validation_protocol,
        agent_loop_metadata=agent_loop_metadata,
        research_program_version=research_program_version,
    )
    dashboard_payload["scenarios"] = [
        {
            "scenario_name": result.scenario_name,
            "severity": result.severity,
            "passed": result.passed,
            "failure_reasons": list(result.failure_reasons),
            "sharpe": result.result.sharpe,
            "max_drawdown": result.result.max_drawdown,
            "execution_pressure_summary": dict(result.result.execution_pressure_summary or {}),
            "resolved_profile": dict(result.resolved_profile or {}),
            "stress_metrics": _stress_metrics_dict(result.stress_metrics),
        }
        for result in scenario_report.results
    ]
    dashboard_payload["stress_liquidity_metrics"] = dict(scenario_report.stress_liquidity_metrics)
    dashboard_payload["regime_scenario_pass_matrix"] = {
        regime: dict(results)
        for regime, results in scenario_report.regime_scenario_pass_matrix.items()
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    runcard_path = output_dir / f"{run_id}.runcard.json"
    dashboard_path = output_dir / f"{run_id}.dashboard.json"
    save_runcard(runcard_path, runcard)
    try:
        logger.info("Writing dashboard bundle for '%s'", run_id)
        write_json_atomic(dashboard_path, dashboard_payload)
    except Exception as e:
        logger.error("Failed to write dashboard for '%s': %s", run_id, e)
        raise

    logger.info("Completed research cycle '%s'", run_id)
    return ResearchCycleExecution(
        report=report,
        runcard=runcard,
        dashboard_payload=dashboard_payload,
        runcard_path=str(runcard_path),
        dashboard_path=str(dashboard_path),
    )


def _scenario_profile_dict(
    scenario: StressScenario,
    snapshot: DataSnapshot | None = None,
) -> dict[str, float | int | str | dict[str, float]]:
    profile: dict[str, float | int | str | dict[str, float]] = {
        "name": scenario.name,
        "severity": scenario.severity,
        "description": scenario.description,
        "calibration_mode": scenario.calibration_mode,
        "funding_multiplier": scenario.funding_multiplier,
        "liquidity_penalty_bps": scenario.liquidity_penalty_bps,
        "spread_multiplier": scenario.spread_multiplier,
        "depth_multiplier": scenario.depth_multiplier,
        "latency_multiplier": scenario.latency_multiplier,
        "latency_delta_bars": scenario.latency_delta_bars,
        "drawdown_multiplier": scenario.drawdown_multiplier,
        "mark_premium_bps": scenario.mark_premium_bps,
        "index_basis_bps": scenario.index_basis_bps,
        "premium_spike_bars": scenario.premium_spike_bars,
        "open_interest_multiplier": scenario.open_interest_multiplier,
        "liquidation_multiplier": scenario.liquidation_multiplier,
        "volatility_multiplier": scenario.volatility_multiplier,
        "target_regimes": list(scenario.target_regimes),
    }
    dislocation_summary = _scenario_dislocation_summary(scenario)
    if dislocation_summary:
        profile["dislocation_summary"] = dislocation_summary
    microstructure_summary = _scenario_microstructure_summary(snapshot)
    if microstructure_summary:
        profile["microstructure_summary"] = microstructure_summary
    return profile


def _scenario_dislocation_summary(scenario: StressScenario) -> dict[str, float | int]:
    summary = {
        "mark_premium_bps": round(max(0.0, float(scenario.mark_premium_bps)), 6),
        "index_basis_bps": round(max(0.0, float(scenario.index_basis_bps)), 6),
        "premium_spike_bars": max(0, int(scenario.premium_spike_bars)),
    }
    if not any(summary.values()):
        return {}
    return summary


def _scenario_microstructure_summary(snapshot: DataSnapshot | None) -> dict[str, float]:
    if snapshot is None:
        return {}
    if not (
        snapshot.spread_bps
        and snapshot.depth_bid_1bp_usd
        and snapshot.depth_ask_1bp_usd
        and snapshot.latency_proxy_ms
    ):
        return {}
    return {
        "spread_bps_mean": round(sum(snapshot.spread_bps) / len(snapshot.spread_bps), 6),
        "depth_bid_1bp_usd_mean": round(sum(snapshot.depth_bid_1bp_usd) / len(snapshot.depth_bid_1bp_usd), 6),
        "depth_ask_1bp_usd_mean": round(sum(snapshot.depth_ask_1bp_usd) / len(snapshot.depth_ask_1bp_usd), 6),
        "latency_proxy_ms_mean": round(sum(snapshot.latency_proxy_ms) / len(snapshot.latency_proxy_ms), 6),
    }


def _stress_metrics_dict(metrics) -> dict[str, float | int]:
    if metrics is None:
        return {}
    return {
        "stress_slippage_quantile": metrics.stress_slippage_quantile,
        "stress_tail_slippage": metrics.stress_tail_slippage,
        "liquidity_stress_score": metrics.liquidity_stress_score,
        "basis_stress_score": metrics.basis_stress_score,
        "cascade_liquidation_count": metrics.cascade_liquidation_count,
    }


def _build_regime_scenario_pass_matrix(split_pack, scenario_results) -> dict[str, dict[str, bool]]:
    matrix: dict[str, dict[str, bool]] = {}
    for result in scenario_results:
        profile = result.resolved_profile or {}
        raw_target_regimes = profile.get("target_regimes", ())
        if isinstance(raw_target_regimes, (list, tuple)):
            target_regimes = [str(item) for item in raw_target_regimes]
        else:
            target_regimes = []
        for regime_label in target_regimes:
            if split_pack.regime_coverage.get(regime_label, 0.0) <= 0.0:
                continue
            matrix.setdefault(regime_label, {})[result.scenario_name] = result.passed
    return matrix
