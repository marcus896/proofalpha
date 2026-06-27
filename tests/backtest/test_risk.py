import unittest

from engine.backtest.risk import max_drawdown


class RiskMetricTests(unittest.TestCase):
    def test_max_drawdown_is_reported_as_fraction_of_peak_equity(self) -> None:
        equity_curve = [0.0, 0.50, 0.25, 0.75]

        self.assertAlmostEqual(max_drawdown(equity_curve), -0.1666666667, places=8)

    def test_max_drawdown_uses_starting_equity_floor(self) -> None:
        equity_curve = [0.0, -0.10, 0.20, 0.05]

        self.assertAlmostEqual(max_drawdown(equity_curve), -0.125, places=8)


if __name__ == "__main__":
    unittest.main()
