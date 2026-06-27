from __future__ import annotations

import hashlib
import json
import math
from statistics import mean, pstdev
from typing import Any


APPROVED_CANDIDATE_FAMILIES = {
    "causal_kalman_state_filter",
    "causal_super_smoother_filter",
    "pivot_atr_breakout",
    "rsi_volume_confirmation",
    "chop_sleep_filter",
    "exit_variant",
}


def build_strategy_tournament_report(
    rows: list[dict[str, object]],
    *,
    minimum_bucket_count: int = 2,
) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = {}
    blockers: list[str] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id", "")).strip()
        if not candidate_id:
            blockers.append("missing_candidate_id")
            continue
        grouped.setdefault(candidate_id, []).append(dict(row))

    ranked: list[dict[str, object]] = []
    for candidate_id, candidate_rows in grouped.items():
        candidate = _summarize_tournament_candidate(candidate_id, candidate_rows)
        if int(candidate["bucket_count"]) < minimum_bucket_count:
            blockers.append(f"insufficient_bucket_count:{candidate_id}")
        ranked.append(candidate)

    ranked.sort(
        key=lambda item: (
            -float(item["stability_score"]),
            str(item["candidate_id"]),
        )
    )
    status = "ready" if ranked and not blockers else "blocked"
    return {
        "artifact_type": "strategy_tournament",
        "status": status,
        "rank_basis": "stability_score",
        "minimum_bucket_count": int(minimum_bucket_count),
        "candidate_count": len(ranked),
        "ranked_candidates": ranked,
        "blockers": sorted(dict.fromkeys(blockers)),
    }


def build_robust_evaluation_scorecard(payload: dict[str, object]) -> dict[str, object]:
    metrics = _mapping(payload.get("metrics"))
    feature_audit = _mapping(payload.get("feature_audit"))
    tournament_candidate = _mapping(payload.get("tournament_candidate"))
    candidate_id = str(payload.get("candidate_id") or tournament_candidate.get("candidate_id") or "unknown")
    blockers: list[str] = []

    if not bool(feature_audit.get("passed")):
        blockers.append("feature_causality_audit_failed")
    if int(_to_float(tournament_candidate.get("bucket_count"), 0.0)) < 2:
        blockers.append("insufficient_tournament_buckets")
    if len(_string_list(tournament_candidate.get("distinct_symbols"))) < 2:
        blockers.append("symbol_specific_candidate")
    if len(_string_list(tournament_candidate.get("distinct_regimes"))) < 2:
        blockers.append("regime_specific_candidate")

    checks = {
        "positive_oos": _to_float(metrics.get("oos_sharpe"), -999.0) > 0.0,
        "positive_sealed_holdout": _to_float(metrics.get("sealed_holdout_sharpe"), -999.0) > 0.0,
        "cpcv": bool(metrics.get("cpcv_pass")),
        "bootstrap": _to_float(metrics.get("bootstrap_pass_rate"), 0.0) >= 0.70,
        "spa": bool(metrics.get("spa_pass")),
        "pbo": _to_float(metrics.get("pbo"), 1.0) <= 0.20,
        "dsr": _to_float(metrics.get("dsr"), 0.0) >= 0.95,
        "regime_stress": _to_float(metrics.get("regime_pass_rate"), 0.0) >= 0.70,
        "scenario_stress": _to_float(metrics.get("scenario_pass_rate"), 0.0) >= 0.70,
        "capacity": bool(metrics.get("capacity_pass")),
        "slippage": _to_float(metrics.get("slippage_bps"), 999.0) <= 25.0,
        "trade_count": int(_to_float(metrics.get("trade_count"), 0.0)) >= 30,
        "drawdown": abs(_to_float(metrics.get("max_drawdown"), -999.0)) <= 0.30,
    }
    blocker_by_check = {
        "positive_oos": "oos_not_positive_post_cost",
        "positive_sealed_holdout": "sealed_holdout_not_positive_post_cost",
        "cpcv": "cpcv_failed",
        "bootstrap": "bootstrap_stability_failed",
        "spa": "spa_failed",
        "pbo": "pbo_too_high",
        "dsr": "deflated_sharpe_too_low",
        "regime_stress": "regime_stress_failed",
        "scenario_stress": "scenario_stress_failed",
        "capacity": "capacity_failed",
        "slippage": "slippage_too_high",
        "trade_count": "insufficient_trade_count",
        "drawdown": "drawdown_too_high",
    }
    for check_name, passed in checks.items():
        if not passed:
            blockers.append(blocker_by_check[check_name])

    in_sample_sharpe = _to_float(metrics.get("in_sample_sharpe"), 0.0)
    oos_sharpe = _to_float(metrics.get("oos_sharpe"), 0.0)
    distortion = 0.0 if abs(in_sample_sharpe) <= 1e-12 else (in_sample_sharpe - oos_sharpe) / abs(in_sample_sharpe)
    if distortion > 0.50:
        blockers.append("is_to_oos_distortion_too_high")

    unique_blockers = sorted(dict.fromkeys(blockers))
    return {
        "artifact_type": "robust_evaluation_scorecard",
        "status": "passed" if not unique_blockers else "blocked",
        "candidate_id": candidate_id,
        "robustness_ready": not unique_blockers,
        "checks": checks,
        "is_to_oos_distortion": round(distortion, 6),
        "blockers": unique_blockers,
        "score": _robust_score(checks, distortion, unique_blockers),
        "source_contract": {
            "requires_feature_causality_audit": True,
            "requires_multi_axis_tournament": True,
            "requires_post_cost_oos_and_holdout": True,
            "requires_bootstrap_spa_pbo_dsr_cpcv": True,
            "requires_regime_scenario_capacity_slippage": True,
        },
    }


