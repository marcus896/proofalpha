from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

from engine.execution.ledger import LedgerEvent


@dataclass(frozen=True)
class StateProjection:
    positions: dict[str, float]
    cash: float
    fees: float
    funding: float
    realized_pnl: float
    projection_digest: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def rebuild_state_projection(events: list[LedgerEvent] | tuple[LedgerEvent, ...]) -> StateProjection:
    positions: dict[str, float] = {}
    cash = 0.0
    fees = 0.0
    funding = 0.0
    realized_pnl = 0.0
    seen_fills: set[str] = set()
    for event in events:
        payload = event.payload
        if event.event_type == "FILL":
            fill_id = str(payload.get("fill_id") or event.event_id)
            if fill_id in seen_fills:
                continue
            seen_fills.add(fill_id)
            symbol = str(payload["symbol"])
            side = str(payload["side"]).upper()
            qty = float(payload.get("qty", 0.0))
            price = float(payload.get("price", 0.0))
            fee = float(payload.get("fee", 0.0))
            signed_qty = qty if side == "BUY" else -qty
            positions[symbol] = round(positions.get(symbol, 0.0) + signed_qty, 12)
            cash -= signed_qty * price
            fees += fee
            cash -= fee
        elif event.event_type == "FUNDING":
            amount = float(payload.get("amount", 0.0))
            funding += amount
            cash += amount
    payload = {
        "positions": dict(sorted(positions.items())),
        "cash": round(cash, 12),
        "fees": round(fees, 12),
        "funding": round(funding, 12),
        "realized_pnl": round(realized_pnl, 12),
    }
    return StateProjection(
        positions=payload["positions"],
        cash=payload["cash"],
        fees=payload["fees"],
        funding=payload["funding"],
        realized_pnl=payload["realized_pnl"],
        projection_digest=_stable_hash(payload),
    )


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
