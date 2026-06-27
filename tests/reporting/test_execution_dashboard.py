from __future__ import annotations

import unittest

from engine.reporting.execution_dashboard import (
    REQUIRED_EXECUTION_DASHBOARD_FIELDS,
    build_execution_dashboard,
)
from engine.reporting.risk_dashboard import build_risk_dashboard


class ExecutionDashboardTests(unittest.TestCase):
    def test_execution_dashboard_surfaces_desk_risk_and_reconciliation_state(self) -> None:
        payload = build_execution_dashboard(
            {
                "pending_intents": [{"intent_id": "intent-1"}],
                "risk_approvals": [{"intent_id": "intent-1", "status": "approved"}],
                "risk_rejections": [{"intent_id": "intent-2", "reason": "symbol_not_allowed"}],
                "translated_orders": [{"client_order_id": "cid-1"}],
                "open_orders": [{"venue_order_id": "order-1"}],
                "fills": [{"fill_id": "fill-1", "fee": 0.42}],
                "partial_fills": [{"fill_id": "fill-2", "fill_ratio": 0.4}],
                "slippage": {"avg_bps": 1.2},
                "fees": {"total": 0.42},
                "funding": {"latest": -0.01},
                "markouts": {"5m": 0.3},
                "client_order_ids": ["cid-1"],
                "websocket_freshness": {"seconds_since_last_event": 4},
                "reconciliation_status": "PASS",
                "risk_state": "NORMAL",
                "circuit_breakers": {"daily_loss": "armed"},
            }
        )

        self.assertEqual(payload["page"], "Execution Desk")
        self.assertEqual(payload["reconciliation_status"], "PASS")
        self.assertEqual(payload["risk_state"], "NORMAL")
        self.assertEqual(payload["pending_intents"][0]["intent_id"], "intent-1")
        self.assertEqual(payload["partial_fills"][0]["fill_ratio"], 0.4)
        for field in REQUIRED_EXECUTION_DASHBOARD_FIELDS:
            self.assertIn(field, payload)

    def test_risk_dashboard_keeps_vetoes_visible(self) -> None:
        payload = build_risk_dashboard(
            {
                "risk_state": "REDUCE_ONLY",
                "approvals": ["close-BTC"],
                "rejections": [{"intent_id": "open-ETH", "reason": "funding_budget"}],
                "circuit_breakers": {"venue_outage": "tripped"},
                "funding_guard": {"status": "blocked"},
                "liquidation_guard": {"buffer": 0.18},
                "margin_leverage": {"max_leverage": 2},
                "reconciliation_status": "FAIL",
            }
        )

        self.assertEqual(payload["page"], "Risk")
        self.assertEqual(payload["risk_state"], "REDUCE_ONLY")
        self.assertEqual(payload["rejections"][0]["reason"], "funding_budget")
        self.assertEqual(payload["circuit_breakers"]["venue_outage"], "tripped")


if __name__ == "__main__":
    unittest.main()
