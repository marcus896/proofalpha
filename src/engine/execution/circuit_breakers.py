from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CircuitBreakerResult:
    passed: bool
    rejections: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_circuit_breakers(
    *,
    daily_loss: float,
    daily_loss_limit: float,
    weekly_loss: float,
    weekly_loss_limit: float,
    drawdown: float,
    drawdown_limit: float,
) -> CircuitBreakerResult:
    rejections: list[str] = []
    if daily_loss > daily_loss_limit:
        rejections.append("daily_loss_breaker")
    if weekly_loss > weekly_loss_limit:
        rejections.append("weekly_loss_breaker")
    if drawdown > drawdown_limit:
        rejections.append("drawdown_breaker")
    return CircuitBreakerResult(not rejections, rejections)
