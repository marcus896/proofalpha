from __future__ import annotations

import unittest

from engine.artifacts.artifact_signature import ArtifactSignature
from engine.artifacts.expiry_policy import ArtifactExpiryPolicy
from engine.artifacts.rollback_manifest import ArtifactRollbackManifest
from engine.validation.gate_matrix import GateMatrix
from engine.validation.min_sample_gate import MinSampleGate


class Phase14ValidationArtifactContractTests(unittest.TestCase):
    def test_min_sample_gate_blocks_too_few_holdout_trades(self) -> None:
        result = MinSampleGate(min_oos_trades=20, min_final_holdout_trades=10, min_regime_coverage=0.8).evaluate(
            oos_trades=25,
            final_holdout_trades=5,
            regime_coverage=0.9,
        )

        self.assertFalse(result.passed)
        self.assertIn("min_final_holdout_trades_not_met", result.reasons)

    def test_artifact_signature_is_stable_and_rollback_has_target(self) -> None:
        signature = ArtifactSignature(
            artifact_id="artifact-1",
            content_hash="content",
            config_hash="config",
            strategy_graph_hash="graph",
            validation_bundle_hash="validation",
            signature_version="v1",
        )
        rollback = ArtifactRollbackManifest(artifact_id="artifact-2", rollback_artifact_id="artifact-1", reason="decay")
        expiry = ArtifactExpiryPolicy(expiry_time="2026-06-07T00:00:00Z", reduce_only_after_expiry=True)

        self.assertEqual(signature.digest(), signature.digest())
        self.assertTrue(rollback.validate().passed)
        self.assertEqual(expiry.action_after_expiry(), "reduce_only")

    def test_gate_matrix_reports_failed_gates(self) -> None:
        matrix = GateMatrix({"holdout_sharpe": True, "min_sample": False})

        self.assertEqual(matrix.failed_gates(), ["min_sample"])


if __name__ == "__main__":
    unittest.main()
