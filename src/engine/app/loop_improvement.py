from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_loop_improvement_gate(
    *,
    ledger_path: Path,
    paper_dashboard_path: Path,
    postrun_summary_path: Path,
    calibration_feedback_path: Path,
    data_sufficiency_path: Path | None = None,
    max_abs_slip_bps: float = 25.0,
    minimum_paper_orders: int = 10,
    minimum_telemetry_quality: float = 0.70,
) -> dict[str, object]:
    ledger = _load_object(ledger_path)
    dashboard = _load_object(paper_dashboard_path)
    postrun = _load_object(postrun_summary_path)
    calibration = _load_object(calibration_feedback_path)
    data_sufficiency = _load_object(data_sufficiency_path) if data_sufficiency_path is not None else None
    missing: list[str] = []

    _check_data_sufficiency(data_sufficiency, missing)
    _check_loop_evidence(ledger, missing)
    _check_paper_dashboard(
        dashboard,
        missing,
        max_abs_slip_bps=max_abs_slip_bps,
        minimum_paper_orders=minimum_paper_orders,
        minimum_telemetry_quality=minimum_telemetry_quality,
    )
    _check_postrun_summary(postrun, missing, minimum_paper_orders=minimum_paper_orders)
    _check_calibration_feedback(calibration, missing, minimum_paper_orders=minimum_paper_orders)

    supported = not missing
    missing_evidence = list(dict.fromkeys(missing))
    return {
        "artifact_type": "loop_improvement_gate",
        "status": "supported" if supported else "not_supported",
        "strategy_improvement_supported": supported,
        "missing_evidence": missing_evidence,
        "next_actions": _build_next_actions(
            ledger=ledger,
            dashboard=dashboard,
            postrun=postrun,
            calibration=calibration,
            missing_evidence=missing_evidence,
        ),
        "inputs": {
            "ledger": str(ledger_path),
            "paper_dashboard": str(paper_dashboard_path),
            "postrun_summary": str(postrun_summary_path),
            "calibration_feedback": str(calibration_feedback_path),
            "data_sufficiency": str(data_sufficiency_path) if data_sufficiency_path is not None else None,
        },
        "thresholds": {
            "max_abs_slip_bps": max_abs_slip_bps,
            "minimum_paper_orders": minimum_paper_orders,
            "minimum_telemetry_quality": minimum_telemetry_quality,
        },
        "summary": {
            "promoted_run_count": _int_value(ledger.get("promoted_run_count")),
            "failed_gate_count": len(ledger.get("failed_gate_counts", {}) or {}),
            "readiness_blocker_count": len(ledger.get("readiness_blocker_counts", {}) or {}),
            "paper_order_count": _int_value((dashboard.get("orders") or {}).get("order_count")),
            "paper_max_abs_slip_bps": _float_value((dashboard.get("orders") or {}).get("max_abs_slip_bps")),
            "paper_status": dashboard.get("status"),
            "calibration_status": calibration.get("status"),
            "data_sufficiency_improvement_ready": bool((data_sufficiency or {}).get("improvement_ready")),
        },
    }


def _check_data_sufficiency(data_sufficiency: dict[str, Any] | None, missing: list[str]) -> None:
    if not isinstance(data_sufficiency, dict) or not data_sufficiency.get("improvement_ready"):
        missing.append("strict_data_not_improvement_ready")
    if not isinstance(data_sufficiency, dict):
        return
    blockers = _string_list(data_sufficiency.get("blockers"))
    missing_requirements = _string_list(data_sufficiency.get("missing_data_requirements"))
    if "liquidation_feature_missing_observed_sidecar" in blockers or "observed_liquidation_sidecar" in missing_requirements:
        missing.append("liquidation_feature_missing_observed_sidecar")
    if "insufficient_history_for_v3_improvement" in blockers or "strict_v3_history" in missing_requirements:
        missing.append("insufficient_history_for_v3_improvement")


def _check_loop_evidence(ledger: dict[str, Any], missing: list[str]) -> None:
    if _int_value(ledger.get("promoted_run_count")) <= 0:
        missing.append("no_promoted_run")
    if ledger.get("failed_gate_counts"):
        missing.append("validation_gates_failed")
    if ledger.get("failure_taxonomy_counts"):
        missing.append("failure_taxonomy_present")
    if ledger.get("readiness_blocker_counts"):
        missing.append("readiness_blockers_present")
    if ledger.get("candidate_duplicate_without_new_evidence") or _int_value(ledger.get("candidate_duplicate_without_new_evidence_count")) > 0:
        missing.append("candidate_duplicate_without_new_evidence")


