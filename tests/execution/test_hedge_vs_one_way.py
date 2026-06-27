from __future__ import annotations

import unittest

from engine.execution.venue_translator.binance_usdm import BinanceUsdMTranslator

from tests.execution.test_tick_step_min_notional import _rules_cache
from tests.execution.test_venue_order_request_schema import _intent


class HedgeVsOneWayTests(unittest.TestCase):
    def test_position_side_is_explicit_for_one_way_and_hedge_modes(self) -> None:
        one_way = BinanceUsdMTranslator(_rules_cache(), position_mode="one_way").translate(
            _intent(), quantity=0.1, price=50_000.0, timestamp=1778083200000
        )
        hedge = BinanceUsdMTranslator(_rules_cache(), position_mode="hedge").translate(
            _intent(), quantity=0.1, price=50_000.0, timestamp=1778083200000
        )

        self.assertEqual(one_way.rounded_order["positionSide"], "BOTH")
        self.assertEqual(hedge.rounded_order["positionSide"], "LONG")


if __name__ == "__main__":
    unittest.main()
