from __future__ import annotations

from pathlib import Path

from engine.agent.contracts import ContractCheck
from engine.io.artifacts import write_json_atomic
from engine.strategy.dsl import build_bounded_strategy_spec_from_payload, validate_bounded_strategy_spec


ALLOWED_MODEL_CHANGE_TYPES = {"strategy", "feature", "cost", "risk", "calibration", "execution"}
ALLOWED_APPROVAL_STATES = {"proposed", "approved", "rejected", "rollback_ready"}


def validate_model_change_record(record: dict[str, object]) -> ContractCheck:
    reasons: list[str] = []
    model_type = record.get("model_type")
    if model_type not in ALLOWED_MODEL_CHANGE_TYPES:
        reasons.append("model_type_not_allowed")
    for field_name in ("model_version", "diff_summary", "replay_comparison", "rollback_target", "approval_state"):
        value = record.get(field_name)
        if value in (None, "", {}, []):
            reasons.append(f"missing:{field_name}")
    if record.get("approval_state") not in ALLOWED_APPROVAL_STATES:
        reasons.append("approval_state_not_allowed")
    replay = record.get("replay_comparison")
    if replay is not None and not isinstance(replay, dict):
        reasons.append("replay_comparison_not_object")
    return ContractCheck(passed=not reasons, reasons=reasons, payload=dict(record))


def build_model_change_records(
    *,
    previous_payload: dict[str, object],
    next_payload: dict[str, object],
    validation_status: str,
    objective_score: float | None,
) -> list[dict[str, object]]:
    previous_validation = validate_bounded_strategy_spec(build_bounded_strategy_spec_from_payload(previous_payload))
    next_validation = validate_bounded_strategy_spec(build_bounded_strategy_spec_from_payload(next_payload))
    if not previous_validation.passed:
        raise ValueError("previous_payload_not_bounded_strategy")
    if not next_validation.passed:
        raise ValueError(";".join(next_validation.reasons))

    approval_state = "approved" if validation_status in {"evaluated", "validated", "promoted"} else "proposed"
    previous_spec = previous_validation.normalized_spec
    next_spec = next_validation.normalized_spec

    records: list[dict[str, object]] = []
    _append_change_record(
        records,
        model_type="strategy",
        before_value={
            "family": previous_spec.get("family"),
            "structure": previous_spec.get("structure"),
            "parameter_schema": previous_spec.get("parameter_schema"),
        },
        after_value={
            "family": next_spec.get("family"),
            "structure": next_spec.get("structure"),
            "parameter_schema": next_spec.get("parameter_schema"),
        },
        previous_identity_hash=previous_validation.identity_hash,
        next_identity_hash=next_validation.identity_hash,
        approval_state=approval_state,
        validation_status=validation_status,
        objective_score=objective_score,
    )
    _append_change_record(
        records,
        model_type="feature",
        before_value={"feature_contracts": previous_spec.get("feature_contracts")},
        after_value={"feature_contracts": next_spec.get("feature_contracts")},
        previous_identity_hash=previous_validation.identity_hash,
        next_identity_hash=next_validation.identity_hash,
        approval_state=approval_state,
        validation_status=validation_status,
        objective_score=objective_score,
    )
    _append_change_record(
        records,
        model_type="risk",
        before_value={"risk_hooks": previous_spec.get("risk_hooks")},
        after_value={"risk_hooks": next_spec.get("risk_hooks")},
        previous_identity_hash=previous_validation.identity_hash,
        next_identity_hash=next_validation.identity_hash,
        approval_state=approval_state,
        validation_status=validation_status,
        objective_score=objective_score,
    )
    _append_change_record(
        records,
        model_type="execution",
        before_value={"execution_policy": previous_spec.get("execution_policy")},
        after_value={"execution_policy": next_spec.get("execution_policy")},
        previous_identity_hash=previous_validation.identity_hash,
        next_identity_hash=next_validation.identity_hash,
        approval_state=approval_state,
        validation_status=validation_status,
        objective_score=objective_score,
    )
    return records


def write_model_governance_artifact(
    *,
    output_dir: Path,
    run_id: str,
    records: list[dict[str, object]],
) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / f"{run_id}.model-governance.json"
    write_json_atomic(
        artifact_path,
        {
            "run_id": run_id,
            "record_count": len(records),
            "records": [dict(record) for record in records],
        },
    )
    return str(artifact_path)


def _append_change_record(
    records: list[dict[str, object]],
    *,
    model_type: str,
    before_value: dict[str, object],
    after_value: dict[str, object],
    previous_identity_hash: str | None,
    next_identity_hash: str | None,
    approval_state: str,
    validation_status: str,
    objective_score: float | None,
) -> None:
    if before_value == after_value:
        return
    changed_fields = sorted(
        field_name
        for field_name in set(before_value) | set(after_value)
        if before_value.get(field_name) != after_value.get(field_name)
    )
    record = {
        "model_type": model_type,
        "model_version": f"{model_type}-{(next_identity_hash or 'unknown')[:12]}",
        "diff_summary": f"changed {', '.join(changed_fields)}",
        "replay_comparison": {
            "previous_identity_hash": previous_identity_hash,
            "next_identity_hash": next_identity_hash,
            "validation_status": validation_status,
            "objective_score": objective_score,
            "changed_fields": changed_fields,
        },
        "rollback_target": f"{model_type}-{(previous_identity_hash or 'baseline')[:12]}",
        "approval_state": approval_state,
        "before": before_value,
        "after": after_value,
    }
    if validate_model_change_record(record).passed:
        records.append(record)
