from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from engine.config.models import BacktestResult, DataSnapshot, OvernightRunReport, PromotionDecision, RunCard, SplitPack, ValidationProtocol
from engine.io.artifacts import write_json_atomic
from engine.validation.scenarios import ScenarioEvaluationReport
from engine.validation.protocol import legacy_validation_protocol, serialize_validation_protocol


def _compute_max_drawdown_amount(equity_curve: list[float]) -> float:
    peak: float | None = None
    max_amount = 0.0
    for value in equity_curve:
        equity = float(value)
        peak = equity if peak is None else max(peak, equity)
        max_amount = max(max_amount, peak - equity)
    return max_amount


def save_runcard(path: Path, runcard: RunCard) -> None:
    payload = asdict(runcard)
    write_json_atomic(path, payload)


def load_runcard(path: Path) -> RunCard:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["decision"] = PromotionDecision(**payload["decision"])
    return RunCard(**payload)


def _serialize_snapshot_quality_report(snapshot: DataSnapshot) -> dict[str, object]:
    if snapshot.quality_report is None:
        return {}
    return {
        "report_id": snapshot.quality_report.report_id,
        "snapshot_id": snapshot.quality_report.snapshot_id,
        "quality_score": snapshot.quality_report.quality_score,
        "passed": snapshot.quality_report.passed,
        "issues": list(snapshot.quality_report.issues),
        "metrics": dict(snapshot.quality_report.metrics),
        "source_checks": dict(snapshot.quality_report.source_checks),
        "generated_at": snapshot.quality_report.generated_at,
    }


def _effective_cost_model(snapshot: DataSnapshot, runtime_settings: dict[str, object] | None) -> dict[str, object]:
    settings = runtime_settings or {}
    venue_profile = snapshot.venue_profile
    maker_fee_bps = snapshot.maker_fee_bps
    taker_fee_bps = snapshot.taker_fee_bps
    source = "data_snapshot"
    venue_source = str(snapshot.provenance.get("provider", snapshot.venue))
    if venue_profile is not None and venue_profile.maker_fee_bps is not None and venue_profile.taker_fee_bps is not None:
        maker_fee_bps = float(venue_profile.maker_fee_bps)
        taker_fee_bps = float(venue_profile.taker_fee_bps)
        source = "venue_profile"
        venue_source = venue_profile.fee_schedule_source or venue_profile.venue
    return {
        "source": source,
        "venue_source": venue_source,
        "venue": snapshot.venue,
        "maker_fee_bps": float(maker_fee_bps),
        "taker_fee_bps": float(taker_fee_bps),
        "maker_fee_rate": round(float(maker_fee_bps) / 10_000.0, 12),
        "taker_fee_rate": round(float(taker_fee_bps) / 10_000.0, 12),
        "slippage_model": str(settings.get("slippage_model", "runtime_slippage_bps")),
        "slippage_bps": float(settings.get("slippage_bps", 0.0)),
    }


