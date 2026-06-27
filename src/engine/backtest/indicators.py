"""Pure-Python indicator library for the strategy signal engine.

All functions operate on plain Python lists, require no numpy, and return
one value per input bar (with NaN-equivalent ``None`` or 0.0 during the
warmup period as documented per function).

Functions
---------
wma(prices, period)          Weighted Moving Average
hma(prices, period)          Hull Moving Average
kama(prices, n, f, s)        Kaufman Adaptive MA + Efficiency Ratio series
atr(highs, lows, closes, p)  Average True Range
ema(prices, period)          Exponential Moving Average
rsi(closes, period)          Relative Strength Index  [0, 100]
zscore(closes, period)       Rolling Z-score of close vs EMA centre
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# WMA — Weighted Moving Average
# ---------------------------------------------------------------------------

def wma(prices: list[float], period: int) -> list[float]:
    """Linearly-weighted moving average.

    Returns a list the same length as ``prices``.  Bars before the first
    complete window are filled with the simple mean of available data.

    Weight of bar at lag k = (period - k), k ∈ [0, period-1].
    """
    p = max(1, int(period))
    result: list[float] = []
    denom = p * (p + 1) / 2.0
    for i in range(len(prices)):
        start = max(0, i - p + 1)
        window = prices[start : i + 1]
        n = len(window)
        if n < p:
            # Warmup: simple mean
            result.append(sum(window) / n)
        else:
            weighted = sum((j + 1) * window[j] for j in range(n))
            result.append(weighted / denom)
    return result


# ---------------------------------------------------------------------------
# HMA — Hull Moving Average
# ---------------------------------------------------------------------------

def hma(prices: list[float], period: int) -> list[float]:
    """Hull Moving Average: WMA(2·WMA(n/2) − WMA(n), √n).

    Reduces lag while smoothing noise.  Returns one value per bar.
    """
    p = max(2, int(period))
    half_p = max(1, p // 2)
    sqrt_p = max(1, int(round(math.sqrt(p))))

    wma_half = wma(prices, half_p)
    wma_full = wma(prices, p)

    # Raw series: 2 × WMA(n/2) − WMA(n)
    diff = [2.0 * wma_half[i] - wma_full[i] for i in range(len(prices))]

    return wma(diff, sqrt_p)


# ---------------------------------------------------------------------------
# KAMA — Kaufman Adaptive Moving Average
# ---------------------------------------------------------------------------

def kama(
    prices: list[float],
    n: int = 10,
    f: int = 2,
    s: int = 30,
) -> tuple[list[float], list[float]]:
    """Kaufman Adaptive Moving Average with Efficiency Ratio.

    Parameters
    ----------
    prices : list[float]
        Close prices.
    n : int
        ER lookback period (default 10).
    f : int
        Fast EMA period for SC calculation (default 2).
    s : int
        Slow EMA period for SC calculation (default 30).

    Returns
    -------
    (kama_series, er_series)
        Both lists have the same length as ``prices``.
        ER is in [0, 1]; values before the first complete n-bar window are 0.0.

    Formula
    -------
    ER_t  = |Close_t - Close_{t-n}| / Σ|Close_i - Close_{i-1}|   for i=t-n+1..t
    SC_t  = (ER_t × (2/(f+1) - 2/(s+1)) + 2/(s+1))²
    KAMA_t = KAMA_{t-1} + SC_t × (Close_t - KAMA_{t-1})
    """
    n_ = max(2, int(n))
    fast_sc = 2.0 / (max(2, int(f)) + 1)
    slow_sc = 2.0 / (max(2, int(s)) + 1)

    kama_vals: list[float] = []
    er_vals: list[float] = []

    # Seed KAMA at first price
    current_kama = prices[0] if prices else 0.0

    for i, price in enumerate(prices):
        if i < n_:
            # Warmup window not complete
            er_vals.append(0.0)
            kama_vals.append(price)
            current_kama = price
            continue

        # Efficiency Ratio
        direction = abs(price - prices[i - n_])
        volatility = sum(
            abs(prices[j] - prices[j - 1]) for j in range(i - n_ + 1, i + 1)
        )
        er = direction / volatility if volatility > 1e-12 else 0.0
        er = max(0.0, min(1.0, er))

        # Smoothing constant
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

        current_kama = current_kama + sc * (price - current_kama)
        er_vals.append(er)
        kama_vals.append(current_kama)

    return kama_vals, er_vals


# ---------------------------------------------------------------------------
# ATR — Average True Range
# ---------------------------------------------------------------------------

def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """Wilder's Average True Range.

    True Range = max(high − low, |high − prev_close|, |low − prev_close|).
    ATR is a Wilder-smoothed (EMA with α=1/period) average of TR.

    Returns one value per bar ≥ 0.  Warmup bars are filled with the
    simple TR mean of available data.
    """
    p = max(1, int(period))
    n = len(closes)
    if n == 0:
        return []

    tr: list[float] = []
    for i in range(n):
        h = highs[i]
        lo = lows[i]
        if i == 0:
            tr.append(h - lo)
        else:
            prev_c = closes[i - 1]
            tr.append(max(h - lo, abs(h - prev_c), abs(lo - prev_c)))

    alpha = 1.0 / p
    result: list[float] = []
    current_atr = sum(tr[:p]) / p if len(tr) >= p else sum(tr) / max(1, len(tr))
    for i, t in enumerate(tr):
        if i < p:
            result.append(sum(tr[: i + 1]) / (i + 1))
        else:
            current_atr = alpha * t + (1.0 - alpha) * current_atr
            result.append(current_atr)
    return result


# ---------------------------------------------------------------------------
# EMA — Exponential Moving Average
# ---------------------------------------------------------------------------

def ema(prices: list[float], period: int) -> list[float]:
    """Standard EMA with α = 2/(period+1).

    Warmup: SMA of available bars until the first complete window.
    """
    p = max(1, int(period))
    alpha = 2.0 / (p + 1)
    result: list[float] = []
    current_ema = prices[0] if prices else 0.0
    running_sum = 0.0
    for i, price in enumerate(prices):
        if i == 0:
            current_ema = price
            running_sum = price
        elif i < p:
            # Simple average during warmup — running sum avoids O(n²)
            running_sum += price
            current_ema = running_sum / (i + 1)
        else:
            current_ema = alpha * price + (1.0 - alpha) * current_ema
        result.append(current_ema)
    return result


# ---------------------------------------------------------------------------
# RSI — Relative Strength Index
# ---------------------------------------------------------------------------

def rsi(closes: list[float], period: int = 14) -> list[float]:
    """Wilder RSI in [0, 100].

    Returns 50.0 for warmup bars (neutral, won't trigger any gate).
    """
    p = max(1, int(period))
    result: list[float] = [50.0] * len(closes)
    if len(closes) <= p:
        return result

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    up = [max(0.0, c) for c in changes]
    dn = [max(0.0, -c) for c in changes]

    avg_up = sum(up[:p]) / p
    avg_dn = sum(dn[:p]) / p

    for i in range(p, len(closes)):
        bar = i - 1  # index into up/dn (length = len(closes)-1)
        if bar >= len(up):
            break
        if i == p:
            # First RSI value uses seed averages directly
            pass
        else:
            avg_up = (avg_up * (p - 1) + up[bar]) / p
            avg_dn = (avg_dn * (p - 1) + dn[bar]) / p

        if avg_up < 1e-12 and avg_dn < 1e-12:
            result[i] = 50.0
        elif avg_dn < 1e-12:
            result[i] = 100.0
        else:
            rs = avg_up / avg_dn
            result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


# ---------------------------------------------------------------------------
# Z-Score — Rolling Z-score of close vs EMA
# ---------------------------------------------------------------------------

def zscore(closes: list[float], period: int = 20) -> list[float]:
    """Rolling Z-score: (close − EMA(period)) / rolling_std(period).

    Returns 0.0 for warmup bars.  A high positive Z means the bar is far
    above the EMA (overbought condition for a fade strategy).
    """
    p = max(2, int(period))
    ema_vals = ema(closes, p)
    result: list[float] = []

    for i, close in enumerate(closes):
        if i < p - 1:
            result.append(0.0)
            continue
        window = closes[max(0, i - p + 1) : i + 1]
        mean = sum(window) / len(window)
        variance = sum((v - mean) ** 2 for v in window) / len(window)
        std = math.sqrt(variance) if variance > 0 else 1e-12
        result.append((close - ema_vals[i]) / std)

    return result
