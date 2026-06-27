from __future__ import annotations

import unittest
from pathlib import Path


RUNBOOK_DIR = Path("docs/runbooks")


class RunbookChecklistTests(unittest.TestCase):
    def test_required_runbooks_exist(self) -> None:
        for name in (
            "local_smoke.md",
            "local_soak.md",
            "cloud_paper_soak.md",
            "extended_paper.md",
            "halt_and_repair.md",
        ):
            with self.subTest(name=name):
                self.assertTrue((RUNBOOK_DIR / name).exists())

    def test_local_protocols_are_executable_checklists(self) -> None:
        for name, duration in (("local_smoke.md", "2-4h"), ("local_soak.md", "8-12h")):
            text = (RUNBOOK_DIR / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn(duration, text)
                self.assertIn("```powershell", text)
                self.assertIn("- [ ]", text)
                self.assertIn("paper", text.lower())

    def test_cloud_paper_soak_blocks_live_keys_and_live_trading(self) -> None:
        text = (RUNBOOK_DIR / "cloud_paper_soak.md").read_text(encoding="utf-8").lower()

        self.assertIn("72h", text)
        self.assertIn("research and promotion stay local", text)
        self.assertIn("no live keys", text)
        self.assertIn("live trading remains disabled", text)
        self.assertIn("paper executor daemon", text)


if __name__ == "__main__":
    unittest.main()
