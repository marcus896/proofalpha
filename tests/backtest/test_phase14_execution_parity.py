from __future__ import annotations

import unittest

from engine.backtest.execution_parity_report import ExecutionParityReport
from engine.backtest.order_intent_simulation import OrderIntentSimulation
from engine.backtest.partial_fill_model import PartialFillModel


class Phase14ExecutionParityTests(unittest.TestCase):
    def test_order_intent_simulation_matches_paper_order_path_shape(self) -> None:
        simulation = OrderIntentSimulation(
            signal_event={"signal": "rebalance"},
            target_portfolio_id="target-1",
            delta_order_plan_id="delta-1",
            internal_order_intent={"intent_id": "intent-1"},
            simulated_venue_order_request={"client_order_id": "cid-1"},
            simulated_fill_events=[{"fill_id": "fill-1"}],
        )

        self.assertEqual(simulation.to_dict()["simulated_venue_order_request"]["client_order_id"], "cid-1")

    def test_partial_fill_model_records_unfilled_quantity(self) -> None:
        model = PartialFillModel(fill_probability=0.4, queue_position_estimate=0.8, filled_quantity=2.0, requested_quantity=5.0)

        self.assertEqual(model.unfilled_quantity, 3.0)

    def test_execution_parity_report_contains_tca_fields(self) -> None:
        report = ExecutionParityReport(
            signal_pnl=10.0,
            execution_adjusted_pnl=8.0,
            fees=0.5,
            funding=0.1,
            slippage=1.0,
            missed_fills=1,
            adverse_selection=0.2,
            cancel_replace_count=2,
            order_reject_count=1,
        )

        self.assertEqual(report.to_learning_row()["execution_drag"], 2.0)


if __name__ == "__main__":
    unittest.main()
