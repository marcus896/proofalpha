from __future__ import annotations

import unittest

from engine.strategy.freeze_manifest import StrategyFreezeManifest
from engine.strategy.intent_contract import StrategyIntentContract
from engine.strategy.lifecycle_state import StrategyLifecycleState, transition_allowed


class Phase14StrategyContractTests(unittest.TestCase):
    def test_strategy_intent_contract_forbids_order_authority(self) -> None:
        contract = StrategyIntentContract(
            artifact_id="artifact-1",
            allowed_symbols=["BTCUSDT"],
            allowed_timeframes=["1h"],
            allowed_execution_modes=["paper"],
            allowed_portfolio_roles=["alpha"],
            forbidden_authority_fields=["raw_order", "set_leverage", "live_order"],
            risk_hooks=["funding_guard"],
        )

        result = contract.validate_payload({"raw_order": True})

        self.assertFalse(result.passed)
        self.assertIn("forbidden_authority_field:raw_order", result.reasons)

    def test_strategy_freeze_manifest_hash_stable(self) -> None:
        manifest = StrategyFreezeManifest(
            artifact_id="artifact-1",
            strategy_graph_hash="graph",
            feature_contract_hash="features",
            code_version="v1",
            config_hash="config",
            validation_bundle_hash="validation",
            created_at="2026-05-07T00:00:00Z",
            expiry_time="2026-06-07T00:00:00Z",
            frozen_by="engine",
        )

        self.assertEqual(manifest.manifest_hash(), manifest.manifest_hash())

    def test_lifecycle_allows_paper_active_reduce_only_then_retire(self) -> None:
        self.assertTrue(transition_allowed(StrategyLifecycleState.PAPER_ACTIVE, StrategyLifecycleState.REDUCE_ONLY))
        self.assertTrue(transition_allowed(StrategyLifecycleState.REDUCE_ONLY, StrategyLifecycleState.RETIRED))
        self.assertFalse(transition_allowed(StrategyLifecycleState.RETIRED, StrategyLifecycleState.PAPER_ACTIVE))


if __name__ == "__main__":
    unittest.main()
