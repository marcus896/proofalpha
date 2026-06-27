from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from engine.data.snapshots import clone_snapshot
from engine.data.schema import Candle

if TYPE_CHECKING:
    from engine.config.models import DataSnapshot


# Optional tsbootstrap dependency — gracefully unavailable when not installed.
try:
    import numpy as _np  # tsbootstrap requires numpy
    import tsbootstrap as _tsbootstrap  # type: ignore[import-untyped]
    from tsbootstrap import BlockBootstrap as _BlockBootstrap  # type: ignore[import-untyped]

    TSBOOTSTRAP_AVAILABLE = True
except ImportError:
    TSBOOTSTRAP_AVAILABLE = False
    _np = None  # type: ignore[assignment]
    _tsbootstrap = None  # type: ignore[assignment]
    _BlockBootstrap = None  # type: ignore[assignment]


# Methods supplied by the stdlib (always available)
_STDLIB_METHODS = frozenset({"moving_block", "stationary_block", "dependent_wild"})

# Methods that require tsbootstrap — registered here so they are discoverable
# even when the library is absent (the caller gets an ImportError with a clear
# message rather than a silent "unsupported method" error).
_TSBOOTSTRAP_METHODS = frozenset({"tsbootstrap_moving_block", "tsbootstrap_stationary_block"})

SUPPORTED_BOOTSTRAP_METHODS = tuple(sorted(_STDLIB_METHODS | _TSBOOTSTRAP_METHODS))


def list_bootstrap_methods() -> dict[str, bool]:
    """Return all method names mapped to whether they are currently available.

    The stdlib methods are always available.  The tsbootstrap methods are
    available only when the ``tsbootstrap`` package is installed.
    """
    result: dict[str, bool] = {}
    for name in sorted(SUPPORTED_BOOTSTRAP_METHODS):
        if name in _STDLIB_METHODS:
            result[name] = True
        else:
            result[name] = TSBOOTSTRAP_AVAILABLE
    return result


def bootstrap_indices_for_method(
    method: str,
    sample_count: int,
    block_size: int,
    seed: int,
) -> list[int]:
    """Dispatch to the appropriate bootstrap implementation by method name.

    Stdlib methods (``moving_block``, ``stationary_block``) never require
    external packages.  The ``tsbootstrap_*`` variants delegate to the
    ``tsbootstrap`` library and raise :class:`ImportError` when it is absent.
    """
    method_name = str(method)
    if method_name == "moving_block":
        return moving_block_bootstrap_indices(sample_count=sample_count, block_size=block_size, seed=seed)
    if method_name == "stationary_block":
        return stationary_block_bootstrap_indices(sample_count=sample_count, block_size=block_size, seed=seed)
    if method_name == "dependent_wild":
        _validate_bootstrap_request(sample_count=sample_count, block_size=block_size)
        return list(range(sample_count))
    if method_name == "multivariate_block":
        return multivariate_block_bootstrap_indices(sample_count=sample_count, block_size=block_size, seed=seed)
    if method_name in _TSBOOTSTRAP_METHODS:
        return _tsbootstrap_indices(
            method=method_name,
            sample_count=sample_count,
            block_size=block_size,
            seed=seed,
        )
    raise ValueError(f"unsupported bootstrap method: {method_name!r}")


def _resample_series(values: list[float], indices: list[int], sample_count: int) -> list[float]:
    if len(values) == sample_count:
        return [values[index] for index in indices]
    return list(values)


