from __future__ import annotations

from dataclasses import dataclass
import math
import random
from statistics import fmean, median


@dataclass(frozen=True)
class JumpDiffusionParams:
    jump_intensity: float
    mean_jump_size: float
    jump_volatility: float
    diffusion_volatility: float
    drift: float


def estimate_jump_params(
    returns: list[float],
    *,
    jump_threshold_sigma: float = 2.0,
) -> JumpDiffusionParams:
    if len(returns) < 2:
        return JumpDiffusionParams(0.0, 0.0, 0.0, 0.0, 0.0)

    mean_return = fmean(returns)
    sigma = _sample_stddev(returns)
    if sigma <= 1e-12:
        return JumpDiffusionParams(0.0, 0.0, 0.0, 0.0, mean_return)

    center = median(returns)
    mad = median(abs(value - center) for value in returns)
    robust_sigma = mad * 1.4826
    threshold = abs(jump_threshold_sigma) * max(robust_sigma, sigma * 0.25, 1e-9)
    jumps = [value for value in returns if abs(value - center) >= threshold]
    diffusion = [value for value in returns if abs(value - center) < threshold]
    if not diffusion:
        diffusion = list(returns)

    jump_intensity = len(jumps) / len(returns)
    mean_jump_size = fmean(jumps) if jumps else 0.0
    if len(jumps) > 1:
        jump_volatility = _sample_stddev(jumps)
    elif len(jumps) == 1:
        jump_volatility = abs(mean_jump_size) * 0.5
    else:
        jump_volatility = 0.0

    diffusion_volatility = _sample_stddev(diffusion) if len(diffusion) > 1 else sigma
    drift = fmean(diffusion)

    return JumpDiffusionParams(
        jump_intensity=round(max(jump_intensity, 0.0), 6),
        mean_jump_size=round(mean_jump_size, 8),
        jump_volatility=round(max(jump_volatility, 0.0), 8),
        diffusion_volatility=round(max(diffusion_volatility, 0.0), 8),
        drift=round(drift, 8),
    )


def generate_jump_stress_path(
    params: JumpDiffusionParams,
    n_bars: int,
    seed: int,
    start_price: float = 1.0,
) -> list[float]:
    if n_bars <= 0:
        return []

    rng = random.Random(seed)
    prices = [max(float(start_price), 1e-9)]
    for _ in range(n_bars - 1):
        diffusion_move = rng.gauss(params.drift, params.diffusion_volatility)
        jump_move = 0.0
        if rng.random() < min(max(params.jump_intensity, 0.0), 1.0):
            jump_sigma = params.jump_volatility if params.jump_volatility > 0.0 else abs(params.mean_jump_size) * 0.25
            jump_move = rng.gauss(params.mean_jump_size, jump_sigma)
        next_price = max(prices[-1] * math.exp(diffusion_move + jump_move), 1e-9)
        prices.append(round(next_price, 8))
    return prices


def extract_returns_from_snapshot(candles: list[object]) -> list[float]:
    closes: list[float] = []
    for candle in candles:
        try:
            close_price = float(candle.close)
        except AttributeError:
            try:
                close_price = float(candle["close"])
            except (KeyError, TypeError):
                continue
        if close_price > 0.0:
            closes.append(close_price)
    returns: list[float] = []
    for previous_close, current_close in zip(closes, closes[1:]):
        if previous_close > 0.0 and current_close > 0.0:
            returns.append(math.log(current_close / previous_close))
    return returns


def _sample_stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = fmean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(variance, 0.0))