def build_sealed_holdout_check(payload: dict[str, object]) -> dict[str, object]:
    candidate_id = str(payload.get("candidate_id", "unknown"))
    robust_evaluation = _mapping(payload.get("robust_evaluation"))
    sealed_metrics = _mapping(payload.get("sealed_metrics"))
    failure_class = "sealed_holdout_passed"
    passed = True
    if not bool(robust_evaluation.get("robustness_ready")):
        passed = False
        failure_class = "robust_eval_not_ready"
    elif _to_float(sealed_metrics.get("trade_count"), 0.0) < 30:
        passed = False
        failure_class = "insufficient_trades"
    elif _to_float(sealed_metrics.get("post_cost_return"), -999.0) <= 0.0:
        passed = False
        failure_class = "negative_post_cost_return"
    elif _to_float(sealed_metrics.get("sharpe"), -999.0) <= 0.0:
        passed = False
        failure_class = "low_holdout_sharpe"
    elif abs(_to_float(sealed_metrics.get("max_drawdown"), -999.0)) > 0.30:
        passed = False
        failure_class = "excess_drawdown"

    return {
        "artifact_type": "sealed_holdout_check",
        "status": "passed" if passed else "failed",
        "candidate_id": candidate_id,
        "passed": passed,
        "failure_class": failure_class,
        "agent_visible": {
            "candidate_id": candidate_id,
            "decision": "pass" if passed else "fail",
            "failure_class": failure_class,
        },
        "sealed_metric_digest": _stable_digest(sealed_metrics),
        "privacy_contract": {
            "agent_receives_tunable_metrics": False,
            "agent_receives_failure_class_only": True,
            "optimization_against_holdout_allowed": False,
        },
    }


