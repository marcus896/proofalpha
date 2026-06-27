from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MemoryEventLog:
    events: list[dict[str, object]] = field(default_factory=list)

    def append(self, event_type: str, payload: dict[str, object]) -> dict[str, object]:
        event = {
            "event_type": event_type,
            "created_at": datetime.now(UTC).isoformat(),
            **dict(payload),
        }
        self.events.append(event)
        return event
