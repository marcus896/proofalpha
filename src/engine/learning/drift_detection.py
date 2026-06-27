from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DriftReport:
    warnings: list[str]
    studies: list[str]
    direct_trading_change_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def detect_learning_drift(*, metrics: dict[str, float], thresholds: dict[str, float]) -> DriftReport:
    warnings = [
        f"drift:{name}"
        for name, value in sorted(metrics.items())
        if abs(float(value)) > float(thresholds.get(name, float("inf")))
    ]
    studies = [warning.replace("drift:", "study:") for warning in warnings]
    return DriftReport(warnings=warnings, studies=studies)
