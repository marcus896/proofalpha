import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import DataSnapshot
from engine.data.schema import Candle
from engine.validation.regimes import (
    analyze_regimes,
    analyze_regimes_bocpd,
    analyze_regimes_hsmm,
    analyze_regimes_model,
    derive_regime_state,
    estimate_bocpd_changepoint_probabilities,
    label_snapshot_regimes_hsmm,
)


def _snapshot_with_regimes() -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    closes = [
        100.0, 102.0, 104.0, 106.0, 108.0, 110.0,
        110.5, 110.2, 110.4, 110.3, 110.5, 110.4,
        108.0, 106.0, 104.0, 102.0, 100.0, 98.0,
        95.0, 90.0, 82.0, 74.0,
        73.0, 72.0, 71.5, 71.0,
        72.0, 76.0, 82.0, 89.0,
    ]
    candles = [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=close - 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=1_000.0 + index,
        )
        for index, close in enumerate(closes)
    ]
    funding_rates = (
        [0.001] * 6
        + [0.0] * 6
        + [-0.003] * 6
        + [-0.02, -0.03, -0.035, -0.04]
        + [0.025, 0.03, 0.028, 0.027]
        + [0.02, 0.03, 0.04, 0.045]
    )
    open_interest = (
        [100.0, 102.0, 104.0, 106.0, 108.0, 110.0]
        + [111.0, 111.5, 111.0, 111.2, 111.1, 111.0]
        + [109.0, 108.0, 107.0, 106.0, 105.0, 104.0]
        + [102.0, 95.0, 88.0, 80.0]
        + [95.0, 110.0, 126.0, 145.0]
        + [150.0, 162.0, 175.0, 190.0]
    )
    liquidation_notional = (
        [5.0] * 18
        + [20.0, 30.0, 180.0, 240.0]
        + [260.0, 280.0, 220.0, 210.0]
        + [180.0, 240.0, 320.0, 400.0]
    )
    return DataSnapshot(
        snapshot_id="regime-snap",
        symbol="SOLUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=funding_rates,
        open_interest=open_interest,
        liquidation_notional=liquidation_notional,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        quality_flags=[],
    )


class RegimeAnalysisTests(unittest.TestCase):
    def test_analyze_regimes_detects_multiple_regime_families(self) -> None:
        analysis = analyze_regimes(_snapshot_with_regimes())

        labels = set(analysis.regime_labels)
        self.assertIn("bull", labels)
        self.assertIn("sideways", labels)
        self.assertIn("bear", labels)
        self.assertIn("crash", labels)
        self.assertIn("liquidity_stress", labels)
        self.assertIn("short_squeeze", labels)

    def test_analyze_regimes_builds_named_crisis_windows_and_coverage(self) -> None:
        analysis = analyze_regimes(_snapshot_with_regimes())

        crisis_window_names = [window.name for window in analysis.crisis_windows]
        self.assertIn("crash-1", crisis_window_names)
        self.assertIn("liquidity-stress-1", crisis_window_names)
        self.assertIn("short-squeeze-1", crisis_window_names)
        self.assertAlmostEqual(sum(analysis.regime_coverage.values()), 1.0, places=6)
        self.assertGreater(analysis.crisis_window_coverage["crash"], 0.0)
        self.assertGreater(analysis.crisis_window_coverage["liquidity_stress"], 0.0)
        self.assertGreater(analysis.crisis_window_coverage["short_squeeze"], 0.0)

    def test_analyze_regimes_hsmm_is_duration_aware_and_keeps_metadata(self) -> None:
        analysis = analyze_regimes_hsmm(_snapshot_with_regimes(), n_states=4, min_duration=3)

        self.assertEqual(analysis.model_name, "hsmm")
        self.assertEqual(len(analysis.regime_labels), len(_snapshot_with_regimes().candles))
        self.assertTrue(analysis.metadata["duration_aware"])
        self.assertIn("regime_state_key", analysis.metadata)

    def test_label_snapshot_regimes_hsmm_smooths_single_bar_noise(self) -> None:
        labels = label_snapshot_regimes_hsmm(_snapshot_with_regimes(), n_states=4, min_duration=3)

        for index in range(1, len(labels) - 1):
            self.assertFalse(labels[index - 1] == labels[index + 1] != labels[index])

    def test_analyze_regimes_bocpd_marks_changepoint_metadata(self) -> None:
        analysis = analyze_regimes_bocpd(_snapshot_with_regimes(), hazard=0.05)

        self.assertEqual(analysis.model_name, "bocpd")
        self.assertEqual(len(analysis.regime_labels), len(_snapshot_with_regimes().candles))
        self.assertTrue(analysis.metadata["online_changepoint"])
        self.assertIn("top_changepoints", analysis.metadata)

    def test_bocpd_probabilities_spike_on_large_market_shift(self) -> None:
        probabilities = estimate_bocpd_changepoint_probabilities(_snapshot_with_regimes(), hazard=0.05)

        self.assertEqual(len(probabilities), len(_snapshot_with_regimes().candles))
        self.assertGreater(max(probabilities), 0.5)

    def test_analyze_regimes_model_dispatches_phase2_models(self) -> None:
        self.assertEqual(analyze_regimes_model(_snapshot_with_regimes(), model_name="hsmm").model_name, "hsmm")
        self.assertEqual(analyze_regimes_model(_snapshot_with_regimes(), model_name="bocpd").model_name, "bocpd")

    def test_derive_regime_state_captures_funding_vol_and_oi_buckets(self) -> None:
        state = derive_regime_state(_snapshot_with_regimes())

        self.assertIn("funding_bucket", state)
        self.assertIn("volatility_bucket", state)
        self.assertIn("open_interest_bucket", state)
        self.assertIn("|", state["regime_state_key"])


if __name__ == "__main__":
    unittest.main()
