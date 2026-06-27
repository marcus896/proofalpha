from __future__ import annotations

import unittest

from engine.execution.risk_state import RiskState, allowed_actions_for_state


class RiskStateMachineTests(unittest.TestCase):
    def test_allowed_actions_by_risk_state(self) -> None:
        self.assertIn("increase", allowed_actions_for_state(RiskState.NORMAL))
        self.assertNotIn("increase", allowed_actions_for_state(RiskState.DEFENSIVE))
        self.assertEqual(allowed_actions_for_state(RiskState.REDUCE_ONLY), {"reduce", "close"})
        self.assertEqual(allowed_actions_for_state(RiskState.HALT), set())


if __name__ == "__main__":
    unittest.main()
