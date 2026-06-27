from __future__ import annotations

from pathlib import Path
import subprocess

from engine.io.artifacts import write_json_atomic


def default_karpathy_git_probe(workspace_root: Path) -> dict[str, object]:
    if not (workspace_root / ".git").exists():
        return {
            "git_available": False,
            "workspace_root": str(workspace_root),
            "branch": None,
            "head_commit": None,
            "blocking_reason": "not_a_git_repository",
        }

    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {
            "git_available": False,
            "workspace_root": str(workspace_root),
            "branch": None,
            "head_commit": None,
            "blocking_reason": "git_command_unavailable",
        }

    if inside.returncode != 0 or inside.stdout.strip().lower() != "true":
        return {
            "git_available": False,
            "workspace_root": str(workspace_root),
            "branch": None,
            "head_commit": None,
            "blocking_reason": "not_a_git_repository",
        }

    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if branch.returncode != 0 or head.returncode != 0:
        return {
            "git_available": False,
            "workspace_root": str(workspace_root),
            "branch": None,
            "head_commit": None,
            "blocking_reason": "not_a_git_repository",
        }
    return {
        "git_available": True,
        "workspace_root": str(workspace_root),
        "branch": branch.stdout.strip() or None,
        "head_commit": head.stdout.strip() or None,
        "blocking_reason": None,
    }


def resolve_karpathy_git_state(
    *,
    settings: object,
    workspace_root: Path,
    git_probe: object,
) -> dict[str, object] | None:
    if getattr(settings, "loop_mode", None) != "karpathy":
        return None
    probe_payload = dict(git_probe(workspace_root))  # type: ignore[operator]
    git_available = bool(probe_payload.get("git_available"))
    requested_mode = str(getattr(settings, "karpathy_execution_mode", "auto"))
    if requested_mode == "artifact-native":
        effective_mode = "artifact-native"
    elif requested_mode in {"git-native", "auto"} and git_available:
        effective_mode = "git-native"
    else:
        effective_mode = "artifact-native"
    blocking_reason = probe_payload.get("blocking_reason")
    if requested_mode == "artifact-native":
        blocking_reason = None
    return {
        "requested_mode": requested_mode,
        "effective_mode": effective_mode,
        "git_available": git_available,
        "workspace_root": str(probe_payload.get("workspace_root", str(workspace_root))),
        "branch": probe_payload.get("branch"),
        "head_commit": probe_payload.get("head_commit"),
        "blocking_reason": blocking_reason,
    }


def write_karpathy_git_state_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_git_state: dict[str, object] | None,
) -> str | None:
    if karpathy_git_state is None:
        return None
    artifact_path = output_dir / f"{root_run_id}.karpathy-git-state.json"
    write_json_atomic(
        artifact_path,
        {
            "run_id": root_run_id,
            "karpathy_git_state": dict(karpathy_git_state),
        },
    )
    return str(artifact_path)


def build_karpathy_git_action_plan(
    *,
    settings: object,
    root_run_id: str,
    karpathy_git_state: dict[str, object] | None,
    karpathy_decisions: list[dict[str, object]],
) -> dict[str, object] | None:
    if getattr(settings, "loop_mode", None) != "karpathy":
        return None
    requested_mode = str(getattr(settings, "karpathy_execution_mode", "auto"))
    if requested_mode == "artifact-native":
        return {
            "status": "not_requested",
            "requested_mode": requested_mode,
            "effective_mode": "artifact-native",
            "branch_name": None,
            "base_branch": None,
            "base_commit": None,
            "blocking_reason": None,
            "actions": [],
        }

    state = dict(karpathy_git_state or {})
    branch_name = f"autoresearch/{root_run_id}"
    effective_mode = str(state.get("effective_mode", "artifact-native"))
    if effective_mode != "git-native":
        return {
            "status": "blocked",
            "requested_mode": requested_mode,
            "effective_mode": effective_mode,
            "branch_name": branch_name,
            "base_branch": state.get("branch"),
            "base_commit": state.get("head_commit"),
            "blocking_reason": state.get("blocking_reason"),
            "actions": [],
        }

    actions: list[dict[str, object]] = [
        {
            "step": "checkout_branch",
            "branch_name": branch_name,
            "from_branch": state.get("branch"),
            "from_commit": state.get("head_commit"),
        }
    ]
    for decision in karpathy_decisions:
        if not isinstance(decision, dict):
            continue
        if str(decision.get("decision")) == "keep":
            actions.append(
                {
                    "step": "commit_candidate",
                    "iteration": decision.get("iteration"),
                    "target_run_ids": (
                        list(decision.get("candidate_run_ids", []))
                        if isinstance(decision.get("candidate_run_ids"), list)
                        else []
                    ),
                    "commit_message": f"autoresearch({root_run_id}): keep iteration {decision.get('iteration')}",
                }
            )
        elif str(decision.get("decision")) == "discard":
            actions.append(
                {
                    "step": "reset_to_incumbent",
                    "iteration": decision.get("iteration"),
                    "target_run_ids": (
                        list(decision.get("kept_run_ids", []))
                        if isinstance(decision.get("kept_run_ids"), list)
                        else []
                    ),
                    "reason": str(decision.get("reason", "objective_not_improved")),
                }
            )
    return {
        "status": "planned",
        "requested_mode": requested_mode,
        "effective_mode": effective_mode,
        "branch_name": branch_name,
        "base_branch": state.get("branch"),
        "base_commit": state.get("head_commit"),
        "blocking_reason": None,
        "actions": actions,
    }


