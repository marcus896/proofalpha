from __future__ import annotations

import unittest

from engine.config.models import BacktestResult
from engine.validation.gate_spec import evaluate_validation_gate_spec


class CapacityTurnoverGateTests(unittest.TestCase):
    def test_capacity_gate_blocks_more_than_25_percent_5x_degradation(self) -> None:
        results = evaluate_validation_gate_spec(
            final_holdout_result=_result(),
            selection_oos_result=_result(),
            capacity_report={
                "turnover_within_budget": True,
                "capacity_5x_edge_erosion": 0.30,
                "capacity_5x_fill_completion": 0.98,
            },
            scenario_report=_passing_matrix(),
            regime_report={"passed": True},
        )

        by_name = {result.name: result for result in results}
        self.assertFalse(by_name["capacity_5x"].passed)
        self.assertEqual(by_name["capacity_5x"].threshold, 0.25)

    def test_turnover_budget_gate_blocks_over_budget_candidates(self) -> None:
        results = evaluate_validation_gate_spec(
            final_holdout_result=_result(),
            selection_oos_result=_result(),
            capacity_report={
                "turnover_within_budget": False,
                "capacity_5x_edge_erosion": 0.10,
                "capacity_5x_fill_completion": 0.98,
            },
            scenario_report=_passing_matrix(),
            regime_report={"passed": True},
        )

        by_name = {result.name: result for result in results}
        self.assertFalse(by_name["turnover_budget"].passed)
        self.assertEqual(by_name["turnover_budget"].reason, "turnover_budget_exceeded")


def _result() -> BacktestResult:
    return BacktestResult(
        trade_count=150,
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


def _passing_matrix() -> dict[str, object]:
    return {"passed": True, "regime_scenario_pass_matrix": {"calm": {"baseline": True}}}


if __name__ == "__main__":
    unittest.main()
