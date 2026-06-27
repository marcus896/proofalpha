from __future__ import annotations

from itertools import combinations
from statistics import median


def resolve_cpcv_config(
    *,
    n_blocks: int = 10,
    n_test_blocks: int = 2,
    purge_bars: int | None = None,
    embargo_bars: int = 0,
    feature_lookback_bars: int = 0,
    barrier_horizon_bars: int = 0,
    holding_horizon_bars: int = 0,
) -> dict[str, int | str]:
    resolved_purge = max(
        int(purge_bars or 0),
        int(feature_lookback_bars),
        int(barrier_horizon_bars),
        int(holding_horizon_bars),
    )
    return {
        "method": "combinatorial_purged_cv",
        "n_blocks": max(2, int(n_blocks)),
        "n_test_blocks": max(1, int(n_test_blocks)),
        "purge_bars": max(0, resolved_purge),
        "embargo_bars": max(0, int(embargo_bars)),
    }


def build_cpcv_path_metrics(
    fold_returns: list[list[float]],
    *,
    n_blocks: int,
    n_test_blocks: int,
) -> dict[str, object]:
    """Aggregate CPCV by path-like combinations, not naive split averaging."""
    if not 8 <= int(n_blocks) <= 16:
        raise ValueError("n_blocks must be in the v3 range [8, 16]")
    if int(n_test_blocks) not in {2, 3}:
        raise ValueError("n_test_blocks must be 2 or 3")
    if len(fold_returns) != int(n_blocks):
        raise ValueError("fold_returns length must match n_blocks")

    block_scores = [_sharpe_like(series) for series in fold_returns]
    path_scores: list[float] = []
    for combo in combinations(range(int(n_blocks)), int(n_test_blocks)):
        combo_scores = [block_scores[index] for index in combo]
        path_scores.append(sum(combo_scores) / len(combo_scores))
    path_scores.sort()
    return {
        "method": "combinatorial_purged_cv",
        "n_blocks": int(n_blocks),
        "n_test_blocks": int(n_test_blocks),
        "path_count": len(path_scores),
        "path_sharpes": path_scores,
        "median_sharpe": median(path_scores) if path_scores else 0.0,
        "p10_sharpe": _quantile(path_scores, 0.10),
    }


def _sharpe_like(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    if variance <= 0.0:
        return 0.0
    return mean_value / (variance ** 0.5)


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = min(max(float(q), 0.0), 1.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = rank - lower
    return sorted_values[lower] * (1.0 - frac) + sorted_values[upper] * frac
