from __future__ import annotations

import hashlib
import json

from engine.execution.errors import DuplicateIntentError
from engine.execution.idempotency import IdempotencyManager
from engine.execution.order_intent import InternalOrderIntent, validate_internal_order_intent
from engine.execution.order_state import (
    OrderLifecycleState,
    OrderRecord,
    OrderStateEvent,
    apply_transition,
)


class OrderManager:
    def __init__(self, *, venue: str = "binance_usdm") -> None:
        self.venue = venue
        self._idempotency = IdempotencyManager()
        self._orders: dict[str, OrderRecord] = {}
        self._order_by_intent: dict[str, str] = {}

    def create_order(self, intent: InternalOrderIntent) -> OrderRecord:
        validation = validate_internal_order_intent(intent)
        if not validation.passed:
            raise ValueError(",".join(validation.issues))
        if not self._idempotency.register(intent, venue=self.venue):
            raise DuplicateIntentError(f"duplicate_intent:{intent.intent_id}")
        order_id = "order-" + _stable_hash({"venue": self.venue, "intent_id": intent.intent_id})[:24]
        event = OrderStateEvent(order_id, None, OrderLifecycleState.CREATED, "intent_created")
        record = OrderRecord(
            order_id=order_id,
            intent_id=intent.intent_id,
            lifecycle_state=OrderLifecycleState.CREATED,
            events=(event,),
        )
        self._orders[order_id] = record
        self._order_by_intent[intent.intent_id] = order_id
        return record

    def transition(self, order_id: str, to_state: OrderLifecycleState, *, reason: str) -> OrderRecord:
        record = self._orders[order_id]
        updated = apply_transition(record, to_state, reason=reason)
        self._orders[order_id] = updated
        return updated

    def get(self, order_id: str) -> OrderRecord:
        return self._orders[order_id]


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
