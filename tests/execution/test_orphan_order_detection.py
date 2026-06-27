from __future__ import annotations

import unittest

from engine.execution.reconciliation_repair import detect_orphan_orders


class OrphanOrderDetectionTests(unittest.TestCase):
    def test_detects_gateway_order_missing_from_local_ledger(self) -> None:
        orphans = detect_orphan_orders(local_order_ids={"order-local"}, gateway_order_ids={"order-local", "order-orphan"})

        self.assertEqual(orphans, ["order-orphan"])


if __name__ == "__main__":
    unittest.main()
