from __future__ import annotations

import json
from pathlib import Path

from engine.io.artifacts import write_json_atomic


VALID_PHASE_STATUSES = {"planned", "pending", "in_progress", "done", "completed", "blocked", "deferred"}


def load_project_status(status_json_path: Path) -> dict[str, object]:
    if not status_json_path.exists():
        return _default_project_status_payload()
    return json.loads(status_json_path.read_text(encoding="utf-8"))


def render_project_status(
    payload: dict[str, object],
    fmt: str,
    *,
    status_json_path: Path | None = None,
) -> str:
    if fmt == "json":
        return json.dumps(payload, sort_keys=True)

    lines = ["Implementation plan status"]
    lines.append(f"Plan version: {payload.get('plan_version', payload.get('plan_title', 'unknown'))}")
    status_file_version = payload.get("status_file_version", payload.get("version"))
    if status_file_version is not None:
        lines.append(f"Status file version: {status_file_version}")
    lines.append(f"Canonical plan file: {payload.get('canonical_plan_file', payload.get('plan_file', 'unknown'))}")
    if status_json_path is not None:
        lines.append(f"Status JSON file: {status_json_path}")
        lines.append(f"Progress ledger: {status_json_path}")
    else:
        lines.append("Progress ledger: PLAN_STATUS.json")
    lines.append(f"Current execution state: {payload.get('current_execution_state', payload.get('current_state', 'unknown'))}")
    next_step = payload.get("highest_priority_next_step", {})
    if isinstance(next_step, dict):
        lines.append(
            "Highest-priority next step: "
            f"{next_step.get('title', 'unknown')} "
            f"({next_step.get('id', 'unknown')}, status={next_step.get('status', 'unknown')})"
        )
    separation = "`enforced`" if bool(payload.get("autoresearch_memory_separation")) else "`disabled`"
    lines.append(f"Autoresearch memory separation: {separation}")
    status_scope = payload.get("status_scope")
    if isinstance(status_scope, str) and status_scope.strip():
        lines.append(f"Status scope: {status_scope.strip()}")
    startup_files = _startup_files(payload)
    if startup_files:
        lines.append("Fetch order:")
        for index, item in enumerate(startup_files, start=1):
            lines.append(f"{index}. {item}")
    repo_reality_check = payload.get("repo_reality_check")
    if isinstance(repo_reality_check, dict):
        summary = repo_reality_check.get("summary")
        if isinstance(summary, str) and summary.strip():
            lines.append(f"Repo reality check: {summary.strip()}")
    _append_data_collection_status(lines, payload.get("data_collection"))
    _append_robustness_ladder_status(lines, payload.get("robustness_ladder"))
    _append_completion_audit(lines, payload.get("completion_audit"))
    _append_progress_items(lines, "Phases", payload.get("phases", []))
    _append_progress_items(lines, "Tasks", payload.get("tasks", []))
    return "\n".join(lines)


def update_project_status(
    payload: dict[str, object],
    *,
    phase_id: str,
    status: str,
    note: str | None = None,
    next_phase_id: str | None = None,
    execution_state: str | None = None,
) -> dict[str, object]:
    if status not in VALID_PHASE_STATUSES:
        raise ValueError(f"invalid status '{status}'")

    phase = _find_phase(payload, phase_id)
    if phase is None:
        raise ValueError(f"unknown phase id '{phase_id}'")

    phase["status"] = status
    if note:
        notes = phase.get("notes", [])
        if not isinstance(notes, list):
            notes = []
        if note not in notes:
            notes.append(note)
        phase["notes"] = notes

    if execution_state is not None:
        payload["current_execution_state"] = execution_state

    payload["resume_order"] = _normalized_resume_order(payload)
    next_step = _resolve_next_step(payload, next_phase_id=next_phase_id)
    if next_step is not None:
        payload["highest_priority_next_step"] = next_step
    return payload


def write_project_status(
    *,
    status_json_path: Path,
    payload: dict[str, object],
) -> None:
    write_json_atomic(status_json_path, payload, sort_keys=False)


def _resolve_next_step(payload: dict[str, object], *, next_phase_id: str | None) -> dict[str, object] | None:
    if next_phase_id is not None:
        phase = _find_phase(payload, next_phase_id)
        if phase is None:
            raise ValueError(f"unknown phase id '{next_phase_id}'")
        return {
            "id": str(phase.get("id", next_phase_id)),
            "title": str(phase.get("title", next_phase_id)),
            "status": str(phase.get("status", "unknown")),
        }

    for candidate_id in _normalized_resume_order(payload):
        phase = _find_phase(payload, str(candidate_id))
        if phase is None:
            continue
        return {
            "id": str(phase.get("id", candidate_id)),
            "title": str(phase.get("title", candidate_id)),
            "status": str(phase.get("status", "unknown")),
        }
    return None


