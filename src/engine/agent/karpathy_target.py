from __future__ import annotations

import ast
from dataclasses import asdict, is_dataclass
import importlib
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types
import uuid

from engine.io.artifacts import write_json_atomic, write_text_atomic

_KARPATHY_STUDY_HOOK_NAMES = (
    "build_strategy_plan",
    "build_directional_layers",
    "build_known_good_filters",
    "build_exit_layers",
    "build_custom_filters",
    "build_layer_stack",
    "build_runtime_settings",
    "build_scenarios",
    "finalize_study",
    "build_study",
    "build_study_patch",
    "mutate_study",
    "build_payload",
    "build_payload_patch",
    "mutate_payload",
)
_KARPATHY_EVALUATION_HOOK_NAMES = (
    "run_experiment",
    "build_experiment_result",
    "evaluate_study",
    "build_validation_result",
)
_KARPATHY_PROGRAM_HOOK_NAMES = (
    "run_research_program",
    "build_research_program_result",
)


def _to_float_or_none(raw: object) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _karpathy_default_working_config_path(*, output_dir: Path, root_run_id: str) -> Path:
    return output_dir / f"{root_run_id}.karpathy-working.json"


def _karpathy_target_path(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None,
    target_kind: str = "json_config",
) -> Path:
    if loop_mode != "karpathy":
        raise ValueError("Karpathy target path requested outside karpathy mode")
    if isinstance(configured_target_path, str) and configured_target_path.strip():
        return Path(configured_target_path)
    if target_kind == "python_source":
        return output_dir / f"{root_run_id}.karpathy-target.py"
    return _karpathy_default_working_config_path(output_dir=output_dir, root_run_id=root_run_id)


def _resolve_karpathy_target_path(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None = None,
    target_kind: str = "json_config",
) -> str | None:
    if loop_mode != "karpathy":
        return None
    return str(
        _karpathy_target_path(
            output_dir=output_dir,
            root_run_id=root_run_id,
            loop_mode=loop_mode,
            configured_target_path=configured_target_path,
            target_kind=target_kind,
        )
    )


def _resolve_karpathy_working_config_path(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None = None,
    target_kind: str = "json_config",
) -> str | None:
    return _resolve_karpathy_target_path(
        output_dir=output_dir,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=configured_target_path,
        target_kind=target_kind,
    )


