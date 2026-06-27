from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from engine.features.contracts import FeatureContract, validate_feature_contract


@dataclass(frozen=True)
class FeatureTtlResult:
    passed: bool
    issues: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_feature_ttl(
    values: dict[str, Any],
    *,
    contracts: dict[str, FeatureContract],
    mode: str,
    now_utc: str,
    observed_at_by_field: dict[str, str],
) -> FeatureTtlResult:
    issues: list[str] = []
    now = _parse_utc(now_utc)
    for name in sorted(values):
        contract = contracts.get(name)
        if contract is None:
            issues.append(f"missing_contract:{name}")
            continue
        validation = validate_feature_contract(contract)
        issues.extend(f"{name}:{issue}" for issue in validation.issues)
        if mode not in contract.allowed_modes:
            issues.append(f"mode_not_allowed:{name}")
        observed_at = _parse_utc(observed_at_by_field.get(name))
        if observed_at is None:
            issues.append(f"missing_observed_at:{name}")
            continue
        if observed_at > now:
            issues.append(f"future_timestamp:{name}")
        if contract.max_age_seconds >= 0 and (now - observed_at).total_seconds() > contract.max_age_seconds:
            issues.append(f"feature_stale:{name}")
    return FeatureTtlResult(not issues, issues)


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
