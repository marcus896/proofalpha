from __future__ import annotations

import math
from statistics import NormalDist


_NORMAL = NormalDist()
_EULER_GAMMA = 0.5772156649015329


def compute_probabilistic_sharpe_ratio(
    returns: list[float],
    benchmark_sharpe: float = 0.0,
) -> float:
    sample_count = len(returns)
    if sample_count < 2:
        return 0.5

    observed_sharpe = compute_observed_sharpe_ratio(returns)
    standard_error = estimate_sharpe_ratio_standard_error(returns, observed_sharpe=observed_sharpe)
    if standard_error <= 0.0:
        return 1.0 if observed_sharpe > benchmark_sharpe else 0.5

    z_score = (observed_sharpe - benchmark_sharpe) / standard_error
    return max(0.0, min(1.0, _NORMAL.cdf(z_score)))


def compute_deflated_sharpe_ratio(
    returns: list[float],
    trial_count: int,
) -> float:
    effective_trials = max(1, int(trial_count))
    if effective_trials <= 1:
        return compute_probabilistic_sharpe_ratio(returns, benchmark_sharpe=0.0)

    observed_sharpe = compute_observed_sharpe_ratio(returns)
    standard_error = estimate_sharpe_ratio_standard_error(returns, observed_sharpe=observed_sharpe)
    benchmark_sharpe = estimate_deflated_sharpe_benchmark(standard_error, effective_trials)
    return compute_probabilistic_sharpe_ratio(returns, benchmark_sharpe=benchmark_sharpe)


def compute_observed_sharpe_ratio(returns: list[float]) -> float:
    sample_count = len(returns)
    if sample_count < 2:
        return 0.0
    mean_return = sum(returns) / sample_count
    variance = sum((value - mean_return) ** 2 for value in returns) / (sample_count - 1)
    if variance <= 0.0:
        return 0.0
    return mean_return / math.sqrt(variance)


def compute_sample_skewness(returns: list[float]) -> float:
    sample_count = len(returns)
    if sample_count < 3:
        return 0.0
    mean_return = sum(returns) / sample_count
    centered = [value - mean_return for value in returns]
    variance = sum(value * value for value in centered) / (sample_count - 1)
    if variance <= 0.0:
        return 0.0
    standard_deviation = math.sqrt(variance)
    third_moment = sum((value / standard_deviation) ** 3 for value in centered)
    return (sample_count / ((sample_count - 1) * (sample_count - 2))) * third_moment


def compute_sample_kurtosis(returns: list[float]) -> float:
    sample_count = len(returns)
    if sample_count < 4:
        return 3.0
    mean_return = sum(returns) / sample_count
    centered = [value - mean_return for value in returns]
    variance = sum(value * value for value in centered) / (sample_count - 1)
    if variance <= 0.0:
        return 3.0
    standard_deviation = math.sqrt(variance)
    fourth_moment = sum((value / standard_deviation) ** 4 for value in centered)
    coefficient = (sample_count * (sample_count + 1)) / (
        (sample_count - 1) * (sample_count - 2) * (sample_count - 3)
    )
    correction = (3 * (sample_count - 1) ** 2) / ((sample_count - 2) * (sample_count - 3))
    excess_kurtosis = coefficient * fourth_moment - correction
    return excess_kurtosis + 3.0


def estimate_sharpe_ratio_standard_error(
    returns: list[float],
    observed_sharpe: float | None = None,
) -> float:
    sample_count = len(returns)
    if sample_count < 2:
        return 0.0

    sharpe_ratio = compute_observed_sharpe_ratio(returns) if observed_sharpe is None else float(observed_sharpe)
    skewness = compute_sample_skewness(returns)
    kurtosis = compute_sample_kurtosis(returns)
    variance = (
        1.0
        - (skewness * sharpe_ratio)
        + (((kurtosis - 1.0) / 4.0) * (sharpe_ratio ** 2))
    ) / (sample_count - 1)
    return math.sqrt(max(variance, 0.0))


def estimate_deflated_sharpe_benchmark(standard_error: float, trial_count: int) -> float:
    effective_trials = max(1, int(trial_count))
    if effective_trials <= 1 or standard_error <= 0.0:
        return 0.0

    first_quantile = _NORMAL.inv_cdf(1.0 - (1.0 / effective_trials))
    second_quantile = _NORMAL.inv_cdf(1.0 - (1.0 / (effective_trials * math.e)))
    return standard_error * ((1.0 - _EULER_GAMMA) * first_quantile + (_EULER_GAMMA * second_quantile))


def compute_minimum_backtest_length(
    returns: list[float],
    target_sharpe: float = 0.0,
    target_psr: float = 0.95,
) -> int:
    """Compute Minimum Backtest Length (MinBTL) in number of sample periods.
    
    This derives the required track record length to achieve the target
    Probabilistic Sharpe Ratio (PSR), given the observed Sharpe, Skew, and Kurtosis.
    Formula derived from Bailey & Lopez de Prado (2012).
    """
    sample_count = len(returns)
    if sample_count < 4:
        return 0

    observed_sharpe = compute_observed_sharpe_ratio(returns)
    if observed_sharpe <= target_sharpe:
        return 9999999  # Functionally infinite if edge is negative

    skew = compute_sample_skewness(returns)
    kurt = compute_sample_kurtosis(returns)

    # Numerator of the standard error's square root argument
    k_term = 1.0 + (0.5 * (observed_sharpe ** 2)) - (skew * observed_sharpe) + (((kurt - 3.0) / 4.0) * (observed_sharpe ** 2))
    k_term = max(0.0001, k_term)

    # Target Z-score for the requested PSR
    # e.g., PSR=0.95 -> Z ~ 1.64485
    z_target = _NORMAL.inv_cdf(target_psr)

    min_btl = 1.0 + k_term * ((z_target / (observed_sharpe - target_sharpe)) ** 2)
    return int(math.ceil(min_btl))
