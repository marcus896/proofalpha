from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class MinSampleGateResult:
    passed: bool
    reasons: list[str]


@dataclass(frozen=True)
class MinSampleGate:
    min_oos_trades: int
    min_final_holdout_trades: int
    min_regime_coverage: float

    def evaluate(self, *, oos_trades: int, final_holdout_trades: int, regime_coverage: float) -> MinSampleGateResult:
        reasons: list[str] = []
        if self.min_oos_trades < 0:
            reasons.append("min_oos_trades_threshold_negative")
        if self.min_final_holdout_trades < 0:
            reasons.append("min_final_holdout_trades_threshold_negative")
        if not math.isfinite(float(self.min_regime_coverage)):
            reasons.append("min_regime_coverage_threshold_non_finite")
        if oos_trades < 0:
            reasons.append("oos_trades_negative")
        if final_holdout_trades < 0:
            reasons.append("final_holdout_trades_negative")
        if not math.isfinite(float(regime_coverage)):
            reasons.append("regime_coverage_non_finite")
        if oos_trades < self.min_oos_trades:
            reasons.append("min_oos_trades_not_met")
        if final_holdout_trades < self.min_final_holdout_trades:
            reasons.append("min_final_holdout_trades_not_met")
        if math.isfinite(float(regime_coverage)) and regime_coverage < self.min_regime_coverage:
            reasons.append("min_regime_coverage_not_met")
        return MinSampleGateResult(not reasons, reasons)
