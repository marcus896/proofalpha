import unittest

from engine.backtest.indicators import rsi


class IndicatorTests(unittest.TestCase):
    def test_rsi_stays_neutral_when_prices_are_flat(self) -> None:
        values = rsi([100.0] * 20, 14)

        self.assertEqual(values[:14], [50.0] * 14)
        self.assertEqual(values[14:], [50.0] * 6)


if __name__ == "__main__":
    unittest.main()