def build_paper_forward_score(payload: dict[str, object]) -> dict[str, object]:
    thresholds = _mapping(payload.get("thresholds"))
    candidate_id = str(payload.get("candidate_id") or "unknown")
    data_inventory = _mapping(payload.get("data_inventory"))
    public_ws = _mapping(payload.get("public_ws"))
    paper_dashboard = _mapping(payload.get("paper_dashboard"))
    postrun_summary = _mapping(payload.get("postrun_summary"))
    calibration_feedback = _mapping(payload.get("calibration_feedback"))
    capacity_report = _mapping(payload.get("capacity_report"))

    minimum_paper_orders = int(_to_float(thresholds.get("minimum_paper_orders"), 10.0))
    minimum_telemetry_quality = _to_float(thresholds.get("minimum_telemetry_quality"), 0.70)
    max_abs_slip_bps = _to_float(thresholds.get("max_abs_slip_bps"), 25.0)
    max_latency_ms = _to_float(thresholds.get("max_latency_ms"), 2_000.0)
    max_funding_shock_bps = _to_float(thresholds.get("max_funding_shock_bps"), 10.0)

    orders = _mapping(paper_dashboard.get("orders"))
    streams = _mapping(paper_dashboard.get("streams"))
    pnl = _mapping(paper_dashboard.get("pnl"))
    calibration_quality = _mapping(calibration_feedback.get("telemetry_quality"))
    priors = _mapping(calibration_feedback.get("priors"))
    readiness = _mapping(postrun_summary.get("calibration_readiness"))

    paper_orders = max(
        int(_to_float(orders.get("order_count"), 0.0)),
        int(_to_float(calibration_feedback.get("sample_count"), 0.0)),
        int(_to_float(readiness.get("sample_count"), 0.0)),
    )
    telemetry_quality = max(
        _to_float(pnl.get("telemetry_quality_score"), 0.0),
        _to_float(calibration_quality.get("score"), 0.0),
        _to_float(calibration_feedback.get("telemetry_quality_score"), 0.0),
    )

    public_ws_window_ready = _public_ws_window_ready(payload, data_inventory, public_ws)
    liquidation_sidecar_ready = bool(
        payload.get("liquidation_sidecar_ready")
        or data_inventory.get("liquidation_sidecar_ready")
        or public_ws.get("liquidation_sidecar_ready")
    )
    force_order_events = _force_order_event_count(public_ws, streams)
    if public_ws_window_ready and liquidation_sidecar_ready:
        liquidation_score = 1.0
    else:
        liquidation_score = 0.0

    slip_bps = _first_float(
        orders.get("max_abs_slip_bps"),
        _prior_sample_mean(priors, "slippage_bps"),
        default=None,
    )
    slippage_score = _inverse_threshold_score(slip_bps, max_abs_slip_bps)

    filled_count = _to_float(orders.get("filled_count"), 0.0)
    rejected_count = _to_float(orders.get("rejected_count"), 0.0)
    risk_blocked_count = _to_float(orders.get("risk_blocked_count"), 0.0)
    queue_fill_prior = _prior_sample_mean(priors, "queue_fill_probability")
    if paper_orders > 0:
        fill_score = max(0.0, min(1.0, (filled_count / paper_orders) - ((rejected_count + risk_blocked_count) / paper_orders)))
    else:
        fill_score = max(0.0, min(1.0, queue_fill_prior if queue_fill_prior is not None else 0.0))

    lag_ms = _first_float(
        orders.get("latency_ms_p95"),
        _mapping(streams.get("lag_ms")).get("p95"),
        _prior_sample_mean(priors, "latency_ms"),
        default=None,
    )
    latency_score = _inverse_threshold_score(lag_ms, max_latency_ms)

    funding_shock_bps = _first_float(
        _prior_sample_mean(priors, "funding_shock_bps"),
        abs(_to_float(pnl.get("funding_fee"), 0.0)) if pnl.get("funding_fee") is not None else None,
        default=None,
    )
    funding_score = _inverse_threshold_score(funding_shock_bps, max_funding_shock_bps)

    capacity_score, capacity_blockers = _capacity_score(capacity_report, calibration_feedback)

    blockers: list[str] = []
    if not public_ws_window_ready:
        blockers.append("public_ws_window_not_ready")
    if paper_orders < minimum_paper_orders:
        blockers.append("paper_sample_too_small")
    if telemetry_quality < minimum_telemetry_quality:
        blockers.append("paper_telemetry_quality_low")
    if slip_bps is None:
        blockers.append("slippage_evidence_missing")
    elif abs(slip_bps) > max_abs_slip_bps:
        blockers.append("paper_slippage_too_high")
    if fill_score <= 0.0:
        blockers.append("fill_evidence_missing")
    elif fill_score < 0.80:
        blockers.append("paper_fill_quality_low")
    if lag_ms is None:
        blockers.append("latency_evidence_missing")
    elif lag_ms > max_latency_ms:
        blockers.append("paper_latency_too_high")
    if funding_shock_bps is None:
        blockers.append("funding_evidence_missing")
    elif funding_shock_bps > max_funding_shock_bps:
        blockers.append("paper_funding_shock_too_high")
    if not liquidation_sidecar_ready:
        blockers.append("liquidation_sidecar_missing")
    blockers.extend(capacity_blockers)

    scores = {
        "slippage_score": slippage_score,
        "fill_score": round(fill_score, 6),
        "latency_score": latency_score,
        "funding_score": funding_score,
        "liquidation_score": round(liquidation_score, 6),
        "capacity_score": round(capacity_score, 6),
    }
    unique_blockers = sorted(dict.fromkeys(blockers))
    aggregate = round(mean(scores.values()), 6)
    status = "ready" if not unique_blockers else "blocked"
    return {
        "artifact_type": "paper_forward_score",
        "status": status,
        "candidate_id": candidate_id,
        "public_ws_window_ready": public_ws_window_ready,
        "liquidation_sidecar_ready": liquidation_sidecar_ready,
        "force_order_event_count": force_order_events,
        "paper_orders": paper_orders,
        "minimum_paper_orders": minimum_paper_orders,
        "telemetry_quality": round(telemetry_quality, 6),
        "minimum_telemetry_quality": minimum_telemetry_quality,
        **scores,
        "execution_realism_score": aggregate,
        "advisory_only": True,
        "live_policy_mutation_allowed": False,
        "can_lower_live_costs": False,
        "blockers": unique_blockers,
        "next_actions": _paper_forward_next_actions(unique_blockers),
        "source_contract": {
            "uses_public_ws": True,
            "uses_paper_telemetry": True,
            "missing_historical_liquidations_treated_as_zero": False,
            "learning_is_advisory_until_governance": True,
        },
        "input_artifact_refs": {
            "data_inventory": _artifact_ref(data_inventory),
            "paper_dashboard": _artifact_ref(paper_dashboard),
            "postrun_summary": _artifact_ref(postrun_summary),
            "calibration_feedback": _artifact_ref(calibration_feedback),
            "capacity_report": _artifact_ref(capacity_report),
        },
    }


