from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class OrderIntentSimulation:
    signal_event: dict[str, object]
    target_portfolio_id: str
    delta_order_plan_id: str
    internal_order_intent: dict[str, object]
    simulated_venue_order_request: dict[str, object]
    simulated_fill_events: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
