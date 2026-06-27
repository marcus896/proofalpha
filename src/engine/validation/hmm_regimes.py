"""Phase 12 — Gaussian HMM regime detection adaptor.

Public API
----------
is_hmmlearn_available() -> bool
fit_regime_model(snapshot, n_states=4) -> GaussianHMM | None
predict_regimes(model, snapshot) -> tuple[list[str], list[list[float]]]
map_hmm_states_to_labels(model) -> dict[int, str]

Design
------
Features fed to the HMM: [log_ret, roll_vol, funding, dOI].
log_ret and roll_vol are computed over a 5-bar rolling window.
Semantic label assignment uses the cluster mean of each state
against the same heuristics as the deterministic labeller.

When hmmlearn is absent every public function raises ImportError with
an install hint. Callers in regimes.py catch this and fall back to
label_snapshot_regimes() so the engine never fails.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_VALID_LABELS = frozenset({"bull", "bear", "sideways", "crash", "liquidity_stress", "short_squeeze"})


def is_hmmlearn_available() -> bool:
    """Return True if hmmlearn and numpy are importable."""
    try:
        import numpy  # noqa: F401
        import hmmlearn  # noqa: F401
        return True
    except ModuleNotFoundError:
        return False


def _require_hmmlearn():
    """Import and return GaussianHMM, raising ImportError with install hint if absent."""
    try:
        import numpy as np
        from hmmlearn.hmm import GaussianHMM
        return GaussianHMM, np
    except ModuleNotFoundError as exc:
        raise ImportError(
            "HMM regime detection requires 'hmmlearn'.  "
            "Install it with: pip install 'crypto-perps-proofalpha[regimes]'"
        ) from exc


def _build_feature_matrix(snapshot) -> tuple[list[list[float]], int]:
    """Build T×4 feature matrix: [log_ret, roll_vol, funding, dOI].

    Returns (rows, n_valid_rows) where rows are the full-length list.
    Rows with insufficient history are replicated from the first valid row.
    """
    candles = snapshot.candles
    n = len(candles)
    closes = [float(c.close) for c in candles]
    funding = list(snapshot.funding_rates)[:n]
    oi = list(snapshot.open_interest)[:n]

    # Pad short series
    while len(funding) < n:
        funding.append(funding[-1] if funding else 0.0)
    while len(oi) < n:
        oi.append(oi[-1] if oi else 1.0)

    window = 5
    rows: list[list[float]] = []
    for i in range(n):
        start = max(0, i - window + 1)
        win_closes = closes[start : i + 1]

        if len(win_closes) < 2:
            rows.append([0.0, 1e-6, funding[i], 0.0])
            continue

        # log return vs window start
        prev = win_closes[0]
        log_ret = math.log(closes[i] / prev) if prev > 0 else 0.0

        # rolling volatility (std of log bar returns in window)
        bar_rets = [
            math.log(win_closes[j] / win_closes[j - 1])
            for j in range(1, len(win_closes))
            if win_closes[j - 1] > 0
        ]
        if len(bar_rets) >= 2:
            mean_r = sum(bar_rets) / len(bar_rets)
            var_r = sum((r - mean_r) ** 2 for r in bar_rets) / max(len(bar_rets) - 1, 1)
            roll_vol = math.sqrt(max(var_r, 0.0))
        else:
            roll_vol = abs(bar_rets[0]) if bar_rets else 1e-6

        # dOI: fractional change in open interest vs previous bar
        prev_oi = oi[i - 1] if i > 0 else oi[i]
        d_oi = abs((oi[i] / prev_oi) - 1.0) if prev_oi > 0 else 0.0

        rows.append([log_ret, roll_vol, funding[i], d_oi])

    return rows, n


def fit_regime_model(snapshot, n_states: int = 4):
    """Fit a GaussianHMM on the snapshot feature matrix.

    Parameters
    ----------
    snapshot : DataSnapshot
        Must have >= 2 * n_states candles for training to be meaningful.
    n_states : int
        Number of latent HMM states (default 4).

    Returns
    -------
    Fitted GaussianHMM instance.

    Raises
    ------
    ImportError
        When hmmlearn is not installed.
    ValueError
        When the snapshot has insufficient candles.
    """
    GaussianHMM, np = _require_hmmlearn()

    if len(snapshot.candles) < 2 * n_states:
        raise ValueError(
            f"Snapshot has {len(snapshot.candles)} candles; need at least {2 * n_states} "
            f"to fit a {n_states}-state HMM."
        )

    rows, _ = _build_feature_matrix(snapshot)
    X = np.array(rows, dtype=float)

    model = GaussianHMM(
        n_components=n_states,
        covariance_type="diag",
        n_iter=100,
        tol=1e-3,
        random_state=42,
    )
    model.fit(X)
    return model


def predict_regimes(model, snapshot) -> tuple[list[str], list[list[float]]]:
    """Decode HMM states for the snapshot and map to semantic regime names.

    Parameters
    ----------
    model : GaussianHMM
        A fitted model from :func:`fit_regime_model`.
    snapshot : DataSnapshot

    Returns
    -------
    labels : list[str]
        Per-bar regime label, one of the 6 canonical names.
    posteriors : list[list[float]]
        Per-bar posterior state probabilities, shape T × n_states.

    Raises
    ------
    ImportError
        When hmmlearn is not installed.
    """
    _, np = _require_hmmlearn()

    rows, n = _build_feature_matrix(snapshot)
    X = np.array(rows, dtype=float)

    state_sequence = model.predict(X)
    posteriors_arr = model.predict_proba(X)

    state_to_label = map_hmm_states_to_labels(model)
    labels = [state_to_label.get(int(s), "sideways") for s in state_sequence]
    posteriors = posteriors_arr.tolist()
    return labels, posteriors


def map_hmm_states_to_labels(model) -> dict[int, str]:
    """Map each HMM state index to a canonical regime label.

    Heuristic based on the cluster mean of [log_ret, roll_vol, funding, dOI]:
      Feature indices: 0=log_ret, 1=roll_vol, 2=funding, 3=dOI

    Label assignment priority (first match wins):
      crash          : roll_vol > 0.04 AND log_ret < -0.05
      short_squeeze  : log_ret > 0.05 AND funding > 0.01 AND dOI > 0.08
      liquidity_stress: |funding| > 0.012 OR dOI > 0.10
      bull           : log_ret > 0.02 AND roll_vol < 0.04
      bear           : log_ret < -0.02 AND roll_vol < 0.04
      sideways       : default

    Raises
    ------
    ImportError
        When hmmlearn is not installed.
    """
    _, np = _require_hmmlearn()

    means = np.array(model.means_, dtype=float)  # shape: n_states × n_features
    n_states = means.shape[0]
    mapping: dict[int, str] = {}

    for state in range(n_states):
        log_ret = float(means[state, 0])
        roll_vol = float(means[state, 1])
        funding = float(means[state, 2])
        d_oi = float(means[state, 3])

        if roll_vol > 0.04 and log_ret < -0.05:
            label = "crash"
        elif log_ret > 0.05 and funding > 0.01 and d_oi > 0.08:
            label = "short_squeeze"
        elif abs(funding) > 0.012 or d_oi > 0.10:
            label = "liquidity_stress"
        elif log_ret > 0.02 and roll_vol < 0.04:
            label = "bull"
        elif log_ret < -0.02 and roll_vol < 0.04:
            label = "bear"
        else:
            label = "sideways"

        mapping[state] = label

    return mapping
