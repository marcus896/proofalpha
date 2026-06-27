from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_loop_evidence_ledger(
    *,
    agent_loop_report_paths: list[Path],
    readiness_scan_paths: list[Path] | None = None,
    readiness_report_paths: list[Path] | None = None,
    paper_dashboard_paths: list[Path] | None = None,
    paper_postrun_summary_paths: list[Path] | None = None,
    paper_calibration_feedback_paths: list[Path] | None = None,
) -> dict[str, object]:
    runs = [_summarize_agent_loop_report(path) for path in agent_loop_report_paths]
    scans = [_load_json(path) for path in readiness_scan_paths or []]
    readiness_reports = [_load_json(path) for path in readiness_report_paths or []]
    paper_dashboards = [_load_json(path) for path in paper_dashboard_paths or []]
    paper_postruns = [_load_json(path) for path in paper_postrun_summary_paths or []]
    paper_calibrations = [_load_json(path) for path in paper_calibration_feedback_paths or []]
    scan_blocker_counts = _merge_count_maps(scan.get("blocked_by_reason", {}) for scan in scans if isinstance(scan, dict))
    report_blocker_counts = _readiness_report_blocker_counts(readiness_reports)
    return {
        "artifact_type": "loop_evidence_ledger",
        "run_count": len(runs),
        "readiness_scan_count": len(scans),
        "readiness_report_count": len(readiness_reports),
        "promoted_run_count": sum(len(run["promoted_run_ids"]) for run in runs),
        "failed_gate_counts": _count_values(run["failed_gates"] for run in runs),
        "failure_taxonomy_counts": _count_values(run["failure_taxonomy"] for run in runs),
        "readiness_blocker_counts": _merge_count_maps_by_max([scan_blocker_counts, report_blocker_counts]),
        "runs": runs,
        "readiness_scans": [_summarize_readiness_scan(path, scan) for path, scan in zip(readiness_scan_paths or [], scans)],
        "readiness_reports": [
            _summarize_readiness_report(path, report) for path, report in zip(readiness_report_paths or [], readiness_reports)
        ],
        "paper_feedback": _summarize_paper_feedback(
            dashboards=paper_dashboards,
            postruns=paper_postruns,
            calibrations=paper_calibrations,
        ),
        "paper_feedback_artifacts": {
            "dashboards": [
                _summarize_paper_dashboard(path, payload) for path, payload in zip(paper_dashboard_paths or [], paper_dashboards)
            ],
            "postrun_summaries": [
                _summarize_paper_postrun(path, payload) for path, payload in zip(paper_postrun_summary_paths or [], paper_postruns)
            ],
            "calibration_feedback": [
                _summarize_paper_calibration(path, payload)
                for path, payload in zip(paper_calibration_feedback_paths or [], paper_calibrations)
            ],
        },
        "paper_next_hypotheses": _paper_next_hypotheses(paper_dashboards, paper_postruns, paper_calibrations),
    }


def _summarize_agent_loop_report(path: Path) -> dict[str, object]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"agent-loop report must be a JSON object: {path}")
    best = payload.get("best_result_summary")
    best = best if isinstance(best, dict) else {}
    run_id = str(payload.get("run_id") or "")
    next_candidate_path = _infer_next_candidate_path(path, run_id)
    return {
        "report_path": str(path),
        "run_id": run_id,
        "status": payload.get("status"),
        "stop_reason": payload.get("stop_reason"),
        "iteration_count": payload.get("iteration_count"),
        "completed_run_ids": _string_list(payload.get("completed_run_ids")),
        "promoted_run_ids": _string_list(payload.get("promoted_run_ids")),
        "objective_score": best.get("objective_score"),
        "failed_gates": _string_list(best.get("failed_gates")),
        "failure_taxonomy": _string_list(best.get("failure_taxonomy")),
        "scenario_failure_names": _string_list(best.get("scenario_failure_names")),
        "next_hypotheses": _next_hypotheses(best),
        "memory_effect": _compact_memory_effect(_latest_memory_summary(payload)),
        "next_candidate_path": str(next_candidate_path),
        "next_candidate_exists": next_candidate_path.exists(),
    }


