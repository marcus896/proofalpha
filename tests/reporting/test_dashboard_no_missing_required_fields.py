from __future__ import annotations

import unittest

from engine.reporting.autoresearch_dashboard import REQUIRED_AUTORESEARCH_DASHBOARD_FIELDS, build_autoresearch_dashboard
from engine.reporting.execution_dashboard import REQUIRED_EXECUTION_DASHBOARD_FIELDS, build_execution_dashboard
from engine.reporting.learning_dashboard import REQUIRED_LEARNING_DASHBOARD_FIELDS, build_learning_dashboard
from engine.reporting.portfolio_dashboard import REQUIRED_PORTFOLIO_DASHBOARD_FIELDS, build_portfolio_dashboard
from engine.reporting.risk_dashboard import REQUIRED_RISK_DASHBOARD_FIELDS, build_risk_dashboard
from engine.reporting.universe_dashboard import REQUIRED_UNIVERSE_DASHBOARD_FIELDS, build_universe_dashboard


class DashboardRequiredFieldTests(unittest.TestCase):
    def test_phase12_dashboards_have_no_missing_required_fields(self) -> None:
        dashboards = [
            (build_execution_dashboard({}), REQUIRED_EXECUTION_DASHBOARD_FIELDS),
            (build_risk_dashboard({}), REQUIRED_RISK_DASHBOARD_FIELDS),
            (build_portfolio_dashboard({}), REQUIRED_PORTFOLIO_DASHBOARD_FIELDS),
            (build_learning_dashboard({}), REQUIRED_LEARNING_DASHBOARD_FIELDS),
            (build_universe_dashboard({}), REQUIRED_UNIVERSE_DASHBOARD_FIELDS),
            (build_autoresearch_dashboard({}), REQUIRED_AUTORESEARCH_DASHBOARD_FIELDS),
        ]

        for payload, required_fields in dashboards:
            with self.subTest(page=payload["page"]):
                self.assertEqual([], [field for field in required_fields if field not in payload])

    def test_portfolio_dashboard_includes_pnl_attribution_buckets(self) -> None:
        payload = build_portfolio_dashboard(
            {
                "target_weights": {"BTCUSDT": 0.4},
                "current_weights": {"BTCUSDT": 0.35},
                "deltas": {"BTCUSDT": 0.05},
                "exposures": {"gross": 0.35},
                "btc_beta": 0.8,
                "eth_beta": 0.2,
                "cluster_exposure": {"majors": 0.35},
                "turnover": 0.12,
                "funding_budget": {"remaining": 3.5},
            }
        )

        for key in (
            "btc_beta",
            "eth_beta",
            "symbol_selection",
            "timing",
            "funding",
            "fees",
            "slippage",
            "spread_impact",
            "rebalance_cost",
            "residual_alpha",
        ):
            self.assertIn(key, payload["pnl_attribution"])


if __name__ == "__main__":
    unittest.main()
