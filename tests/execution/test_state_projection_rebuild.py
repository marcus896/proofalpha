from __future__ import annotations

import unittest

from engine.execution.ledger import ExecutionLedger, LedgerEvent
from engine.execution.state_projection import rebuild_state_projection


class StateProjectionRebuildTests(unittest.TestCase):
    def test_rebuilds_projected_positions_cash_fees_and_pnl_from_ledger(self) -> None:
        ledger = ExecutionLedger()
        ledger.append(LedgerEvent.fill("fill-1", order_id="order-1", symbol="BTCUSDT", side="BUY", qty=0.1, price=50_000.0, fee=2.0))
        ledger.append(LedgerEvent.fill("fill-2", order_id="order-2", symbol="BTCUSDT", side="SELL", qty=0.04, price=50_100.0, fee=1.0))
        ledger.append(LedgerEvent.funding("funding-1", symbol="BTCUSDT", amount=-0.5))

        projection = rebuild_state_projection(ledger.events)

        self.assertEqual(projection.positions["BTCUSDT"], 0.06)
        self.assertEqual(projection.fees, 3.0)
        self.assertEqual(projection.funding, -0.5)
        self.assertEqual(len(projection.projection_digest), 64)


if __name__ == "__main__":
    unittest.main()