def clone_snapshot_with_bootstrap_indices(
    snapshot: "DataSnapshot",
    *,
    indices: list[int],
    snapshot_id: str,
    provenance_updates: dict[str, int | str],
):
    sample_count = len(snapshot.candles)
    return clone_snapshot(
        snapshot,
        snapshot_id=snapshot_id,
        candles=[snapshot.candles[index] for index in indices],
        funding_rates=_resample_series(snapshot.funding_rates, indices, sample_count),
        open_interest=_resample_series(snapshot.open_interest, indices, sample_count),
        liquidation_notional=_resample_series(snapshot.liquidation_notional, indices, sample_count),
        spread_bps=_resample_series(snapshot.spread_bps, indices, sample_count),
        depth_bid_1bp_usd=_resample_series(snapshot.depth_bid_1bp_usd, indices, sample_count),
        depth_ask_1bp_usd=_resample_series(snapshot.depth_ask_1bp_usd, indices, sample_count),
        latency_proxy_ms=_resample_series(snapshot.latency_proxy_ms, indices, sample_count),
        provenance_updates=provenance_updates,
    )


# ─── Stdlib implementations ──────────────────────────────────────────────────

def moving_block_bootstrap_indices(
    sample_count: int,
    block_size: int,
    seed: int,
) -> list[int]:
    if sample_count <= 0:
        return []
    _validate_bootstrap_request(sample_count=sample_count, block_size=block_size)

    rng = random.Random(seed)
    indices: list[int] = []
    max_start = sample_count - block_size

    while len(indices) < sample_count:
        start = rng.randint(0, max_start)
        indices.extend(range(start, start + block_size))

    return indices[:sample_count]


def moving_block_bootstrap(
    candles: list[Candle],
    block_size: int,
    seed: int,
) -> list[Candle]:
    indices = moving_block_bootstrap_indices(len(candles), block_size=block_size, seed=seed)
    return [candles[index] for index in indices]


def stationary_block_bootstrap_indices(
    sample_count: int,
    block_size: int,
    seed: int,
) -> list[int]:
    if sample_count <= 0:
        return []
    _validate_bootstrap_request(sample_count=sample_count, block_size=block_size)

    rng = random.Random(seed)
    restart_probability = 1.0 / block_size
    indices = [rng.randrange(sample_count)]

    while len(indices) < sample_count:
        previous = indices[-1]
        if rng.random() < restart_probability:
            indices.append(rng.randrange(sample_count))
            continue
        indices.append((previous + 1) % sample_count)

    return indices


def dependent_wild_bootstrap_weights(
    sample_count: int,
    block_size: int,
    seed: int,
) -> list[float]:
    """Return dependent wild bootstrap multipliers with local persistence.

    The weights are AR(1)-smoothed Rademacher shocks.  This keeps the stdlib
    path dependency-free while preserving clustered sign/volatility structure
    better than independent wild multipliers.
    """
    if sample_count <= 0:
        return []
    _validate_bootstrap_request(sample_count=sample_count, block_size=block_size)

    rng = random.Random(seed)
    persistence = math.exp(-1.0 / max(1.0, float(block_size)))
    innovation_scale = math.sqrt(max(0.0, 1.0 - (persistence * persistence)))
    weights: list[float] = []
    previous = 1.0 if rng.random() >= 0.5 else -1.0
    for _ in range(sample_count):
        innovation = 1.0 if rng.random() >= 0.5 else -1.0
        current = (persistence * previous) + (innovation_scale * innovation)
        if current == 0.0:
            current = innovation
        weights.append(current)
        previous = current
    return weights


