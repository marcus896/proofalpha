from __future__ import annotations

import unittest

from engine.execution.ledger import ExecutionLedger, LedgerEvent
from engine.execution.reconciliation_repair import build_reconciliation_repair_plan


class ReconciliationRepairTests(unittest.TestCase):
    def test_repair_plan_detects_missing_fill_position_balance_and_stale_clock(self) -> None:
        ledger = ExecutionLedger()
        ledger.append(LedgerEvent.fill("fill-local", order_id="order-1", symbol="BTCUSDT", side="BUY", qty=0.1, price=50_000.0, fee=1.0))

        plan = build_reconciliation_repair_plan(
            ledger.events,
            gateway_fills=[{"fill_id": "fill-missing", "symbol": "BTCUSDT", "side": "BUY", "qty": 0.1, "price": 50_000.0}],
            gateway_positions={"BTCUSDT": 0.2},
            gateway_cash_balance=-10_001.0,
            local_cash_balance=-5_001.0,
            stale_websocket=True,
            clock_drift_seconds=10,
        )

        self.assertEqual(plan.status, "REPAIR_REQUIRED")
        self.assertIn("missing_fill:fill-missing", plan.issues)
        self.assertIn("position_mismatch:BTCUSDT", plan.issues)
        self.assertIn("balance_mismatch", plan.issues)
        self.assertIn("stale_websocket", plan.issues)
        self.assertIn("clock_drift", plan.issues)


if __name__ == "__main__":
    unittest.main()
