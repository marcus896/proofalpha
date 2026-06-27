from __future__ import annotations

import unittest

from engine.execution.reconciliation_repair import reconciliation_allows_new_exposure


class ReconciliationBlocksNewExposureTests(unittest.TestCase):
    def test_reconciliation_mismatch_blocks_new_exposure(self) -> None:
        self.assertFalse(reconciliation_allows_new_exposure("BLOCK", action="increase"))
        self.assertFalse(reconciliation_allows_new_exposure("REPAIR_REQUIRED", action="open"))
        self.assertTrue(reconciliation_allows_new_exposure("PASS", action="increase"))
        self.assertTrue(reconciliation_allows_new_exposure("BLOCK", action="close"))


if __name__ == "__main__":
    unittest.main()
