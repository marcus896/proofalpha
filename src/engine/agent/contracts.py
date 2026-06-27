from __future__ import annotations

from dataclasses import dataclass, field


V3_ALLOWED_POLICY_TYPES = {
    "planner_refinement_heuristic",
    "memory_selection",
    "duplicate_ranking",
    "stop_policy",
    "karpathy_decision_policy",
}

V3_EXPLORATION_BUDGET_PER_100 = {
    "existing_family_refinement": 35,
    "symbol_portability": 20,
    "regime_robustness": 20,
    "new_families": 15,
    "portfolio_allocation": 10,
    "rl_meta_routing": 0,
}


@dataclass(frozen=True)
class ContractCheck:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DuplicateClassification:
    is_duplicate: bool
    match_type: str | None = None
    fail_code: str | None = None
    consumed_budget_bucket: str | None = None
    ast_similarity: float | None = None
    parameter_schema_delta: float | None = None


def validate_policy_contract(policy: dict[str, object]) -> ContractCheck:
    reasons: list[str] = []
    policy_type = policy.get("policy_type")
    if policy_type not in V3_ALLOWED_POLICY_TYPES:
        reasons.append("policy_type_not_allowed")
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id:
        reasons.append("missing_policy_id")
    actions = policy.get("candidate_actions", [])
    if not isinstance(actions, list):
        reasons.append("candidate_actions_not_list")
    if any(str(action) in {"emit_buy_sell_size", "raw_order", "raw_trading_signal"} for action in actions):
        reasons.append("raw_trading_action_not_allowed")
    if any(str(action) in {"raw_forecast_order", "forecast_order", "forecast_trade_action"} for action in actions):
        reasons.append("raw_forecast_action_not_allowed")
    return ContractCheck(passed=not reasons, reasons=reasons, payload=dict(policy))


def evaluate_exploration_budget(usage_per_100: dict[str, int | float]) -> ContractCheck:
    reasons: list[str] = []
    normalized: dict[str, float] = {}
    for bucket, cap in V3_EXPLORATION_BUDGET_PER_100.items():
        used = float(usage_per_100.get(bucket, 0))
        normalized[bucket] = used
        if used > cap:
            reasons.append(f"budget_exceeded:{bucket}")
    for bucket in usage_per_100:
        if bucket not in V3_EXPLORATION_BUDGET_PER_100:
            reasons.append(f"unknown_budget_bucket:{bucket}")
    return ContractCheck(passed=not reasons, reasons=reasons, payload={"usage_per_100": normalized})


def classify_duplicate_candidate(
    *,
    candidate_identity_hash: str,
    existing_identity_hashes: list[str],
    ast_similarity: float,
    parameter_schema_delta: float,
    family_bucket: str,
) -> DuplicateClassification:
    if candidate_identity_hash in set(existing_identity_hashes):
        return DuplicateClassification(
            is_duplicate=True,
            match_type="exact",
            fail_code="duplicate_candidate",
            consumed_budget_bucket=family_bucket,
            ast_similarity=ast_similarity,
            parameter_schema_delta=parameter_schema_delta,
        )
    if ast_similarity > 0.90 and parameter_schema_delta < 0.05:
        return DuplicateClassification(
            is_duplicate=True,
            match_type="near",
            fail_code="duplicate_candidate",
            consumed_budget_bucket=family_bucket,
            ast_similarity=ast_similarity,
            parameter_schema_delta=parameter_schema_delta,
        )
    return DuplicateClassification(
        is_duplicate=False,
        ast_similarity=ast_similarity,
        parameter_schema_delta=parameter_schema_delta,
    )
