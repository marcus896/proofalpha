from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentBudget:
    max_runs: int
    max_wall_clock_seconds: int

    def within_budget(self, runs: int, elapsed_seconds: int) -> bool:
        if self.max_runs < 0 or self.max_wall_clock_seconds < 0:
            return False
        if runs < 0 or elapsed_seconds < 0:
            return False
        return runs <= self.max_runs and elapsed_seconds <= self.max_wall_clock_seconds
