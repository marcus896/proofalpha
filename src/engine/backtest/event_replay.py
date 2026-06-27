from __future__ import annotations


def replay_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [dict(event) for event in events]