def write_karpathy_git_action_plan_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_git_action_plan: dict[str, object] | None,
) -> str | None:
    if karpathy_git_action_plan is None:
        return None
    artifact_path = output_dir / f"{root_run_id}.karpathy-git-action-plan.json"
    write_json_atomic(
        artifact_path,
        {
            "run_id": root_run_id,
            "karpathy_git_action_plan": dict(karpathy_git_action_plan),
        },
    )
    return str(artifact_path)


def execute_karpathy_git_action_plan(
    *,
    settings: object,
    workspace_root: Path,
    output_dir: Path,
    root_run_id: str,
    karpathy_git_state: dict[str, object] | None,
    karpathy_git_action_plan: dict[str, object] | None,
    karpathy_target_path: str | None,
    karpathy_target_kind: str | None,
    karpathy_results_tsv_path: str | None,
) -> dict[str, object] | None:
    if getattr(settings, "loop_mode", None) != "karpathy":
        return None
    if getattr(settings, "karpathy_git_execute_actions", None) is False:
        return {"status": "not_requested", "executed_steps": 0, "blocking_reason": None}
    if not should_execute_karpathy_git_actions(settings, karpathy_git_state):
        blocking_reason = None
        if isinstance(karpathy_git_state, dict):
            blocking_reason = karpathy_git_state.get("blocking_reason")
        return {
            "status": "blocked" if isinstance(blocking_reason, str) and blocking_reason else "not_requested",
            "executed_steps": 0,
            "blocking_reason": blocking_reason,
        }
    if not isinstance(karpathy_git_action_plan, dict):
        return {"status": "blocked", "executed_steps": 0, "blocking_reason": "missing_action_plan"}
    if str(karpathy_git_action_plan.get("status")) != "planned":
        return {
            "status": "blocked",
            "executed_steps": 0,
            "blocking_reason": str(karpathy_git_action_plan.get("blocking_reason") or "action_plan_not_planned"),
        }
    try:
        managed_paths = collect_karpathy_git_managed_paths(
            workspace_root=workspace_root,
            output_dir=output_dir,
            root_run_id=root_run_id,
            karpathy_target_path=karpathy_target_path,
            karpathy_target_kind=karpathy_target_kind,
        )
    except ValueError as exc:
        return {"status": "blocked", "executed_steps": 0, "blocking_reason": str(exc)}
    ensure_karpathy_git_local_excludes(
        workspace_root=workspace_root,
        relative_paths=karpathy_local_exclude_paths(
            workspace_root=workspace_root,
            output_dir=output_dir,
            root_run_id=root_run_id,
            karpathy_results_tsv_path=karpathy_results_tsv_path,
        ),
    )

    executed: list[dict[str, object]] = []
    for action in karpathy_git_action_plan.get("actions", []):
        if not isinstance(action, dict):
            continue
        step = str(action.get("step", "unknown"))
        if step == "checkout_branch":
            run_git_command(workspace_root, ["checkout", "-B", str(action.get("branch_name", f"autoresearch/{root_run_id}"))])
        elif step == "commit_candidate":
            if managed_paths:
                run_git_command(workspace_root, ["add", "--", *managed_paths])
            run_git_command(
                workspace_root,
                ["commit", "--allow-empty", "-m", str(action.get("commit_message", f"autoresearch({root_run_id})"))],
            )
        elif step == "reset_to_incumbent" and managed_paths:
            run_git_command(workspace_root, ["restore", "--source", "HEAD", "--staged", "--worktree", "--", *managed_paths])
        executed.append(dict(action))

    return {
        "status": "executed",
        "executed_steps": len(executed),
        "blocking_reason": None,
        "managed_paths": managed_paths,
        "executed_actions": executed,
        "workspace_root": str(workspace_root),
    }


