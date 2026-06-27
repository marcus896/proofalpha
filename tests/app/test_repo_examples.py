import json
import subprocess
import unittest
from pathlib import Path

from engine.app.config import load_study_config
from engine.app.schema import build_study_schema


class RepoExampleArtifactTests(unittest.TestCase):
    def test_checked_in_schema_matches_runtime_builder(self) -> None:
        schema_path = Path("examples") / "study.schema.json"

        self.assertTrue(schema_path.exists())
        payload = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(payload, build_study_schema())

    def test_checked_in_minimal_builtin_study_runs_successfully(self) -> None:
        config_path = Path("examples") / "minimal_builtin_study.json"
        output_dir = Path("test-output-repo-example")
        output_dir.mkdir(exist_ok=True)
        try:
            study = load_study_config(config_path)
            self.assertEqual(study.runtime_mode, "builtin")

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "run",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            dashboard_payload = json.loads((output_dir / "example-study.dashboard.json").read_text(encoding="utf-8"))
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

        self.assertEqual(dashboard_payload["strategy"]["backbone"], "mom_squeeze")
        # Verify the engine ran to completion and produced a well-formed dashboard.
        # No minimum layer count asserted: without synthetic inflation, layers must
        # genuinely clear statistical validation gates on this small toy dataset.
        self.assertIsInstance(dashboard_payload["strategy"]["layers"], list)

    def test_checked_in_minimal_campaign_manifest_exists(self) -> None:
        manifest_path = Path("examples") / "minimal_campaign.json"

        self.assertTrue(manifest_path.exists())
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["campaign_id"], "minimal-campaign")
        self.assertEqual(len(payload["entries"]), 2)
        self.assertEqual(payload["entries"][0]["command"], "run")
        self.assertEqual(payload["entries"][1]["command"], "autoresearch")


if __name__ == "__main__":
    unittest.main()
