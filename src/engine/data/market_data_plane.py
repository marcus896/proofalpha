from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class MarketDataPlane:
    historical_bars_snapshot_id: str | None = None
    live_public_streams: tuple[str, ...] = ()
    mark_price_snapshot_id: str | None = None
    funding_snapshot_id: str | None = None
    open_interest_snapshot_id: str | None = None
    book_state_snapshot_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["live_public_streams"] = list(self.live_public_streams)
        return payload
