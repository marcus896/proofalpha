from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from engine.agent.trace_audit import CONTROLLED_FAILURE_TAXONOMY
from engine.io.artifacts import write_json_atomic


FORBIDDEN_DEBATE_FIELDS = {"trade_action", "position_size", "executor_action", "emit_buy_sell_size"}


def build_report_only_research_debate(
    candidate_payload: dict[str, object],
    *,
    trace_advisory_notes: dict[str, object] | None = None,
    source_path: str | None = None,
) -> dict[str, object]:
    failure_taxonomy_hints = _controlled_failure_taxonomy_hints(candidate_payload, trace_advisory_notes)
    validation_notes = _validation_notes(candidate_payload, trace_advisory_notes)
    payload = {
        "schema_version": 1,
        "artifact_type": "agent_research_debate_report",
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "research_only": True,
        "report_only": True,
        "executable_artifact_created": False,
        "source": {
            "kind": "candidate_report",
            "path": source_path,
        },
        "provenance": {
            "tradingagents_direct_use": False,
            "tradingagents_status": "not_used_internal_contract",
            "tradingagents_pin_required_before_direct_use": True,
            "contract_source": "internal_optimization_plan_requirements",
        },
        "candidate": _candidate_summary(candidate_payload),
        "reports": [
            {
                "role": "validation_researcher",
                "allowed_scope": "validation evidence review only",
                "findings": validation_notes,
            },
            {
                "role": "risk_analyst",
                "allowed_scope": "risk and failure-taxonomy review only",
                "findings": [f"failure_taxonomy_hint:{label}" for label in failure_taxonomy_hints],
            },
        ],
        "controlled_outputs": {
            "validation_notes": validation_notes,
            "failure_taxonomy_hints": failure_taxonomy_hints,
        },
        "excluded_roles": [
            "trader",
            "portfolio_manager",
            "order_execution_actor",
            "order_timing_actor",
            "sizing_actor",
        ],
        "authority_limits": {
            "promotion_gates_sole_authority": True,
            "immutable_artifact_contract_sole_authority": True,
            "cannot_create_executable_artifacts": True,
            "cannot_emit_buy_sell_decisions": True,
            "cannot_emit_position_sizing": True,
        },
    }
    _reject_forbidden_fields(payload)
    return payload


def write_research_debate_report(path: Path | str, payload: dict[str, object]) -> Path:
    _reject_forbidden_fields(payload)
    return write_json_atomic(Path(path), payload)


def _candidate_summary(candidate_payload: dict[str, object]) -> dict[str, object]:
    snapshot = candidate_payload.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
    return {
        "run_id": _str_or_none(candidate_payload.get("run_id")),
        "symbol": _str_or_none(candidate_payload.get("symbol")) or _str_or_none(snapshot.get("symbol")),
        "timeframe": _str_or_none(candidate_payload.get("timeframe")) or _str_or_none(snapshot.get("timeframe")),
    }


def _validation_notes(
    candidate_payload: dict[str, object],
    trace_advisory_notes: dict[str, object] | None,
) -> list[str]:
    notes: list[str] = []
    validation_bundle = candidate_payload.get("validation_bundle")
    failed_gates: object = None
    if isinstance(validation_bundle, dict):
        failed_gates = validation_bundle.get("failed_gates")
    if failed_gates is None:
        failed_gates = candidate_payload.get("failed_gates")
    for gate_name in _str_list(failed_gates):
        notes.append(f"failed_gate:{gate_name}")
    if isinstance(trace_advisory_notes, dict):
        for note in _str_list(trace_advisory_notes.get("planner_notes")):
            notes.append(f"planner_note:{note}")
    return _dedupe(notes)


def _controlled_failure_taxonomy_hints(
    candidate_payload: dict[str, object],
    trace_advisory_notes: dict[str, object] | None,
) -> list[str]:
    labels = _str_list(candidate_payload.get("failure_taxonomy"))
    if isinstance(trace_advisory_notes, dict):
        for item in trace_advisory_notes.get("controlled_failure_taxonomy_hints", []):
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            if isinstance(label, str):
                labels.append(label)
    return _dedupe([label for label in labels if label in CONTROLLED_FAILURE_TAXONOMY])


def _reject_forbidden_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_DEBATE_FIELDS:
                raise ValueError(f"forbidden_research_debate_field:{key}")
            _reject_forbidden_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_fields(nested)


def _str_or_none(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
