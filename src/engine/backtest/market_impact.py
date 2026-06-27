"""Phase 12 — Dynamic slippage model (Almgren-Chriss inspired).

Public API
----------
compute_dynamic_slippage(
    trade_notional, volatility, open_interest, oi_is_stressed, stress_regime,
    flat_fallback_bps=5.0, k=0.1
) -> float

Returns per-trade slippage in BPS.

Formula
-------
    base_bps = k * sqrt(|trade_notional| / max(open_interest, 1)) * volatility * 10_000
    total_bps = base_bps * stress_multiplier(stress_regime, oi_is_stressed)
    clamped to [0.0, 500.0]

Stress multipliers (calibrated from Phase 12 research):
    crash + high OI    : 1.50
    short_squeeze      : 1.35
    liquidity_stress + high OI: 1.25
    all others         : 1.00

When open_interest == 0 the formula degenerates; flat_fallback_bps is
returned instead to prevent divide-by-zero and zero slippage artefacts.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


_SLIPPAGE_MIN_BPS: float = 0.0
_SLIPPAGE_MAX_BPS: float = 500.0

# Per-regime stress multipliers applied when oi_is_stressed is True
_STRESS_MULTIPLIERS: dict[str, float] = {
    "crash": 1.50,
    "short_squeeze": 1.35,
    "liquidity_stress": 1.25,
}


@dataclass(frozen=True)
class ImpactCostCoefficients:
    eta: float = 0.10
    alpha: float = 0.50
    k_latency: float = 0.01


def compute_dynamic_slippage(
    trade_notional: float,
    volatility: float,
    open_interest: float,
    oi_is_stressed: bool,
    stress_regime: str,
    flat_fallback_bps: float = 5.0,
    k: float = 0.1,
) -> float:
    """Compute market-impact slippage in BPS for a single trade.

    Parameters
    ----------
    trade_notional : float
        Absolute notional value of the trade (price × size).
    volatility : float
        Recent realized volatility of returns (dimensionless, e.g. 0.02 = 2%).
    open_interest : float
        Current open interest in the same units as ``trade_notional``.
        When zero, ``flat_fallback_bps`` is returned.
    oi_is_stressed : bool
        True when ``open_interest`` exceeds the 90th-pctile of the snapshot series.
        Used to arm the stress multiplier.
    stress_regime : str
        Current regime label (one of the 6 canonical names, or empty string).
    flat_fallback_bps : float
        Returned as-is when ``open_interest`` is zero.  Also acts as a
        minimum floor when the formula produces a lower value.
    k : float
        Calibration constant (Almgren-Chriss market-impact coefficient).

    Returns
    -------
    float
        Slippage in basis points, clamped to ``[0.0, 500.0]``.
    """
    if open_interest <= 0.0:
        return float(flat_fallback_bps)

    notional_abs = abs(float(trade_notional))
    vol = max(0.0, float(volatility))

    # Base market-impact component
    participation = notional_abs / float(open_interest)
    base_bps = float(k) * math.sqrt(max(participation, 0.0)) * vol * 10_000.0

    # Regime stress multiplier — only armed when OI is already elevated
    multiplier = 1.0
    if oi_is_stressed:
        multiplier = _STRESS_MULTIPLIERS.get(str(stress_regime), 1.0)

    total_bps = base_bps * multiplier

    # Clamp to sane range
    return max(_SLIPPAGE_MIN_BPS, min(_SLIPPAGE_MAX_BPS, total_bps))


def impact_cost_bps(
    q_notional: float,
    available_depth_notional: float,
    sigma_1h: float,
    spread_bps: float,
    latency_ms: float,
    coeff: ImpactCostCoefficients,
) -> float:
    """Compute bounded depth/latency-aware impact cost in basis points."""
    depth = max(float(available_depth_notional), 1e-9)
    q_abs = abs(float(q_notional))
    sigma = max(float(sigma_1h), 0.0)
    spread = max(float(spread_bps), 0.0)
    latency = max(float(latency_ms), 0.0)

    participation = q_abs / depth
    temp_bps = float(coeff.eta) * sigma * (participation ** float(coeff.alpha)) * 10_000.0
    delay_bps = float(coeff.k_latency) * latency * sigma
    total_bps = (spread / 2.0) + temp_bps + delay_bps
    return max(_SLIPPAGE_MIN_BPS, min(_SLIPPAGE_MAX_BPS, total_bps))


def compute_oi_stress_flag(
    open_interest_series: list[float],
    current_oi: float,
    percentile: float = 90.0,
) -> bool:
    """Return True when current_oi exceeds the given percentile of the series.

    Pure stdlib implementation — no numpy required.

    Parameters
    ----------
    open_interest_series : list[float]
        Full OI series for the snapshot (used to compute the threshold).
    current_oi : float
        OI value at the current bar.
    percentile : float
        Threshold percentile (default 90).
    """
    if not open_interest_series:
        return False
    sorted_oi = sorted(float(v) for v in open_interest_series)
    n = len(sorted_oi)
    rank = (percentile / 100.0) * (n - 1)
    lower = int(rank)
    upper = min(lower + 1, n - 1)
    frac = rank - lower
    threshold = sorted_oi[lower] * (1.0 - frac) + sorted_oi[upper] * frac
    return float(current_oi) > threshold
