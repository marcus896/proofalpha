from __future__ import annotations

import unittest

from engine.execution.idempotency import IdempotencyManager, deterministic_client_order_id

from tests.execution.test_venue_order_request_schema import _intent


class IdempotencyTests(unittest.TestCase):
    def test_client_order_id_is_deterministic_and_duplicate_detection_is_stateful(self) -> None:
        intent = _intent()
        first = deterministic_client_order_id(intent, venue="binance_usdm")
        second = deterministic_client_order_id(intent, venue="binance_usdm")
        manager = IdempotencyManager()

        self.assertEqual(first, second)
        self.assertTrue(manager.register(intent, venue="binance_usdm"))
        self.assertFalse(manager.register(intent, venue="binance_usdm"))


if __name__ == "__main__":
    unittest.main()
