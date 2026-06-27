import unittest

from engine.execution.paper import (
    PaperMarketSnapshot,
    PaperOrderIntent,
    simulate_fill_model_v2,
)


class Phase9AFillModelV2Tests(unittest.TestCase):
    def test_market_buy_walks_ask_depth_and_records_impact_and_adverse_selection(self) -> None:
        intent = PaperOrderIntent(
            symbol="BTCUSDT",
            side="BUY",
            qty=3.0,
            expected_price=100.0,
            order_type="market",
        )
        snapshot = PaperMarketSnapshot(
            ts="2026-04-29T00:00:00Z",
            symbol="BTCUSDT",
            bid=99.9,
            ask=100.1,
            last_trade_price=100.0,
            visible_depth_qty=1.0,
            topn_depth_qty=3.0,
            ask_depth_levels=[["100.10", "1.0"], ["100.20", "2.0"]],
            adverse_price_after_fill=100.3,
        )

        fill = simulate_fill_model_v2(
            intent=intent,
            snapshot=snapshot,
            latency_ms=250.0,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0005,
        )

        self.assertEqual(fill["fill_path"], "market")
        self.assertEqual(fill["qty_filled"], 3.0)
        self.assertEqual(fill["live_vwap_price"], 100.166666666667)
        self.assertEqual(fill["maker_ratio"], 0.0)
        self.assertEqual(fill["latency_bucket"], "250ms_1s")
        self.assertGreater(fill["impact_bps"], 0.0)
        self.assertGreater(fill["adverse_selection_bps"], 0.0)
        self.assertEqual(fill["non_fill_opportunity_loss_quote"], 0.0)

    def test_passive_limit_uses_queue_progress_partial_fill_and_timeout_loss(self) -> None:
        intent = PaperOrderIntent(
            symbol="BTCUSDT",
            side="SELL",
            qty=5.0,
            expected_price=100.0,
            limit_price=100.1,
            order_type="limit",
            post_only=True,
            time_in_force="GTX",
        )
        snapshot = PaperMarketSnapshot(
            ts="2026-04-29T00:00:00Z",
            symbol="BTCUSDT",
            bid=99.9,
            ask=100.1,
            last_trade_price=100.05,
            traded_qty_at_price=3.0,
            canceled_ahead_qty=1.0,
            depth_ahead_qty=2.0,
            visible_depth_qty=10.0,
            topn_depth_qty=10.0,
            bid_depth_levels=[["99.90", "4.0"], ["99.80", "4.0"]],
            adverse_price_after_fill=99.7,
        )

        fill = simulate_fill_model_v2(
            intent=intent,
            snapshot=snapshot,
            latency_ms=25.0,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0005,
        )

        self.assertEqual(fill["fill_path"], "passive")
        self.assertEqual(fill["qty_filled"], 2.0)
        self.assertEqual(fill["qty_canceled"], 3.0)
        self.assertEqual(fill["maker_ratio"], 1.0)
        self.assertEqual(fill["time_in_force"], "GTX")
        self.assertEqual(fill["timeout"], True)
        self.assertEqual(fill["queue_ahead_qty"], 2.0)
        self.assertEqual(fill["queue_progress_qty"], 4.0)
        self.assertGreater(fill["non_fill_opportunity_loss_quote"], 0.0)
        self.assertGreater(fill["adverse_selection_bps"], 0.0)


if __name__ == "__main__":
    unittest.main()
