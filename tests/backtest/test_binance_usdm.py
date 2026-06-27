from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from engine.backtest.binance_usdm import (
    BINANCE_USDM_V3_EXECUTION_MODEL_ID,
    BinanceUsdMOrderRequest,
    BinanceUsdMRuleSet,
    DynamicCostContext,
    approximate_mark_price_liquidation_price,
    funding_cashflow,
    simulate_binance_usdm_order,
    validate_binance_usdm_order,
)


class BinanceUsdMExecutionModelTests(unittest.TestCase):
    def test_rejects_precision_min_notional_post_only_reduce_only_and_expired_orders(self) -> None:
        rules = BinanceUsdMRuleSet(tick_size=0.10, step_size=0.01, min_notional=5.0, maker_fee_bps=2.0, taker_fee_bps=5.0)
        expired = datetime(2024, 1, 1, tzinfo=UTC)

        reasons = validate_binance_usdm_order(
            BinanceUsdMOrderRequest(
                symbol="BTCUSDT",
                side="BUY",
                quantity=0.02,
                price=100.03,
                liquidity_path="taker",
                post_only=True,
                reduce_only=True,
                intent="increase",
                current_position_qty=0.0,
                book_best_ask=100.0,
                submitted_at=expired,
                expires_at=expired - timedelta(seconds=1),
            ),
            rules,
        )

        self.assertIn("price_precision_violation", reasons)
        self.assertIn("min_notional_violation", reasons)
        self.assertIn("post_only_requires_maker_path", reasons)
        self.assertIn("post_only_would_take_liquidity", reasons)
        self.assertIn("reduce_only_requires_reduce_intent", reasons)
        self.assertIn("reduce_only_without_position", reasons)
        self.assertIn("order_expired", reasons)

    def test_simulates_partial_fill_dynamic_cost_and_capacity_rejection(self) -> None:
        rules = BinanceUsdMRuleSet(
            tick_size=0.10,
            step_size=0.01,
            min_notional=5.0,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            max_participation_rate=0.10,
        )
        context = DynamicCostContext(
            symbol="BTCUSDT",
            liquidity_path="taker",
            hour_of_day=8,
            volatility_percentile=0.90,
            spread_percentile=0.75,
            order_size_pct_local_liquidity=0.50,
            oi_percentile=0.80,
            liquidation_intensity_percentile=0.70,
        )

        report = simulate_binance_usdm_order(
            BinanceUsdMOrderRequest(
                symbol="BTCUSDT",
                side="BUY",
                quantity=2.0,
                price=100.0,
                liquidity_path="taker",
                book_best_bid=99.9,
                book_best_ask=100.1,
            ),
            rules=rules,
            cost_context=context,
            local_depth_notional=100.0,
        )

        self.assertEqual(report.execution_model_id, BINANCE_USDM_V3_EXECUTION_MODEL_ID)
        self.assertFalse(report.accepted)
        self.assertIn("capacity_limit_exceeded", report.reason_codes)

        ok_report = simulate_binance_usdm_order(
            BinanceUsdMOrderRequest(
                symbol="BTCUSDT",
                side="BUY",
                quantity=0.05,
                price=100.0,
                liquidity_path="taker",
                book_best_bid=99.9,
                book_best_ask=100.1,
            ),
            rules=rules,
            cost_context=context,
            local_depth_notional=100.0,
        )

        self.assertTrue(ok_report.accepted)
        self.assertGreater(ok_report.total_cost_bps, ok_report.fee_bps)
        self.assertEqual(ok_report.status, "filled")

    def test_funding_and_mark_price_liquidation_helpers_are_side_aware(self) -> None:
        self.assertAlmostEqual(funding_cashflow(10_000.0, 0.0001, position_side="long"), 1.0)
        self.assertAlmostEqual(funding_cashflow(10_000.0, 0.0001, position_side="short"), -1.0)
        self.assertLess(
            approximate_mark_price_liquidation_price(100.0, side="long", leverage=10.0, maintenance_margin_ratio=0.01),
            100.0,
        )
        self.assertGreater(
            approximate_mark_price_liquidation_price(100.0, side="short", leverage=10.0, maintenance_margin_ratio=0.01),
            100.0,
        )


if __name__ == "__main__":
    unittest.main()
