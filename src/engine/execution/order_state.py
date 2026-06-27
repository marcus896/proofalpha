from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from engine.execution.errors import InvalidOrderTransitionError


class OrderLifecycleState(StrEnum):
    CREATED = "CREATED"
    RISK_APPROVED = "RISK_APPROVED"
    TRANSLATED = "TRANSLATED"
    SUBMITTED = "SUBMITTED"
    ACKED = "ACKED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    ORPHANED = "ORPHANED"
    RECONCILED = "RECONCILED"


TERMINAL_STATES = {
    OrderLifecycleState.FILLED,
    OrderLifecycleState.CANCELED,
    OrderLifecycleState.EXPIRED,
    OrderLifecycleState.REJECTED,
    OrderLifecycleState.RECONCILED,
}

ALLOWED_TRANSITIONS = {
    OrderLifecycleState.CREATED: {
        OrderLifecycleState.RISK_APPROVED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.EXPIRED,
    },
    OrderLifecycleState.RISK_APPROVED: {OrderLifecycleState.TRANSLATED, OrderLifecycleState.REJECTED},
    OrderLifecycleState.TRANSLATED: {OrderLifecycleState.SUBMITTED, OrderLifecycleState.REJECTED},
    OrderLifecycleState.SUBMITTED: {
        OrderLifecycleState.ACKED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.ORPHANED,
        OrderLifecycleState.CANCEL_REQUESTED,
    },
    OrderLifecycleState.ACKED: {
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.FILLED,
        OrderLifecycleState.CANCEL_REQUESTED,
        OrderLifecycleState.EXPIRED,
        OrderLifecycleState.ORPHANED,
    },
    OrderLifecycleState.PARTIALLY_FILLED: {
        OrderLifecycleState.FILLED,
        OrderLifecycleState.CANCEL_REQUESTED,
        OrderLifecycleState.EXPIRED,
        OrderLifecycleState.ORPHANED,
    },
    OrderLifecycleState.CANCEL_REQUESTED: {OrderLifecycleState.CANCELED, OrderLifecycleState.FILLED, OrderLifecycleState.ORPHANED},
    OrderLifecycleState.ORPHANED: {OrderLifecycleState.RECONCILED, OrderLifecycleState.REJECTED},
}


@dataclass(frozen=True)
class OrderStateEvent:
    order_id: str
    from_state: OrderLifecycleState | None
    to_state: OrderLifecycleState
    reason: str


@dataclass(frozen=True)
class OrderRecord:
    order_id: str
    intent_id: str
    lifecycle_state: OrderLifecycleState
    events: tuple[OrderStateEvent, ...]


def apply_transition(record: OrderRecord, to_state: OrderLifecycleState, *, reason: str) -> OrderRecord:
    if record.lifecycle_state in TERMINAL_STATES:
        raise InvalidOrderTransitionError(f"terminal_order_state:{record.lifecycle_state}")
    allowed = ALLOWED_TRANSITIONS.get(record.lifecycle_state, set())
    if to_state not in allowed:
        raise InvalidOrderTransitionError(f"invalid_order_transition:{record.lifecycle_state}->{to_state}")
    event = OrderStateEvent(record.order_id, record.lifecycle_state, to_state, reason)
    return OrderRecord(
        order_id=record.order_id,
        intent_id=record.intent_id,
        lifecycle_state=to_state,
        events=(*record.events, event),
    )
