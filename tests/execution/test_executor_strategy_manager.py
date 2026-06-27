from __future__ import annotations

import unittest

from engine.execution.executor_strategy_manager import ExecutorStrategyManager, TacticInput
from engine.execution.execution_tactics import ExecutionTactic
from engine.execution.risk_state import RiskState


class ExecutorStrategyManagerTests(unittest.TestCase):
    def test_strategy_manager_chooses_tactics_without_creating_alpha(self) -> None:
        decision = ExecutorStrategyManager().choose_tactic(
            TacticInput(
                side="BUY",
                action="increase",
                spread_bps=1.0,
                depth_notional=100_000.0,
                volatility_bps=20.0,
                order_flow_imbalance=0.0,
                funding_seconds=3600,
                mark_index_divergence_bps=1.0,
                target_drift_bps=40.0,
                risk_state=RiskState.NORMAL,
                fill_probability=0.8,
                adverse_selection_bps=1.0,
                open_order_count=0,
            )
        )

        self.assertEqual(decision.tactic, ExecutionTactic.POST_ONLY_GTX)
        self.assertEqual(decision.side, "BUY")
        self.assertFalse(decision.creates_alpha)


if __name__ == "__main__":
    unittest.main()
