from __future__ import annotations

import unittest

from engine.reporting.universe_dashboard import build_universe_dashboard


class UniverseDashboardTests(unittest.TestCase):
    def test_universe_dashboard_surfaces_symbol_lifecycle(self) -> None:
        payload = build_universe_dashboard(
            {
                "manifest_state": {"BTCUSDT": "PAPER_ALLOWED", "DOGEUSDT": "RESEARCH_ONLY"},
                "rings": {"core": ["BTCUSDT"], "candidate": ["DOGEUSDT"]},
                "exposure_caps": {"core": 0.5},
                "admissions": [{"symbol": "BTCUSDT", "decision": "admit"}],
                "demotions": [{"symbol": "DOGEUSDT", "decision": "demote"}],
                "quarantine": [{"symbol": "XRPUSDT", "reason": "data_gap"}],
                "scorecards": {"BTCUSDT": {"liquidity": 0.98}},
                "discovery": [{"symbol": "SOLUSDT"}],
            }
        )

        self.assertEqual(payload["page"], "Universe")
        self.assertEqual(payload["manifest_state"]["BTCUSDT"], "PAPER_ALLOWED")
        self.assertEqual(payload["quarantine"][0]["reason"], "data_gap")
        self.assertEqual(payload["scorecards"]["BTCUSDT"]["liquidity"], 0.98)


if __name__ == "__main__":
    unittest.main()
