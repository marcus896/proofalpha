from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyIntentValidation:
    passed: bool
    reasons: list[str]


@dataclass(frozen=True)
class StrategyIntentContract:
    artifact_id: str
    allowed_symbols: list[str]
    allowed_timeframes: list[str]
    allowed_execution_modes: list[str]
    allowed_portfolio_roles: list[str]
    forbidden_authority_fields: list[str]
    risk_hooks: list[str]

    def validate_payload(self, payload: dict[str, object]) -> StrategyIntentValidation:
        reasons = [
            f"forbidden_authority_field:{field}"
            for field in self.forbidden_authority_fields
            if field in payload
        ]
        return StrategyIntentValidation(not reasons, reasons)
