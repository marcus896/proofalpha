from __future__ import annotations

import json
import unittest
from pathlib import Path


class LocalProfilingHarnessTests(unittest.TestCase):
    def _workspace_temp_path(self, name: str) -> Path:
        base = Path("outputs") / "test-temp"
        base.mkdir(parents=True, exist_ok=True)
        path = base / name
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_harness_reports_runtime_and_sql_hotspots(self) -> None:
        from engine.profiling.local_harness import LocalProfilingTask, run_local_profiling_harness

        ticks = iter([0.0, 0.005, 0.005, 0.035])

        def fast_task() -> dict[str, object]:
            return {
                "status": "ok",
                "sql_events": [
                    {"operation": "memory.insert", "elapsed_ms": 4.0, "rows": 3},
                ],
            }

        def slow_task() -> dict[str, object]:
            return {
                "status": "ok",
                "sql_events": [
                    {"operation": "memory.query", "elapsed_ms": 11.0, "rows": 1},
                ],
            }

        report = run_local_profiling_harness(
            [
                LocalProfilingTask("memory_ingest_query_fixture", fast_task),
                LocalProfilingTask("batch_simulator_fixture", slow_task),
            ],
            timer=lambda: next(ticks),
        )

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["profile_id"], "optimization_phase_7_local_profile")
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["task_count"], 2)
        self.assertEqual(report["top_runtime_hotspots"][0]["task_id"], "batch_simulator_fixture")
        self.assertEqual(report["top_runtime_hotspots"][0]["elapsed_ms"], 30.0)
        self.assertEqual(report["top_sql_hotspots"][0]["operation"], "memory.query")
        self.assertEqual(report["top_sql_hotspots"][0]["elapsed_ms"], 11.0)

    def test_write_profile_report_round_trips_atomic_json(self) -> None:
        from engine.profiling.local_harness import (
            build_fixture_profiling_tasks,
            run_local_profiling_harness,
            write_local_profile_report,
        )

        output = self._workspace_temp_path("o7-local-profile.json")
        report = run_local_profiling_harness(build_fixture_profiling_tasks(), timer=lambda: 1.0)

        written = write_local_profile_report(output, report)
        payload = json.loads(written.read_text(encoding="utf-8"))

        self.assertEqual(written, output)
        self.assertEqual(payload["profile_id"], "optimization_phase_7_local_profile")
        self.assertGreaterEqual(payload["task_count"], 5)
        self.assertIn("data_fetch_retry_manifest_fixture", {row["task_id"] for row in payload["results"]})
        self.assertTrue(payload["top_runtime_hotspots"])
        self.assertTrue(payload["top_sql_hotspots"])


if __name__ == "__main__":
    unittest.main()
