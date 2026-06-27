import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.agent import artifacts as agent_artifacts
from engine.agent import controller


class AgentArtifactsModuleTests(unittest.TestCase):
    def test_controller_karpathy_incumbent_wrapper_delegates_to_module(self) -> None:
        with patch.object(agent_artifacts, "write_karpathy_incumbent_artifact", return_value="sentinel") as writer:
            result = controller._write_karpathy_incumbent_artifact(
                output_dir=Path("unused"),
                root_run_id="root",
                karpathy_summary={"decision": "keep"},
                next_payload={"run_id": "next"},
                karpathy_decisions=[],
            )

        self.assertEqual(result, "sentinel")
        writer.assert_called_once()

    def test_artifact_module_writes_karpathy_and_meta_policy_artifacts(self) -> None:
        output_dir = Path("test-output-agent-artifacts-module")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        try:
            output_dir.mkdir(parents=True)
            incumbent_path = agent_artifacts.write_karpathy_incumbent_artifact(
                output_dir=output_dir,
                root_run_id="root",
                karpathy_summary={"decision": "keep"},
                next_payload={"run_id": "next"},
                karpathy_decisions=[{"iteration": 1, "decision": "keep", "kept_run_ids": ["next"]}],
            )
            ledger_path = agent_artifacts.write_karpathy_ledger_artifact(
                output_dir=output_dir,
                root_run_id="root",
                karpathy_decisions=[
                    {"iteration": 1, "decision": "keep", "kept_run_ids": ["next"]},
                    {"iteration": 2, "decision": "discard", "kept_run_ids": ["next"]},
                ],
            )
            results_path = agent_artifacts.write_karpathy_results_tsv(
                output_dir=output_dir,
                root_run_id="root",
                karpathy_decisions=[
                    {
                        "iteration": 1,
                        "candidate_run_ids": ["candidate"],
                        "metric_name": "objective_score",
                        "metric_value": 1.5,
                        "validation_status": "passed",
                        "decision": "keep",
                        "reason": "improved",
                    }
                ],
            )
            meta_path = agent_artifacts.write_meta_policy_artifact(
                output_dir=output_dir,
                run_id="candidate",
                meta_policy={"policy_id": "policy-1", "selected_action": "stop"},
            )

            incumbent = json.loads(Path(incumbent_path).read_text(encoding="utf-8"))
            ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
            results = Path(results_path).read_text(encoding="utf-8")
            meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))

            self.assertEqual(incumbent["next_payload"]["run_id"], "next")
            self.assertEqual([entry["incumbent_changed"] for entry in ledger["entries"]], [True, False])
            self.assertIn("candidate\tobjective_score\t1.5\tpassed\tkeep\timproved", results)
            self.assertEqual(meta["artifact_path"], meta_path)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)


if __name__ == "__main__":
    unittest.main()
