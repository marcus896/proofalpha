from __future__ import annotations

import site
import sys
import json
from typing import Callable
from pathlib import Path

VENDOR_SITE = Path(".vendor")
if str(VENDOR_SITE) not in sys.path:
    sys.path.append(str(VENDOR_SITE))
USER_SITE = site.getusersitepackages()
if isinstance(USER_SITE, str) and USER_SITE and USER_SITE not in sys.path:
    sys.path.append(USER_SITE)

try:
    import optuna
except ModuleNotFoundError:  # pragma: no cover - exercised via patched tests
    optuna = None


ObjectiveFn = Callable[[dict[str, float | int]], dict[str, object] | float | int]


def build_optuna_plan(
    *,
    layer_name: str,
    parameter_grid: dict[str, dict[str, float | int]],
    warm_start_trials: list[dict[str, float | int]],
    objective: ObjectiveFn,
    n_trials: int,
    seed: int,
    sampler_name: str = "tpe",
    pruner_enabled: bool = True,
    startup_trials: int = 2,
) -> dict[str, object]:
    if optuna is None:
        raise ImportError("optuna is required for parameter_search_mode='optuna'")

    sampler = _build_sampler(sampler_name, seed)
    pruner = _build_pruner(pruner_enabled, startup_trials)
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=pruner)

    unique_warm_start_trials = _dedupe_parameter_sets(warm_start_trials)
    for params in unique_warm_start_trials:
        if params:
            study.enqueue_trial(dict(params))

    search_summary: list[dict[str, object]] = []
    seen_trials: dict[str, float] = {}

    def _objective(trial) -> float:
        selected_parameters = _suggest_parameters(trial, parameter_grid)
        param_hash = json.dumps(selected_parameters, sort_keys=True)
        
        if param_hash in seen_trials:
            score = seen_trials[param_hash]
            trial.report(score, step=1)
            return score

        def pruner_callback(step: int, value: float) -> bool:
            trial.report(value, step)
            if trial.should_prune():
                raise optuna.exceptions.TrialPruned()
            return False

        try:
            try:
                result = objective(selected_parameters, pruner=pruner_callback)
            except TypeError:
                result = objective(selected_parameters)
            score, summary = _extract_score_and_summary(result)
            seen_trials[param_hash] = score
            search_summary.append(
                {
                    "parameters": dict(selected_parameters),
                    "score": float(score),
                    "pruned": False,
                    **summary,
                }
            )
            return score
        except optuna.exceptions.TrialPruned:
            seen_trials[param_hash] = -999.0
            search_summary.append(
                {
                    "parameters": dict(selected_parameters),
                    "score": -999.0,
                    "pruned": True,
                }
            )
            raise

    study.optimize(_objective, n_trials=n_trials)
    search_summary.sort(
        key=lambda item: (
            float(item.get("score", 0.0)),
            json.dumps(item.get("parameters", {}), sort_keys=True),
        )
    )
    return {
        "planner_mode": "optuna",
        "layer_name": layer_name,
        "best_parameters": dict(study.best_params),
        "best_score": float(study.best_value),
        "warm_start_trial_count": len(unique_warm_start_trials),
        "trial_count": n_trials,
        "sampler": sampler_name,
        "pruner_enabled": bool(pruner_enabled),
        "startup_trials": int(startup_trials),
        "search_summary": search_summary,
    }


def _suggest_parameters(trial, parameter_grid: dict[str, dict[str, float | int]]) -> dict[str, float | int]:
    selected: dict[str, float | int] = {}
    for name, spec in parameter_grid.items():
        minimum = spec["minimum"]
        maximum = spec["maximum"]
        step = spec.get("step")
        if _is_int_like(minimum) and _is_int_like(maximum) and _is_int_like(step):
            selected[name] = trial.suggest_int(name, int(minimum), int(maximum), step=int(step))
        else:
            selected[name] = trial.suggest_float(
                name,
                float(minimum),
                float(maximum),
                step=float(step) if step is not None else None,
            )
    return selected


def _extract_score_and_summary(result: dict[str, object] | float | int) -> tuple[float, dict[str, object]]:
    if isinstance(result, bool):
        raise TypeError("objective must return a numeric score or {'score': numeric}")
    if isinstance(result, int | float):
        return float(result), {}
    if isinstance(result, dict):
        score = result.get("score")
        if isinstance(score, bool) or not isinstance(score, int | float):
            raise TypeError("objective result dict must include numeric 'score'")
        summary = {
            str(key): value
            for key, value in result.items()
            if key != "score" and isinstance(key, str) and not isinstance(value, bool) and isinstance(value, int | float | str)
        }
        return float(score), summary
    raise TypeError("objective must return a numeric score or {'score': numeric}")


def _is_int_like(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _build_sampler(sampler_name: str, seed: int):
    normalized = sampler_name.strip().lower()
    if normalized == "tpe":
        return optuna.samplers.TPESampler(seed=seed)
    if normalized == "random":
        return optuna.samplers.RandomSampler(seed=seed)
    raise ValueError(f"unsupported optuna sampler: {sampler_name}")


def _build_pruner(pruner_enabled: bool, startup_trials: int):
    if pruner_enabled:
        return optuna.pruners.MedianPruner(n_startup_trials=max(1, int(startup_trials)), n_warmup_steps=1)
    return optuna.pruners.NopPruner()


def _dedupe_parameter_sets(parameter_sets: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    unique: list[dict[str, float | int]] = []
    seen: set[str] = set()
    for parameter_set in parameter_sets:
        key = json.dumps(parameter_set, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(parameter_set))
    return unique
