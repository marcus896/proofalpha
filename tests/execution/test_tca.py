from __future__ import annotations

import unittest

from engine.execution.tca import build_tca_report


class TransactionCostAnalysisTests(unittest.TestCase):
    def test_tca_outputs_learning_dataset_row(self) -> None:
        report = build_tca_report(
            order_id="order-1",
            symbol="BTCUSDT",
            side="BUY",
            decision_price=50_000.0,
            arrival_price=50_010.0,
            limit_price=50_020.0,
            fill_price=50_015.0,
            expected_slippage_bps=2.0,
            maker_taker_fee_bps=5.0,
            markout_prices={"1m": 50_030.0, "5m": 50_040.0, "15m": 49_990.0},
            adverse_selection_bps=1.5,
            missed_fill_cost=0.0,
        )

        self.assertEqual(report.learning_row["symbol"], "BTCUSDT")
        self.assertIn("markout_1m_bps", report.metrics)
        self.assertGreater(report.metrics["realized_vs_expected_slippage_bps"], 0.0)


if __name__ == "__main__":
    unittest.main()
