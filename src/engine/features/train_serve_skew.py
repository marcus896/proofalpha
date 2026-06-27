from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any


@dataclass(frozen=True)
class TrainServeSkewReport:
    passed: bool
    issues: list[str]
    metrics: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_train_serve_skew_report(
    *,
    train_rows: list[dict[str, Any]],
    serve_rows: list[dict[str, Any]],
    feature_names: list[str],
    max_mean_delta: float,
) -> TrainServeSkewReport:
    issues: list[str] = []
    metrics: dict[str, dict[str, float]] = {}
    for name in feature_names:
        train_values = _numeric_values(train_rows, name)
        serve_values = _numeric_values(serve_rows, name)
        if not train_values or not serve_values:
            issues.append(f"missing_values:{name}")
            continue
        train_mean = fmean(train_values)
        serve_mean = fmean(serve_values)
        mean_delta = abs(serve_mean - train_mean)
        metrics[name] = {
            "train_mean": train_mean,
            "serve_mean": serve_mean,
            "mean_delta": mean_delta,
        }
        if mean_delta > max_mean_delta:
            issues.append(f"mean_delta:{name}")
    return TrainServeSkewReport(passed=not issues, issues=issues, metrics=metrics)


def _numeric_values(rows: list[dict[str, Any]], name: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        try:
            values.append(float(row[name]))
        except (KeyError, TypeError, ValueError):
            continue
    return values
