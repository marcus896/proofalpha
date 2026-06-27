from __future__ import annotations

import unittest

from engine.universe.quarantine import evaluate_symbol_quarantine
from engine.universe.manifest import SymbolState


class SymbolQuarantineTests(unittest.TestCase):
    def test_data_gap_or_reconciliation_issue_quarantines_symbol(self) -> None:
        decision = evaluate_symbol_quarantine(data_gap=True, reconciliation_issue=True, venue_rule_change=False)

        self.assertEqual(decision.target_state, SymbolState.QUARANTINED)
        self.assertIn("data_gap", decision.reasons)
        self.assertIn("reconciliation_issue", decision.reasons)


if __name__ == "__main__":
    unittest.main()
