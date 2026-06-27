from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyHealth:
    artifact_id: str
    status: str
    warnings: list[str]