def _check_paper_dashboard(
    dashboard: dict[str, Any],
    missing: list[str],
    *,
    max_abs_slip_bps: float,
    minimum_paper_orders: int,
    minimum_telemetry_quality: float,
) -> None:
    if str(dashboard.get("status") or "") not in {"completed", "healthy", "ok"}:
        missing.append("paper_dashboard_attention")
    orders = dashboard.get("orders")
    orders = orders if isinstance(orders, dict) else {}
    if _int_value(orders.get("order_count")) < minimum_paper_orders:
        missing.append("paper_sample_too_small")
    if _int_value(orders.get("rejected_count")) > 0:
        missing.append("paper_rejections_present")
    if _int_value(orders.get("risk_blocked_count")) > 0:
        missing.append("paper_risk_blocks_present")
    if _float_value(orders.get("max_abs_slip_bps")) > max_abs_slip_bps:
        missing.append("paper_slippage_too_high")
    pnl = dashboard.get("pnl")
    pnl = pnl if isinstance(pnl, dict) else {}
    if _float_value(pnl.get("telemetry_quality_score")) < minimum_telemetry_quality:
        missing.append("paper_telemetry_quality_low")
    risk = dashboard.get("risk")
    risk = risk if isinstance(risk, dict) else {}
    if _int_value(risk.get("risk_block_count")) > 0:
        missing.append("paper_risk_blocks_present")


def _check_postrun_summary(postrun: dict[str, Any], missing: list[str], *, minimum_paper_orders: int) -> None:
    readiness = postrun.get("calibration_readiness")
    readiness = readiness if isinstance(readiness, dict) else {}
    if not readiness.get("ready_for_model_update"):
        missing.append("paper_calibration_guarded")
    if readiness.get("guard_reasons"):
        missing.append("paper_calibration_guarded")
    if _int_value(readiness.get("sample_count")) < minimum_paper_orders:
        missing.append("paper_sample_too_small")
    if postrun.get("weak_artifacts"):
        missing.append("weak_paper_artifacts_present")


def _check_calibration_feedback(calibration: dict[str, Any], missing: list[str], *, minimum_paper_orders: int) -> None:
    if str(calibration.get("status") or "") in {"sample_guarded", "blocked", "attention"}:
        missing.append("paper_calibration_guarded")
    if calibration.get("guard_reasons"):
        missing.append("paper_calibration_guarded")
    if not calibration.get("model_update_allowed"):
        missing.append("paper_model_update_not_allowed")
    if _int_value(calibration.get("sample_count")) < minimum_paper_orders:
        missing.append("paper_sample_too_small")


