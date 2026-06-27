from __future__ import annotations

import unittest

from engine.execution.funding_guard import FundingGuard, FundingGuardConfig


class FundingGuardTests(unittest.TestCase):
    def test_funding_guard_blocks_near_funding_open_over_budget(self) -> None:
        result = FundingGuard(FundingGuardConfig(max_cost_bps=3.0, block_open_seconds_before_funding=300)).evaluate(
            action="increase",
            now_utc="2026-05-07T07:56:00Z",
            next_funding_time_utc="2026-05-07T08:00:00Z",
            expected_funding_cost_bps=4.0,
        )

        self.assertFalse(result.passed)
        self.assertIn("near_funding_open_block", result.rejections)
        self.assertIn("funding_cost_budget_exceeded", result.rejections)


if __name__ == "__main__":
    unittest.main()
