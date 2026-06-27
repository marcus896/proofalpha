from __future__ import annotations

import hashlib
import json

from engine.execution.order_intent import InternalOrderIntent


def deterministic_client_order_id(intent: InternalOrderIntent, *, venue: str) -> str:
    payload = {
        "venue": venue,
        "intent_id": intent.intent_id,
        "artifact_id": intent.artifact_id,
        "portfolio_plan_id": intent.portfolio_plan_id,
        "symbol": intent.symbol,
        "side": intent.side,
        "delta": intent.desired_position_delta,
    }
    return "cid-" + _stable_hash(payload)[:28]


class IdempotencyManager:
    def __init__(self) -> None:
        self._client_order_ids: set[str] = set()

    def register(self, intent: InternalOrderIntent, *, venue: str) -> bool:
        client_id = deterministic_client_order_id(intent, venue=venue)
        if client_id in self._client_order_ids:
            return False
        self._client_order_ids.add(client_id)
        return True


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