def dependent_wild_bootstrap_snapshot(snapshot: "DataSnapshot", block_size: int, seed: int):
    """Create a dependent-wild bootstrap path without reordering bars.

    Returns are centered, multiplied by persistent wild weights, then rebuilt
    into a price path. Perps sidecars are shocked with the same weights in
    lockstep so funding/OI/liquidation pressure remains state-aligned.
    """
    sample_count = len(snapshot.candles)
    if sample_count <= 0:
        return clone_snapshot(
            snapshot,
            snapshot_id=f"{snapshot.snapshot_id}:dependent_wild:{seed}",
            provenance_updates={
                "transformation": "dependent_wild_bootstrap",
                "seed": seed,
                "block_size": block_size,
            },
        )
    weights = dependent_wild_bootstrap_weights(sample_count=sample_count, block_size=block_size, seed=seed)
    candles = _dependent_wild_candles(snapshot.candles, weights)
    return clone_snapshot(
        snapshot,
        snapshot_id=f"{snapshot.snapshot_id}:dependent_wild:{seed}",
        candles=candles,
        funding_rates=_shock_centered_series(snapshot.funding_rates, weights, floor=None),
        open_interest=_shock_centered_series(snapshot.open_interest, weights, floor=0.0),
        liquidation_notional=_shock_centered_series(snapshot.liquidation_notional, weights, floor=0.0),
        spread_bps=_shock_centered_series(snapshot.spread_bps, weights, floor=0.0),
        depth_bid_1bp_usd=_shock_centered_series(snapshot.depth_bid_1bp_usd, weights, floor=0.0),
        depth_ask_1bp_usd=_shock_centered_series(snapshot.depth_ask_1bp_usd, weights, floor=0.0),
        latency_proxy_ms=_shock_centered_series(snapshot.latency_proxy_ms, weights, floor=0.0),
        provenance_updates={
            "transformation": "dependent_wild_bootstrap",
            "seed": seed,
            "block_size": block_size,
            "wild_weight_model": "ar1_rademacher",
        },
    )


def _dependent_wild_candles(candles: list[Candle], weights: list[float]) -> list[Candle]:
    if len(candles) < 2:
        return list(candles)
    closes = [float(candle.close) for candle in candles]
    returns = [
        (current / previous) - 1.0 if previous != 0.0 else 0.0
        for previous, current in zip(closes, closes[1:])
    ]
    mean_return = sum(returns) / len(returns) if returns else 0.0
    rebuilt_closes = [max(closes[0], 1e-9)]
    for index, raw_return in enumerate(returns, start=1):
        weight = weights[index] if index < len(weights) else 1.0
        shocked_return = mean_return + ((raw_return - mean_return) * weight)
        rebuilt_closes.append(max(rebuilt_closes[-1] * (1.0 + shocked_return), 1e-9))

    rebuilt: list[Candle] = []
    for index, candle in enumerate(candles):
        close = rebuilt_closes[index]
        previous_close = rebuilt_closes[index - 1] if index else close
        original_close = closes[index] if closes[index] != 0.0 else close
        high_ratio = max(float(candle.high) / original_close, 1.0)
        low_ratio = min(float(candle.low) / original_close, 1.0)
        open_price = previous_close if index else close
        high = max(open_price, close, close * high_ratio)
        low = min(open_price, close, close * low_ratio)
        rebuilt.append(
            Candle(
                timestamp=candle.timestamp,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=candle.volume,
            )
        )
    return rebuilt


def _shock_centered_series(values: list[float], weights: list[float], floor: float | None) -> list[float]:
    if not values or len(values) != len(weights):
        return list(values)
    mean_value = sum(float(value) for value in values) / len(values)
    shocked = [
        mean_value + ((float(value) - mean_value) * weights[index])
        for index, value in enumerate(values)
    ]
    if floor is None:
        return shocked
    return [max(float(floor), value) for value in shocked]


# ─── tsbootstrap adaptor ─────────────────────────────────────────────────────

