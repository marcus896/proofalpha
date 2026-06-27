from __future__ import annotations

import unittest

from engine.execution.paper import PaperMarketSnapshot, PaperOrderIntent, run_paper_executor_fixture
from engine.portfolio.allocator import PortfolioArtifactCandidate, PortfolioConstraints, build_portfolio_plan
from engine.strategy.artifacts import build_strategy_artifact, paper_authority_decision

from tests.artifacts.test_promotion_manifest import _valid_artifact_payload


class ArtifactManifestRequiredForPaperTests(unittest.TestCase):
    def test_missing_manifest_blocks_paper_executor(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload())
        artifact.pop("promotion_manifest")

        with self.assertRaisesRegex(ValueError, "missing_promotion_manifest"):
            run_paper_executor_fixture(
                artifact,
                order_intents=[
                    PaperOrderIntent(symbol="BTCUSDT", side="BUY", qty=1.0, expected_price=100.0)
                ],
                market_snapshots=[_snapshot()],
            )

    def test_missing_manifest_blocks_portfolio_allocation(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload())
        artifact.pop("promotion_manifest")
        candidate = PortfolioArtifactCandidate(
            artifact_id="artifact-missing-manifest",
            strategy_id="strategy-phase2",
            symbol_scope=("BTCUSDT",),
            regime_scope=("trend",),
            portfolio_role="core",
            target_notional=1000.0,
            max_notional=1000.0,
            expected_return_bps=12.0,
            max_drawdown=0.10,
            approved=True,
            artifact_payload=artifact,
        )

        plan = build_portfolio_plan(
            [candidate],
            PortfolioConstraints(
                equity=10_000.0,
                max_per_symbol_exposure=5_000.0,
                max_aggregate_leverage=1.0,
                drawdown_budget=0.20,
                max_pairwise_correlation=0.90,
            ),
            active_regimes={"BTCUSDT": "trend"},
        )

        self.assertFalse(plan.accepted)
        self.assertEqual(plan.rejections[0].reason_code, "missing_promotion_manifest")

    def test_authority_decision_accepts_valid_manifest(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload())

        decision = paper_authority_decision(artifact, now_utc="2026-05-07T00:00:00Z")

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.reduce_only)


def _snapshot() -> PaperMarketSnapshot:
    return PaperMarketSnapshot(
        ts="2026-05-07T00:00:00Z",
        symbol="BTCUSDT",
        bid=99.9,
        ask=100.1,
        last_trade_price=100.0,
    )


if __name__ == "__main__":
    unittest.main()
