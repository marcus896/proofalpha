from __future__ import annotations

import unittest

from engine.execution.margin_leverage_manager import MarginLeverageManager


class MarginLeverageManagerTests(unittest.TestCase):
    def test_blocks_when_observed_state_differs_from_expected_state(self) -> None:
        result = MarginLeverageManager(expected_margin_mode="cross", expected_leverage=10).check(
            observed_margin_mode="isolated",
            observed_leverage=20,
        )

        self.assertFalse(result.passed)
        self.assertIn("margin_mode_mismatch", result.rejections)
        self.assertIn("leverage_mismatch", result.rejections)


if __name__ == "__main__":
    unittest.main()
