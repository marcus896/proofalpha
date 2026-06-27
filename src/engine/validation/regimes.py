from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
from statistics import median

from engine.config.models import CrisisWindow, DataSnapshot, SnapshotWindow
from engine.data.snapshots import slice_snapshot


CRISIS_REGIMES = {"crash", "liquidity_stress", "short_squeeze"}


@dataclass(frozen=True)
class RegimeAnalysis:
    regime_labels: list[str]
    regime_coverage: dict[str, float]
    crisis_window_coverage: dict[str, float]
    crisis_windows: list[CrisisWindow]
    model_name: str = "deterministic"
    metadata: dict[str, object] | None = None


def analyze_regimes(snapshot: DataSnapshot) -> RegimeAnalysis:
    labels = label_snapshot_regimes(snapshot)
    return _build_regime_analysis(snapshot, labels, model_name="deterministic", metadata=derive_regime_state(snapshot))


def analyze_regimes_model(
    snapshot: DataSnapshot,
    *,
    model_name: str = "deterministic",
    n_states: int = 4,
) -> RegimeAnalysis:
    normalized = str(model_name or "deterministic").strip().lower()
    if normalized in {"deterministic", "baseline"}:
        return analyze_regimes(snapshot)
    if normalized == "hmm":
        return analyze_regimes_hmm(snapshot, n_states=n_states)
    if normalized == "hsmm":
        return analyze_regimes_hsmm(snapshot, n_states=n_states)
    if normalized == "bocpd":
        return analyze_regimes_bocpd(snapshot)
    raise ValueError("regime_model must be one of deterministic, hmm, hsmm, bocpd")


def derive_regime_state(snapshot: DataSnapshot, labels: list[str] | None = None) -> dict[str, object]:
    candles = snapshot.candles
    if not candles:
        return {
            "dominant_regime": "unknown",
            "funding_bucket": "flat",
            "volatility_bucket": "low",
            "open_interest_bucket": "flat",
            "regime_state_key": "unknown|flat|low|flat",
        }
    labels = labels if labels is not None else label_snapshot_regimes(snapshot)
    counts = Counter(labels)
    dominant_regime = counts.most_common(1)[0][0] if counts else "unknown"
    funding = _pad_series(snapshot.funding_rates, len(candles))
    open_interest = _pad_series(snapshot.open_interest, len(candles))
    closes = [float(candle.close) for candle in candles]
    avg_funding = sum(funding) / len(funding) if funding else 0.0
    bar_returns = [
        math.log(closes[index] / closes[index - 1])
        for index in range(1, len(closes))
        if closes[index - 1] > 0 and closes[index] > 0
    ]
    realized_vol = _stddev(bar_returns)
    oi_start = open_interest[0] if open_interest else 0.0
    oi_end = open_interest[-1] if open_interest else 0.0
    oi_change = 0.0 if oi_start == 0.0 else (oi_end / oi_start) - 1.0
    funding_bucket = _bucket_funding(avg_funding)
    volatility_bucket = _bucket_volatility(realized_vol)
    open_interest_bucket = _bucket_open_interest(oi_change)
    return {
        "dominant_regime": dominant_regime,
        "funding_bucket": funding_bucket,
        "volatility_bucket": volatility_bucket,
        "open_interest_bucket": open_interest_bucket,
        "average_funding_rate": round(avg_funding, 10),
        "realized_volatility": round(realized_vol, 10),
        "open_interest_change": round(oi_change, 10),
        "regime_state_key": f"{dominant_regime}|{funding_bucket}|{volatility_bucket}|{open_interest_bucket}",
    }


