import json
import subprocess
import unittest
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[2]


class SkillCliTests(unittest.TestCase):
    def test_list_skills_returns_repo_contracts(self) -> None:
        completed = subprocess.run(
            ["python", "-m", "engine.app.cli", "list-skills", "--format", "json"],
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["skill_count"], 6)
        self.assertEqual(payload["skills"][0]["name"], "campaign-orchestrator")

    def test_inspect_skill_returns_single_contract(self) -> None:
        completed = subprocess.run(
            ["python", "-m", "engine.app.cli", "inspect-skill", "--name", "strategy-composer", "--format", "json"],
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["name"], "strategy-composer")
        self.assertIn("compose legal candidate strategies", payload["purpose"])


if __name__ == "__main__":
    unittest.main()
