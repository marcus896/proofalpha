from __future__ import annotations

from math import sqrt

# Large finite sentinel used when downside deviation is exactly zero
# (all returns ≥ MAR). Bloomberg returns NaN; we use a large finite value
# so downstream JSON serialisation and comparisons remain stable.
_SORTINO_INF_SENTINEL: float = 999.0


def max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    # The simulator equity curve stores cumulative PnL from a 1.0 starting
    # capital base, so risk gates must compare peak-to-trough drawdown as a
    # fraction of equity rather than raw currency delta.
    peak = 1.0 + float(equity_curve[0])
    worst = 0.0
    for value in equity_curve:
        equity = max(1e-9, 1.0 + float(value))
        peak = max(peak, equity)
        drawdown = (equity / peak) - 1.0
        worst = min(worst, drawdown)
    return worst


def sharpe_ratio(returns: list[float], annualization_factor: float = 1.0) -> float:
    """Compute (optionally annualized) Sharpe ratio.

    Parameters
    ----------
    returns:
        Per-bar excess returns (e.g. equity_curve[t] - equity_curve[t-1]).
    annualization_factor:
        Multiply the per-bar ratio by this value.  Pass sqrt(bars_per_year)
        for a fully annualised result.  Crypto conventions:
          1h bars  -> sqrt(8_760)  ≈ 93.57
          4h bars  -> sqrt(2_190)  ≈ 46.80
          daily    -> sqrt(365)    ≈ 19.10
        Default 1.0 preserves legacy (non-annualised) behaviour.
    """
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance <= 0:
        return 0.0
    return (mean / sqrt(variance)) * annualization_factor


def sortino_ratio(
    returns: list[float],
    mar: float = 0.0,
    annualization_factor: float = 1.0,
) -> float:
    """Compute (optionally annualized) Sortino ratio.

    Uses the original Sortino & van der Meer (1991) definition:
    downside deviation is computed from returns **below the MAR**
    (minimum acceptable return), not simply negative returns.

    When no returns fall below the MAR and the mean excess return is
    positive the ratio is mathematically undefined (∞).  We return
    _SORTINO_INF_SENTINEL (999.0) as a large-finite proxy so that
    downstream JSON serialisation and comparisons remain stable.

    Parameters
    ----------
    returns:
        Per-bar returns.
    mar:
        Minimum acceptable return per bar (default 0.0).
    annualization_factor:
        Same convention as sharpe_ratio().  Default 1.0 for legacy compat.
    """
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    # Below-MAR squared deviations — above-MAR returns contribute 0
    downside_sq = [(min(value - mar, 0.0)) ** 2 for value in returns]
    downside_variance = sum(downside_sq) / len(downside_sq)
    if downside_variance <= 0.0:
        # No below-MAR returns
        return _SORTINO_INF_SENTINEL * annualization_factor if mean > mar else 0.0
    return ((mean - mar) / sqrt(downside_variance)) * annualization_factor
