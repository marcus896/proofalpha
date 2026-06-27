from __future__ import annotations

import unittest

from engine.strategy.artifacts import (
    PromotionManifest,
    build_promotion_manifest,
    build_strategy_artifact,
    validate_promotion_manifest,
    validate_strategy_artifact,
)


class PromotionManifestTests(unittest.TestCase):
    def test_promoted_artifact_gets_machine_verifiable_manifest(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload())

        self.assertIn("promotion_manifest", artifact)
        manifest = PromotionManifest.from_dict(artifact["promotion_manifest"])
        self.assertEqual(manifest.artifact_id, artifact["artifact_id"])
        self.assertEqual(manifest.gate_results["final_holdout_calmar"], True)
        self.assertTrue(manifest.paper_eligibility)
        self.assertTrue(validate_promotion_manifest(artifact, manifest.to_dict()).passed)
        self.assertTrue(validate_strategy_artifact(artifact).passed)

    def test_manifest_hashes_bind_to_artifact_inputs(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload())
        manifest = build_promotion_manifest(artifact, expiry_time_utc="2099-01-01T00:00:00Z")
        mutated = dict(manifest.to_dict())
        mutated["validation_bundle_hash"] = "wrong"

        validation = validate_promotion_manifest(artifact, mutated)

        self.assertFalse(validation.passed)
        self.assertIn("manifest_validation_bundle_hash_mismatch", validation.reasons)


def _valid_artifact_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "strategy_id": "strategy-phase2",
        "family": "momentum",
        "variant_id": "variant-phase2",
        "venue": "binance_usdm",
        "signal_timeframe": "1h",
        "execution_timeframe": "15m",
        "symbol_scope": ["BTCUSDT"],
        "regime_scope": ["trend", "neutral"],
        "feature_version": "feature-v1",
        "data_snapshot_ids": ["snapshot-v1"],
        "execution_model": "binance_usdm_v3",
        "cost_model": "cost-v1",
        "scenario_pack": "scenario-v1",
        "parameters": {"lookback": 48},
        "risk_limits": {"max_notional": 1000.0, "max_drawdown": 0.2},
        "order_policy": {"order_type": "limit", "time_in_force": "GTX", "post_only": True},
        "validation_report_id": "validation-v1",
        "code_sha": "code-sha",
        "rollout_stage": "paper",
        "promotion_approved": True,
        "validation_status": "passed",
        "created_at_utc": "2026-05-07T00:00:00Z",
        "validation_gate_details": [
            {"name": "final_holdout_calmar", "passed": True},
            {"name": "capacity_5x", "passed": True},
        ],
        "scenario_results": {"venue_outage": True},
        "regime_results": {"trend": True},
        "capacity_result": {"passed": True},
        "turnover_result": {"passed": True},
        "expiry_time_utc": "2099-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


if __name__ == "__main__":
    unittest.main()
