from __future__ import annotations


class LearningDatasetBuilder:
    def from_events(self, events: list[dict[str, object]]) -> list[dict[str, object]]:
        return [dict(event) for event in events]