def _normalized_resume_order(payload: dict[str, object]) -> list[str]:
    ordered_phase_ids: list[str] = []
    seen: set[str] = set()

    resume_order = payload.get("resume_order", [])
    if isinstance(resume_order, list):
        candidate_ids = [str(candidate_id) for candidate_id in resume_order]
    else:
        candidate_ids = []

    for collection_name in ("phases", "tasks"):
        phases = payload.get(collection_name, [])
        if isinstance(phases, list):
            candidate_ids.extend(
                str(phase.get("id"))
                for phase in phases
                if isinstance(phase, dict) and isinstance(phase.get("id"), str)
            )

    for candidate_id in candidate_ids:
        if candidate_id in seen:
            continue
        phase = _find_phase(payload, candidate_id)
        if phase is None:
            continue
        if phase.get("status") in {"done", "completed"}:
            continue
        ordered_phase_ids.append(candidate_id)
        seen.add(candidate_id)

    return ordered_phase_ids


def _find_phase(payload: dict[str, object], phase_id: str) -> dict[str, object] | None:
    for collection_name in ("phases", "tasks"):
        phases = payload.get(collection_name, [])
        if not isinstance(phases, list):
            continue
        for phase in phases:
            if isinstance(phase, dict) and phase.get("id") == phase_id:
                return phase
    return None


def _find_phase_title(payload: dict[str, object], phase_id: str) -> str:
    phase = _find_phase(payload, phase_id)
    if phase is None:
        return phase_id
    return str(phase.get("title", phase_id))


def _default_project_status_payload() -> dict[str, object]:
    return {
        "plan_version": "Strict V3 Agent Operability And Improvement Plan",
        "status_file_version": 1,
        "canonical_plan_file": "PLAN.md",
        "autoresearch_memory_separation": True,
        "current_execution_state": "not_started",
        "highest_priority_next_step": {
            "id": "none",
            "title": "Initialize PLAN_STATUS.json",
            "status": "planned",
        },
        "startup_files": [
            "PLAN.md",
            "PLAN_STATUS.json",
            "AGENTS.md",
            "research_program.md",
            "docs/existing_module_mapping.md",
        ],
        "phases": [],
        "tasks": [],
        "deferred_work": [],
        "resume_order": [],
    }


def _startup_files(payload: dict[str, object]) -> list[str]:
    startup_files = payload.get("startup_files", [])
    if not isinstance(startup_files, list):
        return []
    return [str(item) for item in startup_files if isinstance(item, str) and item.strip()]


def _append_progress_items(lines: list[str], label: str, items: object) -> None:
    if not isinstance(items, list):
        return
    if not items:
        return
    lines.append(f"{label}:")
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('title', 'unknown')} | id={item.get('id', 'unknown')} | "
            f"status={item.get('status', 'unknown')}"
        )


def _append_data_collection_status(lines: list[str], data_collection: object) -> None:
    if not isinstance(data_collection, dict):
        return
    data_inventory = data_collection.get("data_inventory")
    if isinstance(data_inventory, dict):
        lines.append("Strict data inventory:")
        lines.append(
            "- "
            f"path={data_inventory.get('path', 'unknown')} | "
            f"status={data_inventory.get('status', 'unknown')}"
        )
        lines.append(
            "- "
            f"archive_ready={data_inventory.get('archive_ready', 'unknown')} | "
            f"forward_first_window_ready={data_inventory.get('forward_first_window_ready', 'unknown')}"
        )
        next_action_id = data_inventory.get("next_action_id")
        if next_action_id is not None:
            lines.append(f"- next_action_id={next_action_id}")
    forward_capture = data_collection.get("forward_public_ws_capture")
    if not isinstance(forward_capture, dict):
        return
    lines.append("Forward public WS capture:")
    lines.append(
        "- "
        f"session={forward_capture.get('session_id', 'unknown')} | "
        f"status={forward_capture.get('status', 'unknown')} | "
        f"pid={forward_capture.get('pid', 'unknown')} | "
        f"events={forward_capture.get('observed_stream_events_at_update', 'unknown')}"
    )
    elapsed = forward_capture.get("elapsed_seconds_at_update")
    remaining = forward_capture.get("remaining_to_8h_seconds_at_update")
    if elapsed is not None or remaining is not None:
        lines.append(
            "- "
            f"elapsed_seconds={elapsed if elapsed is not None else 'unknown'} | "
            f"remaining_to_8h_seconds={remaining if remaining is not None else 'unknown'}"
        )
    stale = forward_capture.get("stale_at_update")
    stale_seconds = forward_capture.get("stale_seconds_at_update")
    latest_activity = forward_capture.get("latest_activity_at_utc")
    if stale is not None or stale_seconds is not None or latest_activity is not None:
        lines.append(
            "- "
            f"stale={stale if stale is not None else 'unknown'} | "
            f"stale_seconds={stale_seconds if stale_seconds is not None else 'unknown'} | "
            f"latest_activity_at_utc={latest_activity if latest_activity is not None else 'unknown'}"
        )
    minimum_8h = forward_capture.get("minimum_8h_complete_at_utc")
    expected_12h = forward_capture.get("expected_12h_complete_at_utc")
    if minimum_8h is not None or expected_12h is not None:
        lines.append(
            "- "
            f"minimum_8h_complete_at_utc={minimum_8h if minimum_8h is not None else 'unknown'} | "
            f"expected_12h_complete_at_utc={expected_12h if expected_12h is not None else 'unknown'}"
        )
    blocker = forward_capture.get("blocker")
    if isinstance(blocker, str) and blocker.strip():
        lines.append(f"Capture blocker: {blocker.strip()}")
    requirements = forward_capture.get("remaining_completion_requirements")
    if isinstance(requirements, list):
        normalized_requirements = [
            str(item).strip()
            for item in requirements
            if isinstance(item, str) and item.strip()
        ]
        if normalized_requirements:
            lines.append("Remaining capture requirements:")
            for item in normalized_requirements:
                lines.append(f"- {item}")
    failed_attempts = forward_capture.get("failed_restart_attempts")
    if isinstance(failed_attempts, list) and failed_attempts:
        lines.append("Failed restart attempts:")
        for attempt in failed_attempts:
            if not isinstance(attempt, dict):
                continue
            lines.append(
                "- "
                f"session={attempt.get('session_id', 'unknown')} | "
                f"result={attempt.get('result', 'unknown')} | "
                f"reason={attempt.get('reason', attempt.get('stop_reason', attempt.get('evidence', 'unknown')))}"
            )