def _build_regime_analysis(
    snapshot: DataSnapshot,
    labels: list[str],
    *,
    model_name: str,
    metadata: dict[str, object] | None = None,
) -> RegimeAnalysis:
    crisis_windows = build_crisis_windows(snapshot, labels)
    total = max(1, len(labels))
    label_counts = Counter(labels)
    regime_coverage = {
        label: count / total
        for label, count in sorted(label_counts.items())
    }
    crisis_lengths: dict[str, int] = defaultdict(int)
    for window in crisis_windows:
        crisis_lengths[window.regime_label] += window.snapshot_window.end_index - window.snapshot_window.start_index
    crisis_window_coverage = {
        label: length / total
        for label, length in sorted(crisis_lengths.items())
    }
    return RegimeAnalysis(
        regime_labels=labels,
        regime_coverage=regime_coverage,
        crisis_window_coverage=crisis_window_coverage,
        crisis_windows=crisis_windows,
        model_name=model_name,
        metadata=metadata or {},
    )


def label_snapshot_regimes(snapshot: DataSnapshot) -> list[str]:
    candles = snapshot.candles
    if not candles:
        return []

    closes = [float(candle.close) for candle in candles]
    funding_rates = _pad_series(snapshot.funding_rates, len(closes))
    open_interest = _pad_series(snapshot.open_interest, len(closes))
    liquidation_notional = _pad_series(snapshot.liquidation_notional, len(closes))
    liquidation_baseline = median([value for value in liquidation_notional if value > 0.0] or [1.0])

    labels: list[str] = []
    running_peak = closes[0]
    for index, close in enumerate(closes):
        previous_close = closes[index - 1] if index > 0 else close
        lookback_index = max(0, index - 4)
        window_closes = closes[lookback_index : index + 1]
        lookback_close = window_closes[0]
        short_return = 0.0 if lookback_close == 0 else (close / lookback_close) - 1.0
        one_bar_return = 0.0 if previous_close == 0 else (close / previous_close) - 1.0
        price_slope = close - lookback_close
        running_peak = max(running_peak, close)
        drawdown = 0.0 if running_peak == 0 else (close / running_peak) - 1.0

        funding = funding_rates[index]
        liquidation_ratio = liquidation_notional[index] / max(1.0, liquidation_baseline)
        previous_open_interest = open_interest[index - 1] if index > 0 else open_interest[index]
        open_interest_change = (
            0.0
            if previous_open_interest == 0
            else abs((open_interest[index] / previous_open_interest) - 1.0)
        )

        if one_bar_return <= -0.09 or (drawdown <= -0.18 and one_bar_return <= 0.0):
            labels.append("crash")
            continue
        if one_bar_return >= 0.07 and funding >= 0.01 and liquidation_ratio >= 2.0:
            labels.append("short_squeeze")
            continue
        if abs(funding) >= 0.015 or open_interest_change >= 0.12 or liquidation_ratio >= 2.5:
            labels.append("liquidity_stress")
            continue
        if short_return >= 0.04 and price_slope > 0:
            labels.append("bull")
            continue
        if short_return <= -0.04 and price_slope < 0 and drawdown <= -0.03:
            labels.append("bear")
            continue
        labels.append("sideways")

    return labels


def build_crisis_windows(snapshot: DataSnapshot, regime_labels: list[str]) -> list[CrisisWindow]:
    crisis_windows: list[CrisisWindow] = []
    counters: dict[str, int] = defaultdict(int)
    start_index: int | None = None
    active_label: str | None = None

    for index, label in enumerate(regime_labels):
        if label in CRISIS_REGIMES:
            if active_label == label:
                continue
            if active_label is not None and start_index is not None:
                crisis_windows.append(_build_crisis_window(snapshot, active_label, start_index, index, counters))
            active_label = label
            start_index = index
            continue

        if active_label is not None and start_index is not None:
            crisis_windows.append(_build_crisis_window(snapshot, active_label, start_index, index, counters))
            active_label = None
            start_index = None

    if active_label is not None and start_index is not None:
        crisis_windows.append(_build_crisis_window(snapshot, active_label, start_index, len(regime_labels), counters))

    return crisis_windows


def _build_crisis_window(
    snapshot: DataSnapshot,
    regime_label: str,
    start_index: int,
    end_index: int,
    counters: dict[str, int],
) -> CrisisWindow:
    counters[regime_label] += 1
    window_name = f"{regime_label.replace('_', '-')}-{counters[regime_label]}"
    crisis_snapshot = slice_snapshot(snapshot, start_index, end_index, window_name)
    return CrisisWindow(
        name=window_name,
        snapshot_window=SnapshotWindow(crisis_snapshot, start_index, end_index),
        regime_label=regime_label,
    )


