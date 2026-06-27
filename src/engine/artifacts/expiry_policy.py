from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactExpiryPolicy:
    expiry_time: str
    reduce_only_after_expiry: bool

    def action_after_expiry(self) -> str:
        return "reduce_only" if self.reduce_only_after_expiry else "disable"
