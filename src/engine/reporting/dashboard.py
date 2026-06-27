from __future__ import annotations

import json

from engine.config.models import BacktestResult, BootstrapReport, Candle, PhaseRecord, PromotionDecision, RunCard, SplitPack, StrategyGraph, ValidationProtocol
from engine.validation.protocol import legacy_validation_protocol, serialize_validation_protocol
from engine.validation.phase4_governance import extract_phase4_governance_report


def _safe_json_load(raw: object, fallback: object) -> object:
    if not isinstance(raw, str) or not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _safe_json_object(raw: object) -> dict[str, object]:
    value = _safe_json_load(raw, {})
    return value if isinstance(value, dict) else {}


def _safe_json_list(raw: object) -> list[object]:
    value = _safe_json_load(raw, [])
    return value if isinstance(value, list) else []


def _safe_int(raw: object, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _build_timeseries(split_pack: SplitPack, selection_oos_result: BacktestResult) -> list[dict[str, object]]:
    candles = split_pack.selection_oos.candles
    equity_curve = list(selection_oos_result.equity_curve or [])
    if not candles or not equity_curve:
        return []

    length = min(len(candles), len(equity_curve))
    trimmed_candles: list[Candle] = candles[:length]
    trimmed_equity = equity_curve[:length]
    peak: float | None = None
    rows: list[dict[str, object]] = []
    for candle, equity in zip(trimmed_candles, trimmed_equity):
        equity_value = float(equity)
        absolute_equity = max(1e-9, 1.0 + equity_value)
        peak = absolute_equity if peak is None else max(peak, absolute_equity)
        drawdown = (absolute_equity / peak) - 1.0
        rows.append(
            {
                "timestamp": candle.timestamp.isoformat(),
                "equity": equity_value,
                "drawdown": drawdown,
            }
        )
    return rows


def build_dashboard_payload(
    runcard: RunCard,
    split_pack: SplitPack | None = None,
    selection_oos_result: BacktestResult | None = None,
    bootstrap_report: BootstrapReport | None = None,
    strategy: StrategyGraph | None = None,
    phase_records: list[PhaseRecord] | None = None,
    holdout_decision: PromotionDecision | None = None,
    validation_protocol: ValidationProtocol | None = None,
    agent_loop_metadata: dict[str, object] | None = None,
    research_program_version: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": runcard.run_id,
        "phase": runcard.phase,
        "decision": runcard.decision.decision,
        "reasons": list(runcard.decision.reasons),
        "metrics": dict(runcard.metrics),
        "artifacts": dict(runcard.artifacts),
    }
    if bootstrap_report is not None:
        payload["bootstrap"] = {
            "sample_count": bootstrap_report.sample_count,
            "median_net_profit": bootstrap_report.median_net_profit,
            "median_max_drawdown": bootstrap_report.median_max_drawdown,
            "worst_case_net_profit": bootstrap_report.worst_case_net_profit,
            "worst_case_drawdown": bootstrap_report.worst_case_drawdown,
            "pass_rate": bootstrap_report.pass_rate,
            "bootstrap_method": bootstrap_report.bootstrap_method,
            "block_size": bootstrap_report.block_size,
            "bootstrap_microstructure_overlay": dict(bootstrap_report.bootstrap_microstructure_overlay),
            "bootstrap_regime_summary": dict(bootstrap_report.bootstrap_regime_summary),
        }
    else:
        payload["bootstrap"] = _safe_json_object(runcard.artifacts.get("bootstrap_summary_json", "{}"))
    if strategy is not None:
        payload["strategy"] = {
            "backbone": strategy.backbone,
            "layers": [layer.name for layer in strategy.layers],
            "risk_guards": [layer.name for layer in strategy.risk_guards],
        }
    if phase_records is not None:
        payload["phases"] = [
            {
                "phase_name": record.phase_name,
                "layer_name": record.layer_name,
                "decision": record.decision,
                "accepted": record.accepted,
                "oos_sharpe": record.oos_sharpe,
                "selected_parameters": dict(record.selected_parameters),
                "permutation_count": record.permutation_count,
                "search_summary": list(record.search_summary),
                "candidate_trials": list(record.candidate_trials),
            }
            for record in phase_records
        ]
    if holdout_decision is not None:
        payload["holdout"] = {
            "decision": holdout_decision.decision,
            "reasons": list(holdout_decision.reasons),
        }
    protocol = validation_protocol
    if protocol is None:
        raw_protocol = runcard.artifacts.get("validation_protocol_json")
        if isinstance(raw_protocol, str) and raw_protocol:
            try:
                payload["validation_protocol"] = json.loads(raw_protocol)
            except json.JSONDecodeError:
                payload["validation_protocol"] = serialize_validation_protocol(legacy_validation_protocol())
        else:
            payload["validation_protocol"] = serialize_validation_protocol(legacy_validation_protocol())
    else:
        payload["validation_protocol"] = serialize_validation_protocol(protocol)
        phase4_governance = extract_phase4_governance_report(protocol)
        if phase4_governance:
            payload["candidate_governance"] = phase4_governance
    raw_gate_details = runcard.artifacts.get("validation_gate_details_json")
    if validation_protocol is not None:
        payload["validation_gate_details"] = list(validation_protocol.validation_gate_details)
    else:
        gate_details = _safe_json_load(raw_gate_details, [])
        payload["validation_gate_details"] = gate_details if isinstance(gate_details, list) else []
    payload["snapshot_quality"] = {
        "status": runcard.artifacts.get("snapshot_quality_status", "unknown"),
        "flag_count": _safe_int(runcard.artifacts.get("snapshot_quality_flag_count", "0")),
        "flags": _safe_json_list(runcard.artifacts.get("snapshot_quality_flags_json", "[]")),
        "report": _safe_json_object(runcard.artifacts.get("snapshot_quality_report_json", "{}")),
    }
    snapshot_provenance = _safe_json_object(runcard.artifacts.get("snapshot_provenance_json", "{}"))
    if not snapshot_provenance:
        build_version = runcard.artifacts.get("snapshot_build_version")
        source_hash = runcard.artifacts.get("snapshot_source_hash")
        if isinstance(build_version, str) and build_version:
            snapshot_provenance["build_version"] = build_version
        if isinstance(source_hash, str) and source_hash:
            snapshot_provenance["source_hash"] = source_hash
    payload["snapshot_provenance"] = snapshot_provenance
    payload["runtime_settings"] = _safe_json_object(runcard.artifacts.get("runtime_settings_json", "{}"))
    if selection_oos_result is not None and selection_oos_result.execution_pressure_summary:
        payload["selection_oos_execution_pressure"] = dict(selection_oos_result.execution_pressure_summary)
    else:
        payload["selection_oos_execution_pressure"] = _safe_json_object(
            runcard.artifacts.get("selection_oos_execution_pressure_json", "{}")
        )
    payload["scenario_profiles"] = _safe_json_object(runcard.artifacts.get("scenario_profiles_json", "{}"))
    payload["stress_liquidity_metrics"] = _safe_json_object(runcard.artifacts.get("stress_liquidity_metrics_json", "{}"))
    payload["regime_scenario_pass_matrix"] = _safe_json_object(
        runcard.artifacts.get("regime_scenario_pass_matrix_json", "{}")
    )
    if split_pack is not None:
        payload["regimes"] = {
            "regime_labels": list(split_pack.regime_labels),
            "regime_coverage": dict(split_pack.regime_coverage),
            "crisis_window_coverage": dict(split_pack.crisis_window_coverage),
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
    else:
        payload["regimes"] = _safe_json_object(runcard.artifacts.get("regime_summary_json", "{}"))
    if split_pack is not None and selection_oos_result is not None:
        payload["timeseries"] = _build_timeseries(split_pack, selection_oos_result)
    if agent_loop_metadata is not None:
        payload["agent_loop_metadata"] = dict(agent_loop_metadata)
    if research_program_version is not None:
        payload["research_program_version"] = research_program_version
    forecast_governance = _safe_json_object(runcard.artifacts.get("forecast_governance_json", "{}"))
    if not forecast_governance:
        forecast_model_id = runcard.artifacts.get("forecast_model_id")
        if isinstance(forecast_model_id, str) and forecast_model_id:
            forecast_governance["forecast_model_id"] = forecast_model_id
        ttl_status = runcard.artifacts.get("forecast_ttl_status")
        if isinstance(ttl_status, str) and ttl_status:
            forecast_governance["ttl_status"] = ttl_status
        baseline_comparison = _safe_json_object(runcard.artifacts.get("forecast_baseline_comparison_json", "{}"))
        if baseline_comparison:
            forecast_governance["baseline_comparison"] = baseline_comparison
        decay_status = runcard.artifacts.get("forecast_decay_status")
        if isinstance(decay_status, str) and decay_status:
            forecast_governance["decay_status"] = decay_status
        forbidden_use_status = runcard.artifacts.get("forecast_forbidden_use_status")
        if isinstance(forbidden_use_status, str) and forbidden_use_status:
            forecast_governance["forbidden_use_status"] = forbidden_use_status
    if forecast_governance:
        payload["forecast_governance"] = forecast_governance
    return payload
