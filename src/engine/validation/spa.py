from __future__ import annotations

try:
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - exercised in dependency-light environments
    np = None


def _load_spa_class():
    try:
        from arch.bootstrap import SPA
    except ModuleNotFoundError:
        return None
    return SPA


def run_spa_test(
    benchmark: list[float],
    models: list[list[float]],
    block_size: int,
    reps: int = 2000,
) -> dict[str, object]:
    spa_class = _load_spa_class()
    if spa_class is None or np is None:
        return {
            "status": "skipped",
            "available": False,
            "enforced": False,
            "pvalues": [],
            "rejections": [],
        }

    benchmark_values = np.asarray(benchmark, dtype=float)
    model_values = np.asarray(models, dtype=float).T
    spa = spa_class(
        benchmark_values,
        model_values,
        block_size=block_size,
        reps=reps,
    )
    spa.compute()
    pvalues = list(float(value) for value in spa.pvalues)
    return {
        "status": "ok",
        "available": True,
        "enforced": True,
        "pvalues": pvalues,
        "rejections": [value <= 0.05 for value in pvalues],
    }
