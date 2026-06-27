import json
import subprocess
import sys
import unittest
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[2]


class ReleaseCliTests(unittest.TestCase):
    def test_cli_version_prints_package_version(self) -> None:
        completed = subprocess.run(
            ["python", "-m", "engine.app.cli", "--version"],
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("proofalpha 0.1.0", completed.stdout.strip())

    def test_cli_doctor_reports_release_readiness(self) -> None:
        completed = subprocess.run(
            ["python", "-m", "engine.app.cli", "doctor", "--format", "json"],
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        expected_status = "ok" if (3, 12) <= sys.version_info[:2] < (3, 14) else "failed"
        self.assertEqual(payload["status"], expected_status)
        self.assertEqual(payload["version"], "0.1.0")
        self.assertGreaterEqual(payload["check_count"], 7)
        check_names = {check["name"] for check in payload["checks"]}
        self.assertIn("readme", check_names)
        self.assertIn("pyproject", check_names)
        self.assertIn("builtin_example", check_names)
        self.assertIn("campaign_example", check_names)
        self.assertIn("schema_artifact", check_names)
        self.assertIn("python_runtime", check_names)
        self.assertIn("websocket_dependency", check_names)


if __name__ == "__main__":
    unittest.main()
