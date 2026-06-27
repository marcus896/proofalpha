from __future__ import annotations

import unittest

from engine.execution.order_manager import OrderManager
from engine.execution.order_state import OrderLifecycleState

from tests.execution.test_venue_order_request_schema import _intent


class OrderStateMachineTests(unittest.TestCase):
    def test_order_lifecycle_is_event_sourced(self) -> None:
        manager = OrderManager()
        record = manager.create_order(_intent())

        manager.transition(record.order_id, OrderLifecycleState.RISK_APPROVED, reason="risk_gate_passed")
        manager.transition(record.order_id, OrderLifecycleState.TRANSLATED, reason="venue_request_built")
        manager.transition(record.order_id, OrderLifecycleState.SUBMITTED, reason="paper_submit")
        manager.transition(record.order_id, OrderLifecycleState.ACKED, reason="paper_ack")

        state = manager.get(record.order_id)
        self.assertEqual(state.lifecycle_state, OrderLifecycleState.ACKED)
        self.assertEqual([event.to_state for event in state.events][-1], OrderLifecycleState.ACKED)
        self.assertEqual(state.events[0].to_state, OrderLifecycleState.CREATED)


if __name__ == "__main__":
    unittest.main()
