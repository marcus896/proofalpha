from __future__ import annotations

import unittest

from engine.universe.filters import executor_symbol_allowed
from engine.universe.manifest import SymbolState, UniverseManifest


class ExecutorRejectsSymbolNotAllowedTests(unittest.TestCase):
    def test_executor_rejects_symbol_outside_manifest_or_not_paper_allowed(self) -> None:
        manifest = UniverseManifest.create(universe_id="usdm-v1", approved_by="risk").add_symbol("BTCUSDT")
        active = manifest.with_state("BTCUSDT", SymbolState.PAPER_ACTIVE, reason="admission_passed")

        self.assertTrue(executor_symbol_allowed(active, "BTCUSDT").allowed)
        self.assertFalse(executor_symbol_allowed(active, "DOGEUSDT").allowed)
        self.assertFalse(executor_symbol_allowed(manifest, "BTCUSDT").allowed)


if __name__ == "__main__":
    unittest.main()
