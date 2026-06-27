from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class SymbolTarget:
    symbol: str
    artifact_id: str
    role: str
    target_weight: float
    target_notional: float
    max_loss_budget: float
    max_slippage_bps: float
    max_funding_cost_bps: float
    rebalance_reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SymbolTargetValidation:
    passed: bool
    issues: list[str]


def validate_symbol_target(target: SymbolTarget) -> SymbolTargetValidation:
    issues: list[str] = []
    if not target.symbol:
        issues.append("missing_symbol")
    if not target.artifact_id:
        issues.append("missing_artifact_id")
    if not target.role:
        issues.append("missing_role")
    for field_name in (
        "target_weight",
        "target_notional",
        "max_loss_budget",
        "max_slippage_bps",
        "max_funding_cost_bps",
    ):
        value = float(getattr(target, field_name))
        if not math.isfinite(value):
            issues.append(f"non_finite_{field_name}")
            continue
        if value < 0:
            issues.append(f"negative_{field_name}")
    if not target.rebalance_reason:
        issues.append("missing_rebalance_reason")
    return SymbolTargetValidation(not issues, issues)