def should_execute_karpathy_git_actions(settings: object, karpathy_git_state: dict[str, object] | None) -> bool:
    if getattr(settings, "karpathy_git_execute_actions", None) is False:
        return False
    if getattr(settings, "karpathy_git_execute_actions", None) is True:
        return True
    return isinstance(karpathy_git_state, dict) and str(karpathy_git_state.get("effective_mode")) == "git-native"


def collect_karpathy_git_managed_paths(
    *,
    workspace_root: Path,
    output_dir: Path,
    root_run_id: str,
    karpathy_target_path: str | None,
    karpathy_target_kind: str | None,
) -> list[str]:
    resolved_workspace_root = workspace_root.resolve()
    resolved_output_dir = output_dir.resolve()
    try:
        resolved_output_dir.relative_to(resolved_workspace_root)
    except ValueError as exc:
        raise ValueError("output_dir_outside_workspace_root") from exc

    candidate_paths = [
        resolved_output_dir / f"{root_run_id}.karpathy-working.json",
        resolved_output_dir / f"{root_run_id}.karpathy-incumbent.json",
        resolved_output_dir / f"{root_run_id}.karpathy-ledger.json",
        resolved_output_dir / f"{root_run_id}.karpathy-git-state.json",
        resolved_output_dir / f"{root_run_id}.karpathy-git-action-plan.json",
        resolved_output_dir / f"{root_run_id}.karpathy-git-execution.json",
        resolved_output_dir / f"{root_run_id}.agent-loop.json",
        resolved_output_dir / f"{root_run_id}.phase5-frontier.json",
        resolved_output_dir / f"{root_run_id}.phase5-evolution-summary.json",
        resolved_output_dir / f"{root_run_id}.model-governance.json",
    ]
    if karpathy_target_kind == "python_source" and isinstance(karpathy_target_path, str) and karpathy_target_path:
        candidate_paths.append(Path(karpathy_target_path).resolve())
    managed_paths: list[str] = []
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            relative_path = path.relative_to(resolved_workspace_root)
        except ValueError:
            continue
        managed_paths.append(str(relative_path))
    return managed_paths


def karpathy_local_exclude_paths(
    *,
    workspace_root: Path,
    output_dir: Path,
    root_run_id: str,
    karpathy_results_tsv_path: str | None,
) -> list[str]:
    relative_paths = [
        str((output_dir.resolve() / f"{root_run_id}.agent-loop.json").relative_to(workspace_root.resolve())).replace("\\", "/"),
        str((output_dir.resolve() / f"{root_run_id}.karpathy-git-execution.json").relative_to(workspace_root.resolve())).replace("\\", "/"),
        str((output_dir.resolve() / f"{root_run_id}.phase5-frontier.json").relative_to(workspace_root.resolve())).replace("\\", "/"),
        str((output_dir.resolve() / f"{root_run_id}.phase5-evolution-summary.json").relative_to(workspace_root.resolve())).replace("\\", "/"),
        str((output_dir.resolve() / f"{root_run_id}.model-governance.json").relative_to(workspace_root.resolve())).replace("\\", "/"),
        str((output_dir.resolve() / "phase5-regression-cache-*.json").relative_to(workspace_root.resolve())).replace("\\", "/"),
    ]
    if isinstance(karpathy_results_tsv_path, str) and karpathy_results_tsv_path:
        results_path = Path(karpathy_results_tsv_path).resolve()
        try:
            relative_paths.append(str(results_path.relative_to(workspace_root.resolve())).replace("\\", "/"))
        except ValueError:
            pass
    return relative_paths


def run_git_command(workspace_root: Path, args: list[str]) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"git {' '.join(args)} failed")


def ensure_karpathy_git_local_excludes(*, workspace_root: Path, relative_paths: list[str]) -> None:
    exclude_path = workspace_root / ".git" / "info" / "exclude"
    if not exclude_path.exists():
        return
    existing_lines = set(exclude_path.read_text(encoding="utf-8").splitlines())
    additions = [path for path in relative_paths if path and path not in existing_lines]
    if not additions:
        return
    with exclude_path.open("a", encoding="utf-8") as handle:
        for path in additions:
            handle.write(f"{path}\n")


def write_karpathy_git_execution_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_git_execution: dict[str, object] | None,
) -> str | None:
    if karpathy_git_execution is None:
        return None
    artifact_path = output_dir / f"{root_run_id}.karpathy-git-execution.json"
    write_json_atomic(
        artifact_path,
        {
            "run_id": root_run_id,
            "karpathy_git_execution": dict(karpathy_git_execution),
        },
    )
    return str(artifact_path)
