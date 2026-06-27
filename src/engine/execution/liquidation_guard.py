from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LiquidationGuardConfig:
    min_distance_bps: float
    stress_move_bps: float


@dataclass(frozen=True)
class LiquidationGuardResult:
    passed: bool
    rejections: list[str]
    distance_bps: float
    stress_distance_bps: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class LiquidationGuard:
    def __init__(self, config: LiquidationGuardConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        side: str,
        entry_price: float,
        mark_price: float,
        liquidation_price: float,
    ) -> LiquidationGuardResult:
        distance = abs(float(mark_price) - float(liquidation_price)) / max(abs(float(mark_price)), 1e-9) * 10_000.0
        stress_distance = distance - float(self.config.stress_move_bps)
        rejections: list[str] = []
        if distance < self.config.min_distance_bps:
            rejections.append("liquidation_distance_breach")
        if stress_distance < self.config.min_distance_bps:
            rejections.append("stress_liquidation_distance_breach")
        return LiquidationGuardResult(
            passed=not rejections,
            rejections=rejections,
            distance_bps=round(distance, 12),
            stress_distance_bps=round(stress_distance, 12),
        )
