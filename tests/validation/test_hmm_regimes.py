"""Tests for Phase 12 HMM regime detection.

These tests pass without ``hmmlearn`` or ``numpy`` by using deterministic
test doubles for the optional dependency boundary.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from engine.config.models import DataSnapshot
from engine.data.schema import Candle
from engine.validation.hmm_regimes import (
    is_hmmlearn_available,
    map_hmm_states_to_labels,
)
from engine.validation.regimes import (
    analyze_regimes,
    analyze_regimes_hmm,
    label_snapshot_regimes,
    label_snapshot_regimes_hmm,
)


_VALID_LABELS = frozenset({"bull", "bear", "sideways", "crash", "liquidity_stress", "short_squeeze"})


class _FakeArray:
    def __init__(self, data):
        self._data = self._normalize(data)

    @staticmethod
    def _normalize(data):
        if isinstance(data, _FakeArray):
            return data.tolist()
        if isinstance(data, list):
            return [_FakeArray._normalize(item) if isinstance(item, list) else item for item in data]
        if isinstance(data, tuple):
            return [_FakeArray._normalize(item) if isinstance(item, (list, tuple)) else item for item in data]
        return data

    @property
    def shape(self) -> tuple[int, ...]:
        if isinstance(self._data, list) and self._data and isinstance(self._data[0], list):
            return (len(self._data), len(self._data[0]))
        if isinstance(self._data, list):
            return (len(self._data),)
        return ()

    @property
    def ndim(self) -> int:
        return len(self.shape)

    @property
    def size(self) -> int:
        if self.ndim == 2:
            return self.shape[0] * self.shape[1]
        if self.ndim == 1:
            return self.shape[0]
        return 0

    def __len__(self) -> int:
        if isinstance(self._data, list):
            return len(self._data)
        return 0

    def __getitem__(self, key):
        if isinstance(key, tuple):
            row, col = key
            return self._data[row][col]
        return self._data[key]

    def reshape(self, *_shape):
        if self.ndim == 1:
            return _FakeArray([list(self._data)])
        return _FakeArray(self._data)

    def tolist(self):
        if isinstance(self._data, list):
            return [
                item.tolist() if isinstance(item, _FakeArray) else item
                for item in self._data
            ]
        return self._data


class _FakeNP:
    @staticmethod
    def array(data, dtype=float):
        return _FakeArray(data)

    @staticmethod
    def asarray(data, dtype=float):
        return _FakeArray(data)

    @staticmethod
    def zeros(shape, dtype=float):
        if isinstance(shape, tuple) and len(shape) == 2:
            rows, cols = shape
            return _FakeArray([[0.0 for _ in range(cols)] for _ in range(rows)])
        if isinstance(shape, int):
            return _FakeArray([0.0 for _ in range(shape)])
        return _FakeArray([])


class _FakeGaussianHMM:
    def __init__(
        self,
        n_components: int,
        covariance_type: str = "diag",
        n_iter: int = 100,
        tol: float = 1e-3,
        random_state: int | None = None,
    ) -> None:
        self.n_components = n_components
        self.covariance_type = covariance_type
        self.n_iter = n_iter
        self.tol = tol
        self.random_state = random_state
        self.means_ = [[0.0, 0.0, 0.0, 0.0] for _ in range(n_components)]

    def fit(self, X):
        rows = _FakeNP.asarray(X, dtype=float)
        data = rows.tolist()
        if rows.size == 0:
            self.means_ = [[0.0, 0.0, 0.0, 0.0] for _ in range(self.n_components)]
            return self
        if rows.ndim == 1:
            data = [data]
        self.means_ = [list(data[min(index, len(data) - 1)]) for index in range(self.n_components)]
        return self

    def predict(self, X):
        rows = _FakeNP.asarray(X, dtype=float)
        return [index % self.n_components for index in range(len(rows))]

    def predict_proba(self, X):
        rows = _FakeNP.asarray(X, dtype=float)
        posteriors = []
        for index in range(len(rows)):
            row = [0.0] * self.n_components
            row[index % self.n_components] = 1.0
            posteriors.append(row)
        return _FakeArray(posteriors)


def _make_snapshot(n: int = 40, crash_at: int | None = None) -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    closes = [100.0 + i * 0.5 for i in range(n)]
    if crash_at is not None:
        closes[crash_at] = closes[crash_at - 1] * 0.80

    candles = [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=c - 0.1,
            high=c + 0.5,
            low=c - 0.5,
            close=c,
            volume=1_000.0,
        )
        for i, c in enumerate(closes)
    ]
    funding = [0.001 if i % 5 == 0 else 0.0003 for i in range(n)]
    oi = [1_000.0 + i * 5 for i in range(n)]
    liq = [10.0] * n
    return DataSnapshot(
        snapshot_id="hmm-test",
        symbol="BTCUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=funding,
        open_interest=oi,
        liquidation_notional=liq,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        quality_flags=[],
    )


class HmmAvailabilityTests(unittest.TestCase):
    def test_is_hmmlearn_available_returns_bool(self) -> None:
        self.assertIsInstance(is_hmmlearn_available(), bool)

    def test_is_hmmlearn_available_does_not_raise(self) -> None:
        try:
            is_hmmlearn_available()
        except Exception as exc:  # pragma: no cover
            self.fail(f"is_hmmlearn_available() raised unexpectedly: {exc}")


class HmmFallbackTests(unittest.TestCase):
    def test_label_snapshot_regimes_hmm_falls_back_when_hmmlearn_missing(self) -> None:
        snap = _make_snapshot(20)
        with patch("engine.validation.hmm_regimes.is_hmmlearn_available", return_value=False):
            with patch(
                "engine.validation.hmm_regimes._require_hmmlearn",
                side_effect=ImportError("hmmlearn not installed"),
            ):
                labels = label_snapshot_regimes_hmm(snap, n_states=4)

        self.assertEqual(len(labels), len(snap.candles))
        for label in labels:
            self.assertIn(label, _VALID_LABELS)

    def test_label_snapshot_regimes_hmm_returns_correct_length(self) -> None:
        snap = _make_snapshot(30)
        labels = label_snapshot_regimes_hmm(snap, n_states=4)
        self.assertEqual(len(labels), len(snap.candles))

    def test_label_snapshot_regimes_hmm_returns_only_valid_labels(self) -> None:
        snap = _make_snapshot(30)
        labels = label_snapshot_regimes_hmm(snap, n_states=4)
        for label in labels:
            self.assertIn(label, _VALID_LABELS)

    def test_label_snapshot_regimes_hmm_falls_back_for_short_snapshot(self) -> None:
        snap = _make_snapshot(6)
        labels_hmm = label_snapshot_regimes_hmm(snap, n_states=4)
        labels_det = label_snapshot_regimes(snap)
        self.assertEqual(labels_hmm, labels_det)

    def test_analyze_regimes_hmm_returns_regime_analysis_instance(self) -> None:
        from engine.validation.regimes import RegimeAnalysis

        self.assertIsInstance(analyze_regimes_hmm(_make_snapshot(30), n_states=4), RegimeAnalysis)

    def test_analyze_regimes_hmm_coverage_sums_to_one(self) -> None:
        result = analyze_regimes_hmm(_make_snapshot(30), n_states=4)
        self.assertAlmostEqual(sum(result.regime_coverage.values()), 1.0, places=6)

    def test_analyze_regimes_hmm_label_count_matches_candles(self) -> None:
        snap = _make_snapshot(30)
        result = analyze_regimes_hmm(snap, n_states=4)
        self.assertEqual(len(result.regime_labels), len(snap.candles))

    def test_analyze_regimes_hmm_produces_same_type_as_analyze_regimes(self) -> None:
        snap = _make_snapshot(30)
        self.assertEqual(type(analyze_regimes(snap)), type(analyze_regimes_hmm(snap, n_states=4)))


class HmmMapLabelsTests(unittest.TestCase):
    def _make_fake_model(self, means: list[list[float]]):
        model = MagicMock()
        model.means_ = means
        return model

    def _map_labels(self, model) -> dict[int, str]:
        with patch("engine.validation.hmm_regimes._require_hmmlearn", return_value=(object, _FakeNP)):
            return map_hmm_states_to_labels(model)

    def test_map_labels_returns_dict_keyed_by_state_index(self) -> None:
        mapping = self._map_labels(self._make_fake_model([[0.03, 0.02, 0.0003, 0.01], [-0.06, 0.05, -0.001, 0.02]]))
        self.assertIn(0, mapping)
        self.assertIn(1, mapping)

    def test_map_labels_assigns_crash_for_high_vol_negative_return(self) -> None:
        self.assertEqual(self._map_labels(self._make_fake_model([[-0.08, 0.06, 0.0, 0.01]]))[0], "crash")

    def test_map_labels_assigns_bull_for_positive_return_low_vol(self) -> None:
        self.assertEqual(self._map_labels(self._make_fake_model([[0.03, 0.01, 0.0001, 0.01]]))[0], "bull")

    def test_map_labels_assigns_bear_for_negative_return_low_vol(self) -> None:
        self.assertEqual(self._map_labels(self._make_fake_model([[-0.03, 0.01, -0.0001, 0.01]]))[0], "bear")

    def test_map_labels_assigns_liquidity_stress_for_high_funding(self) -> None:
        self.assertEqual(self._map_labels(self._make_fake_model([[0.01, 0.02, 0.02, 0.01]]))[0], "liquidity_stress")

    def test_map_labels_all_values_are_valid_regime_names(self) -> None:
        mapping = self._map_labels(
            self._make_fake_model(
                [
                    [0.06, 0.06, 0.015, 0.12],
                    [-0.07, 0.05, 0.0, 0.02],
                    [0.03, 0.02, 0.0003, 0.05],
                    [-0.03, 0.015, -0.001, 0.01],
                ]
            )
        )
        for label in mapping.values():
            self.assertIn(label, _VALID_LABELS)


class HmmFitPredictTests(unittest.TestCase):
    def _patch_fake_hmmlearn(self):
        return patch("engine.validation.hmm_regimes._require_hmmlearn", return_value=(_FakeGaussianHMM, _FakeNP))

    def test_fit_regime_model_returns_fitted_model(self) -> None:
        from engine.validation.hmm_regimes import fit_regime_model

        with self._patch_fake_hmmlearn():
            model = fit_regime_model(_make_snapshot(50, crash_at=25), n_states=4)
        self.assertIsNotNone(model)
        self.assertTrue(hasattr(model, "means_"))

    def test_predict_regimes_returns_correct_length(self) -> None:
        from engine.validation.hmm_regimes import fit_regime_model, predict_regimes

        snap = _make_snapshot(50, crash_at=25)
        with self._patch_fake_hmmlearn():
            model = fit_regime_model(snap, n_states=4)
            labels, posteriors = predict_regimes(model, snap)
        self.assertEqual(len(labels), len(snap.candles))
        self.assertEqual(len(posteriors), len(snap.candles))

    def test_predict_regimes_posteriors_sum_to_one(self) -> None:
        from engine.validation.hmm_regimes import fit_regime_model, predict_regimes

        snap = _make_snapshot(50, crash_at=25)
        with self._patch_fake_hmmlearn():
            model = fit_regime_model(snap, n_states=4)
            _, posteriors = predict_regimes(model, snap)
        for row in posteriors:
            self.assertAlmostEqual(sum(row), 1.0, places=6)

    def test_fit_raises_for_too_short_snapshot(self) -> None:
        from engine.validation.hmm_regimes import fit_regime_model

        with self._patch_fake_hmmlearn():
            with self.assertRaises(ValueError):
                fit_regime_model(_make_snapshot(4), n_states=4)


if __name__ == "__main__":
    unittest.main()
