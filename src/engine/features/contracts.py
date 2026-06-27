from __future__ import annotations

from dataclasses import asdict, dataclass
import math


EXECUTION_MODES = {"shadow", "paper", "live-disabled"}
KNOWN_MODES = {"research", "validation", *EXECUTION_MODES}
KNOWN_LEAKAGE_RISKS = {"low", "medium", "high", "research_only"}


@dataclass(frozen=True)
class FeatureContract:
    name: str
    source: str
    timestamp_source: str
    earliest_available_at: str
    allowed_modes: set[str]
    max_age_seconds: int
    leakage_risk: str
    required_symbol_fields: set[str]
    input_fields: tuple[str, ...] = ()
    lookback_bars: int = 0
    warmup_bars: int = 0
    availability_lag_bars: int = 0
    uses_centered_window: bool = False
    uses_negative_shift: bool = False
    uses_future_bars: bool = False
    allows_repainting: bool = False
    smoothing: str = "causal"

    @classmethod
    def paper_safe(cls, name: str, *, source: str, max_age_seconds: int) -> "FeatureContract":
        return cls(
            name=name,
            source=source,
            timestamp_source="exchange_event_time",
            earliest_available_at="bar_close",
            allowed_modes={"research", "validation", "shadow", "paper"},
            max_age_seconds=max_age_seconds,
            leakage_risk="low",
            required_symbol_fields=set(),
            input_fields=(name,),
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["allowed_modes"] = sorted(self.allowed_modes)
        payload["required_symbol_fields"] = sorted(self.required_symbol_fields)
        payload["input_fields"] = list(self.input_fields)
        return payload


@dataclass(frozen=True)
class FeatureContractValidation:
    passed: bool
    issues: list[str]


def validate_feature_contract(contract: FeatureContract) -> FeatureContractValidation:
    issues: list[str] = []
    if not contract.name:
        issues.append("missing_name")
    if not contract.source:
        issues.append("missing_source")
    if not contract.timestamp_source:
        issues.append("missing_timestamp_source")
    if not contract.earliest_available_at:
        issues.append("missing_earliest_available_at")
    if not math.isfinite(float(contract.max_age_seconds)):
        issues.append("non_finite_max_age_seconds")
    elif contract.max_age_seconds < 0:
        issues.append("negative_max_age_seconds")
    unknown_modes = sorted(contract.allowed_modes - KNOWN_MODES)
    issues.extend(f"unknown_mode:{mode}" for mode in unknown_modes)
    if contract.leakage_risk not in KNOWN_LEAKAGE_RISKS:
        issues.append(f"unknown_leakage_risk:{contract.leakage_risk}")
    if contract.leakage_risk == "research_only" and contract.allowed_modes.intersection(EXECUTION_MODES):
        issues.append("research_only_execution_mode_allowed")
    if contract.lookback_bars < 0:
        issues.append("negative_lookback_bars")
    if contract.warmup_bars < 0:
        issues.append("negative_warmup_bars")
    if contract.availability_lag_bars < 0:
        issues.append("negative_availability_lag_bars")
    if contract.uses_centered_window:
        issues.append("centered_window")
    if contract.uses_negative_shift:
        issues.append("negative_shift")
    if contract.uses_future_bars:
        issues.append("future_bars")
    if contract.allows_repainting:
        issues.append("repainting_allowed")
    if str(contract.smoothing).lower() not in {"causal", "none", "recursive", "expanding"}:
        issues.append(f"non_causal_smoothing:{contract.smoothing}")
    return FeatureContractValidation(not issues, issues)