def build_runcard(
    run_id: str,
    snapshot: DataSnapshot,
    split_pack: SplitPack,
    report: OvernightRunReport,
    selection_oos_result: BacktestResult,
    scenario_report: ScenarioEvaluationReport,
    seed: int,
    study_signature: str | None = None,
    runtime_settings: dict[str, object] | None = None,
    validation_protocol: ValidationProtocol | None = None,
    agent_loop_metadata: dict[str, object] | None = None,
    forecast_governance: dict[str, object] | None = None,
) -> RunCard:
    accepted_layers = sum(1 for phase_record in report.phase_records if phase_record.accepted)
    split_id = (
        f"{snapshot.snapshot_id}:"
        f"{len(split_pack.in_sample.candles)}-"
        f"{len(split_pack.selection_oos.candles)}-"
        f"{len(split_pack.final_holdout.candles)}"
    )
    selected_parameters = {
        phase_record.layer_name: dict(phase_record.selected_parameters)
        for phase_record in report.phase_records
        if phase_record.accepted and phase_record.selected_parameters
    }
    parameter_search = {
        phase_record.layer_name: {
            "permutation_count": phase_record.permutation_count,
            "search_summary": list(phase_record.search_summary),
            **({"candidate_trials": list(phase_record.candidate_trials)} if phase_record.candidate_trials else {}),
        }
        for phase_record in report.phase_records
        if phase_record.accepted
        and (phase_record.permutation_count > 1 or phase_record.search_summary or phase_record.candidate_trials)
    }
    quality_flags = list(snapshot.quality_flags)
    quality_status = "dirty" if quality_flags else "clean"
    scenario_profiles = {
        result.scenario_name: dict(result.resolved_profile or {})
        for result in scenario_report.results
        if result.resolved_profile
    }
    bootstrap_report = report.final_evaluation.bootstrap_report if report.final_evaluation is not None else None
    regime_summary = {
        "regime_model": split_pack.regime_model,
        "regime_labels": list(split_pack.regime_labels),
        "regime_coverage": dict(split_pack.regime_coverage),
        "crisis_window_coverage": dict(split_pack.crisis_window_coverage),
        "regime_metadata": dict(split_pack.regime_metadata),
        "crisis_windows": [
            {
                "name": window.name,
                "regime_label": window.regime_label,
                "start_index": window.snapshot_window.start_index,
                "end_index": window.snapshot_window.end_index,
                "snapshot_id": window.snapshot_window.snapshot.snapshot_id,
            }
            for window in split_pack.crisis_windows
        ],
    }
    max_drawdown_amount = _compute_max_drawdown_amount(selection_oos_result.equity_curve)
    protocol = validation_protocol or report.validation_protocol or legacy_validation_protocol(report.holdout_decision)
    serialized_protocol = serialize_validation_protocol(protocol)
    validation_metrics = {
        "probabilistic_sharpe_ratio": protocol.probabilistic_sharpe_ratio,
        "deflated_sharpe_ratio": protocol.deflated_sharpe_ratio,
        "in_sample_permutation_pvalue": protocol.in_sample_permutation_pvalue,
        "walk_forward_permutation_pvalue": protocol.walk_forward_permutation_pvalue,
        "validation_trial_count": protocol.validation_trial_count,
    }
    stress_metrics = dict(scenario_report.stress_liquidity_metrics)
    snapshot_provenance = dict(snapshot.provenance)
    snapshot_quality_report = _serialize_snapshot_quality_report(snapshot)
    execution_pressure_summary = dict(selection_oos_result.execution_pressure_summary or {})
    effective_cost_model = _effective_cost_model(snapshot, runtime_settings)

    return RunCard(
        run_id=run_id,
        strategy_hash=report.final_strategy.strategy_hash,
        phase=report.phase_records[-1].phase_name if report.phase_records else "phase-1",
        split_id=split_id,
        seed=seed,
        decision=PromotionDecision(decision=report.status, reasons=report.holdout_decision.reasons if report.holdout_decision else []),
        metrics={
            "selection_oos_sharpe": selection_oos_result.sharpe,
            "selection_oos_net_pnl": selection_oos_result.net_pnl,
            "selection_oos_drawdown": selection_oos_result.max_drawdown,
            "selection_oos_drawdown_amount": max_drawdown_amount,
            "sortino_ratio": selection_oos_result.sortino,
            "total_trades": float(selection_oos_result.trade_count),
            "win_rate": selection_oos_result.win_rate,
            "scenario_pass_rate": scenario_report.pass_rate,
            "accepted_layers": float(accepted_layers),
            **{key: value for key, value in validation_metrics.items() if value is not None},
            **{key: value for key, value in stress_metrics.items() if isinstance(value, int | float)},
        },
        artifacts={
            "snapshot_id": snapshot.snapshot_id,
            "final_status": report.status,
            "symbol": snapshot.symbol,
            "venue": snapshot.venue,
            "snapshot_quality_status": quality_status,
            "snapshot_quality_flag_count": str(len(quality_flags)),
            "snapshot_quality_flags_json": json.dumps(quality_flags, sort_keys=True),
            "snapshot_quality_report_json": json.dumps(snapshot_quality_report, sort_keys=True),
            "snapshot_provenance_json": json.dumps(snapshot_provenance, sort_keys=True),
            "snapshot_build_version": str(snapshot_provenance.get("build_version", "")),
            "snapshot_source_hash": str(snapshot_provenance.get("source_hash", "")),
            "study_signature": study_signature or "",
            "runtime_settings_json": json.dumps(runtime_settings or {}, sort_keys=True),
            "effective_cost_model_json": json.dumps(effective_cost_model, sort_keys=True),
            "selection_oos_execution_pressure_json": json.dumps(execution_pressure_summary, sort_keys=True),
            "agent_loop_metadata_json": json.dumps(agent_loop_metadata or {}, sort_keys=True),
            "forecast_governance_json": json.dumps(forecast_governance or {}, sort_keys=True),
            "selected_parameters_json": json.dumps(selected_parameters, sort_keys=True),
            "parameter_search_json": json.dumps(parameter_search, sort_keys=True),
            "scenario_profiles_json": json.dumps(scenario_profiles, sort_keys=True),
            "stress_liquidity_metrics_json": json.dumps(stress_metrics, sort_keys=True),
            "regime_scenario_pass_matrix_json": json.dumps(
                scenario_report.regime_scenario_pass_matrix,
                sort_keys=True,
            ),
            "regime_summary_json": json.dumps(regime_summary, sort_keys=True),
            "bootstrap_summary_json": json.dumps(
                {
                    "bootstrap_method": bootstrap_report.bootstrap_method if bootstrap_report is not None else None,
                    "block_size": bootstrap_report.block_size if bootstrap_report is not None else None,
                    "bootstrap_microstructure_overlay": (
                        dict(bootstrap_report.bootstrap_microstructure_overlay) if bootstrap_report is not None else {}
                    ),
                    "bootstrap_regime_summary": (
                        dict(bootstrap_report.bootstrap_regime_summary) if bootstrap_report is not None else {}
                    ),
                },
                sort_keys=True,
            ),
            "validation_status": protocol.status,
            "validation_protocol_json": json.dumps(serialized_protocol, sort_keys=True),
            "validation_gate_results_json": json.dumps(protocol.validation_gate_results, sort_keys=True),
            "validation_gate_details_json": json.dumps(protocol.validation_gate_details, sort_keys=True),
        },
    )
