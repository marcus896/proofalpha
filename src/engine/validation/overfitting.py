from __future__ import annotations

import math
from itertools import combinations

try:
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - exercised in dependency-light environments
    np = None


def compute_benjamini_hochberg_fdr(pvalues: list[float], alpha: float) -> dict[str, object]:
    ordered = sorted(enumerate(float(value) for value in pvalues), key=lambda item: item[1])
    count = len(ordered)
    adjusted = [1.0] * count
    running = 1.0
    for reverse_index, (original_index, pvalue) in enumerate(reversed(ordered), start=1):
        rank = count - reverse_index + 1
        candidate = min(1.0, (pvalue * count) / rank)
        running = min(running, candidate)
        adjusted[original_index] = running
    rejected = [value <= alpha for value in adjusted]
    return {"adjusted_pvalues": adjusted, "rejected": rejected}


def compute_cscv_pbo(perf_matrix: list[list[float]], S: int = 16) -> dict[str, object]:
    if np is None:
        return _compute_cscv_pbo_pure_python(perf_matrix, S=S)

    matrix = np.asarray(perf_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 2:
        raise ValueError("perf_matrix must be a 2D matrix with at least 2 rows and 2 columns")

    partitions = int(S)
    if partitions < 2 or partitions % 2 != 0:
        raise ValueError("S must be an even integer greater than or equal to 2")
    if matrix.shape[0] != partitions:
        raise ValueError("perf_matrix row count must match S; silent truncation is not allowed")

    row_indices = range(partitions)
    logits: list[float] = []
    selected_models: list[int] = []
    half = partitions // 2
    for train_rows in combinations(row_indices, half):
        test_rows = tuple(index for index in row_indices if index not in train_rows)
        train_scores = matrix[list(train_rows), :].mean(axis=0)
        test_scores = matrix[list(test_rows), :].mean(axis=0)
        winner = int(np.argmax(train_scores))
        ranking = np.argsort(np.argsort(test_scores))
        percentile = (float(ranking[winner]) + 1.0) / float(matrix.shape[1])
        percentile = min(max(percentile, 1e-9), 1.0 - 1e-9)
        logits.append(math.log(percentile / (1.0 - percentile)))
        selected_models.append(winner)

    pbo = sum(1 for value in logits if value < 0.0) / max(1, len(logits))
    return {"pbo": float(pbo), "logits": logits, "selected_models": selected_models}


def _compute_cscv_pbo_pure_python(perf_matrix: list[list[float]], S: int = 16) -> dict[str, object]:
    matrix = [[float(value) for value in row] for row in perf_matrix]
    if len(matrix) < 2 or any(len(row) < 2 for row in matrix):
        raise ValueError("perf_matrix must be a 2D matrix with at least 2 rows and 2 columns")
    column_count = len(matrix[0])
    if any(len(row) != column_count for row in matrix):
        raise ValueError("perf_matrix rows must all have the same length")

    partitions = int(S)
    if partitions < 2 or partitions % 2 != 0:
        raise ValueError("S must be an even integer greater than or equal to 2")
    if len(matrix) != partitions:
        raise ValueError("perf_matrix row count must match S; silent truncation is not allowed")

    row_indices = range(partitions)
    half = partitions // 2
    logits: list[float] = []
    selected_models: list[int] = []
    for train_rows in combinations(row_indices, half):
        test_rows = tuple(index for index in row_indices if index not in train_rows)
        train_scores = _column_means(matrix, train_rows)
        test_scores = _column_means(matrix, test_rows)
        winner = max(range(column_count), key=lambda index: train_scores[index])
        ranking = _rank_values(test_scores)
        percentile = (float(ranking[winner]) + 1.0) / float(column_count)
        percentile = min(max(percentile, 1e-9), 1.0 - 1e-9)
        logits.append(math.log(percentile / (1.0 - percentile)))
        selected_models.append(winner)

    pbo = sum(1 for value in logits if value < 0.0) / max(1, len(logits))
    return {"pbo": float(pbo), "logits": logits, "selected_models": selected_models}


def _column_means(matrix: list[list[float]], row_indices: tuple[int, ...] | range) -> list[float]:
    indices = list(row_indices)
    column_count = len(matrix[0])
    return [
        sum(matrix[row_index][column_index] for row_index in indices) / len(indices)
        for column_index in range(column_count)
    ]


def _rank_values(values: list[float]) -> list[int]:
    ordered_indices = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0] * len(values)
    for rank, index in enumerate(ordered_indices):
        ranks[index] = rank
    return ranks
