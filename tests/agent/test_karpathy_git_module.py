import shutil
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.agent import controller
from engine.agent import karpathy_git


class KarpathyGitModuleTests(unittest.TestCase):
    def test_controller_git_action_plan_wrapper_delegates_to_module(self) -> None:
        settings = controller.AgentLoopSettings(loop_mode="karpathy", karpathy_execution_mode="git-native")
        with patch.object(karpathy_git, "build_karpathy_git_action_plan", return_value={"status": "sentinel"}) as planner:
            result = controller._build_karpathy_git_action_plan(
                settings=settings,
                root_run_id="root",
                karpathy_git_state={"effective_mode": "git-native"},
                karpathy_decisions=[],
            )

        self.assertEqual(result, {"status": "sentinel"})
        planner.assert_called_once()

    def test_git_action_plan_and_managed_paths_live_in_git_module(self) -> None:
        workspace_root = Path("test-output-karpathy-git-module")
        output_dir = workspace_root / "outputs"
        if workspace_root.exists():
            shutil.rmtree(workspace_root)
        try:
            output_dir.mkdir(parents=True)
            (workspace_root / ".git" / "info").mkdir(parents=True)
            (workspace_root / ".git" / "info" / "exclude").write_text("", encoding="utf-8")
            (output_dir / "root.karpathy-working.json").write_text("{}", encoding="utf-8")
            target_path = workspace_root / "target.py"
            target_path.write_text("PAYLOAD = {}\n", encoding="utf-8")

            settings = types.SimpleNamespace(loop_mode="karpathy", karpathy_execution_mode="git-native")
            plan = karpathy_git.build_karpathy_git_action_plan(
                settings=settings,
                root_run_id="root",
                karpathy_git_state={"effective_mode": "git-native", "branch": "main", "head_commit": "abc123"},
                karpathy_decisions=[
                    {"decision": "keep", "iteration": 1, "candidate_run_ids": ["candidate"]},
                    {"decision": "discard", "iteration": 2, "kept_run_ids": ["candidate"], "reason": "worse"},
                ],
            )
            managed_paths = karpathy_git.collect_karpathy_git_managed_paths(
                workspace_root=workspace_root,
                output_dir=output_dir,
                root_run_id="root",
                karpathy_target_path=str(target_path),
                karpathy_target_kind="python_source",
            )

            self.assertEqual(plan["status"], "planned")
            self.assertEqual([action["step"] for action in plan["actions"]], ["checkout_branch", "commit_candidate", "reset_to_incumbent"])
            self.assertIn(str(Path("outputs") / "root.karpathy-working.json"), managed_paths)
            self.assertIn("target.py", managed_paths)
        finally:
            if workspace_root.exists():
                shutil.rmtree(workspace_root)


if __name__ == "__main__":
    unittest.main()
