from __future__ import annotations

from dataclasses import asdict, dataclass

from engine.agent.action_schema import AgentActionSchema


@dataclass(frozen=True)
class NoTradePolicyResult:
    allowed: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def enforce_no_trade_authority(actions: list[str]) -> NoTradePolicyResult:
    reasons: list[str] = []
    for action in actions:
        validation = AgentActionSchema.validate_action(action)
        if not validation.allowed:
            reasons.extend(validation.reasons)
    return NoTradePolicyResult(not reasons, reasons)
