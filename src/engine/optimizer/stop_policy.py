from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopPolicy:
    max_repeated_failures: int

    def should_stop(self, repeated_failures: int) -> bool:
        return repeated_failures >= self.max_repeated_failures
