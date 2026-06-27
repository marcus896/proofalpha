from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemorySchemaVersion:
    version: int
    migration_id: str

    @staticmethod
    def current() -> "MemorySchemaVersion":
        return MemorySchemaVersion(version=1, migration_id="phase14_event_sourced_memory_v1")
