from __future__ import annotations

import unittest

from engine.execution.executor_risk_manager import ExecutorRiskManager
from engine.execution.risk_state import RiskState


class ExecutorRiskManagerTests(unittest.TestCase):
    def test_risk_manager_can_approve_reduce_only_lockdown_and_halt(self) -> None:
        manager = ExecutorRiskManager()

        self.assertEqual(manager.evaluate(action="increase", state=RiskState.NORMAL).decision, "approved")
        self.assertEqual(manager.evaluate(action="increase", state=RiskState.REDUCE_ONLY).decision, "reduce_only")
        self.assertEqual(manager.evaluate(action="increase", state=RiskState.LOCKDOWN).decision, "lockdown")
        self.assertEqual(manager.evaluate(action="increase", state=RiskState.HALT).decision, "halt")


if __name__ == "__main__":
    unittest.main()
