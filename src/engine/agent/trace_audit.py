from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from engine.io.artifacts import write_json_atomic


HALO_PINNED_REF = "9f3a14197de2e08879f3940f60ee7a828ff22ce6"
FORBIDDEN_TRACE_EXPORT_FIELDS = {"order", "trade_action", "position_size", "executor_action", "emit_buy_sell_size"}
FORBIDDEN_ADVISORY_FIELDS = FORBIDDEN_TRACE_EXPORT_FIELDS | {
    "code_edit",
    "diff",
    "file_edit",
    "git_action",
    "patch",
    "proposed_code_edit",
}
CONTROLLED_FAILURE_TAXONOMY = (
    "resource_license_risk",
    "upstream_provenance_gap",
    "data_quality_failure",
    "venue_profile_gap",
    "liquidation_realism_failure",
    "insufficient_backtest_length",
    "multiple_testing_failure",
    "overfit_high_pbo",
    "holdout_failure",
    "stress_failure",
    "regime_brittleness",
    "agent_schema_violation",
    "catalog_violation",
    "forecast_unavailable",
    "forecast_leakage",
    "forecast_baseline_failure",
)


def build_trace_audit_export(report_payload: dict[str, object], *, source_path: str | None = None) -> dict[str, object]:
    payload = {
        "schema_version": 1,
        "artifact_type": "agent_loop_trace_audit_export",
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "research_only": True,
        "advisory_only": True,
        "source": {
            "kind": "agent_loop_report",
            "path": source_path,
        },
        "halo_reference": {
            "repo": "context-labs/HALO",
            "url": "https://github.com/context-labs/HALO",
            "license": "MIT",
            "pinned_ref": HALO_PINNED_REF,
            "intended_usage": "candidate_report_only_trace_audit",
        },
        "loop": _compact_loop(report_payload),
        "events": _compact_events(report_payload.get("events")),
        "iterations": _compact_iterations(report_payload.get("iteration_results")),
        "failure_taxonomy_counts": _failure_taxonomy_counts(report_payload.get("scratchpad")),
        "guardrails": {
            "no_autonomous_code_edits": True,
            "no_trading_decisions": True,
            "allowed_destinations": ["controlled_failure_taxonomy_hints", "planner_notes"],
            "forbidden_authority": ["direct_planner_authority", "execution_timing", "position_sizing", "buy_sell_decisions"],
        },
    }
    _reject_forbidden_fields(payload)
    return payload


def write_trace_audit_export(path: Path | str, payload: dict[str, object]) -> Path:
    _reject_forbidden_fields(payload)
    return write_json_atomic(Path(path), payload)


def build_controlled_trace_advisory(
    advisory_payload: dict[str, object],
    *,
    trace_export: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = {
        "schema_version": 1,
        "artifact_type": "agent_loop_trace_advisory_notes",
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "research_only": True,
        "advisory_only": True,
        "source_loop": _source_loop(trace_export),
        "halo_reference": {
            "repo": "context-labs/HALO",
            "url": "https://github.com/context-labs/HALO",
            "license": "MIT",
            "pinned_ref": HALO_PINNED_REF,
            "intended_usage": "controlled_report_only_advisory_ingestion",
        },
        "controlled_failure_taxonomy_hints": _controlled_failure_taxonomy_hints(advisory_payload.get("findings")),
        "planner_notes": _planner_notes(advisory_payload.get("planner_notes")),
        "rejected_fields": sorted(_collect_rejected_fields(advisory_payload)),
        "guardrails": {
            "no_autonomous_code_edits": True,
            "no_trading_decisions": True,
            "allowed_destinations": ["controlled_failure_taxonomy_hints", "planner_notes"],
            "forbidden_authority": ["direct_planner_authority", "execution_timing", "position_sizing", "buy_sell_decisions"],
        },
    }
    _reject_forbidden_fields(payload)
    return payload


def write_trace_advisory_notes(path: Path | str, payload: dict[str, object]) -> Path:
    _reject_forbidden_fields(payload)
    return write_json_atomic(Path(path), payload)


def _compact_loop(report_payload: dict[str, object]) -> dict[str, object]:
    return {
        "run_id": _str_or_none(report_payload.get("run_id")),
        "status": _str_or_none(report_payload.get("status")),
        "stop_reason": _str_or_none(report_payload.get("stop_reason")),
        "loop_mode": _str_or_none(report_payload.get("loop_mode")),
        "iteration_count": _int_or_zero(report_payload.get("iteration_count")),
        "completed_run_ids": _str_list(report_payload.get("completed_run_ids")),
        "promoted_run_ids": _str_list(report_payload.get("promoted_run_ids")),
    }


def _compact_events(value: object) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    if not isinstance(value, list):
        return events
    for item in value:
        if not isinstance(item, dict):
            continue
        compact = {
            "event": _str_or_none(item.get("event")),
            "iteration": _int_or_none(item.get("iteration")),
            "run_id": _str_or_none(item.get("run_id")),
        }
        events.append({key: nested for key, nested in compact.items() if nested is not None})
    return events


def _compact_iterations(value: object) -> list[dict[str, object]]:
    iterations: list[dict[str, object]] = []
    if not isinstance(value, list):
        return iterations
    for item in value:
        if not isinstance(item, dict):
            continue
        compact = {
            "iteration": _int_or_none(item.get("iteration")),
            "status": _str_or_none(item.get("status")),
            "run_ids": _str_list(item.get("run_ids")),
            "promoted_run_ids": _str_list(item.get("promoted_run_ids")),
            "failure_taxonomy": _str_list(item.get("failure_taxonomy")),
            "meta_policy_selected_action": _str_or_none(item.get("meta_policy_selected_action")),
        }
        iterations.append({key: nested for key, nested in compact.items() if nested is not None and nested != []})
    return iterations


def _failure_taxonomy_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts = value.get("failure_taxonomy_counts")
    if not isinstance(counts, dict):
        return {}
    result: dict[str, int] = {}
    for key, count in counts.items():
        try:
            result[str(key)] = int(count)
        except (TypeError, ValueError):
            continue
    return result


def _source_loop(trace_export: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(trace_export, dict):
        return {}
    loop = trace_export.get("loop")
    if not isinstance(loop, dict):
        return {}
    return {
        key: value
        for key, value in {
            "run_id": _str_or_none(loop.get("run_id")),
            "status": _str_or_none(loop.get("status")),
            "stop_reason": _str_or_none(loop.get("stop_reason")),
            "loop_mode": _str_or_none(loop.get("loop_mode")),
            "iteration_count": _int_or_none(loop.get("iteration_count")),
        }.items()
        if value is not None
    }


def _controlled_failure_taxonomy_hints(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    hints: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = _str_or_none(item.get("failure_taxonomy")) or _str_or_none(item.get("label"))
        note = _str_or_none(item.get("note"))
        if label not in CONTROLLED_FAILURE_TAXONOMY or note is None:
            continue
        hints.append({"label": label, "note": note})
    return hints


def _planner_notes(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _collect_rejected_fields(value: object) -> set[str]:
    rejected: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_ADVISORY_FIELDS:
                rejected.add(key)
            rejected.update(_collect_rejected_fields(nested))
    elif isinstance(value, list):
        for nested in value:
            rejected.update(_collect_rejected_fields(nested))
    return rejected


def _reject_forbidden_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_TRACE_EXPORT_FIELDS:
                raise ValueError(f"forbidden_trace_audit_field:{key}")
            _reject_forbidden_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_fields(nested)


def _str_or_none(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: object) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0
