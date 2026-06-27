from __future__ import annotations

import unittest

from engine.universe.manifest import SymbolState, UniverseManifest


class UniverseManifestTests(unittest.TestCase):
    def test_new_symbols_start_research_only_and_manifest_controls_paper_active(self) -> None:
        manifest = UniverseManifest.create(universe_id="usdm-v1", approved_by="risk")
        manifest = manifest.add_symbol("SOLUSDT")

        self.assertEqual(manifest.symbols["SOLUSDT"].state, SymbolState.RESEARCH_ONLY)
        self.assertFalse(manifest.paper_allowed("SOLUSDT"))

        approved = manifest.with_state("SOLUSDT", SymbolState.PAPER_ALLOWED, reason="admission_passed")
        self.assertTrue(approved.paper_allowed("SOLUSDT"))


if __name__ == "__main__":
    unittest.main()
