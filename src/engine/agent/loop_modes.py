from __future__ import annotations

from enum import StrEnum

from engine.agent.action_schema import ALLOWED_AGENT_ACTIONS


class AgentLoopMode(StrEnum):
    SCOUT = "SCOUT"
    EXPLOIT = "EXPLOIT"
    STRESS = "STRESS"
    CALIBRATE = "CALIBRATE"
    PORTFOLIO = "PORTFOLIO"
    EXECUTOR = "EXECUTOR"
    STOP = "STOP"


MODE_ACTIONS = {
    AgentLoopMode.SCOUT: {"ProposeStudy", "RequestAblation", "RequestForecastValidationStudy", "StopCampaign"},
    AgentLoopMode.EXPLOIT: {"NarrowParameters", "CompareIncumbent", "StopCampaign"},
    AgentLoopMode.STRESS: {"ExpandScenarioStress", "RequestAblation", "StopCampaign"},
    AgentLoopMode.CALIBRATE: {"RequestCalibrationStudy", "RequestForecastValidationStudy", "CompareIncumbent", "StopCampaign"},
    AgentLoopMode.PORTFOLIO: {"ProposeStudy", "CompareIncumbent", "StopCampaign"},
    AgentLoopMode.EXECUTOR: {"RequestCalibrationStudy", "CompareIncumbent", "StopCampaign"},
    AgentLoopMode.STOP: {"StopCampaign"},
}


def allowed_actions_for_mode(mode: AgentLoopMode) -> set[str]:
    return set(MODE_ACTIONS[mode]).intersection(ALLOWED_AGENT_ACTIONS)