def build_strategy_evidence_card(payload: dict[str, object]) -> dict[str, object]:
    candidate_id = str(payload.get("candidate_id") or "unknown")
    promotion_governance_approved = bool(payload.get("promotion_governance_approved"))
    data_matrix = _mapping(payload.get("data_matrix"))
    feature_audit = _mapping(payload.get("feature_audit"))
    tournament = _mapping(payload.get("strategy_tournament"))
    robust_evaluation = _mapping(payload.get("robust_evaluation"))
    sealed_holdout = _mapping(payload.get("sealed_holdout"))
    paper_forward = _mapping(payload.get("paper_forward_score"))

    candidate_id = _first_non_empty(
        candidate_id,
        data_matrix.get("candidate_id"),
        feature_audit.get("candidate_id"),
        robust_evaluation.get("candidate_id"),
        sealed_holdout.get("candidate_id"),
        paper_forward.get("candidate_id"),
        default="unknown",
    )

    blockers: list[str] = []
    if not data_matrix or str(data_matrix.get("status") or "") != "ready" or not bool(data_matrix.get("robustness_ready", True)):
        blockers.append("data_matrix_not_ready")
    if not feature_audit or not bool(feature_audit.get("passed")):
        blockers.append("feature_causality_audit_not_passed")
    if not tournament or str(tournament.get("status") or "") != "ready":
        blockers.append("strategy_tournament_not_ready")
    if not robust_evaluation or not bool(robust_evaluation.get("robustness_ready")):
        blockers.append("robust_evaluation_not_ready")
    if not sealed_holdout or not bool(sealed_holdout.get("passed")):
        blockers.append("sealed_holdout_not_passed")
    if not paper_forward or str(paper_forward.get("status") or "") != "ready":
        blockers.append("paper_forward_score_not_ready")
    if paper_forward and bool(paper_forward.get("advisory_only")) and not promotion_governance_approved:
        blockers.append("paper_forward_score_advisory_without_governance_approval")

    unique_blockers = sorted(dict.fromkeys(blockers))
    can_claim = not unique_blockers
    status = "ready" if can_claim else "blocked"
    return {
        "artifact_type": "strategy_evidence_card",
        "candidate_id": candidate_id,
        "data_matrix_id": _artifact_id(data_matrix),
        "feature_audit_id": _artifact_id(feature_audit),
        "tournament_id": _artifact_id(tournament),
        "robust_evaluation_id": _artifact_id(robust_evaluation),
        "sealed_holdout_id": _artifact_id(sealed_holdout),
        "paper_forward_score_id": _artifact_id(paper_forward),
        "status": status,
        "can_claim_strategy_improvement": can_claim,
        "promotion_governance_approved": promotion_governance_approved,
        "blockers": unique_blockers,
        "next_allowed_action": _strategy_card_next_action(unique_blockers),
        "agent_visible_holdout": _mapping(sealed_holdout.get("agent_visible")),
        "sealed_holdout_metric_digest": sealed_holdout.get("sealed_metric_digest"),
        "input_artifact_refs": {
            "data_matrix": _artifact_ref(data_matrix),
            "feature_audit": _artifact_ref(feature_audit),
            "strategy_tournament": _artifact_ref(tournament),
            "robust_evaluation": _artifact_ref(robust_evaluation),
            "sealed_holdout": _artifact_ref(sealed_holdout),
            "paper_forward_score": _artifact_ref(paper_forward),
        },
        "safe_operation_contract": {
            "agent_receives_holdout_tunable_metrics": False,
            "single_backtest_improvement_claim_allowed": False,
            "live_private_trading_enabled": False,
            "live_policy_mutation_allowed": False,
        },
    }