def _load_karpathy_working_payload(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None = None,
    target_kind: str = "json_config",
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, object] | None:
    if loop_mode != "karpathy":
        return None
    working_path = _karpathy_target_path(
        output_dir=output_dir,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=configured_target_path,
        target_kind=target_kind,
    )
    if not working_path.exists():
        return None
    if target_kind == "python_source":
        try:
            return _read_karpathy_python_target_payload(
                working_path,
                base_payload=base_payload,
                source_context=source_context,
            )
        except ValueError:
            if _read_karpathy_python_target_program_bundle(
                working_path,
                base_payload=base_payload,
                source_context=source_context,
            ) is not None:
                return dict(base_payload or {})
            raise
    payload = json.loads(working_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Karpathy working payload must be a JSON object: {working_path}")
    return dict(payload)


def _write_karpathy_working_payload(
    *,
    output_dir: Path,
    root_run_id: str,
    loop_mode: str,
    configured_target_path: str | None = None,
    target_kind: str = "json_config",
    payload: dict[str, object],
) -> None:
    if loop_mode != "karpathy":
        return
    working_path = _karpathy_target_path(
        output_dir=output_dir,
        root_run_id=root_run_id,
        loop_mode=loop_mode,
        configured_target_path=configured_target_path,
        target_kind=target_kind,
    )
    working_path.parent.mkdir(parents=True, exist_ok=True)
    if target_kind == "python_source":
        if isinstance(configured_target_path, str) and configured_target_path.strip() and working_path.exists():
            return
        _write_karpathy_python_target_payload(working_path, payload)
        return
    write_json_atomic(working_path, payload)


def _load_karpathy_python_target_source(
    target_path: Path,
    *,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> tuple[str, ast.Module, dict[str, object], object | None, dict[str, object]]:
    source = target_path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(target_path))
    module_name = f"_karpathy_target_{target_path.stem}"
    temporary_module = types.ModuleType(module_name)
    temporary_module.__file__ = str(target_path)
    namespace = temporary_module.__dict__
    target_parent = str(target_path.parent.resolve())
    original_sys_path = list(sys.path)
    previous_module = sys.modules.get(module_name)
    importlib.invalidate_caches()
    sys.path.insert(0, target_parent)
    sys.modules[module_name] = temporary_module
    try:
        exec(compile(source, str(target_path), "exec"), namespace, namespace)
    finally:
        sys.path[:] = original_sys_path
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
    resolved_context = dict(source_context or {})
    source_module = _resolve_karpathy_source_module(namespace, dict(base_payload or {}), resolved_context)
    return source, module, namespace, source_module, resolved_context


def _coerce_karpathy_research_program_bundle(raw: object) -> dict[str, dict[str, object] | None] | None:
    if not isinstance(raw, dict):
        return None
    study = raw.get("study")
    evaluation = raw.get("evaluation")
    experiment = raw.get("experiment")
    if not isinstance(study, dict) and not isinstance(evaluation, dict) and not isinstance(experiment, dict):
        return None
    return {
        "study": {str(key): value for key, value in study.items()} if isinstance(study, dict) else None,
        "evaluation": (
            {str(key): value for key, value in evaluation.items()} if isinstance(evaluation, dict) else None
        ),
        "experiment": (
            {str(key): value for key, value in experiment.items()} if isinstance(experiment, dict) else None
        ),
    }


def _read_karpathy_python_target_program_bundle(
    target_path: Path,
    *,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, dict[str, object] | None] | None:
    source, module, namespace, source_module, resolved_context = _load_karpathy_python_target_source(
        target_path,
        base_payload=base_payload,
        source_context=source_context,
    )
    del source
    del module
    program_hook = _resolve_karpathy_source_hook(namespace, source_module, "run_research_program")
    if not callable(program_hook):
        program_hook = _resolve_karpathy_source_hook(namespace, source_module, "build_research_program_result")
    if not callable(program_hook):
        return None
    raw_bundle = _call_karpathy_source_hook(program_hook, dict(base_payload or {}), dict(resolved_context))
    return _coerce_karpathy_research_program_bundle(raw_bundle)


def _karpathy_python_target_has_study_contract(
    target_path: Path,
    *,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> bool:
    source, module, namespace, source_module, _ = _load_karpathy_python_target_source(
        target_path,
        base_payload=base_payload,
        source_context=source_context,
    )
    if _karpathy_python_target_has_main(module) and _karpathy_python_target_supports_emit_study(source):
        return True
    for hook_name in (
        "build_strategy_plan",
        "build_directional_layers",
        "build_known_good_filters",
        "build_exit_layers",
        "build_custom_filters",
        "build_layer_stack",
        "build_runtime_settings",
        "build_scenarios",
        "finalize_study",
        "build_study",
        "build_study_patch",
        "mutate_study",
        "build_payload",
        "build_payload_patch",
        "mutate_payload",
    ):
        if callable(_resolve_karpathy_source_hook(namespace, source_module, hook_name)):
            return True
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PAYLOAD":
                    return True
    return False


def _build_karpathy_program_runtime(
    *,
    target_path: str | None,
    target_kind: str | None,
    root_run_id: str,
    iteration: int,
    loop_mode: str,
    base_payload: dict[str, object] | None,
    karpathy_program_first: bool,
    karpathy_primary_artifact_kind: str | None,
    karpathy_git_state: dict[str, object] | None,
) -> dict[str, object] | None:
    if target_kind != "python_source" or not isinstance(target_path, str) or not target_path.strip():
        return None
    path = Path(target_path)
    runtime: dict[str, object] = {
        "target_path": str(path),
        "target_kind": "python_source",
        "target_exists": path.exists(),
        "source_of_truth": "python_source_target" if karpathy_program_first else "materialized_study",
        "materialization_mode": "program_first" if karpathy_program_first else "materialized_study",
        "primary_artifact_kind": (
            str(karpathy_primary_artifact_kind) if isinstance(karpathy_primary_artifact_kind, str) else None
        ),
        "bootstrap": {
            "python_executable": sys.executable,
            "target_parent": str(path.parent.resolve()),
            "root_run_id": root_run_id,
            "iteration": iteration,
            "loop_mode": loop_mode,
        },
        "repo_snapshot": dict(karpathy_git_state) if isinstance(karpathy_git_state, dict) else {},
    }
    if not path.exists():
        return runtime
    source_context = {
        "iteration": iteration,
        "root_run_id": root_run_id,
        "loop_mode": loop_mode,
    }
    source, module, namespace, source_module, _ = _load_karpathy_python_target_source(
        path,
        base_payload=base_payload,
        source_context=source_context,
    )
    study_hooks = [
        hook_name
        for hook_name in _KARPATHY_STUDY_HOOK_NAMES
        if callable(_resolve_karpathy_source_hook(namespace, source_module, hook_name))
    ]
    evaluation_hooks = [
        hook_name
        for hook_name in _KARPATHY_EVALUATION_HOOK_NAMES
        if callable(_resolve_karpathy_source_hook(namespace, source_module, hook_name))
    ]
    program_hook_name = next(
        (
            hook_name
            for hook_name in _KARPATHY_PROGRAM_HOOK_NAMES
            if callable(_resolve_karpathy_source_hook(namespace, source_module, hook_name))
        ),
        None,
    )
    evaluation_emit_flag = _karpathy_python_target_eval_emit_flag(source)
    runtime["contract_inventory"] = {
        "has_main": _karpathy_python_target_has_main(module),
        "supports_emit_study": _karpathy_python_target_supports_emit_study(source),
        "evaluation_emit_flag": evaluation_emit_flag,
        "study_hooks": study_hooks,
        "evaluation_hooks": evaluation_hooks,
        "program_hook": program_hook_name,
        "study_contract_present": _karpathy_python_target_has_study_contract(
            path,
            base_payload=base_payload,
            source_context=source_context,
        ),
        "evaluation_contract_present": bool(evaluation_hooks or evaluation_emit_flag),
        "program_bundle_contract_present": program_hook_name is not None,
    }
    return runtime


def _read_karpathy_python_target_payload(
    target_path: Path,
    *,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, object]:
    source, module, namespace, source_module, resolved_context = _load_karpathy_python_target_source(
        target_path,
        base_payload=base_payload,
        source_context=source_context,
    )
    if _karpathy_python_target_has_main(module):
        if _karpathy_python_target_supports_emit_study(source):
            return _read_karpathy_python_target_payload_via_main(
                target_path,
                base_payload=base_payload,
                source_context=source_context,
            )
        if _karpathy_python_target_eval_emit_flag(source) is not None:
            return dict(base_payload or {})
    base_study = dict(base_payload or {})
    domain_patch: dict[str, object] = {}
    strategy_plan = _call_karpathy_source_hook(
        _resolve_karpathy_source_hook(namespace, source_module, "build_strategy_plan"),
        base_study,
        resolved_context,
    )
    strategy_plan_patch = _coerce_karpathy_strategy_plan_patch(strategy_plan, base_study, resolved_context)
    if strategy_plan_patch:
        _deep_merge_dict(domain_patch, strategy_plan_patch)
    strategy_section_hooks = {
        "directional_layers": "build_directional_layers",
        "known_good_filters": "build_known_good_filters",
        "exit_layers": "build_exit_layers",
        "custom_filters": "build_custom_filters",
    }
    for target_field, hook_name in strategy_section_hooks.items():
        section_values = _call_karpathy_source_hook(
            _resolve_karpathy_source_hook(namespace, source_module, hook_name),
            base_study,
            resolved_context,
        )
        if isinstance(section_values, list):
            domain_patch[target_field] = section_values
    layer_stack = _call_karpathy_source_hook(
        _resolve_karpathy_source_hook(namespace, source_module, "build_layer_stack"),
        base_study,
        resolved_context,
    )
    if isinstance(layer_stack, dict):
        _deep_merge_dict(domain_patch, layer_stack)
    runtime_settings = _call_karpathy_source_hook(
        _resolve_karpathy_source_hook(namespace, source_module, "build_runtime_settings"),
        base_study,
        resolved_context,
    )
    if isinstance(runtime_settings, dict):
        runtime_patch = domain_patch.get("runtime")
        if not isinstance(runtime_patch, dict):
            runtime_patch = {}
            domain_patch["runtime"] = runtime_patch
        _deep_merge_dict(runtime_patch, runtime_settings)
    scenarios = _call_karpathy_source_hook(
        _resolve_karpathy_source_hook(namespace, source_module, "build_scenarios"),
        base_study,
        resolved_context,
    )
    if isinstance(scenarios, list) and scenarios:
        domain_patch["scenarios"] = scenarios
    if domain_patch:
        payload = dict(base_payload or {})
        _deep_merge_dict(payload, domain_patch)
        finalize_study = _resolve_karpathy_source_hook(namespace, source_module, "finalize_study")
        if callable(finalize_study):
            result = _call_karpathy_source_hook(finalize_study, payload, resolved_context)
            if isinstance(result, dict):
                return {str(key): value for key, value in result.items()}
        return {str(key): value for key, value in payload.items()}
    finalize_study = _resolve_karpathy_source_hook(namespace, source_module, "finalize_study")
    if callable(finalize_study):
        payload = dict(base_payload or {})
        result = _call_karpathy_source_hook(finalize_study, payload, resolved_context)
        if isinstance(result, dict):
            return {str(key): value for key, value in result.items()}
        return {str(key): value for key, value in payload.items()}
    study_builder = _resolve_karpathy_source_hook(namespace, source_module, "build_study")
    if callable(study_builder):
        payload = _call_karpathy_source_hook(study_builder, dict(base_payload or {}), dict(source_context or {}))
        if isinstance(payload, dict):
            return {str(key): value for key, value in payload.items()}

    study_patch_builder = _resolve_karpathy_source_hook(namespace, source_module, "build_study_patch")
    if callable(study_patch_builder):
        patch = _call_karpathy_source_hook(study_patch_builder, dict(base_payload or {}), dict(source_context or {}))
        if isinstance(patch, dict):
            payload = dict(base_payload or {})
            _deep_merge_dict(payload, patch)
            return {str(key): value for key, value in payload.items()}

    study_mutator = _resolve_karpathy_source_hook(namespace, source_module, "mutate_study")
    if callable(study_mutator):
        payload = dict(base_payload or {})
        result = _call_karpathy_source_hook(study_mutator, payload, dict(source_context or {}))
        if isinstance(result, dict):
            return {str(key): value for key, value in result.items()}
        return {str(key): value for key, value in payload.items()}

    builder = _resolve_karpathy_source_hook(namespace, source_module, "build_payload")
    if callable(builder):
        payload = _call_karpathy_source_hook(builder, dict(base_payload or {}), dict(source_context or {}))
        if isinstance(payload, dict):
            return {str(key): value for key, value in payload.items()}

    patch_builder = _resolve_karpathy_source_hook(namespace, source_module, "build_payload_patch")
    if callable(patch_builder):
        patch = _call_karpathy_source_hook(patch_builder, dict(base_payload or {}), dict(source_context or {}))
        if isinstance(patch, dict):
            payload = dict(base_payload or {})
            _deep_merge_dict(payload, patch)
            return {str(key): value for key, value in payload.items()}

    mutator = _resolve_karpathy_source_hook(namespace, source_module, "mutate_payload")
    if callable(mutator):
        payload = dict(base_payload or {})
        result = _call_karpathy_source_hook(mutator, payload, dict(source_context or {}))
        if isinstance(result, dict):
            return {str(key): value for key, value in result.items()}
        return {str(key): value for key, value in payload.items()}

    for hook_name in ("run_experiment", "build_experiment_result", "evaluate_study", "build_validation_result"):
        hook = _resolve_karpathy_source_hook(namespace, source_module, hook_name)
        if callable(hook):
            return dict(base_payload or {})

    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PAYLOAD":
                    payload = ast.literal_eval(node.value)
                    if not isinstance(payload, dict):
                        break
                    return {str(key): value for key, value in payload.items()}
    raise ValueError(
        f"Karpathy python target must define main(), build_strategy_plan(), build_directional_layers(), build_known_good_filters(), build_exit_layers(), build_custom_filters(), build_layer_stack(), build_runtime_settings(), build_scenarios(), finalize_study(), build_study(), build_study_patch(), mutate_study(), build_payload(), build_payload_patch(), mutate_payload(), or PAYLOAD dict: {target_path}"
    )


def _deep_merge_dict(target: dict[str, object], patch: dict[str, object]) -> None:
    for key, value in patch.items():
        current_value = target.get(key)
        if isinstance(current_value, dict) and isinstance(value, dict):
            _deep_merge_dict(current_value, value)
            continue
        target[key] = value


def _karpathy_python_target_has_main(module: ast.Module) -> bool:
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            return True
    return False


def _karpathy_python_target_eval_emit_flag(source: str) -> str | None:
    if "--emit-experiment" in source:
        return "--emit-experiment"
    if "--emit-eval" in source:
        return "--emit-eval"
    return None


def _karpathy_python_target_supports_emit_study(source: str) -> bool:
    return "--emit-study" in source


def _run_karpathy_python_target_main_json(
    target_path: Path,
    *,
    emit_flag: str,
    output_filename: str,
    output_label: str,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, object]:
    temp_root = target_path.parent.resolve() / f".karpathy-main-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=False)
    try:
        base_study_path = temp_root / "base-study.json"
        context_path = temp_root / "context.json"
        output_path = temp_root / output_filename
        write_json_atomic(base_study_path, base_payload or {})
        write_json_atomic(context_path, source_context or {})
        completed = subprocess.run(
            [
                sys.executable,
                str(target_path.resolve()),
                emit_flag,
                "--base-study",
                str(base_study_path.resolve()),
                "--context",
                str(context_path.resolve()),
                "--output",
                str(output_path.resolve()),
            ],
            cwd=str(target_path.parent.resolve()),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError(
                f"Karpathy python target main() failed while emitting {output_label} for {target_path}: "
                f"{completed.stderr.strip() or completed.stdout.strip() or 'no error output'}"
            )
        if not output_path.exists():
            raise ValueError(f"Karpathy python target main() did not write output {output_label}: {target_path}")
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Karpathy python target main() must emit a JSON object {output_label}: {target_path}")
        return {str(key): value for key, value in payload.items()}
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _read_karpathy_python_target_payload_via_main(
    target_path: Path,
    *,
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, object]:
    return _run_karpathy_python_target_main_json(
        target_path,
        emit_flag="--emit-study",
        output_filename="materialized-study.json",
        output_label="study",
        base_payload=base_payload,
        source_context=source_context,
    )


def _read_karpathy_python_target_eval_via_main(
    target_path: Path,
    *,
    emit_flag: str = "--emit-eval",
    base_payload: dict[str, object] | None = None,
    source_context: dict[str, object] | None = None,
) -> dict[str, object]:
    return _run_karpathy_python_target_main_json(
        target_path,
        emit_flag=emit_flag,
        output_filename="validation-result.json",
        output_label="evaluation result",
        base_payload=base_payload,
        source_context=source_context,
    )


def _coerce_karpathy_experiment_direction(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"maximize", "max", "higher_is_better"}:
        return "maximize"
    if normalized in {"minimize", "min", "lower_is_better"}:
        return "minimize"
    return None


def _normalize_karpathy_experiment_result(
    raw_result: dict[str, object],
    *,
    payload: dict[str, object],
) -> dict[str, object]:
    normalized = dict(raw_result)
    metric_name = raw_result.get("metric_name")
    metric_value = _to_float_or_none(raw_result.get("metric_value"))
    metric_direction = _coerce_karpathy_experiment_direction(raw_result.get("metric_direction"))
    fallback_run_id = raw_result.get("run_id")
    if fallback_run_id is None:
        fallback_run_id = payload.get("run_id")
    run_ids = raw_result.get("run_ids")
    if isinstance(run_ids, list):
        normalized["run_ids"] = [str(value) for value in run_ids]
    elif isinstance(fallback_run_id, str):
        normalized["run_ids"] = [fallback_run_id]
    else:
        normalized["run_ids"] = []
    promoted_run_ids = raw_result.get("promoted_run_ids")
    if isinstance(promoted_run_ids, list):
        normalized["promoted_run_ids"] = [str(value) for value in promoted_run_ids]
    elif bool(raw_result.get("promoted")):
        normalized["promoted_run_ids"] = list(normalized["run_ids"])
    else:
        normalized["promoted_run_ids"] = []
    normalized["status"] = str(raw_result.get("status", "evaluated"))
    if normalized["status"] == "evaluated" and normalized["promoted_run_ids"]:
        normalized["status"] = "promoted"
    if normalized.get("objective_score") is None and metric_value is not None:
        normalized["objective_score"] = -metric_value if metric_direction == "minimize" else metric_value
    if isinstance(metric_name, str):
        normalized["metric_name"] = metric_name
    if metric_value is not None:
        normalized["metric_value"] = metric_value
    if metric_direction is not None:
        normalized["metric_direction"] = metric_direction
    if not isinstance(normalized.get("failed_gates"), list):
        normalized["failed_gates"] = []
    if not isinstance(normalized.get("regime_failure_labels"), list):
        normalized["regime_failure_labels"] = []
    if not isinstance(normalized.get("scenario_failure_names"), list):
        normalized["scenario_failure_names"] = []
    if not isinstance(normalized.get("failure_taxonomy"), list):
        normalized["failure_taxonomy"] = []
    if not isinstance(normalized.get("memory_summary"), dict):
        normalized["memory_summary"] = {}
    if "description" in raw_result and normalized.get("note") is None and isinstance(raw_result.get("description"), str):
        normalized["note"] = str(raw_result["description"])
    return normalized


def _coerce_karpathy_strategy_plan_patch(
    strategy_plan: object,
    base_study: dict[str, object],
    context: dict[str, object],
) -> dict[str, object]:
    if strategy_plan is None:
        return {}
    behavioral_patch = _call_karpathy_source_hook(
        getattr(strategy_plan, "to_study_patch", None),
        dict(base_study),
        dict(context),
    )
    if isinstance(behavioral_patch, dict):
        return dict(behavioral_patch)
    if isinstance(strategy_plan, dict):
        raw_plan: dict[str, object] = dict(strategy_plan)
    elif is_dataclass(strategy_plan) and not isinstance(strategy_plan, type):
        raw_plan = asdict(strategy_plan)
    else:
        try:
            raw_plan = {
                str(key): value
                for key, value in vars(strategy_plan).items()
                if not str(key).startswith("_")
            }
        except TypeError:
            return {}
    patch: dict[str, object] = {}
    for list_field in ("directional_layers", "known_good_filters", "exit_layers", "custom_filters", "scenarios"):
        list_value = raw_plan.get(list_field)
        if isinstance(list_value, list):
            patch[list_field] = list_value
    layer_stack = raw_plan.get("layer_stack")
    if isinstance(layer_stack, dict):
        _deep_merge_dict(patch, dict(layer_stack))
    runtime_settings = raw_plan.get("runtime_settings")
    if isinstance(runtime_settings, dict):
        runtime_patch = patch.get("runtime")
        if not isinstance(runtime_patch, dict):
            runtime_patch = {}
            patch["runtime"] = runtime_patch
        _deep_merge_dict(runtime_patch, dict(runtime_settings))
    for dict_field in ("incumbent", "holdout_decision"):
        dict_value = raw_plan.get(dict_field)
        if isinstance(dict_value, dict):
            patch[dict_field] = dict(dict_value)
    for scalar_field in ("run_id", "seed"):
        scalar_value = raw_plan.get(scalar_field)
        if scalar_value is not None:
            patch[scalar_field] = scalar_value
    return patch


def _call_karpathy_source_hook(
    hook: object,
    *args: dict[str, object],
) -> object:
    if not callable(hook):
        return None
    parameters = inspect.signature(hook).parameters
    if len(parameters) == 0:
        return hook()
    if len(parameters) == 1:
        return hook(args[0])
    return hook(*args[: len(parameters)])


def _resolve_karpathy_source_module(
    namespace: dict[str, object],
    base_study: dict[str, object],
    context: dict[str, object],
) -> object | None:
    module_factory = namespace.get("build_study_module")
    if callable(module_factory):
        module = _call_karpathy_source_hook(module_factory, base_study, context)
        if module is not None:
            return module
    module = namespace.get("study_module")
    if module is not None:
        return module
    module_class = namespace.get("StudyModule")
    if callable(module_class):
        module = _call_karpathy_source_hook(module_class, base_study, context)
        if module is None:
            return None
        namespace["study_module"] = module
        return module
    return None


def _resolve_karpathy_source_hook(
    namespace: dict[str, object],
    source_module: object | None,
    hook_name: str,
) -> object:
    top_level = namespace.get(hook_name)
    if callable(top_level):
        return top_level
    if source_module is None:
        return None
    return getattr(source_module, hook_name, None)


def _write_karpathy_python_target_payload(target_path: Path, payload: dict[str, object]) -> None:
    rendered = (
        "from __future__ import annotations\n\n"
        "import argparse\n"
        "import json\n"
        "from dataclasses import dataclass, field\n\n"
        "from pathlib import Path\n\n"
        "def _deep_merge_dict(target: dict[str, object], patch: dict[str, object]) -> None:\n"
        "    for key, value in patch.items():\n"
        "        current_value = target.get(key)\n"
        "        if isinstance(current_value, dict) and isinstance(value, dict):\n"
        "            _deep_merge_dict(current_value, value)\n"
        "            continue\n"
        "        target[key] = value\n\n"
        "@dataclass\n"
        "class StrategyPlan:\n"
        "    directional_layers: list[str] = field(default_factory=list)\n"
        "    known_good_filters: list[str] = field(default_factory=list)\n"
        "    exit_layers: list[str] = field(default_factory=list)\n"
        "    custom_filters: list[str] = field(default_factory=list)\n"
        "    layer_stack: dict[str, object] = field(default_factory=dict)\n"
        "    runtime_settings: dict[str, object] = field(default_factory=dict)\n"
        "    scenarios: list[dict[str, object]] = field(default_factory=list)\n"
        "    incumbent: dict[str, object] = field(default_factory=dict)\n"
        "    holdout_decision: dict[str, object] = field(default_factory=dict)\n"
        "    run_id: str | None = None\n"
        "    seed: int | None = None\n\n"
        "    def to_study_patch(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> dict[str, object] | None:\n"
        "        return None\n\n"
        "def _strategy_plan_to_patch(plan: StrategyPlan | dict[str, object] | None) -> dict[str, object]:\n"
        "    if plan is None:\n"
        "        return {}\n"
        "    behavioral_patch = plan.to_study_patch({}, {}) if hasattr(plan, \"to_study_patch\") else None\n"
        "    if isinstance(behavioral_patch, dict):\n"
        "        return behavioral_patch\n"
        "    if isinstance(plan, dict):\n"
        "        raw = dict(plan)\n"
        "    else:\n"
        "        raw = {}\n"
        "        for field_name in (\n"
        "            \"directional_layers\",\n"
        "            \"known_good_filters\",\n"
        "            \"exit_layers\",\n"
        "            \"custom_filters\",\n"
        "            \"layer_stack\",\n"
        "            \"runtime_settings\",\n"
        "            \"scenarios\",\n"
        "            \"incumbent\",\n"
        "            \"holdout_decision\",\n"
        "            \"run_id\",\n"
        "            \"seed\",\n"
        "        ):\n"
        "            value = getattr(plan, field_name, None)\n"
        "            if value is not None:\n"
        "                raw[field_name] = value\n"
        "    patch: dict[str, object] = {}\n"
        "    for field_name in (\"directional_layers\", \"known_good_filters\", \"exit_layers\", \"custom_filters\", \"scenarios\"):\n"
        "        value = raw.get(field_name)\n"
        "        if isinstance(value, list):\n"
        "            patch[field_name] = value\n"
        "    layer_stack = raw.get(\"layer_stack\")\n"
        "    if isinstance(layer_stack, dict):\n"
        "        _deep_merge_dict(patch, layer_stack)\n"
        "    runtime_settings = raw.get(\"runtime_settings\")\n"
        "    if isinstance(runtime_settings, dict):\n"
        "        runtime_patch = patch.get(\"runtime\")\n"
        "        if not isinstance(runtime_patch, dict):\n"
        "            runtime_patch = {}\n"
        "            patch[\"runtime\"] = runtime_patch\n"
        "        _deep_merge_dict(runtime_patch, runtime_settings)\n"
        "    for field_name in (\"incumbent\", \"holdout_decision\"):\n"
        "        value = raw.get(field_name)\n"
        "        if isinstance(value, dict):\n"
        "            patch[field_name] = value\n"
        "    for field_name in (\"run_id\", \"seed\"):\n"
        "        value = raw.get(field_name)\n"
        "        if value is not None:\n"
        "            patch[field_name] = value\n"
        "    return patch\n\n"
        "class StudyModule:\n"
        "    def __init__(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> None:\n"
        "        self.base_study = dict(base_study or {})\n"
        "        self.context = dict(context or {})\n\n"
        "    def build_strategy_plan(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> StrategyPlan | None:\n"
        "        return None\n\n"
        "    def build_directional_layers(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> list[str] | None:\n"
        "        return None\n\n"
        "    def build_known_good_filters(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> list[str] | None:\n"
        "        return None\n\n"
        "    def build_exit_layers(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> list[str] | None:\n"
        "        return None\n\n"
        "    def build_custom_filters(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> list[str] | None:\n"
        "        return None\n\n"
        "    def build_layer_stack(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> dict[str, object]:\n"
        "        return {}\n\n"
        "    def build_runtime_settings(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> dict[str, object]:\n"
        "        return {}\n\n"
        "    def build_scenarios(\n"
        "        self,\n"
        "        base_study: dict[str, object] | None = None,\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> list[dict[str, object]]:\n"
        "        return []\n\n"
        "    def finalize_study(\n"
        "        self,\n"
        "        study: dict[str, object],\n"
        "        context: dict[str, object] | None = None,\n"
        "    ) -> None:\n"
        "        return None\n\n"
        "def build_study_module(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> StudyModule:\n"
        "    return StudyModule(base_study, context)\n\n"
        "study_module = build_study_module({}, {})\n\n"
        "def build_strategy_plan(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> StrategyPlan | None:\n"
        "    return study_module.build_strategy_plan(base_study, context)\n\n"
        "def build_directional_layers(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> list[str] | None:\n"
        "    return study_module.build_directional_layers(base_study, context)\n\n"
        "def build_known_good_filters(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> list[str] | None:\n"
        "    return study_module.build_known_good_filters(base_study, context)\n\n"
        "def build_exit_layers(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> list[str] | None:\n"
        "    return study_module.build_exit_layers(base_study, context)\n\n"
        "def build_custom_filters(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> list[str] | None:\n"
        "    return study_module.build_custom_filters(base_study, context)\n\n"
        "def build_layer_stack(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    return study_module.build_layer_stack(base_study, context)\n\n"
        "def build_runtime_settings(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    return study_module.build_runtime_settings(base_study, context)\n\n"
        "def build_scenarios(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> list[dict[str, object]]:\n"
        "    return study_module.build_scenarios(base_study, context)\n\n"
        "def finalize_study(\n"
        "    study: dict[str, object],\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> None:\n"
        "    return study_module.finalize_study(study, context)\n\n"
        "def build_study_patch(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    patch = "
        f"{json.dumps(payload, indent=4, sort_keys=True).replace(chr(10), chr(10) + '    ')}"
        "\n"
        "    strategy_plan_patch = _strategy_plan_to_patch(build_strategy_plan(base_study, context))\n"
        "    if strategy_plan_patch:\n"
        "        _deep_merge_dict(patch, strategy_plan_patch)\n"
        "    directional_layers = build_directional_layers(base_study, context)\n"
        "    if isinstance(directional_layers, list):\n"
        "        patch[\"directional_layers\"] = directional_layers\n"
        "    known_good_filters = build_known_good_filters(base_study, context)\n"
        "    if isinstance(known_good_filters, list):\n"
        "        patch[\"known_good_filters\"] = known_good_filters\n"
        "    exit_layers = build_exit_layers(base_study, context)\n"
        "    if isinstance(exit_layers, list):\n"
        "        patch[\"exit_layers\"] = exit_layers\n"
        "    custom_filters = build_custom_filters(base_study, context)\n"
        "    if isinstance(custom_filters, list):\n"
        "        patch[\"custom_filters\"] = custom_filters\n"
        "    layer_stack = build_layer_stack(base_study, context)\n"
        "    if isinstance(layer_stack, dict):\n"
        "        _deep_merge_dict(patch, layer_stack)\n"
        "    runtime_settings = build_runtime_settings(base_study, context)\n"
        "    if isinstance(runtime_settings, dict):\n"
        "        runtime_patch = patch.get(\"runtime\")\n"
        "        if not isinstance(runtime_patch, dict):\n"
        "            runtime_patch = {}\n"
        "            patch[\"runtime\"] = runtime_patch\n"
        "        _deep_merge_dict(runtime_patch, runtime_settings)\n"
        "    scenarios = build_scenarios(base_study, context)\n"
        "    if isinstance(scenarios, list) and scenarios:\n"
        "        patch[\"scenarios\"] = scenarios\n"
        "    return patch\n\n"
        "def mutate_study(study: dict[str, object], context: dict[str, object] | None = None) -> None:\n"
        "    _deep_merge_dict(study, build_study_patch(study, context))\n"
        "    finalize_study(study, context)\n\n"
        "def build_study(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    program_result = run_research_program(base_study, context)\n"
        "    if isinstance(program_result, dict):\n"
        "        study_from_program = program_result.get('study')\n"
        "        if isinstance(study_from_program, dict):\n"
        "            return study_from_program\n"
        "    study = dict(base_study or {})\n"
        "    mutate_study(study, context)\n"
        "    return study\n\n"
        "def build_payload_patch(\n"
        "    base_payload: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    return build_study_patch(base_payload, context)\n\n"
        "def mutate_payload(payload: dict[str, object], context: dict[str, object] | None = None) -> None:\n"
        "    mutate_study(payload, context)\n\n"
        "def build_payload(\n"
        "    base_payload: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    return build_study(base_payload, context)\n\n"
        "def _default_experiment_result(\n"
        "    study: dict[str, object],\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    del context\n"
        "    metric_value = study.get('validation_score') if isinstance(study, dict) else None\n"
        "    try:\n"
        "        metric_value = float(metric_value)\n"
        "    except (TypeError, ValueError):\n"
        "        metric_value = 0.0\n"
        "    run_id = str(study.get('run_id', 'karpathy-script-run'))\n"
        "    return {\n"
        "        'run_id': run_id,\n"
        "        'run_ids': [run_id],\n"
        "        'promoted_run_ids': [],\n"
        "        'status': 'evaluated',\n"
        "        'metric_name': 'objective_score',\n"
        "        'metric_value': metric_value,\n"
        "        'metric_direction': 'maximize',\n"
        "        'objective_score': metric_value,\n"
        "        'failed_gates': [],\n"
        "        'regime_failure_labels': [],\n"
        "        'scenario_failure_names': [],\n"
        "        'failure_taxonomy': [],\n"
        "        'memory_summary': {},\n"
        "        'description': 'default generated experiment result',\n"
        "        'next_payload': dict(study),\n"
        "    }\n\n"
        "def _experiment_to_validation_result(\n"
        "    experiment: dict[str, object],\n"
        "    study: dict[str, object],\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    del context\n"
        "    validation = dict(experiment)\n"
        "    run_id = str(study.get('run_id', validation.get('run_id', 'karpathy-script-run')))\n"
        "    run_ids = validation.get('run_ids')\n"
        "    if not isinstance(run_ids, list) or not run_ids:\n"
        "        validation['run_ids'] = [run_id]\n"
        "    promoted_run_ids = validation.get('promoted_run_ids')\n"
        "    if not isinstance(promoted_run_ids, list):\n"
        "        validation['promoted_run_ids'] = []\n"
        "    validation.setdefault('status', 'evaluated')\n"
        "    validation.setdefault('failed_gates', [])\n"
        "    validation.setdefault('regime_failure_labels', [])\n"
        "    validation.setdefault('scenario_failure_names', [])\n"
        "    validation.setdefault('failure_taxonomy', [])\n"
        "    validation.setdefault('memory_summary', {})\n"
        "    validation.setdefault('next_payload', dict(study))\n"
        "    if validation.get('objective_score') is None:\n"
        "        metric_value = validation.get('metric_value')\n"
        "        metric_direction = str(validation.get('metric_direction', 'maximize')).lower()\n"
        "        if isinstance(metric_value, (int, float)):\n"
        "            value = float(metric_value)\n"
        "            validation['objective_score'] = -value if metric_direction == 'minimize' else value\n"
        "    return validation\n\n"
        "def run_experiment(\n"
        "    study: dict[str, object],\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    program_result = run_research_program(study, context)\n"
        "    if isinstance(program_result, dict):\n"
        "        experiment_from_program = program_result.get('experiment')\n"
        "        if isinstance(experiment_from_program, dict):\n"
        "            return experiment_from_program\n"
        "        evaluation_from_program = program_result.get('evaluation')\n"
        "        if isinstance(evaluation_from_program, dict):\n"
        "            return evaluation_from_program\n"
        "    return _default_experiment_result(study, context)\n\n"
        "def run_research_program(\n"
        "    base_study: dict[str, object] | None = None,\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object] | None:\n"
        "    return None\n\n"
        "def evaluate_study(\n"
        "    study: dict[str, object],\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    program_result = run_research_program(study, context)\n"
        "    if isinstance(program_result, dict):\n"
        "        evaluation_from_program = program_result.get('evaluation')\n"
        "        if isinstance(evaluation_from_program, dict):\n"
        "            return _experiment_to_validation_result(evaluation_from_program, study, context)\n"
        "        experiment_from_program = program_result.get('experiment')\n"
        "        if isinstance(experiment_from_program, dict):\n"
        "            return _experiment_to_validation_result(experiment_from_program, study, context)\n"
        "    return _experiment_to_validation_result(run_experiment(study, context), study, context)\n\n"
        "def build_experiment_result(\n"
        "    study: dict[str, object],\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    return run_experiment(study, context)\n\n"
        "def build_validation_result(\n"
        "    study: dict[str, object],\n"
        "    context: dict[str, object] | None = None,\n"
        ") -> dict[str, object]:\n"
        "    return evaluate_study(study, context)\n\n"
        "def main(argv: list[str] | None = None) -> int:\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--emit-study', action='store_true')\n"
        "    parser.add_argument('--emit-experiment', action='store_true')\n"
        "    parser.add_argument('--emit-eval', action='store_true')\n"
        "    parser.add_argument('--base-study')\n"
        "    parser.add_argument('--context')\n"
        "    parser.add_argument('--output')\n"
        "    args = parser.parse_args(argv)\n"
        "    if not args.emit_study and not args.emit_eval and not args.emit_experiment:\n"
        "        return 1\n"
        "    base_study = json.loads(Path(args.base_study).read_text(encoding='utf-8')) if args.base_study else {}\n"
        "    context = json.loads(Path(args.context).read_text(encoding='utf-8')) if args.context else {}\n"
        "    study = build_study(base_study, context)\n"
        "    if args.emit_study:\n"
        "        Path(args.output).write_text(json.dumps(study, indent=2, sort_keys=True), encoding='utf-8')\n"
        "        return 0\n"
        "    if args.emit_experiment:\n"
        "        experiment = build_experiment_result(study, context)\n"
        "        Path(args.output).write_text(json.dumps(experiment, indent=2, sort_keys=True), encoding='utf-8')\n"
        "        return 0\n"
        "    evaluation = build_validation_result(study, context)\n"
        "    Path(args.output).write_text(json.dumps(evaluation, indent=2, sort_keys=True), encoding='utf-8')\n"
        "    return 0\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    )
    write_text_atomic(target_path, rendered)


def _try_read_karpathy_python_target_direct_eval(
    context: dict[str, object],
    materialized: dict[str, object],
) -> dict[str, object] | None:
    settings = context.get("settings", {})
    if str(settings.get("loop_mode", "bounded")) != "karpathy":
        return None
    if str(settings.get("karpathy_target_kind", "json_config")) != "python_source":
        return None
    target_path_raw = materialized.get("karpathy_target_path")
    if not isinstance(target_path_raw, str) or not target_path_raw.strip():
        return None
    target_path = Path(target_path_raw)
    if not target_path.exists():
        return None
    bundled_result = materialized.get("karpathy_program_result")
    if isinstance(bundled_result, dict):
        raw_result = dict(bundled_result)
        result_mode = (
            str(materialized.get("karpathy_program_result_mode"))
            if isinstance(materialized.get("karpathy_program_result_mode"), str)
            else "bundle"
        )
    else:
        raw_result = None
        result_mode = None
    payload = dict(materialized.get("payload", context.get("payload", {})))
    source_context = {
        "iteration": int(context["iteration"]),
        "root_run_id": str(context["root_run_id"]),
        "loop_mode": str(settings.get("loop_mode", "bounded")),
    }
    if raw_result is None:
        source, module, namespace, source_module, resolved_context = _load_karpathy_python_target_source(
            target_path,
            base_payload=payload,
            source_context=source_context,
        )
        for hook_name in ("run_experiment", "build_experiment_result", "evaluate_study", "build_validation_result"):
            hook = _resolve_karpathy_source_hook(namespace, source_module, hook_name)
            if callable(hook):
                result = _call_karpathy_source_hook(hook, dict(payload), dict(resolved_context))
                if isinstance(result, dict):
                    raw_result = {str(key): value for key, value in result.items()}
                    result_mode = f"hook:{hook_name}"
                    break
        emit_flag = _karpathy_python_target_eval_emit_flag(source)
        if raw_result is None and _karpathy_python_target_has_main(module) and isinstance(emit_flag, str):
            raw_result = _read_karpathy_python_target_eval_via_main(
                target_path,
                emit_flag=emit_flag,
                base_payload=payload,
                source_context=source_context,
            )
            result_mode = f"main:{emit_flag}"
    if raw_result is None:
        return None
    normalized = _normalize_karpathy_experiment_result(raw_result, payload=payload)
    normalized["karpathy_program_result"] = dict(raw_result)
    normalized["karpathy_program_result_mode"] = result_mode
    normalized["karpathy_program_first"] = bool(materialized.get("karpathy_program_first"))
    if isinstance(materialized.get("karpathy_primary_artifact_path"), str):
        normalized["karpathy_primary_artifact_path"] = str(materialized.get("karpathy_primary_artifact_path"))
    if isinstance(materialized.get("karpathy_primary_artifact_kind"), str):
        normalized["karpathy_primary_artifact_kind"] = str(materialized.get("karpathy_primary_artifact_kind"))
    return normalized

karpathy_default_working_config_path = _karpathy_default_working_config_path
karpathy_target_path = _karpathy_target_path
resolve_karpathy_target_path = _resolve_karpathy_target_path
resolve_karpathy_working_config_path = _resolve_karpathy_working_config_path
load_karpathy_working_payload = _load_karpathy_working_payload
write_karpathy_working_payload = _write_karpathy_working_payload
load_karpathy_python_target_source = _load_karpathy_python_target_source
read_karpathy_python_target_program_bundle = _read_karpathy_python_target_program_bundle
karpathy_python_target_has_study_contract = _karpathy_python_target_has_study_contract
build_karpathy_program_runtime = _build_karpathy_program_runtime
read_karpathy_python_target_payload = _read_karpathy_python_target_payload
read_karpathy_python_target_eval_via_main = _read_karpathy_python_target_eval_via_main
normalize_karpathy_experiment_result = _normalize_karpathy_experiment_result
write_karpathy_python_target_payload = _write_karpathy_python_target_payload
try_read_karpathy_python_target_direct_eval = _try_read_karpathy_python_target_direct_eval
