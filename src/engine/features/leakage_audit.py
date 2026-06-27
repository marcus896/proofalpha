from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from typing import Any

from engine.features.contracts import FeatureContract, validate_feature_contract


@dataclass(frozen=True)
class LeakageAuditReport:
    status: str
    passed: bool
    issues: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_feature_leakage(
    values: dict[str, Any],
    *,
    contracts: dict[str, FeatureContract],
    as_of_utc: str,
    observed_at_by_field: dict[str, str],
    mode: str,
) -> LeakageAuditReport:
    issues: list[str] = []
    as_of = _parse_utc(as_of_utc)
    for name in sorted(values):
        contract = contracts.get(name)
        if contract is None:
            issues.append(f"missing_contract:{name}")
            continue
        if contract.leakage_risk == "research_only" and mode != "research":
            issues.append(f"research_only_field:{name}")
        observed_at = _parse_utc(observed_at_by_field.get(name))
        if observed_at is None:
            issues.append(f"missing_observed_at:{name}")
        elif observed_at > as_of:
            issues.append(f"future_timestamp:{name}")
    return LeakageAuditReport(
        status="passed" if not issues else "failed",
        passed=not issues,
        issues=issues,
    )


def audit_feature_causality_from_signals(
    baseline_signals: dict[str, list[Any]],
    *,
    mutated_signals: dict[str, list[Any]],
    contracts: dict[str, FeatureContract],
    spike_index: int,
    mode: str,
) -> LeakageAuditReport:
    issues: list[str] = []
    if spike_index < 0:
        issues.append("negative_spike_index")
    for name in sorted(set(baseline_signals) | set(mutated_signals)):
        contract = contracts.get(name)
        if contract is None:
            issues.append(f"missing_contract:{name}")
            continue
        contract_validation = validate_feature_contract(contract)
        for issue in contract_validation.issues:
            issues.append(f"{issue}:{name}")
        if not contract.input_fields and not contract.required_symbol_fields:
            issues.append(f"missing_input_fields:{name}")
        if mode not in contract.allowed_modes:
            issues.append(f"mode_not_allowed:{name}:{mode}")
        baseline = baseline_signals.get(name)
        mutated = mutated_signals.get(name)
        if not isinstance(baseline, list) or not isinstance(mutated, list):
            issues.append(f"missing_signal_series:{name}")
            continue
        if len(baseline) != len(mutated):
            issues.append(f"signal_length_mismatch:{name}")
            continue
        if spike_index >= len(baseline):
            issues.append(f"spike_index_out_of_range:{name}")
            continue
        first_observable_index = spike_index + max(0, int(contract.availability_lag_bars))
        for index in range(min(first_observable_index, len(baseline))):
            if not _same_signal_value(baseline[index], mutated[index]):
                issues.append(f"future_spike_changed_pre_observable_signal:{name}:{index}")
                break
    return LeakageAuditReport(
        status="passed" if not issues else "failed",
        passed=not issues,
        issues=issues,
    )


def build_feature_causality_audit_report(payload: dict[str, object]) -> dict[str, object]:
    contracts = {
        str(item.get("name")): _feature_contract_from_payload(item)
        for item in _dict_items(payload.get("features"))
        if isinstance(item.get("name"), str)
    }
    baseline = {
        str(key): list(value)
        for key, value in _dict_mapping(payload.get("baseline_signals")).items()
        if isinstance(value, list)
    }
    mutated = {
        str(key): list(value)
        for key, value in _dict_mapping(payload.get("mutated_signals")).items()
        if isinstance(value, list)
    }
    report = audit_feature_causality_from_signals(
        baseline,
        mutated_signals=mutated,
        contracts=contracts,
        spike_index=int(payload.get("spike_index", 0) or 0),
        mode=str(payload.get("mode", "validation") or "validation"),
    )
    return {
        "artifact_type": "feature_causality_audit",
        "status": report.status,
        "passed": report.passed,
        "issues": report.issues,
        "feature_count": len(contracts),
        "spike_index": int(payload.get("spike_index", 0) or 0),
    }


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _same_signal_value(left: Any, right: Any) -> bool:
    if isinstance(left, int | float) and isinstance(right, int | float):
        left_float = float(left)
        right_float = float(right)
        if math.isnan(left_float) and math.isnan(right_float):
            return True
        return abs(left_float - right_float) <= 1e-12
    return left == right


def _feature_contract_from_payload(payload: dict[str, object]) -> FeatureContract:
    return FeatureContract(
        name=str(payload.get("name", "")),
        source=str(payload.get("source", "")),
        timestamp_source=str(payload.get("timestamp_source", "")),
        earliest_available_at=str(payload.get("earliest_available_at", "")),
        allowed_modes=set(_string_items(payload.get("allowed_modes"))) or {"research", "validation"},
        max_age_seconds=int(payload.get("max_age_seconds", 0) or 0),
        leakage_risk=str(payload.get("leakage_risk", "low") or "low"),
        required_symbol_fields=set(_string_items(payload.get("required_symbol_fields"))),
        input_fields=tuple(_string_items(payload.get("input_fields"))),
        lookback_bars=int(payload.get("lookback_bars", 0) or 0),
        warmup_bars=int(payload.get("warmup_bars", 0) or 0),
        availability_lag_bars=int(payload.get("availability_lag_bars", 0) or 0),
        uses_centered_window=bool(payload.get("uses_centered_window")),
        uses_negative_shift=bool(payload.get("uses_negative_shift")),
        uses_future_bars=bool(payload.get("uses_future_bars")),
        allows_repainting=bool(payload.get("allows_repainting")),
        smoothing=str(payload.get("smoothing", "causal") or "causal"),
    )


def _dict_items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _dict_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list | tuple | set):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]