def _summarize_tournament_candidate(candidate_id: str, rows: list[dict[str, object]]) -> dict[str, object]:
    sharpes = [_to_float(row.get("oos_sharpe"), 0.0) for row in rows]
    drawdowns = [abs(_to_float(row.get("max_drawdown"), 0.0)) for row in rows]
    trades = [int(_to_float(row.get("trade_count"), 0.0)) for row in rows]
    symbols = sorted(dict.fromkeys(str(row.get("symbol", "unknown")) for row in rows))
    timeframes = sorted(dict.fromkeys(str(row.get("timeframe", "unknown")) for row in rows))
    years = sorted(dict.fromkeys(str(row.get("year", "unknown")) for row in rows))
    regimes = sorted(dict.fromkeys(str(row.get("regime", "unknown")) for row in rows))
    bucket_keys = {
        (
            str(row.get("symbol", "unknown")),
            str(row.get("timeframe", "unknown")),
            str(row.get("year", "unknown")),
            str(row.get("regime", "unknown")),
        )
        for row in rows
    }
    family = str(rows[0].get("family", "unknown"))
    sharpe_mean = mean(sharpes) if sharpes else 0.0
    sharpe_stdev = pstdev(sharpes) if len(sharpes) > 1 else abs(sharpe_mean)
    worst_drawdown = max(drawdowns) if drawdowns else 1.0
    bucket_count = len(bucket_keys)
    coverage_bonus = min(bucket_count, 6) / 6.0
    family_penalty = 0.0 if family in APPROVED_CANDIDATE_FAMILIES else 0.10
    stability_score = sharpe_mean - sharpe_stdev - (0.50 * worst_drawdown) + coverage_bonus - family_penalty
    return {
        "candidate_id": candidate_id,
        "family": family,
        "approved_family": family in APPROVED_CANDIDATE_FAMILIES,
        "bucket_count": bucket_count,
        "distinct_symbols": symbols,
        "distinct_timeframes": timeframes,
        "distinct_years": years,
        "distinct_regimes": regimes,
        "mean_oos_sharpe": round(sharpe_mean, 6),
        "worst_oos_sharpe": round(min(sharpes) if sharpes else 0.0, 6),
        "max_abs_drawdown": round(worst_drawdown, 6),
        "trade_count": sum(trades),
        "stability_score": round(stability_score, 6),
        "rank_notes": ["ranked_by_stability_not_raw_profit"],
    }