def _append_robustness_ladder_status(lines: list[str], robustness_ladder: object) -> None:
    if not isinstance(robustness_ladder, dict):
        return
    lines.append("Robustness Ladder:")
    lines.append(
        "- "
        f"design={robustness_ladder.get('approved_design', 'unknown')} | "
        f"status={robustness_ladder.get('status', 'unknown')}"
    )
    completed_artifacts = robustness_ladder.get("completed_artifacts")
    artifact_source = completed_artifacts if isinstance(completed_artifacts, dict) else robustness_ladder
    dataset_matrix = artifact_source.get("dataset_matrix") if isinstance(artifact_source, dict) else None
    if isinstance(dataset_matrix, dict):
        lines.append(
            "- "
            f"dataset_matrix={dataset_matrix.get('path', 'unknown')} | "
            f"status={dataset_matrix.get('status', 'unknown')} | "
            f"robustness_ready={dataset_matrix.get('robustness_ready', 'unknown')}"
        )
        reason = dataset_matrix.get("reason")
        expected_exit_code = dataset_matrix.get("expected_exit_code")
        if expected_exit_code is not None or (isinstance(reason, str) and reason.strip()):
            lines.append(
                "- "
                f"expected_exit_code={expected_exit_code if expected_exit_code is not None else 'unknown'} | "
                f"reason={reason.strip() if isinstance(reason, str) and reason.strip() else 'unknown'}"
            )
    for artifact_key in (
        "feature_causality_audit",
        "strategy_tournament",
        "robust_evaluation",
        "sealed_holdout_check",
        "paper_forward_score",
        "strategy_evidence_card",
    ):
        artifact = artifact_source.get(artifact_key) if isinstance(artifact_source, dict) else None
        if not isinstance(artifact, dict):
            continue
        line = (
            "- "
            f"{artifact_key}={artifact.get('path', 'unknown')} | "
            f"status={artifact.get('status', 'unknown')}"
        )
        if "passed" in artifact:
            line += f" | passed={artifact.get('passed')}"
        if "robustness_ready" in artifact:
            line += f" | robustness_ready={artifact.get('robustness_ready')}"
        lines.append(line)
    claim_allowed = robustness_ladder.get("strategy_improvement_claim_allowed")
    if claim_allowed is not None:
        lines.append(f"- strategy_improvement_claim_allowed={claim_allowed}")
    claim_blocker = robustness_ladder.get("claim_blocker")
    if isinstance(claim_blocker, str) and claim_blocker.strip():
        lines.append(f"- claim_blocker={claim_blocker.strip()}")
    next_task_id = robustness_ladder.get("next_task_id")
    if next_task_id is not None:
        lines.append(f"- next_task_id={next_task_id}")


def _append_completion_audit(lines: list[str], completion_audit: object) -> None:
    if not isinstance(completion_audit, dict):
        return
    status = completion_audit.get("status", "unknown")
    decision = completion_audit.get("completion_decision")
    lines.append(f"Completion audit: status={status}")
    if isinstance(decision, str) and decision.strip():
        lines.append(f"Completion decision: {decision.strip()}")
    blockers = completion_audit.get("blocking_requirements")
    if isinstance(blockers, list) and blockers:
        lines.append("Completion blockers:")
        for blocker in blockers:
            if not isinstance(blocker, dict):
                continue
            lines.append(
                "- "
                f"{blocker.get('requirement', 'unknown')} | "
                f"status={blocker.get('status', 'unknown')}"
            )
