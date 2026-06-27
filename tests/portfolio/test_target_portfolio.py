from __future__ import annotations

import unittest

from engine.portfolio.allocator import PortfolioAllocation
from engine.portfolio.target_portfolio import build_target_portfolio


class TargetPortfolioTests(unittest.TestCase):
    def test_approved_allocations_become_target_weights(self) -> None:
        portfolio = build_target_portfolio(
            universe_id="binance-usdm-major",
            artifact_set_id="artifact-set-v1",
            capital_base=100_000.0,
            allocations=[
                PortfolioAllocation(
                    artifact_id="artifact-btc",
                    strategy_id="strategy-btc",
                    symbols=("BTCUSDT",),
                    portfolio_role="core",
                    notional=25_000.0,
                    expected_return_bps=12.0,
                    max_drawdown=0.08,
                )
            ],
            btc_beta_target=0.30,
            eth_beta_target=0.10,
            max_symbol_weight=0.40,
            max_cluster_weight=0.60,
        )

        self.assertEqual(portfolio.gross_exposure_target, 0.25)
        self.assertEqual(portfolio.net_exposure_target, 0.25)
        self.assertEqual(portfolio.symbol_targets[0].target_weight, 0.25)
        self.assertEqual(portfolio.to_dict()["symbol_targets"][0]["artifact_id"], "artifact-btc")

    def test_target_portfolio_rejects_non_finite_capital_and_allocation_notional(self) -> None:
        with self.assertRaisesRegex(ValueError, "capital_base_must_be_finite"):
            build_target_portfolio(
                universe_id="binance-usdm-major",
                artifact_set_id="artifact-set-v1",
                capital_base=float("inf"),
                allocations=[],
            )

        with self.assertRaisesRegex(ValueError, "allocation_notional_must_be_finite"):
            build_target_portfolio(
                universe_id="binance-usdm-major",
                artifact_set_id="artifact-set-v1",
                capital_base=100_000.0,
                allocations=[
                    PortfolioAllocation(
                        artifact_id="artifact-btc",
                        strategy_id="strategy-btc",
                        symbols=("BTCUSDT",),
                        portfolio_role="core",
                        notional=float("nan"),
                        expected_return_bps=12.0,
                        max_drawdown=0.08,
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
