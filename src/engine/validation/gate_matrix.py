from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateMatrix:
    gates: dict[str, bool]

    def failed_gates(self) -> list[str]:
        return sorted(name for name, passed in self.gates.items() if not passed)
