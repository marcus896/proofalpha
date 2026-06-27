from __future__ import annotations

import unittest

from engine.execution.reconciliation_repair import detect_duplicate_fills


class DuplicateFillDetectionTests(unittest.TestCase):
    def test_detects_duplicate_fill_ids(self) -> None:
        duplicates = detect_duplicate_fills(
            [
                {"fill_id": "fill-1"},
                {"fill_id": "fill-1"},
                {"fill_id": "fill-2"},
            ]
        )

        self.assertEqual(duplicates, ["fill-1"])


if __name__ == "__main__":
    unittest.main()
