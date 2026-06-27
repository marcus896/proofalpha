from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

from engine.execution.idempotency import deterministic_client_order_id
from engine.execution.order_intent import InternalOrderIntent


@dataclass(frozen=True)
class VenueOrderRequest:
    venue: str
    symbol: str
    side: str
    positionSide: str
    type: str
    timeInForce: str | None
    quantity: float
    price: float | None
    stopPrice: float | None
    reduceOnly: bool
    closePosition: bool
    workingType: str
    priceProtect: bool
    newClientOrderId: str
    selfTradePreventionMode: str
    recvWindow: int
    timestamp: int
    metadata_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class VenueOrderRequestValidation:
    passed: bool
    issues: list[str]


def build_venue_order_request(
    intent: InternalOrderIntent,
    *,
    venue: str,
    quantity: float,
    order_type: str,
    time_in_force: str | None = None,
    price: float | None = None,
    stop_price: float | None = None,
    timestamp: int,
    position_side: str = "BOTH",
    working_type: str = "CONTRACT_PRICE",
    price_protect: bool = True,
    self_trade_prevention_mode: str = "EXPIRE_TAKER",
    recv_window: int = 5000,
) -> VenueOrderRequest:
    client_id = deterministic_client_order_id(intent, venue=venue)
    metadata = {
        "intent_id": intent.intent_id,
        "artifact_id": intent.artifact_id,
        "portfolio_plan_id": intent.portfolio_plan_id,
        "guards": {
            "max_slippage_bps": intent.max_slippage_bps,
            "max_spread_bps": intent.max_spread_bps,
            "max_participation_rate": intent.max_participation_rate,
            "funding": intent.funding_guard_policy,
            "liquidation": intent.liquidation_guard_policy,
        },
    }
    return VenueOrderRequest(
        venue=venue,
        symbol=intent.symbol,
        side=intent.side,
        positionSide=position_side,
        type=order_type,
        timeInForce=time_in_force,
        quantity=float(quantity),
        price=price,
        stopPrice=stop_price,
        reduceOnly=bool(intent.reduce_only_required),
        closePosition=intent.intent_type == "close",
        workingType=working_type,
        priceProtect=bool(price_protect),
        newClientOrderId=client_id,
        selfTradePreventionMode=self_trade_prevention_mode,
        recvWindow=int(recv_window),
        timestamp=int(timestamp),
        metadata_hash=_stable_hash(metadata),
    )


def validate_venue_order_request(request: VenueOrderRequest) -> VenueOrderRequestValidation:
    issues: list[str] = []
    if not request.venue:
        issues.append("missing_venue")
    if not request.symbol:
        issues.append("missing_symbol")
    if request.side not in {"BUY", "SELL"}:
        issues.append("invalid_side")
    if request.quantity <= 0:
        issues.append("invalid_quantity")
    if request.type.upper() == "LIMIT" and request.price is None:
        issues.append("limit_price_required")
    if not request.newClientOrderId:
        issues.append("missing_client_order_id")
    if len(request.metadata_hash) != 64:
        issues.append("invalid_metadata_hash")
    return VenueOrderRequestValidation(not issues, issues)


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