def _pad_series(values: list[float], length: int) -> list[float]:
    if len(values) >= length:
        return [float(value) for value in values[:length]]
    padded = [float(value) for value in values]
    if not padded:
        padded = [0.0]
    while len(padded) < length:
        padded.append(float(padded[-1]))
    return padded


# ---------------------------------------------------------------------------
# Phase 12 — HMM regime delegation
# ---------------------------------------------------------------------------

def label_snapshot_regimes_hmm(snapshot, n_states: int = 4) -> list[str]:
    """Return regime labels using a Gaussian HMM when hmmlearn is available.

    Falls back silently to :func:`label_snapshot_regimes` otherwise.

    Parameters
    ----------
    snapshot : DataSnapshot
    n_states : int
        Number of latent states for the HMM (default 4).

    Returns
    -------
    list[str]
        Per-bar regime label; same length as ``snapshot.candles``.
    """
    try:
        from engine.validation.hmm_regimes import fit_regime_model, predict_regimes
        if len(snapshot.candles) < 2 * n_states:
            return label_snapshot_regimes(snapshot)
        model = fit_regime_model(snapshot, n_states=n_states)
        labels, _ = predict_regimes(model, snapshot)
        return labels
    except ImportError:
        return label_snapshot_regimes(snapshot)
    except Exception:  # pragma: no cover — HMM fit may fail on degenerate data
        return label_snapshot_regimes(snapshot)


def analyze_regimes_hmm(snapshot, n_states: int = 4) -> RegimeAnalysis:
    """Same as :func:`analyze_regimes` but uses HMM labels when hmmlearn is available.

    Falls back to deterministic labels when hmmlearn is absent or the
    snapshot has insufficient bars to train the model.
    """
    labels = label_snapshot_regimes_hmm(snapshot, n_states=n_states)
    metadata = derive_regime_state(snapshot, labels)
    metadata.update({"n_states": int(n_states)})
    return _build_regime_analysis(
        snapshot,
        labels,
        model_name="hmm",
        metadata=metadata,
    )


def label_snapshot_regimes_hsmm(snapshot: DataSnapshot, n_states: int = 4, min_duration: int = 3) -> list[str]:
    base_labels = label_snapshot_regimes_hmm(snapshot, n_states=n_states)
    return _smooth_labels_by_duration(base_labels, min_duration=max(1, int(min_duration)))


def analyze_regimes_hsmm(snapshot: DataSnapshot, n_states: int = 4, min_duration: int = 3) -> RegimeAnalysis:
    labels = label_snapshot_regimes_hsmm(snapshot, n_states=n_states, min_duration=min_duration)
    metadata = derive_regime_state(snapshot, labels)
    metadata.update(
        {
            "duration_aware": True,
            "n_states": int(n_states),
            "min_duration": int(min_duration),
            "segment_count": _count_segments(labels),
        }
    )
    return _build_regime_analysis(snapshot, labels, model_name="hsmm", metadata=metadata)


def label_snapshot_regimes_bocpd(snapshot: DataSnapshot, hazard: float = 0.05, surprise_threshold: float = 0.65) -> list[str]:
    base_labels = label_snapshot_regimes(snapshot)
    probabilities = estimate_bocpd_changepoint_probabilities(snapshot, hazard=hazard)
    labels: list[str] = []
    for index, label in enumerate(base_labels):
        if index < len(probabilities) and probabilities[index] >= surprise_threshold:
            labels.append("liquidity_stress" if label == "sideways" else label)
        else:
            labels.append(label)
    return labels


