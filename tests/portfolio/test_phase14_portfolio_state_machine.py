from __future__ import annotations

import unittest

from engine.portfolio.portfolio_state_machine import PortfolioState, allowed_portfolio_action


class Phase14PortfolioStateMachineTests(unittest.TestCase):
    def test_defensive_state_is_reduce_only_for_new_exposure(self) -> None:
        self.assertFalse(allowed_portfolio_action(PortfolioState.DEFENSIVE, "increase"))
        self.assertTrue(allowed_portfolio_action(PortfolioState.DEFENSIVE, "reduce"))

    def test_halt_blocks_all_portfolio_actions(self) -> None:
        self.assertFalse(allowed_portfolio_action(PortfolioState.HALT, "reduce"))


if __name__ == "__main__":
    unittest.main()
