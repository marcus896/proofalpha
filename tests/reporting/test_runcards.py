import json
import unittest
from pathlib import Path

from engine.config.models import PromotionDecision, RunCard
from engine.reporting.runcards import load_runcard, save_runcard


class RunCardPersistenceTests(unittest.TestCase):
    def test_save_and_load_round_trip(self) -> None:
        runcard = RunCard(
            run_id="run-1",
            strategy_hash="abc123",
            phase="phase-3",
            split_id="split-a",
            seed=7,
            decision=PromotionDecision(decision="accept", reasons=[]),
            metrics={"oos_sharpe": 0.9},
            artifacts={"dashboard": "dash.html"},
        )
        tmp_dir = Path("test-output")
        tmp_dir.mkdir(exist_ok=True)
        path = tmp_dir / "run.json"
        try:
            save_runcard(path, runcard)
            loaded = load_runcard(path)
            raw_payload = json.loads(path.read_text(encoding="utf-8"))
        finally:
            if path.exists():
                path.unlink()
            if tmp_dir.exists():
                tmp_dir.rmdir()

        self.assertEqual(loaded, runcard)
        self.assertEqual(raw_payload["run_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
