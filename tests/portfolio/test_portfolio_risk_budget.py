from __future__ import annotations

import unittest

from engine.portfolio.risk_budget import PortfolioRiskBudget, evaluate_portfolio_risk_budget
from engine.portfolio.symbol_target import SymbolTarget


class PortfolioRiskBudgetTests(unittest.TestCase):
    def test_constraints_produce_explicit_rejections(self) -> None:
        result = evaluate_portfolio_risk_budget(
            [
                SymbolTarget(
                    symbol="BTCUSDT",
                    artifact_id="artifact-btc",
                    role="core",
                    target_weight=0.55,
                    target_notional=55_000.0,
                    max_loss_budget=1_000.0,
                    max_slippage_bps=8.0,
                    max_funding_cost_bps=6.0,
                    rebalance_reason="risk",
                )
            ],
            PortfolioRiskBudget(
                max_symbol_weight=0.40,
                max_cluster_weight=0.50,
                max_btc_beta=0.30,
                max_eth_beta=0.20,
                max_funding_cost_bps=4.0,
                max_turnover_weight=0.25,
                cluster_by_symbol={"BTCUSDT": "majors"},
                beta_by_symbol={"BTCUSDT": {"BTC": 1.0, "ETH": 0.1}},
                turnover_weight=0.30,
            ),
        )

        self.assertFalse(result.passed)
        self.assertIn("symbol_cap:BTCUSDT", result.rejections)
        self.assertIn("cluster_cap:majors", result.rejections)
        self.assertIn("btc_beta_cap", result.rejections)
        self.assertIn("funding_budget:BTCUSDT", result.rejections)
        self.assertIn("turnover_budget", result.rejections)

    def test_risk_budget_rejects_non_finite_target_and_budget_numbers(self) -> None:
        result = evaluate_portfolio_risk_budget(
            [
                SymbolTarget(
                    symbol="BTCUSDT",
                    artifact_id="artifact-btc",
                    role="core",
                    target_weight=float("nan"),
                    target_notional=55_000.0,
                    max_loss_budget=1_000.0,
                    max_slippage_bps=8.0,
                    max_funding_cost_bps=6.0,
                    rebalance_reason="risk",
                )
            ],
            PortfolioRiskBudget(
                max_symbol_weight=0.40,
                max_cluster_weight=float("inf"),
                max_btc_beta=0.30,
                max_eth_beta=0.20,
                max_funding_cost_bps=4.0,
                max_turnover_weight=0.25,
                cluster_by_symbol={"BTCUSDT": "majors"},
                beta_by_symbol={"BTCUSDT": {"BTC": 1.0}},
                turnover_weight=float("nan"),
            ),
        )

        self.assertFalse(result.passed)
        self.assertIn("target_non_finite:BTCUSDT:target_weight", result.rejections)
        self.assertIn("budget_non_finite:max_cluster_weight", result.rejections)
        self.assertIn("budget_non_finite:turnover_weight", result.rejections)


if __name__ == "__main__":
    unittest.main()
