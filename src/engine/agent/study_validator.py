from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class StudyProposal:
    layer: str
    features: list[str]
    scenario_pack: str
    parameter_ranges: dict[str, tuple[float, float]]
    signature: str
    search_budget: int
    validation_gate_spec: str


@dataclass(frozen=True)
class StudyValidationResult:
    passed: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class StudyValidator:
    def __init__(
        self,
        *,
        approved_layers: set[str],
        feature_contracts: set[str],
        scenario_packs: set[str],
        seen_signatures: set[str],
        max_search_budget: int,
        required_validation_gate_spec: str,
    ) -> None:
        self.approved_layers = approved_layers
        self.feature_contracts = feature_contracts
        self.scenario_packs = scenario_packs
        self.seen_signatures = seen_signatures
        self.max_search_budget = int(max_search_budget)
        self.required_validation_gate_spec = required_validation_gate_spec

    def validate(self, proposal: StudyProposal) -> StudyValidationResult:
        reasons: list[str] = []
        if proposal.layer not in self.approved_layers:
            reasons.append("layer_not_approved")
        missing_features = sorted(set(proposal.features) - self.feature_contracts)
        reasons.extend(f"feature_contract_missing:{name}" for name in missing_features)
        if proposal.scenario_pack not in self.scenario_packs:
            reasons.append("scenario_pack_not_approved")
        for name, bounds in proposal.parameter_ranges.items():
            if not _valid_parameter_bounds(bounds):
                reasons.append(f"invalid_parameter_range:{name}")
        if proposal.signature in self.seen_signatures:
            reasons.append("duplicate_signature")
        if proposal.search_budget <= 0:
            reasons.append("search_budget_not_positive")
        if self.max_search_budget <= 0:
            reasons.append("max_search_budget_not_positive")
        if proposal.search_budget > self.max_search_budget:
            reasons.append("search_budget_exceeded")
        if proposal.validation_gate_spec != self.required_validation_gate_spec:
            reasons.append("validation_gate_spec_mismatch")
        return StudyValidationResult(not reasons, reasons)


def _valid_parameter_bounds(bounds: object) -> bool:
    try:
        if len(bounds) != 2:  # type: ignore[arg-type]
            return False
        lower = float(bounds[0])  # type: ignore[index]
        upper = float(bounds[1])  # type: ignore[index]
    except (TypeError, ValueError, IndexError):
        return False
    return math.isfinite(lower) and math.isfinite(upper) and lower <= upper
