from __future__ import annotations

import unittest

from engine.config.models import BacktestResult
from engine.validation.gate_spec import evaluate_validation_gate_spec


class ScenarioRegimePassMatrixTests(unittest.TestCase):
    def test_scenario_pass_matrix_is_enforced(self) -> None:
        results = evaluate_validation_gate_spec(
            final_holdout_result=_result(),
            selection_oos_result=_result(),
            capacity_report=_passing_capacity(),
            scenario_report={"passed": True, "regime_scenario_pass_matrix": {"crash": {"venue_outage": False}}},
            regime_report={"passed": True},
        )

        by_name = {result.name: result for result in results}
        self.assertFalse(by_name["scenario_pass_matrix"].passed)
        self.assertEqual(by_name["scenario_pass_matrix"].reason, "scenario_pass_matrix_failed")

    def test_regime_pass_matrix_is_enforced(self) -> None:
        results = evaluate_validation_gate_spec(
            final_holdout_result=_result(),
            selection_oos_result=_result(),
            capacity_report=_passing_capacity(),
            scenario_report={"passed": True, "regime_scenario_pass_matrix": {"calm": {"baseline": True}}},
            regime_report={"passed": False},
        )

        by_name = {result.name: result for result in results}
        self.assertFalse(by_name["regime_pass_matrix"].passed)
        self.assertEqual(by_name["regime_pass_matrix"].reason, "regime_pass_matrix_failed")


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


def _passing_capacity() -> dict[str, object]:
    return {
        "turnover_within_budget": True,
        "capacity_5x_edge_erosion": 0.10,
        "capacity_5x_fill_completion": 0.98,
    }


if __name__ == "__main__":
    unittest.main()
