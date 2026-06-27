from __future__ import annotations

import unittest

from engine.execution.ledger import ExecutionLedger, LedgerEvent


class ExecutionLedgerTests(unittest.TestCase):
    def test_ledger_records_order_fill_fee_funding_position_cash_and_risk_events(self) -> None:
        ledger = ExecutionLedger()
        ledger.append(LedgerEvent.order("order-1", symbol="BTCUSDT", side="BUY", qty=0.1, price=50_000.0))
        ledger.append(LedgerEvent.fill("fill-1", order_id="order-1", symbol="BTCUSDT", side="BUY", qty=0.1, price=50_010.0, fee=2.5))
        ledger.append(LedgerEvent.funding("funding-1", symbol="BTCUSDT", amount=-1.2))
        ledger.append(LedgerEvent.risk("risk-1", reason_code="spread_too_wide"))

        self.assertEqual(len(ledger.events), 4)
        self.assertEqual(ledger.events[1].event_type, "FILL")
        self.assertEqual(len(ledger.digest), 64)


if __name__ == "__main__":
    unittest.main()
