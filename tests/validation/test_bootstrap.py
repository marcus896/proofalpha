import unittest
from datetime import UTC, datetime, timedelta

from engine.data.schema import Candle
from engine.validation.bootstrap import (
    bootstrap_indices_for_method,
    dependent_wild_bootstrap_snapshot,
    dependent_wild_bootstrap_weights,
    moving_block_bootstrap,
    moving_block_bootstrap_indices,
    stationary_block_bootstrap_indices,
)


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_preserves_length_and_uses_real_blocks(self) -> None:
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(timestamp=base_time + timedelta(hours=index), open=float(index), high=float(index), low=float(index), close=float(index), volume=100.0)
            for index in range(20)
        ]

        resampled = moving_block_bootstrap(candles, block_size=4, seed=11)

        self.assertEqual(len(resampled), len(candles))
        first_block = [candle.close for candle in resampled[:4]]
        self.assertIn(first_block, [[float(start + offset) for offset in range(4)] for start in range(17)])

    def test_bootstrap_indices_can_resample_sidecars_in_lockstep(self) -> None:
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(timestamp=base_time + timedelta(hours=index), open=float(index), high=float(index), low=float(index), close=float(index), volume=100.0)
            for index in range(20)
        ]
        funding_rates = [round(index / 1000.0, 4) for index in range(20)]

        indices = moving_block_bootstrap_indices(len(candles), block_size=4, seed=11)
        resampled = moving_block_bootstrap(candles, block_size=4, seed=11)
        resampled_funding = [funding_rates[index] for index in indices]

        self.assertEqual(len(indices), len(candles))
        self.assertEqual([candle.close for candle in resampled], [float(index) for index in indices])
        self.assertEqual(resampled_funding, [round(candle.close / 1000.0, 4) for candle in resampled])

    def test_stationary_bootstrap_is_seeded_and_preserves_length(self) -> None:
        first = stationary_block_bootstrap_indices(sample_count=20, block_size=4, seed=11)
        second = stationary_block_bootstrap_indices(sample_count=20, block_size=4, seed=11)
        moving = moving_block_bootstrap_indices(sample_count=20, block_size=4, seed=11)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 20)
        self.assertNotEqual(first, moving)
        self.assertTrue(all(0 <= index < 20 for index in first))

    def test_bootstrap_method_dispatch_rejects_unknown_method(self) -> None:
        indices = bootstrap_indices_for_method(
            method="stationary_block",
            sample_count=20,
            block_size=4,
            seed=11,
        )

        self.assertEqual(len(indices), 20)
        with self.assertRaisesRegex(ValueError, "unsupported bootstrap method"):
            bootstrap_indices_for_method(
                method="unknown_method",
                sample_count=20,
                block_size=4,
                seed=11,
            )

    def test_dependent_wild_weights_are_seeded_and_locally_persistent(self) -> None:
        first = dependent_wild_bootstrap_weights(sample_count=30, block_size=6, seed=19)
        second = dependent_wild_bootstrap_weights(sample_count=30, block_size=6, seed=19)
        other = dependent_wild_bootstrap_weights(sample_count=30, block_size=6, seed=20)

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 30)
        self.assertGreater(sum(1 for left, right in zip(first, first[1:]) if left * right > 0.0), 12)

    def test_dependent_wild_dispatch_is_first_class_shape_preserving_method(self) -> None:
        indices = bootstrap_indices_for_method(
            method="dependent_wild",
            sample_count=12,
            block_size=4,
            seed=7,
        )

        self.assertEqual(indices, list(range(12)))


