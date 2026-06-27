from __future__ import annotations

import unittest

from engine.execution.paper import PaperMarketSnapshot, PaperOrderIntent, run_paper_executor_fixture
from engine.strategy.artifacts import build_strategy_artifact, paper_authority_decision

from tests.artifacts.test_promotion_manifest import _valid_artifact_payload


class ArtifactExpiryReduceOnlyTests(unittest.TestCase):
    def test_expired_artifact_can_only_reduce_or_close(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload(expiry_time_utc="2026-05-01T00:00:00Z"))

        decision = paper_authority_decision(artifact, now_utc="2026-05-07T00:00:00Z")

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.reduce_only)
        self.assertIn("artifact_expired", decision.reasons)

    def test_expired_artifact_blocks_non_reduce_only_paper_intent(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload(expiry_time_utc="2026-05-01T00:00:00Z"))

        with self.assertRaisesRegex(ValueError, "artifact_expired"):
            run_paper_executor_fixture(
                artifact,
                order_intents=[PaperOrderIntent(symbol="BTCUSDT", side="BUY", qty=1.0, expected_price=100.0)],
                market_snapshots=[_snapshot()],
            )

    def test_expired_artifact_allows_reduce_only_paper_intent(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload(expiry_time_utc="2026-05-01T00:00:00Z"))

        result = run_paper_executor_fixture(
            artifact,
            order_intents=[
                PaperOrderIntent(symbol="BTCUSDT", side="SELL", qty=1.0, expected_price=100.0, reduce_only=True)
            ],
            market_snapshots=[_snapshot()],
        )

        self.assertEqual(result["status"], "completed")


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
