from __future__ import annotations

import unittest

from engine.execution.errors import DuplicateIntentError
from engine.execution.order_manager import OrderManager

from tests.execution.test_venue_order_request_schema import _intent


class DuplicateIntentRejectedTests(unittest.TestCase):
    def test_duplicate_submit_is_impossible(self) -> None:
        manager = OrderManager()
        intent = _intent()

        manager.create_order(intent)

        with self.assertRaises(DuplicateIntentError):
            manager.create_order(intent)


if __name__ == "__main__":
    unittest.main()
