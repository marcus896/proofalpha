from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class ForecastState(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    BASELINE_PASSED = "BASELINE_PASSED"
    FEATURE_ALLOWED = "FEATURE_ALLOWED"
    DECAYING = "DECAYING"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class ForecastDecayGateResult:
    state: str
    action: str
    reasons: list[str]
    direct_order_change: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ForecastDecayGate:
    min_baseline_edge: float
    max_calibration_error: float
    max_directional_decay: float
    max_staleness: int
    min_symbol_coverage: float

    def evaluate(
        self,
        *,
        baseline_edge: float,
        calibration_error: float,
        directional_decay: float,
        staleness_seconds: float,
        symbol_coverage: float,
    ) -> ForecastDecayGateResult:
        reasons: list[str] = []
        if baseline_edge < self.min_baseline_edge:
            reasons.append("baseline_edge_below_min")
        if calibration_error > self.max_calibration_error:
            reasons.append("calibration_error_above_max")
        if directional_decay > self.max_directional_decay:
            reasons.append("directional_decay_above_max")
        if staleness_seconds > float(self.max_staleness):
            reasons.append("staleness_above_max")
        if symbol_coverage < self.min_symbol_coverage:
            reasons.append("symbol_coverage_below_min")
        if reasons:
            return ForecastDecayGateResult(ForecastState.DISABLED.value, "disable_research_feature", reasons)
        return ForecastDecayGateResult(ForecastState.FEATURE_ALLOWED.value, "allow_research_feature", [])
