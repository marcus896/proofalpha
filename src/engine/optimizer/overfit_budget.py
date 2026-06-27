from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class OverfitBudgetResult:
    passed: bool
    reasons: list[str]


@dataclass(frozen=True)
class OverfitBudget:
    max_trials: int
    max_strategy_variants: int
    max_parameter_reuse: int
    max_failed_gate_retries: int
    pbo_ceiling: float
    multiple_testing_penalty_policy: str

    def evaluate(
        self,
        *,
        trials: int,
        strategy_variants: int,
        parameter_reuse: int,
        failed_gate_retries: int,
        pbo: float,
    ) -> OverfitBudgetResult:
        reasons: list[str] = []
        for name, value in (
            ("trials", trials),
            ("strategy_variants", strategy_variants),
            ("parameter_reuse", parameter_reuse),
            ("failed_gate_retries", failed_gate_retries),
        ):
            if int(value) < 0:
                reasons.append(f"negative_{name}")
        if not math.isfinite(float(pbo)):
            reasons.append("non_finite_pbo")
        if not math.isfinite(float(self.pbo_ceiling)):
            reasons.append("non_finite_pbo_ceiling")
        for name, value in (
            ("max_trials", self.max_trials),
            ("max_strategy_variants", self.max_strategy_variants),
            ("max_parameter_reuse", self.max_parameter_reuse),
            ("max_failed_gate_retries", self.max_failed_gate_retries),
        ):
            if int(value) < 0:
                reasons.append(f"negative_{name}")
        if trials > self.max_trials:
            reasons.append("max_trials_exceeded")
        if strategy_variants > self.max_strategy_variants:
            reasons.append("max_strategy_variants_exceeded")
        if parameter_reuse > self.max_parameter_reuse:
            reasons.append("max_parameter_reuse_exceeded")
        if failed_gate_retries > self.max_failed_gate_retries:
            reasons.append("max_failed_gate_retries_exceeded")
        if math.isfinite(float(pbo)) and math.isfinite(float(self.pbo_ceiling)) and pbo > self.pbo_ceiling:
            reasons.append("pbo_ceiling_exceeded")
        return OverfitBudgetResult(not reasons, reasons)
