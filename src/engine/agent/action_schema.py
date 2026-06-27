from __future__ import annotations

from dataclasses import asdict, dataclass


ALLOWED_AGENT_ACTIONS = {
    "ProposeStudy",
    "RetryFailedStudy",
    "NarrowParameters",
    "ExpandScenarioStress",
    "RequestAblation",
    "RequestCalibrationStudy",
    "RequestForecastValidationStudy",
    "CompareIncumbent",
    "StopCampaign",
}

FORBIDDEN_AGENT_ACTIONS = {
    "PlaceOrder",
    "PromoteArtifactDirectly",
    "ChangeRiskLimit",
    "ApproveSymbolForPaper",
    "EditVenueTranslator",
    "DisableCircuitBreaker",
    "EnableLive",
}


@dataclass(frozen=True)
class AgentActionValidation:
    allowed: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AgentActionSchema:
    allowed_actions = ALLOWED_AGENT_ACTIONS
    forbidden_actions = FORBIDDEN_AGENT_ACTIONS

    @staticmethod
    def validate_action(action: str) -> AgentActionValidation:
        if action in FORBIDDEN_AGENT_ACTIONS:
            return AgentActionValidation(False, [f"forbidden_action:{action}"])
        if action not in ALLOWED_AGENT_ACTIONS:
            return AgentActionValidation(False, [f"unknown_action:{action}"])
        return AgentActionValidation(True, [])