class MultivariateBootstrapTests(unittest.TestCase):
    """Phase 12 — multivariate_block bootstrap preserves cross-series correlation."""

    def _make_snapshot(self, n: int = 20) -> "DataSnapshot":
        from engine.config.models import DataSnapshot as DS
        from datetime import UTC, datetime, timedelta
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(
                timestamp=start + timedelta(hours=i),
                open=float(i), high=float(i) + 0.5,
                low=float(i) - 0.5, close=float(i), volume=100.0,
            )
            for i in range(n)
        ]
        funding = [round(i * 0.0001, 6) for i in range(n)]
        oi = [1_000.0 + i * 10 for i in range(n)]
        liq = [float(i) * 5 for i in range(n)]
        return DS(
            snapshot_id="mv-snap",
            symbol="BTCUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=funding,
            open_interest=oi,
            liquidation_notional=liq,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            spread_bps=[1.0 + (i * 0.1) for i in range(n)],
            depth_bid_1bp_usd=[1_000_000.0 + (i * 1_000.0) for i in range(n)],
            depth_ask_1bp_usd=[1_100_000.0 + (i * 1_000.0) for i in range(n)],
            latency_proxy_ms=[10.0 + i for i in range(n)],
            quality_flags=[],
        )

    def test_multivariate_indices_correct_length(self) -> None:
        from engine.validation.bootstrap import multivariate_block_bootstrap_indices
        indices = multivariate_block_bootstrap_indices(sample_count=20, block_size=4, seed=7)
        self.assertEqual(len(indices), 20)
        self.assertTrue(all(0 <= i < 20 for i in indices))

    def test_multivariate_indices_seeded_reproducible(self) -> None:
        from engine.validation.bootstrap import multivariate_block_bootstrap_indices
        a = multivariate_block_bootstrap_indices(20, block_size=4, seed=42)
        b = multivariate_block_bootstrap_indices(20, block_size=4, seed=42)
        self.assertEqual(a, b)

    def test_multivariate_indices_different_seeds_differ(self) -> None:
        from engine.validation.bootstrap import multivariate_block_bootstrap_indices
        a = multivariate_block_bootstrap_indices(20, block_size=4, seed=1)
        b = multivariate_block_bootstrap_indices(20, block_size=4, seed=2)
        self.assertNotEqual(a, b)

    def test_multivariate_bootstrap_returns_datasnapshot(self) -> None:
        from engine.config.models import DataSnapshot as DS
        from engine.validation.bootstrap import multivariate_block_bootstrap
        snap = self._make_snapshot(20)
        result = multivariate_block_bootstrap(snap, block_size=4, seed=5)
        self.assertIsInstance(result, DS)
        self.assertEqual(len(result.candles), 20)

    def test_multivariate_bootstrap_preserves_paired_structure(self) -> None:
        """The (close, funding) pair at each output bar should match the original pair at the same source index."""
        from engine.validation.bootstrap import multivariate_block_bootstrap, multivariate_block_bootstrap_indices
        snap = self._make_snapshot(20)
        indices = multivariate_block_bootstrap_indices(20, block_size=4, seed=99)
        result = multivariate_block_bootstrap(snap, block_size=4, seed=99)
        for out_bar, src_idx in enumerate(indices):
            self.assertAlmostEqual(result.candles[out_bar].close, snap.candles[src_idx].close)
            self.assertAlmostEqual(result.funding_rates[out_bar], snap.funding_rates[src_idx])
            self.assertAlmostEqual(result.open_interest[out_bar], snap.open_interest[src_idx])
            self.assertAlmostEqual(result.liquidation_notional[out_bar], snap.liquidation_notional[src_idx])

    def test_multivariate_bootstrap_resamples_typed_microstructure_in_lockstep(self) -> None:
        from engine.validation.bootstrap import multivariate_block_bootstrap, multivariate_block_bootstrap_indices

        snap = self._make_snapshot(20)
        indices = multivariate_block_bootstrap_indices(20, block_size=4, seed=13)
        result = multivariate_block_bootstrap(snap, block_size=4, seed=13)

        self.assertEqual(result.spread_bps, [snap.spread_bps[index] for index in indices])
        self.assertEqual(result.depth_bid_1bp_usd, [snap.depth_bid_1bp_usd[index] for index in indices])
        self.assertEqual(result.depth_ask_1bp_usd, [snap.depth_ask_1bp_usd[index] for index in indices])
        self.assertEqual(result.latency_proxy_ms, [snap.latency_proxy_ms[index] for index in indices])

    def test_multivariate_bootstrap_dispatches_via_method_string(self) -> None:
        from engine.validation.bootstrap import bootstrap_indices_for_method
        indices = bootstrap_indices_for_method("multivariate_block", sample_count=20, block_size=4, seed=3)
        self.assertEqual(len(indices), 20)

    def test_multivariate_block_is_in_supported_methods(self) -> None:
        from engine.validation.bootstrap import SUPPORTED_BOOTSTRAP_METHODS
        self.assertIn("multivariate_block", SUPPORTED_BOOTSTRAP_METHODS)

    def test_multivariate_bootstrap_snapshot_id_encodes_seed(self) -> None:
        from engine.validation.bootstrap import multivariate_block_bootstrap
        snap = self._make_snapshot(20)
        result = multivariate_block_bootstrap(snap, block_size=4, seed=77)
        self.assertIn("mv_bootstrap", result.snapshot_id)
        self.assertIn("77", result.snapshot_id)

    def test_dependent_wild_bootstrap_snapshot_keeps_sidecars_aligned_without_reordering(self) -> None:
        snap = self._make_snapshot(20)
        result = dependent_wild_bootstrap_snapshot(snap, block_size=4, seed=77)

        self.assertEqual(len(result.candles), len(snap.candles))
        self.assertEqual([candle.timestamp for candle in result.candles], [candle.timestamp for candle in snap.candles])
        self.assertNotEqual([candle.close for candle in result.candles], [candle.close for candle in snap.candles])
        self.assertEqual(len(result.funding_rates), len(snap.funding_rates))
        self.assertEqual(len(result.open_interest), len(snap.open_interest))
        self.assertTrue(all(value >= 0.0 for value in result.open_interest))
        self.assertEqual(result.provenance["transformation"], "dependent_wild_bootstrap")


if __name__ == "__main__":
    unittest.main()
