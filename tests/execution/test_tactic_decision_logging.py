from __future__ import annotations

import unittest

from engine.execution.execution_policy_registry import ExecutionPolicyRegistry
from engine.execution.execution_tactics import ExecutionTactic


class TacticDecisionLoggingTests(unittest.TestCase):
    def test_risk_and_tactic_decisions_are_journaled(self) -> None:
        registry = ExecutionPolicyRegistry()
        registry.log_risk_decision(order_id="order-1", decision="rejected", reasons=["spread_too_wide"])
        registry.log_tactic_decision(order_id="order-1", tactic=ExecutionTactic.SKIP, reasons=["spread_too_wide"])

        self.assertEqual(len(registry.journal), 2)
        self.assertEqual(registry.journal[0]["decision_type"], "risk")
        self.assertEqual(registry.journal[1]["tactic"], "SKIP")


if __name__ == "__main__":
    unittest.main()
