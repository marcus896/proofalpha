from __future__ import annotations

import unittest

from engine.execution.order_intent import InternalOrderIntent
from engine.execution.venue_translator.binance_usdm import BinanceUsdMTranslator

from tests.execution.test_tick_step_min_notional import _rules_cache


class ClosePositionMappingTests(unittest.TestCase):
    def test_close_position_is_reduce_only_and_cannot_open_reverse_exposure(self) -> None:
        intent = InternalOrderIntent.create(
            artifact_id="artifact-btc",
            portfolio_plan_id="portfolio-v1",
            symbol="BTCUSDT",
            desired_position_delta=-10_000.0,
            side="SELL",
            intent_type="close",
            urgency="urgent",
            reduce_only_required=True,
            max_slippage_bps=8.0,
            max_spread_bps=5.0,
            max_participation_rate=0.10,
            funding_guard_policy="block_if_positive_cost_gt_budget",
            liquidation_guard_policy="block_if_liquidation_buffer_breached",
            created_at="2026-05-07T00:00:00Z",
            expires_at="2026-05-07T00:15:00Z",
        )

        report = BinanceUsdMTranslator(_rules_cache()).translate(
            intent,
            quantity=0.1,
            price=50_000.0,
            current_position_notional=10_000.0,
            close_position=True,
            timestamp=1778083200000,
        )

        self.assertTrue(report.passed, report.rejection_reasons)
        self.assertTrue(report.rounded_order["reduceOnly"])
        self.assertTrue(report.rounded_order["closePosition"])


if __name__ == "__main__":
    unittest.main()
