from __future__ import annotations

import unittest

from engine.learning.dataset_builder import build_learning_dataset


class LearningDatasetBuilderTests(unittest.TestCase):
    def test_paper_telemetry_builds_learning_dataset_rows(self) -> None:
        dataset = build_learning_dataset(
            orders=[{"order_id": "order-1", "symbol": "BTCUSDT", "side": "BUY"}],
            fills=[{"order_id": "order-1", "fill_price": 50015.0, "qty": 0.1}],
            rejects=[],
            paper_session_telemetry=[{"order_id": "order-1", "spread_bps": 1.2, "slip_bps": 3.5}],
            websocket_quality={"score": 0.95},
            book_depth=[{"symbol": "BTCUSDT", "depth_notional": 100000.0}],
            spread_history=[1.0, 1.2],
            funding_history=[0.01],
            portfolio_exposures={"BTCUSDT": 25000.0},
            artifact_performance={"artifact-btc": {"sharpe": 1.4}},
            validation_history=[{"validation_report_id": "validation-v1", "passed": True}],
        )

        self.assertEqual(dataset.status, "ready")
        self.assertEqual(dataset.rows[0]["symbol"], "BTCUSDT")
        self.assertFalse(dataset.direct_trading_change_allowed)


if __name__ == "__main__":
    unittest.main()
