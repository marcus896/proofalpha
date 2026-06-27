from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ForecastDriftResult:
    status: str
    directional_decay: float
    direct_order_change: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ForecastDriftMonitor:
    max_directional_decay: float

    def evaluate(self, *, previous_directional_accuracy: float, current_directional_accuracy: float) -> ForecastDriftResult:
        decay = max(0.0, float(previous_directional_accuracy) - float(current_directional_accuracy))
        if decay > self.max_directional_decay:
            return ForecastDriftResult("DISABLED", decay)
        if decay > 0.0:
            return ForecastDriftResult("DECAYING", decay)
        return ForecastDriftResult("BASELINE_PASSED", decay)
