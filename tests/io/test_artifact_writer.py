import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.io.artifacts import write_json_atomic, write_text_atomic


class AtomicArtifactWriterTests(unittest.TestCase):
    def test_write_json_atomic_keeps_previous_file_when_replace_fails(self) -> None:
        output_dir = Path("test-output-atomic-artifacts")
        path = output_dir / "artifact.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            path.write_text('{"status":"old"}', encoding="utf-8")

            with patch("engine.io.artifacts.os.replace", side_effect=OSError("simulated replace crash")):
                with self.assertRaisesRegex(OSError, "simulated replace crash"):
                    write_json_atomic(path, {"status": "new"})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"status": "old"})
            self.assertEqual(list(output_dir.glob(".*.tmp-*")), [])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_write_text_atomic_creates_parent_and_replaces_existing_content(self) -> None:
        output_dir = Path("test-output-atomic-artifacts")
        path = output_dir / "nested" / "artifact.txt"
        try:
            write_text_atomic(path, "first\n")
            write_text_atomic(path, "second\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "second\n")
            self.assertEqual(list(path.parent.glob(".*.tmp-*")), [])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)


if __name__ == "__main__":
    unittest.main()
