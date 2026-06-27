from __future__ import annotations

import unittest

from engine.execution.liquidation_guard import LiquidationGuard, LiquidationGuardConfig


class LiquidationGuardTests(unittest.TestCase):
    def test_liquidation_guard_blocks_low_distance_and_stress_distance(self) -> None:
        result = LiquidationGuard(LiquidationGuardConfig(min_distance_bps=500.0, stress_move_bps=300.0)).evaluate(
            side="long",
            entry_price=100.0,
            mark_price=96.0,
            liquidation_price=95.0,
        )

        self.assertFalse(result.passed)
        self.assertIn("liquidation_distance_breach", result.rejections)
        self.assertIn("stress_liquidation_distance_breach", result.rejections)


if __name__ == "__main__":
    unittest.main()
