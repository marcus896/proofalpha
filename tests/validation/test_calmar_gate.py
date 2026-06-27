from __future__ import annotations

import unittest

from engine.config.models import BacktestResult
from engine.validation.gate_spec import compute_final_holdout_calmar, evaluate_validation_gate_spec


class CalmarGateTests(unittest.TestCase):
    def test_calmar_uses_net_pnl_over_absolute_drawdown(self) -> None:
        self.assertEqual(compute_final_holdout_calmar(_result(net_pnl=1.5, max_drawdown=-0.5)), 3.0)

    def test_final_holdout_calmar_gate_blocks_bad_holdout(self) -> None:
        results = evaluate_validation_gate_spec(
            final_holdout_result=_result(net_pnl=0.30, max_drawdown=-0.60, sharpe=1.5, trade_count=150),
            selection_oos_result=_result(trade_count=150),
            capacity_report=_passing_capacity(),
            scenario_report=_passing_matrix(),
            regime_report={"passed": True},
        )

        by_name = {result.name: result for result in results}
        self.assertFalse(by_name["final_holdout_calmar"].passed)
        self.assertEqual(by_name["final_holdout_calmar"].actual, 0.5)
        self.assertEqual(by_name["final_holdout_calmar"].threshold, 0.75)


def _result(
    *,
    net_pnl: float = 1.0,
    max_drawdown: float = -0.10,
    sharpe: float = 1.25,
    trade_count: int = 120,
) -> BacktestResult:
    return BacktestResult(
        trade_count=trade_count,
        win_rate=0.55,
        gross_pnl=net_pnl + 0.2,
        net_pnl=net_pnl,
        fee_spend=0.1,
        funding_spend=0.1,
        sharpe=sharpe,
        sortino=sharpe,
        max_drawdown=max_drawdown,
        equity_curve=[0.0, max(net_pnl / 2.0, 0.0), net_pnl],
    )


def _passing_capacity() -> dict[str, object]:
    return {
        "turnover_within_budget": True,
        "capacity_5x_edge_erosion": 0.10,
        "capacity_5x_fill_completion": 0.98,
    }


def _passing_matrix() -> dict[str, object]:
    return {"passed": True, "regime_scenario_pass_matrix": {"calm": {"baseline": True}}}


if __name__ == "__main__":
    unittest.main()
