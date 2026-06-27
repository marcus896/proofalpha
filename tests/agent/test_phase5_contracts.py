import unittest

from engine.agent.contracts import (
    V3_EXPLORATION_BUDGET_PER_100,
    classify_duplicate_candidate,
    evaluate_exploration_budget,
    validate_policy_contract,
)
from engine.agent.model_governance import validate_model_change_record
from engine.strategy.dsl import build_bounded_strategy_spec_from_payload, validate_bounded_strategy_spec


class Phase5ContractTests(unittest.TestCase):
    def test_policy_contract_allows_only_bounded_policy_types(self) -> None:
        accepted = validate_policy_contract(
            {
                "policy_type": "planner_refinement_heuristic",
                "policy_id": "plateau-router",
                "candidate_actions": ["refine_existing_family"],
                "payload": {"single_mechanism_only": True},
            }
        )
        rejected = validate_policy_contract(
            {
                "policy_type": "raw_trading_signal",
                "policy_id": "llm-buy-sell",
                "candidate_actions": ["emit_buy_sell_size"],
            }
        )

        self.assertTrue(accepted.passed)
        self.assertFalse(rejected.passed)
        self.assertIn("policy_type_not_allowed", rejected.reasons)

    def test_exploration_budget_enforces_v3_bucket_caps_and_zero_rl(self) -> None:
        self.assertEqual(V3_EXPLORATION_BUDGET_PER_100["existing_family_refinement"], 35)

        ok = evaluate_exploration_budget({"existing_family_refinement": 35, "new_families": 15})
        over = evaluate_exploration_budget({"existing_family_refinement": 36})
        rl = evaluate_exploration_budget({"rl_meta_routing": 1})

        self.assertTrue(ok.passed)
        self.assertFalse(over.passed)
        self.assertFalse(rl.passed)
        self.assertIn("budget_exceeded:existing_family_refinement", over.reasons)
        self.assertIn("budget_exceeded:rl_meta_routing", rl.reasons)

    def test_duplicate_rules_cover_exact_and_near_duplicate_candidates(self) -> None:
        exact = classify_duplicate_candidate(
            candidate_identity_hash="abc",
            existing_identity_hashes=["abc"],
            ast_similarity=0.0,
            parameter_schema_delta=1.0,
            family_bucket="momentum",
        )
        near = classify_duplicate_candidate(
            candidate_identity_hash="def",
            existing_identity_hashes=["abc"],
            ast_similarity=0.91,
            parameter_schema_delta=0.04,
            family_bucket="momentum",
        )
        distinct = classify_duplicate_candidate(
            candidate_identity_hash="def",
            existing_identity_hashes=["abc"],
            ast_similarity=0.88,
            parameter_schema_delta=0.04,
            family_bucket="momentum",
        )

        self.assertEqual(exact.fail_code, "duplicate_candidate")
        self.assertEqual(exact.match_type, "exact")
        self.assertEqual(near.match_type, "near")
        self.assertEqual(near.consumed_budget_bucket, "momentum")
        self.assertIsNone(distinct.fail_code)

    def test_bounded_strategy_dsl_rejects_free_form_code_and_unknown_fields(self) -> None:
        valid = validate_bounded_strategy_spec(
            {
                "family": "momentum",
                "variant_id": "v1",
                "feature_contracts": ["ohlcv", "funding"],
                "parameter_schema": {"lookback": {"minimum": 24, "maximum": 72, "step": 12}},
                "risk_hooks": ["max_drawdown", "funding_shock"],
                "execution_policy": {"venue": "binance", "signal_tf": "1h", "execution_tf": "15m"},
            }
        )
        invalid = validate_bounded_strategy_spec(
            {
                "family": "momentum",
                "variant_id": "v2",
                "feature_contracts": ["ohlcv"],
                "parameter_schema": {},
                "risk_hooks": [],
                "execution_policy": {"venue": "binance", "signal_tf": "1h", "execution_tf": "15m"},
                "python_code": "def trade(): return 'BUY'",
            }
        )

        self.assertTrue(valid.passed)
        self.assertTrue(valid.identity_hash)
        self.assertFalse(invalid.passed)
        self.assertIn("free_form_code_not_allowed", invalid.reasons)

    def test_bounded_strategy_payload_normalizes_engine_timeframe_for_signal_tf(self) -> None:
        spec = build_bounded_strategy_spec_from_payload(
            {
                "run_id": "real-btcusdt-1h",
                "snapshot": {
                    "venue": "binance",
                    "timeframe": "1Hour",
                    "candles": [],
                    "funding_rates": [],
                    "open_interest": [],
                    "liquidation_notional": [],
                },
                "incumbent": {"backbone": "mom_squeeze"},
                "directional_layers": ["kama"],
                "known_good_filters": ["flat9"],
            }
        )

        self.assertEqual(spec["execution_policy"]["signal_tf"], "1h")
        self.assertTrue(validate_bounded_strategy_spec(spec).passed)

    def test_bounded_strategy_payload_accepts_one_minute_engine_timeframe(self) -> None:
        spec = build_bounded_strategy_spec_from_payload(
            {
                "run_id": "real-btcusdt-1m",
                "snapshot": {
                    "venue": "binance",
                    "timeframe": "1Min",
                    "candles": [],
                    "funding_rates": [],
                    "open_interest": [],
                    "liquidation_notional": [],
                },
                "incumbent": {"backbone": "mom_squeeze"},
                "directional_layers": ["kama"],
                "known_good_filters": ["flat9"],
            }
        )

        self.assertEqual(spec["execution_policy"]["signal_tf"], "1m")
        self.assertEqual(spec["execution_policy"]["execution_tf"], "1m")
        self.assertTrue(validate_bounded_strategy_spec(spec).passed)

    def test_model_change_governance_requires_version_replay_rollback_and_approval_state(self) -> None:
        accepted = validate_model_change_record(
            {
                "model_type": "cost",
                "model_version": "cost-v2",
                "diff_summary": "raise impact coefficient",
                "replay_comparison": {"old_sharpe": 1.1, "new_sharpe": 1.0},
                "rollback_target": "cost-v1",
                "approval_state": "approved",
            }
        )
        rejected = validate_model_change_record(
            {
                "model_type": "execution",
                "model_version": "exec-v2",
                "diff_summary": "",
                "approval_state": "approved",
            }
        )

        self.assertTrue(accepted.passed)
        self.assertFalse(rejected.passed)
        self.assertIn("missing:diff_summary", rejected.reasons)
        self.assertIn("missing:replay_comparison", rejected.reasons)
        self.assertIn("missing:rollback_target", rejected.reasons)
