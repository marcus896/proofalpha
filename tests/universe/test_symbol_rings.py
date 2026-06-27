from __future__ import annotations

import unittest

from engine.universe.rings import Ring, ring_for_symbol, ring_weight_cap


class SymbolRingsTests(unittest.TestCase):
    def test_rings_assign_btc_eth_and_enforce_exposure_caps(self) -> None:
        self.assertEqual(ring_for_symbol("BTCUSDT"), Ring.RING_0_CORE)
        self.assertEqual(ring_for_symbol("ETHUSDT"), Ring.RING_0_CORE)
        self.assertLess(ring_weight_cap(Ring.RING_3_RESEARCH), ring_weight_cap(Ring.RING_0_CORE))


if __name__ == "__main__":
    unittest.main()