def _robust_score(checks: dict[str, bool], distortion: float, blockers: list[str]) -> float:
    passed_count = sum(1 for passed in checks.values() if passed)
    raw = passed_count / max(1, len(checks))
    distortion_penalty = max(0.0, distortion) * 0.15
    blocker_penalty = min(0.50, len(blockers) * 0.03)
    return round(max(0.0, raw - distortion_penalty - blocker_penalty), 6)


def _stable_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _artifact_id(payload: dict[str, object]) -> str | None:
    if not payload:
        return None
    for key in ("artifact_id", "id", "path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return _stable_digest(payload)


def _artifact_ref(payload: dict[str, object]) -> dict[str, object] | None:
    if not payload:
        return None
    return {
        "artifact_type": payload.get("artifact_type"),
        "artifact_id": _artifact_id(payload),
        "artifact_sha256": payload.get("artifact_sha256"),
        "status": payload.get("status"),
        "path": payload.get("path"),
    }


def _public_ws_window_ready(
    payload: dict[str, object],
    data_inventory: dict[str, object],
    public_ws: dict[str, object],
) -> bool:
    if bool(payload.get("public_ws_window_ready") or data_inventory.get("forward_first_window_ready") or public_ws.get("forward_first_window_ready")):
        return True
    elapsed = _first_float(
        payload.get("observed_window_seconds"),
        data_inventory.get("observed_window_seconds"),
        public_ws.get("observed_window_seconds"),
        public_ws.get("elapsed_seconds"),
        public_ws.get("elapsed_seconds_at_update"),
        default=0.0,
    )
    minimum = _first_float(payload.get("min_forward_seconds"), data_inventory.get("min_forward_seconds"), public_ws.get("min_forward_seconds"), default=8 * 60 * 60)
    return bool(elapsed is not None and minimum is not None and elapsed >= minimum)


def _force_order_event_count(public_ws: dict[str, object], streams: dict[str, object]) -> int:
    count = int(_to_float(public_ws.get("force_order_event_count"), 0.0))
    for field_name in ("observed_streams_at_update", "stream_counts"):
        observed = public_ws.get(field_name)
        if isinstance(observed, dict):
            count += sum(int(_to_float(value, 0.0)) for key, value in observed.items() if "forceOrder" in str(key))
    stream_counts = streams.get("event_counts_by_stream")
    if isinstance(stream_counts, dict):
        count += sum(int(_to_float(value, 0.0)) for key, value in stream_counts.items() if "forceOrder" in str(key))
    return count


def _prior_sample_mean(priors: dict[str, object], name: str) -> float | None:
    prior = _mapping(priors.get(name))
    if not prior:
        return None
    return _first_float(prior.get("sample_mean"), prior.get("shrunk_value"), default=None)


def _first_float(*values: object, default: float | None) -> float | None:
    for value in values:
        if value is None:
            continue
        number = _to_float(value, math.nan)
        if math.isfinite(number):
            return number
    return default


def _inverse_threshold_score(value: float | None, threshold: float) -> float:
    if value is None:
        return 0.0
    threshold = max(float(threshold), 1e-12)
    return round(max(0.0, min(1.0, 1.0 - (abs(float(value)) / threshold))), 6)


def _capacity_score(capacity_report: dict[str, object], calibration_feedback: dict[str, object]) -> tuple[float, list[str]]:
    if capacity_report:
        if bool(capacity_report.get("passed")):
            return 1.0, []
        reasons = _string_list(capacity_report.get("failure_reasons"))
        return 0.0, reasons or ["capacity_evidence_failed"]
    questions = _mapping(calibration_feedback.get("capacity_questions"))
    if not questions:
        return 0.0, ["capacity_evidence_missing"]
    participation = _to_float(questions.get("max_participation_rate_seen"), 1.0)
    fill = _to_float(questions.get("mean_fill_completion_rate"), 0.0)
    edge = _to_float(questions.get("mean_edge_erosion_bps"), 999.0)
    score = min(1.0, max(0.0, (fill * 0.50) + ((1.0 - min(participation / 0.05, 1.0)) * 0.25) + ((1.0 - min(edge / 25.0, 1.0)) * 0.25)))
    blockers: list[str] = []
    if fill < 0.80:
        blockers.append("capacity_fill_quality_low")
    if participation > 0.05:
        blockers.append("capacity_participation_too_high")
    if edge > 25.0:
        blockers.append("capacity_edge_erosion_too_high")
    return round(score, 6), blockers


def _paper_forward_next_actions(blockers: list[str]) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    if "public_ws_window_not_ready" in blockers or "liquidation_sidecar_missing" in blockers:
        actions.append(
            {
                "id": "collect_public_ws_evidence",
                "priority": 1,
                "action": "Continue public WS capture and export observed liquidation sidecar after the valid window.",
                "evidence": [item for item in blockers if item in {"public_ws_window_not_ready", "liquidation_sidecar_missing"}],
            }
        )
    if any(item.startswith("paper_") or item.endswith("_evidence_missing") for item in blockers):
        actions.append(
            {
                "id": "collect_paper_forward_telemetry",
                "priority": 2,
                "action": "Collect enough paper orders with slippage, fill, latency, funding, and calibration telemetry.",
                "evidence": [item for item in blockers if item.startswith("paper_") or item.endswith("_evidence_missing")],
            }
        )
    if any(item.startswith("capacity_") for item in blockers):
        actions.append(
            {
                "id": "repair_capacity_evidence",
                "priority": 3,
                "action": "Build or repair capacity evidence before promotion or improvement claims.",
                "evidence": [item for item in blockers if item.startswith("capacity_")],
            }
        )
    return actions


def _strategy_card_next_action(blockers: list[str]) -> str:
    if not blockers:
        return "claim_strategy_improvement_allowed"
    if "data_matrix_not_ready" in blockers:
        return "repair_dataset_matrix"
    if "feature_causality_audit_not_passed" in blockers:
        return "repair_feature_causality"
    if "strategy_tournament_not_ready" in blockers:
        return "run_strategy_tournament"
    if "robust_evaluation_not_ready" in blockers:
        return "repair_robust_evaluation"
    if "sealed_holdout_not_passed" in blockers:
        return "reject_or_rework_candidate_without_holdout_tuning"
    if "paper_forward_score_not_ready" in blockers:
        return "collect_paper_forward_score"
    if "paper_forward_score_advisory_without_governance_approval" in blockers:
        return "request_promotion_governance_review"
    return "repair_strategy_evidence"


def _first_non_empty(*values: object, default: str) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text != "unknown":
            return text
    return default


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple | set):
        return []
    return [str(item) for item in value if str(item).strip()]


def _to_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        candidate = float(value)
    elif isinstance(value, str):
        try:
            candidate = float(value)
        except ValueError:
            return default
    else:
        return default
    if not math.isfinite(candidate):
        return default
    return candidate
