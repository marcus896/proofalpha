from __future__ import annotations

from dataclasses import replace as dataclass_replace
import json
from pathlib import Path

from engine.agent.karpathy_target import (
    try_read_karpathy_python_target_direct_eval,
)
from engine.app.autoresearch import (
    execute_autoresearch,
    load_duplicate_baseline_variant_history_for_lineage,
    materialize_next_study_variants,
)
from engine.app.config import build_study_signature_from_payload, load_study_config
from engine.io.artifacts import write_json_atomic
from engine.memory.query import query_run_memory
from engine.memory.store import ingest_artifact_directory
from engine.reporting.runcards import load_runcard, save_runcard


def default_validator(context: dict[str, object], materialized: dict[str, object]) -> dict[str, object]:
    direct_eval_result = try_read_karpathy_python_target_direct_eval(context, materialized)
    if isinstance(direct_eval_result, dict):
        return direct_eval_result

    from engine.agent import controller as _controller

    config_paths = materialized.get("config_paths", [])
    if not isinstance(config_paths, list) or not config_paths:
        raise ValueError("materializer did not provide config_paths")
    config_path = Path(config_paths[0])
    payload = dict(materialized.get("payload", context["payload"]))
    settings = context["settings"]
    study = load_study_config(config_path)
    if bool(settings.get("strict_quality")):
        study = dataclass_replace(
            study,
            runtime_settings=dataclass_replace(study.runtime_settings, fail_on_quality_flags=True),
        )
        if study.snapshot.quality_flags:
            raise SystemExit(f"study snapshot quality flags block execution for {config_path}")

    execution = execute_autoresearch(
        study=study,
        output_dir=Path(context["output_dir"]),
        db_path=Path(context["db_path"]),
        memory_dir=Path(context["output_dir"]),
        memory_limit=int(settings.get("memory_limit", 25)),
        memory_quality_policy=str(settings.get("memory_quality_policy", "clean-only")),
        study_signature=build_study_signature_from_payload(payload),
        agent_loop_metadata={
            "loop_id": str(context["root_run_id"]),
            "parent_loop_run_id": str(context["root_run_id"]),
            "iteration": int(context["iteration"]),
            "source_run_id": study.run_id,
            "requested_loop_mode": str(context["mode_runtime"].get("requested_loop_mode", "")),
            "effective_loop_mode": str(context["mode_runtime"].get("effective_loop_mode", "")),
            "loop_mode_selection_reason": str(context["mode_runtime"].get("loop_mode_selection_reason", "")),
            "karpathy_target_kind": str(context["mode_runtime"].get("karpathy_target_kind", "")),
        },
    )

    duplicate_baseline_history = load_duplicate_baseline_variant_history_for_lineage(
        db_path=Path(context["db_path"]),
        research_lineage=study.research_lineage,
        memory_quality_policy=str(settings.get("memory_quality_policy", "clean-only")),
        snapshot_provenance=study.snapshot.provenance,
    )
    meta_policy_training_examples = _controller._build_meta_policy_training_examples(
        query_run_memory(
            Path(context["db_path"]),
            symbol=study.snapshot.symbol,
            venue=study.snapshot.venue,
            limit=int(settings.get("memory_limit", 25)),
        ),
        exclude_run_id=study.run_id,
    )

    failed_gates: list[str] = []
    objective_score: float | None = None
    runcard = None
    if execution.runcard_path:
        runcard = load_runcard(Path(execution.runcard_path))
        objective_score = _controller._to_float_or_none(runcard.metrics.get("selection_oos_sharpe"))
        failed_gates = _controller._failed_gate_names(runcard.artifacts.get("validation_gate_results_json"))

    regime_failure_labels: list[str] = []
    scenario_failure_names: list[str] = []
    if execution.dashboard_path:
        dashboard_payload = json.loads(Path(execution.dashboard_path).read_text(encoding="utf-8"))
        regime_failure_labels = _controller._regime_failure_labels(dashboard_payload.get("regime_scenario_pass_matrix"))
        scenario_failure_names = _controller._scenario_failure_names(dashboard_payload.get("scenarios"))
    failure_taxonomy = _controller._build_failure_taxonomy(
        failed_gates=failed_gates,
        regime_failure_labels=regime_failure_labels,
        scenario_failure_names=scenario_failure_names,
        quality_flags=study.snapshot.quality_flags,
        has_venue_profile=study.snapshot.venue_profile is not None,
    )
    next_study_paths = materialize_next_study_variants(
        payload,
        execution.memory_summary,
        Path(context["output_dir"]),
        study.run_id,
        duplicate_baseline_history_by_variant=duplicate_baseline_history,
    )
    meta_policy = _controller._build_bounded_meta_policy(
        run_id=study.run_id,
        execution_status=execution.status,
        objective_score=objective_score,
        failed_gates=failed_gates,
        regime_failure_labels=regime_failure_labels,
        scenario_failure_names=scenario_failure_names,
        failure_taxonomy=failure_taxonomy,
        next_study_paths=next_study_paths,
        training_examples=meta_policy_training_examples,
    )
    meta_policy_artifact_path = _controller._write_meta_policy_artifact(
        output_dir=Path(context["output_dir"]),
        run_id=study.run_id,
        meta_policy=meta_policy,
    )
    meta_policy_record = dict(meta_policy)
    meta_policy_record["artifact_path"] = meta_policy_artifact_path
    if runcard is not None:
        runcard.artifacts["meta_policies_json"] = json.dumps([meta_policy_record], sort_keys=True)
        runcard.artifacts["meta_policy_json"] = json.dumps(meta_policy_record, sort_keys=True)
        save_runcard(Path(execution.runcard_path), runcard)
        ingest_artifact_directory(Path(context["db_path"]), Path(context["output_dir"]))

    selected_variant = str(meta_policy.get("selected_action", "stop"))
    next_payload: dict[str, object] | None = None
    next_payload_path: Path | None = None
    completed_run_ids = _controller._coerce_str_list(context["scratchpad"].get("completed_runs")) + [study.run_id]
    for variant_name, variant_path_raw in next_study_paths.items():
        variant_path = Path(variant_path_raw)
        variant_payload = json.loads(variant_path.read_text(encoding="utf-8"))
        variant_payload = _controller._attach_agent_loop_metadata(
            variant_payload,
            root_run_id=str(context["root_run_id"]),
            iteration=int(context["iteration"]),
            source_run_id=study.run_id,
            completed_run_ids=completed_run_ids,
            requested_loop_mode=str(context["mode_runtime"].get("requested_loop_mode", "")),
            effective_loop_mode=str(context["mode_runtime"].get("effective_loop_mode", "")),
            loop_mode_selection_reason=str(context["mode_runtime"].get("loop_mode_selection_reason", "")),
            karpathy_target_kind=str(context["mode_runtime"].get("karpathy_target_kind", "")),
        )
        if variant_name == selected_variant and selected_variant != "stop":
            lineage = variant_payload.get("research_lineage")
            if not isinstance(lineage, dict):
                lineage = {}
            lineage.update(
                {
                    "meta_policy_id": meta_policy_record["policy_id"],
                    "meta_policy_action": selected_variant,
                    "meta_policy_artifact_path": meta_policy_artifact_path,
                }
            )
            variant_payload["research_lineage"] = lineage
            next_payload = dict(variant_payload)
            next_payload_path = variant_path
        write_json_atomic(variant_path, variant_payload)

    if execution.autoresearch_report_path:
        report_path = Path(execution.autoresearch_report_path)
        autoresearch_report = json.loads(report_path.read_text(encoding="utf-8"))
        autoresearch_report["agent_loop_metadata"] = {
            "loop_id": str(context["root_run_id"]),
            "parent_loop_run_id": str(context["root_run_id"]),
            "iteration": int(context["iteration"]),
            "source_run_id": study.run_id,
            "requested_loop_mode": str(context["mode_runtime"].get("requested_loop_mode", "")),
            "effective_loop_mode": str(context["mode_runtime"].get("effective_loop_mode", "")),
            "loop_mode_selection_reason": str(context["mode_runtime"].get("loop_mode_selection_reason", "")),
            "karpathy_target_kind": str(context["mode_runtime"].get("karpathy_target_kind", "")),
        }
        autoresearch_report["meta_policy"] = dict(meta_policy_record)
        write_json_atomic(report_path, autoresearch_report)

    promoted_run_ids = [execution.run_id] if execution.status == "promoted" else []
    memory_summary = dict(execution.memory_summary)
    memory_summary["meta_policy"] = {
        "policy_id": meta_policy_record["policy_id"],
        "selected_action": selected_variant,
        "status": meta_policy_record["status"],
        "policy_family": meta_policy_record["policy_family"],
    }
    return {
        "run_ids": [execution.run_id],
        "promoted_run_ids": promoted_run_ids,
        "status": execution.status,
        "objective_score": objective_score,
        "failed_gates": failed_gates,
        "regime_failure_labels": regime_failure_labels,
        "scenario_failure_names": scenario_failure_names,
        "failure_taxonomy": failure_taxonomy,
        "memory_summary": memory_summary,
        "meta_policy": meta_policy_record,
        "meta_policy_artifact_path": meta_policy_artifact_path,
        "meta_policy_selected_action": selected_variant,
        "next_payload": next_payload,
        "next_payload_path": str(next_payload_path) if next_payload_path is not None else None,
        "next_payload_paths": [str(Path(path)) for path in next_study_paths.values()],
    }
