from __future__ import annotations

import unittest

from engine.config.models import BacktestResult
from engine.validation.gate_spec import evaluate_validation_gate_spec


class MinOosTradesGateTests(unittest.TestCase):
    def test_min_oos_trade_gate_blocks_small_selection_oos_sample(self) -> None:
        results = evaluate_validation_gate_spec(
            final_holdout_result=_result(trade_count=150),
            selection_oos_result=_result(trade_count=17),
            capacity_report={
                "turnover_within_budget": True,
                "capacity_5x_edge_erosion": 0.10,
                "capacity_5x_fill_completion": 0.98,
            },
            scenario_report={"passed": True, "regime_scenario_pass_matrix": {"calm": {"baseline": True}}},
            regime_report={"passed": True},
        )

        by_name = {result.name: result for result in results}
        self.assertFalse(by_name["min_oos_trades"].passed)
        self.assertEqual(by_name["min_oos_trades"].actual, 17)
        self.assertEqual(by_name["min_oos_trades"].threshold, 120)


def _result(*, trade_count: int) -> BacktestResult:
    return BacktestResult(
        trade_count=trade_count,
        win_rate=0.55,
        gross_pnl=1.2,
        net_pnl=1.0,
        fee_spend=0.1,
        funding_spend=0.1,
        sharpe=1.25,
        sortino=1.25,
        max_drawdown=-0.10,
        equity_curve=[0.0, 0.5, 1.0],
    )


if __name__ == "__main__":
    unittest.main()
