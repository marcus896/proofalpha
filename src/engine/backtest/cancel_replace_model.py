from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CancelReplaceModel:
    cancel_replace_count: int
    max_cancel_replace: int

    def within_budget(self) -> bool:
        return self.cancel_replace_count <= self.max_cancel_replace
