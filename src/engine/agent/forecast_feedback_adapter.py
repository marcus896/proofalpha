from __future__ import annotations

from engine.agent.action_schema import AgentActionSchema


def forecast_feedback_to_study_request(feedback: dict[str, object]) -> dict[str, object]:
    action = "RequestForecastValidationStudy"
    validation = AgentActionSchema.validate_action(action)
    if not validation.allowed:
        raise ValueError(",".join(validation.reasons))
    return {
        "action": action,
        "trade_authority": False,
        "direct_order_change": False,
        "artifact_promotion": False,
        "risk_limit_mutation": False,
        "study": {
            "forecast_model_id": feedback.get("forecast_model_id"),
            "ttl_status": feedback.get("ttl_status", "UNKNOWN"),
            "baseline_comparison": dict(feedback.get("baseline_comparison", {})),
            "decay_status": feedback.get("decay_status", "UNKNOWN"),
            "purpose": "forecast_validation_only",
        },
    }
