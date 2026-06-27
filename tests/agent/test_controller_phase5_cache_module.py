import json
import shutil
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from engine.agent.controller import AgentLoopSettings
from engine.agent.regression import AgentLoopPolicyVariant


class AgentLoopPhase5CacheModuleTests(unittest.TestCase):
    def test_phase5_cache_module_exports_cache_key_and_schema_validation(self) -> None:
        from engine.agent.phase5_cache import phase5_regression_cache_key, is_valid_phase5_regression_cache_payload

        settings = AgentLoopSettings(max_iterations=1, run_budget=1)
        baseline = AgentLoopPolicyVariant.baseline()
        current = replace(baseline, variant_id="current")

        cache_key = phase5_regression_cache_key(
            settings=settings,
            baseline_variant=baseline,
            current_variant=current,
        )
        payload = {
            "artifact_type": "agent_loop_phase5_regression_cache",
            "cache_schema_version": 1,
            "cache_key": cache_key,
            "controller_settings": asdict(settings),
            "baseline_variant": asdict(baseline),
            "current_variant": asdict(current),
            "phase5_regression_result": {"variant_id": "current"},
            "phase5_frontier": {"frontier": []},
            "phase5_evolution_summary": {},
        }

        self.assertEqual(len(cache_key), 64)
        self.assertTrue(is_valid_phase5_regression_cache_payload(payload, cache_key))
        self.assertFalse(is_valid_phase5_regression_cache_payload({**payload, "phase5_frontier": {}}, cache_key))

    def test_phase5_cache_module_writes_run_specific_artifacts_from_shared_cache(self) -> None:
        from engine.agent.phase5_cache import write_cached_phase5_regression_artifacts

        output_dir = Path("test-output-agent-controller-phase5-cache-module")
        try:
            settings = AgentLoopSettings(max_iterations=1, run_budget=1)
            baseline = AgentLoopPolicyVariant.baseline()
            current = replace(baseline, variant_id="current")

            first = write_cached_phase5_regression_artifacts(
                output_dir=output_dir,
                root_run_id="phase5-module-a",
                settings=settings,
                baseline_variant=baseline,
                current_variant=current,
            )
            second = write_cached_phase5_regression_artifacts(
                output_dir=output_dir,
                root_run_id="phase5-module-b",
                settings=settings,
                baseline_variant=baseline,
                current_variant=current,
            )

            self.assertEqual(first.cache_info["status"], "miss")
            self.assertEqual(second.cache_info["status"], "hit")
            self.assertNotEqual(first.frontier_artifact_path, second.frontier_artifact_path)
            self.assertTrue(first.frontier_artifact_path.exists())
            self.assertTrue(second.evolution_summary_artifact_path.exists())
            self.assertIn(
                "frontier",
                json.loads(second.frontier_artifact_path.read_text(encoding="utf-8")),
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)


if __name__ == "__main__":
    unittest.main()