def analyze_regimes_bocpd(snapshot: DataSnapshot, hazard: float = 0.05) -> RegimeAnalysis:
    probabilities = estimate_bocpd_changepoint_probabilities(snapshot, hazard=hazard)
    labels = label_snapshot_regimes_bocpd(snapshot, hazard=hazard)
    top_changepoints = sorted(
        [
            {"index": index, "probability": round(probability, 6)}
            for index, probability in enumerate(probabilities)
            if probability >= 0.5
        ],
        key=lambda item: (-float(item["probability"]), int(item["index"])),
    )[:10]
    metadata = derive_regime_state(snapshot, labels)
    metadata.update(
        {
            "online_changepoint": True,
            "hazard": float(hazard),
            "changepoint_count": len(top_changepoints),
            "top_changepoints": top_changepoints,
        }
    )
    return _build_regime_analysis(snapshot, labels, model_name="bocpd", metadata=metadata)


def estimate_bocpd_changepoint_probabilities(snapshot: DataSnapshot, hazard: float = 0.05) -> list[float]:
    candles = snapshot.candles
    if not candles:
        return []
    closes = [float(candle.close) for candle in candles]
    returns = [0.0]
    for index in range(1, len(closes)):
        previous = closes[index - 1]
        returns.append(math.log(closes[index] / previous) if previous > 0 and closes[index] > 0 else 0.0)
    funding = _pad_series(snapshot.funding_rates, len(candles))
    open_interest = _pad_series(snapshot.open_interest, len(candles))
    doi = [0.0]
    for index in range(1, len(open_interest)):
        previous = open_interest[index - 1]
        doi.append(0.0 if previous == 0.0 else (open_interest[index] / previous) - 1.0)

    probabilities: list[float] = []
    window = 12
    base_hazard = max(0.001, min(0.5, float(hazard)))
    for index in range(len(candles)):
        start = max(0, index - window)
        surprise = max(
            _rolling_surprise(returns, index, start),
            _rolling_surprise(funding, index, start),
            _rolling_surprise(doi, index, start),
        )
        probability = min(0.99, base_hazard + (1.0 - base_hazard) * (surprise / (surprise + 3.0)))
        probabilities.append(probability)
    return probabilities


def _smooth_labels_by_duration(labels: list[str], min_duration: int) -> list[str]:
    if not labels or min_duration <= 1:
        return list(labels)
    smoothed = list(labels)
    segments: list[tuple[int, int, str]] = []
    start = 0
    for index in range(1, len(labels) + 1):
        if index == len(labels) or labels[index] != labels[start]:
            segments.append((start, index, labels[start]))
            start = index
    for segment_index, (start, end, label) in enumerate(segments):
        if end - start >= min_duration:
            continue
        left_label = segments[segment_index - 1][2] if segment_index > 0 else None
        right_label = segments[segment_index + 1][2] if segment_index + 1 < len(segments) else None
        replacement = left_label or right_label or label
        if left_label == right_label and left_label is not None:
            replacement = left_label
        for index in range(start, end):
            smoothed[index] = replacement
    return smoothed


def _count_segments(labels: list[str]) -> int:
    if not labels:
        return 0
    return 1 + sum(1 for index in range(1, len(labels)) if labels[index] != labels[index - 1])


def _rolling_surprise(values: list[float], index: int, start: int) -> float:
    if index <= start + 2:
        return 0.0
    history = values[start:index]
    mean_value = sum(history) / len(history)
    std_value = _stddev(history)
    return abs(values[index] - mean_value) / max(std_value, 1e-9)


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / len(values)
    return math.sqrt(sum((value - mean_value) ** 2 for value in values) / (len(values) - 1))


def _bucket_funding(value: float) -> str:
    if value >= 0.01:
        return "positive_extreme"
    if value >= 0.001:
        return "positive"
    if value <= -0.01:
        return "negative_extreme"
    if value <= -0.001:
        return "negative"
    return "flat"


def _bucket_volatility(value: float) -> str:
    if value >= 0.04:
        return "high"
    if value >= 0.015:
        return "medium"
    return "low"


def _bucket_open_interest(value: float) -> str:
    if value >= 0.15:
        return "rising_fast"
    if value >= 0.03:
        return "rising"
    if value <= -0.15:
        return "falling_fast"
    if value <= -0.03:
        return "falling"
    return "flat"
