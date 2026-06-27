from __future__ import annotations

from pathlib import Path

from engine.io.artifacts import write_json_atomic, write_text_atomic


def write_agent_loop_report(report_path: Path, report_payload: dict[str, object]) -> str:
    write_json_atomic(report_path, report_payload)
    return str(report_path)


def write_karpathy_incumbent_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_summary: dict[str, object] | None,
    next_payload: dict[str, object] | None,
    karpathy_decisions: list[dict[str, object]],
) -> str | None:
    if karpathy_summary is None:
        return None
    artifact_path = output_dir / f"{root_run_id}.karpathy-incumbent.json"
    artifact_payload = {
        "run_id": root_run_id,
        "karpathy_summary": dict(karpathy_summary),
        "karpathy_decisions": [dict(item) for item in karpathy_decisions],
        "next_payload": dict(next_payload) if isinstance(next_payload, dict) else None,
    }
    write_json_atomic(artifact_path, artifact_payload)
    return str(artifact_path)


def write_karpathy_ledger_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_decisions: list[dict[str, object]],
) -> str | None:
    if not karpathy_decisions:
        return None
    artifact_path = output_dir / f"{root_run_id}.karpathy-ledger.json"
    previous_kept_run_ids: list[str] | None = None
    entries: list[dict[str, object]] = []
    for decision in karpathy_decisions:
        kept_run_ids = (
            [str(item) for item in decision.get("kept_run_ids", [])]
            if isinstance(decision.get("kept_run_ids"), list)
            else []
        )
        entry = dict(decision)
        entry["incumbent_changed"] = previous_kept_run_ids != kept_run_ids
        entries.append(entry)
        previous_kept_run_ids = kept_run_ids
    write_json_atomic(
        artifact_path,
        {
            "run_id": root_run_id,
            "entries": entries,
        },
    )
    return str(artifact_path)


def write_karpathy_results_tsv(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_decisions: list[dict[str, object]],
) -> str | None:
    if not karpathy_decisions:
        return None
    artifact_path = output_dir / f"{root_run_id}.results.tsv"
    lines = [
        "\t".join(
            [
                "iteration",
                "run_id",
                "metric_name",
                "metric_value",
                "validation_status",
                "decision",
                "description",
            ]
        )
    ]
    for decision in karpathy_decisions:
        run_ids = decision.get("candidate_run_ids", [])
        run_id = str(run_ids[0]) if isinstance(run_ids, list) and run_ids else ""
        metric_name = decision.get("metric_name")
        metric_value = decision.get("metric_value")
        lines.append(
            "\t".join(
                [
                    str(decision.get("iteration", "")),
                    run_id,
                    str(metric_name if metric_name is not None else decision.get("objective", "")),
                    "" if metric_value is None else str(metric_value),
                    str(decision.get("validation_status", "")),
                    str(decision.get("decision", "")),
                    str(decision.get("reason", "")),
                ]
            )
        )
    write_text_atomic(artifact_path, "\n".join(lines) + "\n")
    return str(artifact_path)


def write_karpathy_program_runtime_artifact(
    *,
    output_dir: Path,
    root_run_id: str,
    karpathy_program_runtime: dict[str, object] | None,
) -> str | None:
    if karpathy_program_runtime is None:
        return None
    artifact_path = output_dir / f"{root_run_id}.karpathy-program-runtime.json"
    write_json_atomic(
        artifact_path,
        {
            "run_id": root_run_id,
            "karpathy_program_runtime": dict(karpathy_program_runtime),
        },
    )
    return str(artifact_path)


def write_meta_policy_artifact(
    *,
    output_dir: Path,
    run_id: str,
    meta_policy: dict[str, object],
) -> str:
    artifact_path = output_dir / f"{run_id}.meta-policy.json"
    payload = dict(meta_policy)
    payload["artifact_path"] = str(artifact_path)
    write_json_atomic(artifact_path, payload)
    return str(artifact_path)
