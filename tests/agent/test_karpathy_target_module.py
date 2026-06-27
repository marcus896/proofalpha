import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.agent import controller
from engine.agent import karpathy_target


class KarpathyTargetModuleTests(unittest.TestCase):
    def test_controller_target_path_wrapper_delegates_to_module(self) -> None:
        with patch.object(karpathy_target, "resolve_karpathy_target_path", return_value="sentinel") as resolver:
            result = controller._resolve_karpathy_target_path(
                output_dir=Path("unused"),
                root_run_id="root",
                loop_mode="karpathy",
                configured_target_path=None,
                target_kind="json_config",
            )

        self.assertEqual(result, "sentinel")
        resolver.assert_called_once()

    def test_python_source_working_payload_round_trips_from_target_module(self) -> None:
        output_dir = Path("test-output-karpathy-target-module")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        try:
            payload = {
                "run_id": "target-module",
                "validation_score": 1.25,
                "runtime": {"symbol": "BTCUSDT"},
            }
            karpathy_target.write_karpathy_working_payload(
                output_dir=output_dir,
                root_run_id="target-module-root",
                loop_mode="karpathy",
                configured_target_path=None,
                target_kind="python_source",
                payload=payload,
            )
            target_path = output_dir / "target-module-root.karpathy-target.py"

            loaded = karpathy_target.load_karpathy_working_payload(
                output_dir=output_dir,
                root_run_id="target-module-root",
                loop_mode="karpathy",
                configured_target_path=None,
                target_kind="python_source",
                base_payload={"run_id": "base"},
                source_context={"iteration": 1, "root_run_id": "target-module-root", "loop_mode": "karpathy"},
            )
            runtime = karpathy_target.build_karpathy_program_runtime(
                target_path=str(target_path),
                target_kind="python_source",
                root_run_id="target-module-root",
                iteration=1,
                loop_mode="karpathy",
                base_payload={"run_id": "base"},
                karpathy_program_first=False,
                karpathy_primary_artifact_kind="materialized_study",
                karpathy_git_state={"effective_mode": "artifact-native"},
            )

            self.assertEqual(loaded["run_id"], "target-module")
            self.assertEqual(loaded["runtime"], {"symbol": "BTCUSDT"})
            self.assertIsInstance(runtime, dict)
            self.assertEqual(runtime["contract_inventory"]["study_contract_present"], True)
            self.assertEqual(runtime["contract_inventory"]["supports_emit_study"], True)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)


if __name__ == "__main__":
    unittest.main()
