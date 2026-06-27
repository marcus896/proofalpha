from __future__ import annotations

import unittest

from engine.execution.cancel_replace_manager import CancelReplaceBudget, CancelReplaceManager


class CancelReplaceBudgetTests(unittest.TestCase):
    def test_cancel_replace_is_budgeted_and_tracks_amends(self) -> None:
        manager = CancelReplaceManager(CancelReplaceBudget(max_amends=1, max_cancel_replace=1, maker_timeout_seconds=30))

        first = manager.evaluate(
            order_id="order-1",
            created_at_utc="2026-05-07T00:00:00Z",
            now_utc="2026-05-07T00:01:00Z",
            amend_count=0,
        )
        manager.record_amend("order-1")
        second = manager.evaluate(
            order_id="order-1",
            created_at_utc="2026-05-07T00:00:00Z",
            now_utc="2026-05-07T00:02:00Z",
            amend_count=1,
        )

        self.assertTrue(first.allowed)
        self.assertEqual(first.action, "cancel_replace")
        self.assertFalse(second.allowed)
        self.assertIn("max_amends_reached", second.reasons)


if __name__ == "__main__":
    unittest.main()