def _tsbootstrap_indices(
    method: str,
    sample_count: int,
    block_size: int,
    seed: int,
) -> list[int]:
    """Route to ``tsbootstrap`` implementations.

    Raises
    ------
    ImportError
        When ``tsbootstrap`` (and/or ``numpy``) is not installed.
    ValueError
        When an unrecognised ``tsbootstrap_*`` method name is requested.
    """
    if not TSBOOTSTRAP_AVAILABLE:
        raise ImportError(
            f"bootstrap method {method!r} requires the 'tsbootstrap' package, "
            "which is not installed.  Install it with: pip install tsbootstrap"
        )
    _validate_bootstrap_request(sample_count=sample_count, block_size=block_size)

    # tsbootstrap uses numpy arrays; map method name to block_bootstrap_type
    if method == "tsbootstrap_moving_block":
        block_bootstrap_type = "moving"
    elif method == "tsbootstrap_stationary":
        block_bootstrap_type = "stationary"
    elif method == "tsbootstrap_stationary_block":
        block_bootstrap_type = "stationary"
    else:
        raise ValueError(f"unrecognised tsbootstrap method: {method!r}")

    # Build deterministic input series (dummy series — we only want indices)
    arr = _np.arange(sample_count, dtype=float)

    bootstrapper = _BlockBootstrap(
        n_bootstraps=1,
        block_length=block_size,
        block_length_distribution=None if block_bootstrap_type == "moving" else "geometric",
        wrap_around_flag=False,
        overlap_flag=True,
        rng=seed,
    )

    raw_indices: list[int] = []
    for sample in bootstrapper.bootstrap(arr):
        idx_array = sample
        if isinstance(sample, tuple) and sample:
            idx_array = sample[0]
        raw_indices = [int(i) for i in _np.asarray(idx_array).flatten().tolist()]
        break  # only one bootstrap sample

    # Clip/extend to exact sample_count
    if len(raw_indices) >= sample_count:
        return raw_indices[:sample_count]
    # If shorter, extend by repeating with offset to avoid modifying the block structure
    extended = list(raw_indices)
    while len(extended) < sample_count:
        extended.extend(raw_indices[: sample_count - len(extended)])
    return extended


# ─── Shared validation ────────────────────────────────────────────────────────

def _validate_bootstrap_request(sample_count: int, block_size: int) -> None:
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if block_size > sample_count:
        raise ValueError("block_size cannot exceed candle count")


# ─── Phase 12: Multivariate block bootstrap ───────────────────────────────────

def multivariate_block_bootstrap_indices(
    sample_count: int,
    block_size: int,
    seed: int,
) -> list[int]:
    """Produce a bootstrap index list using numpy's default_rng.

    Uses the **same** index list for all series in the snapshot so that
    cross-series structure (e.g. the pairing of returns with funding rates)
    is preserved exactly within and across blocks.

    Parameters
    ----------
    sample_count : int
        Number of observations in the original series.
    block_size : int
        Fixed block length.
    seed : int
        RNG seed for reproducibility.

    Returns
    -------
    list[int]
        Exactly ``sample_count`` indices drawn from ``[0, sample_count)``.
    """
    if sample_count <= 0:
        return []
    _validate_bootstrap_request(sample_count=sample_count, block_size=block_size)

    rng = random.Random(seed)
    max_start = sample_count - block_size
    indices: list[int] = []
    while len(indices) < sample_count:
        start = rng.randint(0, max_start)
        indices.extend(range(start, start + block_size))
    return indices[:sample_count]


def multivariate_block_bootstrap(snapshot, block_size: int, seed: int):
    """Jointly resample all four snapshot series using one shared index list.

    Returns a new ``DataSnapshot`` where ``candles``, ``funding_rates``,
    ``open_interest``, and ``liquidation_notional`` are all resampled with
    the same block indices so that cross-series correlations (e.g. the
    funding rate that co-occurred with a given return) are preserved.

    Parameters
    ----------
    snapshot : DataSnapshot
        Source snapshot.
    block_size : int
        Fixed block length.
    seed : int
        RNG seed.

    Returns
    -------
    DataSnapshot
        New snapshot with jointly-resampled series.
    """
    indices = multivariate_block_bootstrap_indices(
        sample_count=len(snapshot.candles),
        block_size=block_size,
        seed=seed,
    )
    return clone_snapshot_with_bootstrap_indices(
        snapshot,
        indices=indices,
        snapshot_id=f"{snapshot.snapshot_id}:mv_bootstrap:{seed}",
        provenance_updates={
            "transformation": "multivariate_block_bootstrap",
            "seed": seed,
            "block_size": block_size,
        },
    )


# Register multivariate_block as a stdlib method (numpy is now core)
_STDLIB_METHODS = frozenset(_STDLIB_METHODS | {"multivariate_block"})
SUPPORTED_BOOTSTRAP_METHODS = tuple(sorted(_STDLIB_METHODS | _TSBOOTSTRAP_METHODS))
