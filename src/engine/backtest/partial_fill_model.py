from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PartialFillModel:
    fill_probability: float
    queue_position_estimate: float
    filled_quantity: float
    requested_quantity: float
    timeout_policy: str = "cancel_remainder"

    @property
    def unfilled_quantity(self) -> float:
        return max(0.0, self.requested_quantity - self.filled_quantity)
