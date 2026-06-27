from __future__ import annotations


class FailureTaxonomyV2:
    validation_failures = {"holdout_sharpe", "min_sample", "pbo", "spa"}
    execution_failures = {"orphan_order", "missing_fill", "duplicate_fill", "order_reject"}
    data_failures = {"missing_mark", "missing_funding", "stale_book"}
    portfolio_failures = {"cluster_cap", "beta_cap", "funding_budget"}
    agent_policy_failures = {"forbidden_tool", "trade_authority"}
    learning_failures = {"shadow_validation", "model_card_missing"}

    @classmethod
    def classify(cls, reason: str) -> str:
        for family in (
            "validation_failures",
            "execution_failures",
            "data_failures",
            "portfolio_failures",
            "agent_policy_failures",
            "learning_failures",
        ):
            if reason in getattr(cls, family):
                return family
        return "unknown_failures"
