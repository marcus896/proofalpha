from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean


@dataclass(frozen=True)
class HawkesKernelParams:
    baseline_intensity: float
    excitation: float
    decay: float
    average_event_size: float
    branching_ratio: float


def fit_hawkes_intensity(
    event_times: list[float],
    event_sizes: list[float] | None = None,
) -> HawkesKernelParams:
    if not event_times:
        return HawkesKernelParams(0.0, 0.0, 1.0, 0.0, 0.0)

    ordered_times = sorted(float(value) for value in event_times)
    sizes = [1.0] * len(ordered_times) if event_sizes is None else [max(float(value), 0.0) for value in event_sizes]
    average_size = fmean(sizes) if sizes else 0.0
    horizon = max(ordered_times[-1] - ordered_times[0], 1.0)
    baseline_intensity = len(ordered_times) / horizon

    if len(ordered_times) == 1:
        return HawkesKernelParams(
            baseline_intensity=round(baseline_intensity, 8),
            excitation=0.0,
            decay=1.0,
            average_event_size=round(average_size, 8),
            branching_ratio=0.0,
        )

    gaps = [max(right - left, 1e-6) for left, right in zip(ordered_times, ordered_times[1:])]
    average_gap = fmean(gaps)
    clustering_score = 1.0 / (1.0 + average_gap)
    size_score = average_size / (average_size + 1.0) if average_size > 0.0 else 0.0
    branching_ratio = min(0.99, max(0.0, clustering_score * (0.5 + (0.5 * size_score))))
    excitation = branching_ratio * (1.0 + size_score)
    decay = 1.0 / average_gap

    return HawkesKernelParams(
        baseline_intensity=round(baseline_intensity, 8),
        excitation=round(excitation, 8),
        decay=round(decay, 8),
        average_event_size=round(average_size, 8),
        branching_ratio=round(branching_ratio, 6),
    )


def hawkes_cascade_multiplier(
    kernel_params: HawkesKernelParams,
    oi_concentration: float,
) -> float:
    concentration = min(max(float(oi_concentration), 0.0), 1.0)
    raw_multiplier = 1.0 + kernel_params.branching_ratio * (1.0 + concentration) + (kernel_params.excitation * 0.1)
    return round(min(max(raw_multiplier, 1.0), 4.0), 6)


def compute_oi_concentration(open_interest: list[float]) -> float:
    if len(open_interest) < 2:
        return 0.0
    minimum = min(open_interest)
    maximum = max(open_interest)
    if maximum <= minimum:
        return 0.0
    latest = open_interest[-1]
    return round((latest - minimum) / (maximum - minimum), 6)
