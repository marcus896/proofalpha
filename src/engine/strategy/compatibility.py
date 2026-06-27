from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyCompatibility:
    artifact_id: str
    compatible: bool
    reasons: list[str]
