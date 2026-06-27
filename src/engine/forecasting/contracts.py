from __future__ import annotations

from engine.agent.contracts import ContractCheck


ALLOWED_FORECAST_INTENDED_USAGE = "research_only_feature"
ALLOWED_FORECAST_OUTPUTS = {
    "forecast_artifact",
    "forecast_feature",
    "risk_feature",
    "validation_evidence",
}
FORBIDDEN_FORECAST_ACTIONS = {
    "emit_buy_sell_size",
    "raw_order",
    "raw_trading_signal",
    "live_execution",
    "execution_signal",
}
ALLOWED_INITIAL_FINE_TUNING_POLICIES = {
    "none",
    "none_initial",
    "none_initial_lora_later_only",
    "lora_later_only",
}


def validate_forecast_source_contract(record: dict[str, object]) -> ContractCheck:
    reasons: list[str] = []
    if record.get("intended_usage") != ALLOWED_FORECAST_INTENDED_USAGE:
        reasons.append("intended_usage_not_research_only_feature")

    source_id = record.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        reasons.append("missing_source_id")

    source_kind = record.get("source_kind")
    if source_kind not in {"forecast_model", "forecast_fixture", "forecast_audit_method"}:
        reasons.append("source_kind_not_allowed")

    allowed_outputs = record.get("allowed_outputs", [])
    if not isinstance(allowed_outputs, list):
        reasons.append("allowed_outputs_not_list")
        allowed_outputs = []
    if any(str(output) not in ALLOWED_FORECAST_OUTPUTS for output in allowed_outputs):
        reasons.append("raw_trading_output_not_allowed")

    candidate_actions = record.get("candidate_actions", [])
    if candidate_actions is None:
        candidate_actions = []
    if not isinstance(candidate_actions, list):
        reasons.append("candidate_actions_not_list")
        candidate_actions = []
    if any(str(action) in FORBIDDEN_FORECAST_ACTIONS for action in candidate_actions):
        reasons.append("raw_trading_action_not_allowed")

    if record.get("execution_routing_enabled") is not False:
        reasons.append("execution_routing_not_allowed")
    if record.get("live_trading_enabled") is not False:
        reasons.append("live_trading_not_allowed")

    fine_tuning_policy = record.get("fine_tuning_policy", "none_initial")
    if fine_tuning_policy not in ALLOWED_INITIAL_FINE_TUNING_POLICIES:
        reasons.append("fine_tuning_policy_not_allowed_initially")

    return ContractCheck(passed=not reasons, reasons=reasons, payload=dict(record))
