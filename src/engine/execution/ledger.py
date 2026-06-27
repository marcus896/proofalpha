from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    event_type: str
    payload: dict[str, object]

    @classmethod
    def order(cls, event_id: str, *, symbol: str, side: str, qty: float, price: float) -> "LedgerEvent":
        return cls(event_id, "ORDER", {"symbol": symbol, "side": side.upper(), "qty": float(qty), "price": float(price)})

    @classmethod
    def fill(
        cls,
        event_id: str,
        *,
        order_id: str,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        fee: float = 0.0,
    ) -> "LedgerEvent":
        return cls(
            event_id,
            "FILL",
            {
                "fill_id": event_id,
                "order_id": order_id,
                "symbol": symbol,
                "side": side.upper(),
                "qty": float(qty),
                "price": float(price),
                "fee": float(fee),
            },
        )

    @classmethod
    def funding(cls, event_id: str, *, symbol: str, amount: float) -> "LedgerEvent":
        return cls(event_id, "FUNDING", {"symbol": symbol, "amount": float(amount)})

    @classmethod
    def risk(cls, event_id: str, *, reason_code: str) -> "LedgerEvent":
        return cls(event_id, "RISK", {"reason_code": reason_code})

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ExecutionLedger:
    def __init__(self, events: list[LedgerEvent] | None = None) -> None:
        self.events: list[LedgerEvent] = list(events or [])

    def append(self, event: LedgerEvent) -> None:
        self.events.append(event)

    @property
    def digest(self) -> str:
        return _stable_hash([event.to_dict() for event in self.events])


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
