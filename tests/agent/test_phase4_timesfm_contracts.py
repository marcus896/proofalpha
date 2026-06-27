import unittest
from pathlib import Path
import shutil

from engine.agent.contracts import classify_duplicate_candidate, validate_policy_contract
from engine.agent.controller import _build_failure_taxonomy, _default_materializer
from engine.strategy.dsl import validate_bounded_strategy_spec


class Phase4TimesFmAgentContractTests(unittest.TestCase):
    def test_dsl_accepts_bounded_forecast_feature_contract_and_hashes_config(self) -> None:
        base = _spec()
        no_forecast_spec = {**base, "feature_contracts": ["ohlcv"]}
        no_forecast_spec.pop("forecast_feature_config")
        no_forecast = validate_bounded_strategy_spec(no_forecast_spec)
        forecast_a = validate_bounded_strategy_spec(base)
        forecast_b = validate_bounded_strategy_spec(
            {
                **base,
                "forecast_feature_config": {
                    **base["forecast_feature_config"],
                    "horizon": 4,
                },
            }
        )

        self.assertTrue(forecast_a.passed, forecast_a.reasons)
        self.assertTrue(no_forecast.passed, no_forecast.reasons)
        self.assertTrue(forecast_a.identity_hash)
        self.assertNotEqual(no_forecast.identity_hash, forecast_a.identity_hash)
        self.assertNotEqual(forecast_a.identity_hash, forecast_b.identity_hash)
        self.assertEqual(
            forecast_a.normalized_spec["forecast_feature_config"]["feature_fields"],
            ["timesfm_confidence_bucket", "timesfm_q50_return"],
        )

    def test_dsl_rejects_raw_forecast_execution_and_raw_forecast_fields(self) -> None:
        raw_order = validate_bounded_strategy_spec(
            {
                **_spec(),
                "execution_policy": {
                    "venue": "binance",
                    "signal_tf": "1h",
                    "execution_tf": "15m",
                    "raw_forecast_order": True,
                },
            }
        )
        raw_feature = validate_bounded_strategy_spec(
            {
                **_spec(),
                "forecast_feature_config": {
                    **_spec()["forecast_feature_config"],
                    "feature_fields": ["q50", "timesfm_q50_return"],
                },
            }
        )

        self.assertFalse(raw_order.passed)
        self.assertIn("execution_policy_field_not_allowed:raw_forecast_order", raw_order.reasons)
        self.assertFalse(raw_feature.passed)
        self.assertIn("forecast_feature_field_not_allowed", raw_feature.reasons)

    def test_policy_contract_allows_forecast_feature_request_but_rejects_raw_forecast_actions(self) -> None:
        accepted = validate_policy_contract(
            {
                "policy_type": "planner_refinement_heuristic",
                "policy_id": "forecast-feature-router",
                "candidate_actions": ["request_forecast_feature", "refine_existing_family"],
            }
        )
        rejected = validate_policy_contract(
            {
                "policy_type": "planner_refinement_heuristic",
                "policy_id": "raw-forecast-order",
                "candidate_actions": ["raw_forecast_order", "emit_buy_sell_size"],
            }
        )

        self.assertTrue(accepted.passed, accepted.reasons)
        self.assertFalse(rejected.passed)
        self.assertIn("raw_forecast_action_not_allowed", rejected.reasons)
        self.assertIn("raw_trading_action_not_allowed", rejected.reasons)

    def test_duplicate_detection_distinguishes_forecast_config_variants(self) -> None:
        base = validate_bounded_strategy_spec(_spec())
        changed = validate_bounded_strategy_spec(
            {
                **_spec(),
                "forecast_feature_config": {
                    **_spec()["forecast_feature_config"],
                    "config_checksum": "sha256:timesfm-alt",
                },
            }
        )

        exact = classify_duplicate_candidate(
            candidate_identity_hash=base.identity_hash,
            existing_identity_hashes=[base.identity_hash],
            ast_similarity=0.0,
            parameter_schema_delta=1.0,
            family_bucket="momentum",
        )
        distinct = classify_duplicate_candidate(
            candidate_identity_hash=changed.identity_hash,
            existing_identity_hashes=[base.identity_hash],
            ast_similarity=0.0,
            parameter_schema_delta=1.0,
            family_bucket="momentum",
        )

        self.assertTrue(exact.is_duplicate)
        self.assertFalse(distinct.is_duplicate)

    def test_forecast_failures_route_to_controlled_taxonomy(self) -> None:
        taxonomy = _build_failure_taxonomy(
            failed_gates=["forecast_unavailable", "forecast_leakage", "forecast_baseline_failure"],
            regime_failure_labels=[],
            scenario_failure_names=[],
            quality_flags=[],
            has_venue_profile=True,
        )

        self.assertEqual(
            taxonomy,
            ["forecast_unavailable", "forecast_leakage", "forecast_baseline_failure"],
        )

    def test_agent_materializer_persists_research_only_forecast_feature_spec(self) -> None:
        output_dir = Path("test-output-phase4-forecast-materializer")
        try:
            context = {
                "iteration": 1,
                "output_dir": output_dir,
                "payload": {
                    "run_id": "phase4-forecast-feature",
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": ["flat9"],
                    "custom_filters": [],
                    "exit_layers": ["time_stop"],
                    "snapshot": {"symbol": "BTCUSDT", "venue": "binance", "timeframe": "1h"},
                    "forecast_feature_config": _spec()["forecast_feature_config"],
                },
                "settings": {"loop_mode": "bounded", "karpathy_target_kind": "json_config"},
                "root_run_id": "phase4-forecast-feature",
            }

            result = _default_materializer(context, {"mode": "single"})
            artifact_path = Path(result["bounded_strategy_artifact_path"])
            artifact = artifact_path.read_text(encoding="utf-8")

            self.assertIn("forecast_feature", result["bounded_strategy_spec"]["feature_contracts"])
            self.assertEqual(
                result["bounded_strategy_spec"]["forecast_feature_config"]["provider"],
                "timesfm",
            )
            self.assertIn("timesfm_q50_return", artifact)
            self.assertNotIn("raw_forecast_order", artifact)
            self.assertNotIn("emit_buy_sell_size", artifact)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)


def _spec() -> dict[str, object]:
    return {
        "family": "momentum",
        "variant_id": "forecast-v1",
        "feature_contracts": ["ohlcv", "forecast_feature"],
        "forecast_feature_config": {
            "provider": "timesfm",
            "model_id": "google/timesfm-2.5-200m-pytorch",
            "feature_fields": ["timesfm_q50_return", "timesfm_confidence_bucket"],
            "horizon": 2,
            "context_length": 512,
            "config_checksum": "sha256:timesfm-feature-config",
        },
        "parameter_schema": {"lookback": {"minimum": 24, "maximum": 72, "step": 12}},
        "risk_hooks": ["max_drawdown"],
        "execution_policy": {"venue": "binance", "signal_tf": "1h", "execution_tf": "15m"},
    }


if __name__ == "__main__":
    unittest.main()