def _build_next_actions(
    *,
    ledger: dict[str, Any],
    dashboard: dict[str, Any],
    postrun: dict[str, Any],
    calibration: dict[str, Any],
    missing_evidence: list[str],
) -> list[dict[str, object]]:
    if not missing_evidence:
        return []
    actions: list[dict[str, object]] = []
    readiness_blockers = ledger.get("readiness_blocker_counts") if isinstance(ledger.get("readiness_blocker_counts"), dict) else {}
    failed_gates = ledger.get("failed_gate_counts") if isinstance(ledger.get("failed_gate_counts"), dict) else {}
    failure_taxonomy = ledger.get("failure_taxonomy_counts") if isinstance(ledger.get("failure_taxonomy_counts"), dict) else {}

    if "strict_data_not_improvement_ready" in missing_evidence or "insufficient_history_for_v3_improvement" in missing_evidence:
        actions.append(
            {
                "id": "collect_strict_v3_data",
                "priority": 0,
                "action": "Collect strict v3 public data and rerun data sufficiency before claiming strategy improvement.",
                "evidence": [
                    name
                    for name in [
                        "strict_data_not_improvement_ready",
                        "insufficient_history_for_v3_improvement",
                        "liquidation_feature_missing_observed_sidecar",
                    ]
                    if name in missing_evidence
                ],
            }
        )
    if "candidate_duplicate_without_new_evidence" in missing_evidence:
        actions.append(
            {
                "id": "dedupe_candidate_without_new_evidence",
                "priority": 1,
                "action": "Do not rerun duplicate candidate payloads until new evidence changes the queue state.",
                "evidence": ["candidate_duplicate_without_new_evidence"],
            }
        )
    if "readiness_blockers_present" in missing_evidence:
        actions.append(
            {
                "id": "build_clean_real_study",
                "priority": 2,
                "action": "Acquire or import observed liquidation_notional coverage, hydrate the study, then require loop-readiness eligibility before rerun.",
                "evidence": sorted(str(name) for name in readiness_blockers),
            }
        )
    if "validation_gates_failed" in missing_evidence:
        actions.append(
            {
                "id": "repair_validation_failures",
                "priority": 3,
                "action": "Use failed gates to constrain the next-study variant before another bounded agent-loop run.",
                "evidence": sorted(str(name) for name in failed_gates),
            }
        )
    if "failure_taxonomy_present" in missing_evidence:
        actions.append(
            {
                "id": "route_failure_taxonomy",
                "priority": 4,
                "action": "Route failure taxonomy into explicit hypotheses and avoid repeating known-bad regimes or scenarios.",
                "evidence": sorted(str(name) for name in failure_taxonomy),
            }
        )
    if "no_promoted_run" in missing_evidence:
        actions.append(
            {
                "id": "rerun_until_candidate_promotes",
                "priority": 5,
                "action": "Do not claim improvement; continue only after a clean run promotes a candidate with no failed gates.",
                "evidence": [],
            }
        )
    if "paper_sample_too_small" in missing_evidence:
        actions.append(
            {
                "id": "collect_paper_samples",
                "priority": 6,
                "action": "Collect enough paper orders per bucket before allowing calibration or paper-backed improvement claims.",
                "evidence": _paper_sample_evidence(dashboard, postrun, calibration),
            }
        )
    if any(
        name in missing_evidence
        for name in [
            "paper_dashboard_attention",
            "paper_rejections_present",
            "paper_risk_blocks_present",
            "paper_slippage_too_high",
            "weak_paper_artifacts_present",
        ]
    ):
        actions.append(
            {
                "id": "investigate_paper_execution",
                "priority": 7,
                "action": "Inspect paper rejects, risk blocks, weak artifacts, and slippage before tuning execution assumptions.",
                "evidence": _paper_execution_evidence(dashboard, postrun),
            }
        )
    if "paper_calibration_guarded" in missing_evidence or "paper_model_update_not_allowed" in missing_evidence:
        actions.append(
            {
                "id": "keep_calibration_guarded",
                "priority": 8,
                "action": "Keep model updates disabled until paper calibration guard reasons clear.",
                "evidence": _guard_reasons(postrun, calibration),
            }
        )
    for hypothesis in _string_list(ledger.get("paper_next_hypotheses")):
        actions.append(
            {
                "id": hypothesis,
                "priority": 9,
                "action": "Carry paper feedback hypothesis into the next research loop.",
                "evidence": [hypothesis],
            }
        )
    return _unique_actions(actions)


def _paper_sample_evidence(dashboard: dict[str, Any], postrun: dict[str, Any], calibration: dict[str, Any]) -> list[str]:
    orders = dashboard.get("orders") if isinstance(dashboard.get("orders"), dict) else {}
    readiness = postrun.get("calibration_readiness") if isinstance(postrun.get("calibration_readiness"), dict) else {}
    return [
        f"paper_order_count={_int_value(orders.get('order_count'))}",
        f"postrun_sample_count={_int_value(readiness.get('sample_count'))}",
        f"calibration_sample_count={_int_value(calibration.get('sample_count'))}",
    ]


def _paper_execution_evidence(dashboard: dict[str, Any], postrun: dict[str, Any]) -> list[str]:
    orders = dashboard.get("orders") if isinstance(dashboard.get("orders"), dict) else {}
    weak_ids: list[str] = []
    weak_artifacts = postrun.get("weak_artifacts")
    if isinstance(weak_artifacts, list):
        weak_ids = [str(item.get("artifact_id")) for item in weak_artifacts if isinstance(item, dict) and item.get("artifact_id")]
    return [
        f"rejected_count={_int_value(orders.get('rejected_count'))}",
        f"risk_blocked_count={_int_value(orders.get('risk_blocked_count'))}",
        f"max_abs_slip_bps={_float_value(orders.get('max_abs_slip_bps'))}",
        *[f"weak_artifact={artifact_id}" for artifact_id in weak_ids],
    ]


def _guard_reasons(postrun: dict[str, Any], calibration: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    readiness = postrun.get("calibration_readiness") if isinstance(postrun.get("calibration_readiness"), dict) else {}
    reasons.extend(_string_list(readiness.get("guard_reasons")))
    reasons.extend(_string_list(calibration.get("guard_reasons")))
    return sorted(dict.fromkeys(reasons))


def _unique_actions(actions: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    unique: list[dict[str, object]] = []
    for action in sorted(actions, key=lambda item: int(item.get("priority", 99))):
        action_id = str(action.get("id") or "")
        if not action_id or action_id in seen:
            continue
        seen.add(action_id)
        unique.append(action)
    return unique


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
