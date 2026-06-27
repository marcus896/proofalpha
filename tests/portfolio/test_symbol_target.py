from __future__ import annotations

import unittest

from engine.portfolio.symbol_target import SymbolTarget, validate_symbol_target


class SymbolTargetTests(unittest.TestCase):
    def test_symbol_target_records_limits_and_rebalance_reason(self) -> None:
        target = SymbolTarget(
            symbol="BTCUSDT",
            artifact_id="artifact-btc",
            role="core",
            target_weight=0.25,
            target_notional=25_000.0,
            max_loss_budget=1_000.0,
            max_slippage_bps=8.0,
            max_funding_cost_bps=4.0,
            rebalance_reason="scheduled",
        )

        validation = validate_symbol_target(target)

        self.assertTrue(validation.passed, validation.issues)
        self.assertEqual(target.to_dict()["target_notional"], 25_000.0)

    def test_symbol_target_rejects_non_finite_numeric_fields(self) -> None:
        target = SymbolTarget(
            symbol="BTCUSDT",
            artifact_id="artifact-btc",
            role="core",
            target_weight=float("nan"),
            target_notional=float("inf"),
            max_loss_budget=1_000.0,
            max_slippage_bps=8.0,
            max_funding_cost_bps=4.0,
            rebalance_reason="scheduled",
        )

        validation = validate_symbol_target(target)

        self.assertFalse(validation.passed)
        self.assertIn("non_finite_target_weight", validation.issues)
        self.assertIn("non_finite_target_notional", validation.issues)


if __name__ == "__main__":
    unittest.main()
