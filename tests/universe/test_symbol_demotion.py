from __future__ import annotations

import unittest

from engine.universe.demotion import evaluate_symbol_demotion
from engine.universe.manifest import SymbolState


class SymbolDemotionTests(unittest.TestCase):
    def test_liquidity_failure_or_repeated_strategy_failure_demotes_symbol(self) -> None:
        decision = evaluate_symbol_demotion(
            data_gap=False,
            liquidity_failure=True,
            reconciliation_issue=False,
            slippage_shock=False,
            funding_shock=False,
            repeated_strategy_failure=True,
        )

        self.assertEqual(decision.target_state, SymbolState.REDUCE_ONLY)
        self.assertIn("liquidity_failure", decision.reasons)


if __name__ == "__main__":
    unittest.main()
