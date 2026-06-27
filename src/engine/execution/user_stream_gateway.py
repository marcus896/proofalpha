from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class UserStreamEvent:
    event_type: str
    event_time: str
    order_id: str | None
    symbol: str | None
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def user_stream_event_from_paper_telemetry(row: dict[str, object]) -> UserStreamEvent:
    return UserStreamEvent(
        event_type="ORDER_TRADE_UPDATE",
        event_time=str(row.get("ts_ack") or row.get("ts_send") or ""),
        order_id=str(row.get("telemetry_id") or ""),
        symbol=str(row.get("symbol") or ""),
        payload=dict(row),
    )