def _summarize_readiness_scan(path: Path, payload: object) -> dict[str, object]:
    scan = payload if isinstance(payload, dict) else {}
    return {
        "path": str(path),
        "study_count": scan.get("study_count", 0),
        "eligible_count": scan.get("eligible_count", 0),
        "blocked_count": scan.get("blocked_count", 0),
        "blocked_by_reason": dict(scan.get("blocked_by_reason", {})),
    }


def _summarize_readiness_report(path: Path, payload: object) -> dict[str, object]:
    report = payload if isinstance(payload, dict) else {}
    return {
        "path": str(path),
        "eligible": bool(report.get("eligible", False)),
        "run_id": report.get("run_id"),
        "config_path": report.get("config_path"),
        "blockers": _string_list(report.get("blockers")),
    }


def _readiness_report_blocker_counts(reports: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in reports:
        if not isinstance(report, dict):
            continue
        for blocker in _string_list(report.get("blockers")):
            counts[blocker] = counts.get(blocker, 0) + 1
    return counts


def _summarize_paper_feedback(
    *,
    dashboards: list[object],
    postruns: list[object],
    calibrations: list[object],
) -> dict[str, object]:
    dashboard_maps = [payload for payload in dashboards if isinstance(payload, dict)]
    postrun_maps = [payload for payload in postruns if isinstance(payload, dict)]
    calibration_maps = [payload for payload in calibrations if isinstance(payload, dict)]
    max_slip_values = [
        _float_value((dashboard.get("orders") if isinstance(dashboard.get("orders"), dict) else {}).get("max_abs_slip_bps"))
        for dashboard in dashboard_maps
    ]
    return {
        "dashboard_count": len(dashboard_maps),
        "postrun_summary_count": len(postrun_maps),
        "calibration_feedback_count": len(calibration_maps),
        "order_count": sum(
            _int_value((dashboard.get("orders") if isinstance(dashboard.get("orders"), dict) else {}).get("order_count"))
            for dashboard in dashboard_maps
        ),
        "rejected_count": sum(
            _int_value((dashboard.get("orders") if isinstance(dashboard.get("orders"), dict) else {}).get("rejected_count"))
            for dashboard in dashboard_maps
        ),
        "risk_blocked_count": sum(
            _int_value(
                (dashboard.get("orders") if isinstance(dashboard.get("orders"), dict) else {}).get("risk_blocked_count")
            )
            for dashboard in dashboard_maps
        ),
        "max_abs_slip_bps": max(max_slip_values) if max_slip_values else None,
        "model_update_allowed": any(bool(calibration.get("model_update_allowed")) for calibration in calibration_maps)
        if calibration_maps
        else None,
        "guard_reasons": sorted(_paper_guard_reasons(postrun_maps, calibration_maps)),
        "weak_artifact_ids": sorted(_paper_weak_artifact_ids(postrun_maps)),
        "suggested_next_experiments": sorted(_paper_suggested_next_experiments(postrun_maps)),
        "risk_block_reasons": sorted(_paper_risk_block_reasons(dashboard_maps, postrun_maps)),
    }


def _summarize_paper_dashboard(path: Path, payload: object) -> dict[str, object]:
    dashboard = payload if isinstance(payload, dict) else {}
    orders = dashboard.get("orders") if isinstance(dashboard.get("orders"), dict) else {}
    pnl = dashboard.get("pnl") if isinstance(dashboard.get("pnl"), dict) else {}
    risk = dashboard.get("risk") if isinstance(dashboard.get("risk"), dict) else {}
    return {
        "path": str(path),
        "status": dashboard.get("status"),
        "order_count": _int_value(orders.get("order_count")),
        "rejected_count": _int_value(orders.get("rejected_count")),
        "risk_blocked_count": _int_value(orders.get("risk_blocked_count")),
        "max_abs_slip_bps": _float_value(orders.get("max_abs_slip_bps")),
        "telemetry_quality_score": _float_value(pnl.get("telemetry_quality_score")),
        "risk_block_reasons": sorted(str(reason) for reason in (risk.get("blocks_by_reason") or {}) if isinstance(risk, dict)),
    }


def _summarize_paper_postrun(path: Path, payload: object) -> dict[str, object]:
    postrun = payload if isinstance(payload, dict) else {}
    session = postrun.get("session") if isinstance(postrun.get("session"), dict) else {}
    readiness = postrun.get("calibration_readiness") if isinstance(postrun.get("calibration_readiness"), dict) else {}
    return {
        "path": str(path),
        "status": postrun.get("status"),
        "session_status": session.get("status"),
        "order_count": _int_value(session.get("order_count")),
        "risk_block_count": _int_value(session.get("risk_block_count")),
        "ready_for_model_update": bool(readiness.get("ready_for_model_update")),
        "guard_reasons": _string_list(readiness.get("guard_reasons")),
        "weak_artifact_ids": sorted(_paper_weak_artifact_ids([postrun])),
        "suggested_next_experiments": sorted(_paper_suggested_next_experiments([postrun])),
    }


def _summarize_paper_calibration(path: Path, payload: object) -> dict[str, object]:
    calibration = payload if isinstance(payload, dict) else {}
    quality = calibration.get("telemetry_quality") if isinstance(calibration.get("telemetry_quality"), dict) else {}
    return {
        "path": str(path),
        "status": calibration.get("status"),
        "sample_count": _int_value(calibration.get("sample_count")),
        "model_update_allowed": bool(calibration.get("model_update_allowed")),
        "guard_reasons": _string_list(calibration.get("guard_reasons")),
        "telemetry_quality_score": _float_value(quality.get("score")),
    }


def _paper_next_hypotheses(dashboards: list[object], postruns: list[object], calibrations: list[object]) -> list[str]:
    dashboard_maps = [payload for payload in dashboards if isinstance(payload, dict)]
    postrun_maps = [payload for payload in postruns if isinstance(payload, dict)]
    calibration_maps = [payload for payload in calibrations if isinstance(payload, dict)]
    return sorted(
        dict.fromkeys(
            [
                *[f"paper_experiment:{name}" for name in _paper_suggested_next_experiments(postrun_maps)],
                *[f"paper_guard:{reason}" for reason in _paper_guard_reasons(postrun_maps, calibration_maps)],
                *[f"paper_risk_block:{reason}" for reason in _paper_risk_block_reasons(dashboard_maps, postrun_maps)],
                *[f"paper_weak_artifact:{artifact_id}" for artifact_id in _paper_weak_artifact_ids(postrun_maps)],
            ]
        )
    )


def _paper_guard_reasons(postruns: list[dict[str, object]], calibrations: list[dict[str, object]]) -> set[str]:
    reasons: set[str] = set()
    for postrun in postruns:
        readiness = postrun.get("calibration_readiness") if isinstance(postrun.get("calibration_readiness"), dict) else {}
        reasons.update(_string_list(readiness.get("guard_reasons")))
    for calibration in calibrations:
        reasons.update(_string_list(calibration.get("guard_reasons")))
    return reasons


def _paper_suggested_next_experiments(postruns: list[dict[str, object]]) -> set[str]:
    names: set[str] = set()
    for postrun in postruns:
        names.update(_string_list(postrun.get("suggested_next_experiments")))
    return names


def _paper_weak_artifact_ids(postruns: list[dict[str, object]]) -> set[str]:
    artifact_ids: set[str] = set()
    for postrun in postruns:
        weak_artifacts = postrun.get("weak_artifacts")
        if not isinstance(weak_artifacts, list):
            continue
        for artifact in weak_artifacts:
            if isinstance(artifact, dict) and artifact.get("artifact_id"):
                artifact_ids.add(str(artifact["artifact_id"]))
    return artifact_ids


def _paper_risk_block_reasons(dashboards: list[dict[str, object]], postruns: list[dict[str, object]]) -> set[str]:
    reasons: set[str] = set()
    for dashboard in dashboards:
        risk = dashboard.get("risk") if isinstance(dashboard.get("risk"), dict) else {}
        blocks = risk.get("blocks_by_reason")
        if isinstance(blocks, dict):
            reasons.update(str(reason) for reason in blocks)
    for postrun in postruns:
        top_reasons = postrun.get("top_failure_reasons")
        if not isinstance(top_reasons, list):
            continue
        for item in top_reasons:
            if isinstance(item, dict) and item.get("reason_code"):
                reasons.add(str(item["reason_code"]))
    return reasons


def _latest_memory_summary(payload: dict[str, Any]) -> dict[str, object]:
    scratchpad = payload.get("scratchpad")
    if isinstance(scratchpad, dict) and isinstance(scratchpad.get("latest_memory_summary"), dict):
        return dict(scratchpad["latest_memory_summary"])
    for event in reversed(payload.get("events", []) if isinstance(payload.get("events"), list) else []):
        if not isinstance(event, dict):
            continue
        details = event.get("details")
        if isinstance(details, dict) and isinstance(details.get("memory_summary"), dict):
            return dict(details["memory_summary"])
    return {}


def _compact_memory_effect(summary: dict[str, object]) -> dict[str, object]:
    meta_policy = summary.get("meta_policy")
    meta_policy = meta_policy if isinstance(meta_policy, dict) else {}
    return {
        "prior_runs": summary.get("prior_runs", 0),
        "blocked_runs": summary.get("blocked_runs", 0),
        "promoted_runs": summary.get("promoted_runs", 0),
        "excluded_dirty_runs": summary.get("excluded_dirty_runs", 0),
        "memory_quality_policy": summary.get("memory_quality_policy"),
        "meta_policy": {
            "status": meta_policy.get("status"),
            "selected_action": meta_policy.get("selected_action"),
        },
        "validation_failures": _top_named_counts(summary.get("validation_failures"), "gate_name"),
        "regime_coverage_gaps": _top_named_counts(summary.get("regime_coverage_gaps"), "regime_label"),
        "scenario_avoidance_names": sorted(
            str(name)
            for name in (summary.get("scenario_profile_avoidance", {}) or {})
            if isinstance(summary.get("scenario_profile_avoidance"), dict)
        ),
    }


def _next_hypotheses(best: dict[str, object]) -> list[str]:
    explicit = _string_list(best.get("next_hypotheses"))
    if explicit:
        return explicit
    return list(
        dict.fromkeys(
            [
                *[f"failed_gate:{gate}" for gate in _string_list(best.get("failed_gates"))],
                *[f"failure_taxonomy:{name}" for name in _string_list(best.get("failure_taxonomy"))],
                *[f"scenario_failure:{name}" for name in _string_list(best.get("scenario_failure_names"))],
            ]
        )
    )


def _top_named_counts(value: object, key_name: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        rows.append({"name": item.get(key_name), "count": item.get("count")})
    return rows


def _infer_next_candidate_path(report_path: Path, run_id: str) -> Path:
    if run_id:
        return report_path.parent / f"{run_id}.next-study.json"
    name = report_path.name.removesuffix(".agent-loop.json")
    return report_path.parent / f"{name}.next-study.json"


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _count_values(groups: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for group in groups:
        for value in group:
            counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _merge_count_maps(maps: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for mapping in maps:
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            try:
                amount = int(value)
            except (TypeError, ValueError):
                amount = 0
            counts[str(key)] = counts.get(str(key), 0) + amount
    return dict(sorted(counts.items()))


def _merge_count_maps_by_max(maps: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for mapping in maps:
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            try:
                amount = int(value)
            except (TypeError, ValueError):
                amount = 0
            counts[str(key)] = max(counts.get(str(key), 0), amount)
    return dict(sorted(counts.items()))


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
