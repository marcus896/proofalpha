from __future__ import annotations

from dataclasses import dataclass

from engine.features.contracts import FeatureContract


@dataclass(frozen=True)
class FeatureAvailabilityMatrix:
    contracts: dict[str, FeatureContract]

    def available_for_mode(self, mode: str) -> list[str]:
        return sorted(
            name
            for name, contract in self.contracts.items()
            if mode in contract.allowed_modes and contract.leakage_risk != "research_only"
        )

    def unavailable_for_mode(self, mode: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, contract in self.contracts.items():
            if contract.leakage_risk == "research_only":
                result[name] = "research_only"
            elif mode not in contract.allowed_modes:
                result[name] = "mode_not_allowed"
        return dict(sorted(result.items()))
