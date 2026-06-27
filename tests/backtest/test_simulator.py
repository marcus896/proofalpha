import unittest
from datetime import UTC, datetime, timedelta

from engine.backtest.simulator import _resolve_execution_fill_ratio, simulate_strategy
from engine.config.models import DataSnapshot, VenueProfile
from engine.data.schema import Candle


def _snapshot() -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(timestamp=start + timedelta(hours=index), open=100 + index, high=101 + index, low=99 + index, close=100 + index, volume=1_000.0)
        for index in range(6)
    ]
    return DataSnapshot(
        snapshot_id="snap-1",
        symbol="SOLUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=[0.0, 0.0001, 0.0001, 0.0, 0.0, 0.0],
        open_interest=[100.0] * 6,
        liquidation_notional=[0.0] * 6,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        quality_flags=[],
    )


class SimulatorTests(unittest.TestCase):
    def test_resolve_execution_fill_ratio_returns_partial_fill_under_thin_depth(self) -> None:
        fill_ratio = _resolve_execution_fill_ratio(
            trade_notional=500.0,
            bar_index=2,
            use_realistic_slippage=True,
            microstructure={
                "spread_bps": [2.0, 2.0, 2.0],
                "depth_bid_1bp_usd": [5_000.0, 5_000.0, 125.0],
                "depth_ask_1bp_usd": [5_000.0, 5_000.0, 125.0],
                "latency_proxy_ms": [10.0, 10.0, 10.0],
            },
            oi_stressed=[False, False, True],
            funding_z=[0.0, 0.0, 2.5],
            liquidation_z=[0.0, 0.0, 2.5],
            depth_depleted=[False, False, True],
        )

        self.assertGreater(fill_ratio, 0.0)
        self.assertLess(fill_ratio, 1.0)

    def test_simulator_realistic_slippage_reduces_position_size_when_depth_is_thin(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(
                timestamp=start + timedelta(hours=index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.0 + index,
                volume=1_000.0,
            )
            for index in range(6)
        ]
        deep_snapshot = DataSnapshot(
            snapshot_id="deep-depth-fill",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[0.0] * 6,
            spread_bps=[2.0] * 6,
            depth_bid_1bp_usd=[10_000.0] * 6,
            depth_ask_1bp_usd=[10_000.0] * 6,
            latency_proxy_ms=[10.0] * 6,
            maker_fee_bps=0.0,
            taker_fee_bps=0.0,
            quality_flags=[],
        )
        thin_snapshot = DataSnapshot(
            snapshot_id="thin-depth-fill",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[0.0] * 6,
            spread_bps=[2.0] * 6,
            depth_bid_1bp_usd=[120.0] * 6,
            depth_ask_1bp_usd=[120.0] * 6,
            latency_proxy_ms=[10.0] * 6,
            maker_fee_bps=0.0,
            taker_fee_bps=0.0,
            quality_flags=[],
        )

        deep_result = simulate_strategy(
            snapshot=deep_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            slippage_bps=0.0,
            slippage_model="realistic",
        )
        thin_result = simulate_strategy(
            snapshot=thin_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            slippage_bps=0.0,
            slippage_model="realistic",
        )

        self.assertGreater(deep_result.gross_pnl, thin_result.gross_pnl)
        self.assertGreater(deep_result.net_pnl, thin_result.net_pnl)
        self.assertEqual(deep_result.execution_pressure_summary["partial_fill_event_count"], 0)
        self.assertGreater(thin_result.execution_pressure_summary["partial_fill_event_count"], 0)
        self.assertLess(thin_result.execution_pressure_summary["average_fill_ratio"], 1.0)

    def test_simulator_scales_entry_fee_with_leverage(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(timestamp=start + timedelta(hours=index), open=100.0, high=100.0, low=100.0, close=100.0, volume=1_000.0)
            for index in range(4)
        ]
        snapshot = DataSnapshot(
            snapshot_id="leveraged-fee-snap",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * 4,
            open_interest=[100.0] * 4,
            liquidation_notional=[0.0] * 4,
            maker_fee_bps=0.0,
            taker_fee_bps=100.0,
            quality_flags=[],
        )

        result = simulate_strategy(
            snapshot=snapshot,
            entry_signals=[False, True, False, False],
            exit_signals=[False, False, True, False],
            position_leverage=5.0,
        )

        self.assertAlmostEqual(result.fee_spend, 10.0, places=8)
        self.assertAlmostEqual(result.net_pnl, -10.0, places=8)

    def test_simulator_exit_bar_equity_matches_net_pnl(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(timestamp=start + timedelta(hours=index), open=price, high=price, low=price, close=price, volume=1_000.0)
            for index, price in enumerate([100.0, 100.0, 110.0, 110.0])
        ]
        snapshot = DataSnapshot(
            snapshot_id="equity-exit-snap",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * 4,
            open_interest=[100.0] * 4,
            liquidation_notional=[0.0] * 4,
            maker_fee_bps=0.0,
            taker_fee_bps=0.0,
            quality_flags=[],
        )

        result = simulate_strategy(
            snapshot=snapshot,
            entry_signals=[False, True, False, False],
            exit_signals=[False, False, True, False],
        )

        self.assertAlmostEqual(result.net_pnl, 10.0, places=8)
        self.assertAlmostEqual(result.equity_curve[-1], result.net_pnl, places=8)

    def test_simulator_nets_fees_and_funding_into_pnl(self) -> None:
        result = simulate_strategy(
            snapshot=_snapshot(),
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            slippage_bps=10.0,
            latency_bars=0,
        )

        self.assertEqual(result.trade_count, 1)
        self.assertGreater(result.gross_pnl, result.net_pnl)
        self.assertGreater(result.fee_spend, 0.0)
        self.assertGreaterEqual(result.funding_spend, 0.0)
        self.assertLess(result.max_drawdown, 0.0)

    def test_simulator_applies_funding_direction_by_position_side(self) -> None:
        start = datetime(2024, 1, 1, 7, 0, tzinfo=UTC)
        candles = [
            Candle(timestamp=start + timedelta(hours=index), open=100.0, high=100.0, low=100.0, close=100.0, volume=1_000.0)
            for index in range(11)
        ]
        snapshot = DataSnapshot(
            snapshot_id="funding-side-snap",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0001] * 11,
            open_interest=[100.0] * 11,
            liquidation_notional=[0.0] * 11,
            maker_fee_bps=0.0,
            taker_fee_bps=0.0,
            quality_flags=[],
        )

        long_result = simulate_strategy(
            snapshot=snapshot,
            entry_signals=[True] + ([False] * 10),
            exit_signals=([False] * 10) + [True],
            position_side="long",
        )
        short_result = simulate_strategy(
            snapshot=snapshot,
            entry_signals=[True] + ([False] * 10),
            exit_signals=([False] * 10) + [True],
            position_side="short",
        )

        self.assertGreater(long_result.funding_spend, 0.0)
        self.assertLess(short_result.funding_spend, 0.0)
        self.assertLess(long_result.net_pnl, 0.0)
        self.assertGreater(short_result.net_pnl, 0.0)
        self.assertAlmostEqual(long_result.funding_spend, -short_result.funding_spend, places=8)

    def test_simulator_applies_funding_only_on_settlement_bars(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(timestamp=start + timedelta(hours=index), open=100.0, high=100.0, low=100.0, close=100.0, volume=1_000.0)
            for index in range(10)
        ]
        snapshot = DataSnapshot(
            snapshot_id="funding-settlement-snap",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.01] * 10,
            open_interest=[100.0] * 10,
            liquidation_notional=[0.0] * 10,
            maker_fee_bps=0.0,
            taker_fee_bps=0.0,
            quality_flags=[],
        )

        result = simulate_strategy(
            snapshot=snapshot,
            entry_signals=[True] + ([False] * 9),
            exit_signals=([False] * 9) + [True],
        )

        self.assertAlmostEqual(result.funding_spend, 1.0, places=8)

    def test_simulator_records_liquidation_when_low_crosses_threshold(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        result = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
        )

        self.assertEqual(result.trade_count, 1)
        self.assertEqual(result.win_rate, 0.0)
        self.assertEqual(len(result.liquidation_events), 1)
        self.assertIn("liquidation@", result.liquidation_events[0])
        self.assertLess(result.net_pnl, 0.0)

    def test_simulator_applies_liquidation_fee_bps_on_forced_exit(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        without_liquidation_fee = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
        )
        with_liquidation_fee = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=100.0,
        )

        self.assertLess(with_liquidation_fee.net_pnl, without_liquidation_fee.net_pnl)
        self.assertGreater(with_liquidation_fee.fee_spend, without_liquidation_fee.fee_spend)

    def test_simulator_can_use_mark_price_proxy_instead_of_raw_wick_for_liquidation(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        wick_triggered = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=0.0,
        )
        mark_smoothed = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=1.0,
        )

        self.assertEqual(len(wick_triggered.liquidation_events), 1)
        self.assertEqual(mark_smoothed.liquidation_events, [])
        self.assertGreater(mark_smoothed.net_pnl, wick_triggered.net_pnl)

    def test_simulator_can_partially_liquidate_and_keep_remainder_open(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_candles[4] = Candle(
            timestamp=liquidation_candles[4].timestamp,
            open=104.0,
            high=110.0,
            low=103.0,
            close=109.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        full_liquidation = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, True, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            partial_liquidation_ratio=1.0,
        )
        partial_liquidation = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            partial_liquidation_ratio=0.5,
        )

        self.assertEqual(len(partial_liquidation.liquidation_events), 1)
        self.assertIn("size=2.5000", partial_liquidation.liquidation_events[0])
        self.assertEqual(partial_liquidation.trade_count, 2)
        self.assertGreater(partial_liquidation.net_pnl, full_liquidation.net_pnl)

    def test_simulator_respects_liquidation_cooldown_bars(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_candles[3] = Candle(
            timestamp=liquidation_candles[3].timestamp,
            open=103.0,
            high=104.0,
            low=79.0,
            close=100.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        without_cooldown = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            partial_liquidation_ratio=0.5,
            liquidation_cooldown_bars=0,
        )
        with_cooldown = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            partial_liquidation_ratio=0.5,
            liquidation_cooldown_bars=2,
        )

        self.assertEqual(len(without_cooldown.liquidation_events), 2)
        self.assertEqual(len(with_cooldown.liquidation_events), 1)
        self.assertGreater(with_cooldown.net_pnl, without_cooldown.net_pnl)

    def test_simulator_uses_liquidation_step_schedule_for_repeated_events(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_candles[3] = Candle(
            timestamp=liquidation_candles[3].timestamp,
            open=103.0,
            high=104.0,
            low=79.0,
            close=100.0,
            volume=1_000.0,
        )
        liquidation_candles[4] = Candle(
            timestamp=liquidation_candles[4].timestamp,
            open=104.0,
            high=105.0,
            low=78.0,
            close=99.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        scheduled = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, False, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_step_schedule=[0.25, 0.5, 1.0],
        )

        self.assertEqual(len(scheduled.liquidation_events), 3)
        self.assertIn("size=1.2500", scheduled.liquidation_events[0])   # 5.0 * 0.25
        self.assertIn("size=1.8750", scheduled.liquidation_events[1])   # 3.75 * 0.5
        self.assertIn("size=1.8750", scheduled.liquidation_events[2])   # 1.875 * 1.0
        self.assertEqual(scheduled.trade_count, 3)

    def test_simulator_uses_tiered_liquidation_step_schedule_from_venue_profile(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_candles[3] = Candle(
            timestamp=liquidation_candles[3].timestamp,
            open=103.0,
            high=104.0,
            low=79.0,
            close=100.0,
            volume=1_000.0,
        )
        liquidation_candles[4] = Candle(
            timestamp=liquidation_candles[4].timestamp,
            open=104.0,
            high=105.0,
            low=78.0,
            close=99.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            venue_profile=VenueProfile(
                venue=snapshot.venue,
                liquidation_style="partial",
                maintenance_margin_schedule=[
                    {
                        "max_leverage": 10.0,
                        "maintenance_margin_ratio": 0.01,
                        "liquidation_step_schedule": [0.25, 0.5, 1.0],
                    },
                ],
            ),
        )

        scheduled = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, False, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
        )

        self.assertEqual(len(scheduled.liquidation_events), 3)
        self.assertIn("size=1.2500", scheduled.liquidation_events[0])
        self.assertIn("size=1.8750", scheduled.liquidation_events[1])
        self.assertIn("size=1.8750", scheduled.liquidation_events[2])

    def test_simulator_re_resolves_liquidation_step_schedule_after_notional_tier_change(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_candles[3] = Candle(
            timestamp=liquidation_candles[3].timestamp,
            open=103.0,
            high=104.0,
            low=79.0,
            close=100.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        scheduled = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, False, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            maintenance_margin_schedule=[
                {
                    "max_notional": 400.0,
                    "maintenance_margin_ratio": 0.01,
                    "liquidation_step_schedule": [1.0],
                },
                {
                    "max_notional": 600.0,
                    "maintenance_margin_ratio": 0.01,
                    "liquidation_step_schedule": [0.25],
                },
            ],
        )

        self.assertEqual(len(scheduled.liquidation_events), 2)
        self.assertIn("size=1.2500", scheduled.liquidation_events[0])
        self.assertIn("size=3.7500", scheduled.liquidation_events[1])

    def test_simulator_explicit_liquidation_step_schedule_overrides_tiered_schedule(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_candles[3] = Candle(
            timestamp=liquidation_candles[3].timestamp,
            open=103.0,
            high=104.0,
            low=79.0,
            close=100.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            venue_profile=VenueProfile(
                venue=snapshot.venue,
                liquidation_style="partial",
                maintenance_margin_schedule=[
                    {
                        "max_leverage": 10.0,
                        "maintenance_margin_ratio": 0.01,
                        "liquidation_step_schedule": [0.25],
                    },
                ],
            ),
        )

        explicit = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, False, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_step_schedule=[0.5, 1.0],
        )

        self.assertEqual(len(explicit.liquidation_events), 2)
        self.assertIn("size=2.5000", explicit.liquidation_events[0])
        self.assertIn("size=2.5000", explicit.liquidation_events[1])

    def test_simulator_can_trigger_liquidation_from_mark_price_premium(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=83.0,
            close=83.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        without_premium = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=1.0,
            liquidation_mark_premium_bps=0.0,
        )
        with_premium = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=1.0,
            liquidation_mark_premium_bps=150.0,
        )

        self.assertEqual(without_premium.liquidation_events, [])
        self.assertEqual(len(with_premium.liquidation_events), 1)
        self.assertLess(with_premium.net_pnl, without_premium.net_pnl)

    def test_simulator_uses_maintenance_margin_schedule_for_high_leverage(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=82.5,
            close=82.5,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        flat_margin = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=1.0,
        )
        scheduled_margin = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            maintenance_margin_schedule=[
                {"max_leverage": 3.0, "maintenance_margin_ratio": 0.01},
                {"max_leverage": 10.0, "maintenance_margin_ratio": 0.03},
            ],
            liquidation_mark_price_weight=1.0,
        )

        self.assertEqual(flat_margin.liquidation_events, [])
        self.assertEqual(len(scheduled_margin.liquidation_events), 1)
        self.assertLess(scheduled_margin.net_pnl, flat_margin.net_pnl)

    def test_simulator_uses_liquidation_fee_schedule_for_high_leverage(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        flat_fee = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
        )
        scheduled_fee = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_fee_schedule=[
                {"max_leverage": 3.0, "liquidation_fee_bps": 0.0},
                {"max_leverage": 10.0, "liquidation_fee_bps": 100.0},
            ],
        )

        self.assertEqual(len(flat_fee.liquidation_events), 1)
        self.assertEqual(len(scheduled_fee.liquidation_events), 1)
        self.assertGreater(scheduled_fee.fee_spend, flat_fee.fee_spend)
        self.assertLess(scheduled_fee.net_pnl, flat_fee.net_pnl)

    def test_simulator_supports_short_position_pnl(self) -> None:
        snapshot = _snapshot()

        result = simulate_strategy(
            snapshot=snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_side="short",
        )

        self.assertEqual(result.trade_count, 1)
        self.assertLess(result.gross_pnl, 0.0)
        self.assertLess(result.net_pnl, 0.0)

    def test_simulator_liquidates_short_when_price_rises_through_threshold(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=121.0,
            low=101.0,
            close=118.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        result = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_side="short",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=0.0,
        )

        self.assertEqual(result.trade_count, 1)
        self.assertEqual(len(result.liquidation_events), 1)
        self.assertIn("liquidation@", result.liquidation_events[0])
        self.assertLess(result.net_pnl, 0.0)

    def test_simulator_uses_venue_profile_liquidation_defaults_when_args_omitted(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_candles[4] = Candle(
            timestamp=liquidation_candles[4].timestamp,
            open=104.0,
            high=110.0,
            low=103.0,
            close=109.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            venue_profile=VenueProfile(
                venue=snapshot.venue,
                liquidation_style="partial",
                partial_liquidation_ratio=0.5,
                liquidation_cooldown_bars=2,
            ),
        )

        result = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
        )

        self.assertEqual(len(result.liquidation_events), 1)
        self.assertIn("size=2.5000", result.liquidation_events[0])
        self.assertEqual(result.trade_count, 2)

    def test_simulator_uses_full_liquidation_style_from_venue_profile(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_candles[4] = Candle(
            timestamp=liquidation_candles[4].timestamp,
            open=104.0,
            high=110.0,
            low=103.0,
            close=109.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            venue_profile=VenueProfile(
                venue=snapshot.venue,
                liquidation_style="full",
                partial_liquidation_ratio=0.5,
                liquidation_cooldown_bars=2,
            ),
        )

        result = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
        )

        self.assertEqual(len(result.liquidation_events), 1)
        self.assertIn("size=5.0000", result.liquidation_events[0])
        self.assertEqual(result.trade_count, 1)

    def test_simulator_explicit_partial_liquidation_ratio_overrides_full_venue_style(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_candles[4] = Candle(
            timestamp=liquidation_candles[4].timestamp,
            open=104.0,
            high=110.0,
            low=103.0,
            close=109.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            venue_profile=VenueProfile(
                venue=snapshot.venue,
                liquidation_style="full",
                partial_liquidation_ratio=1.0,
                liquidation_cooldown_bars=0,
            ),
        )

        result = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            partial_liquidation_ratio=0.5,
            liquidation_cooldown_bars=2,
        )

        self.assertEqual(len(result.liquidation_events), 1)
        self.assertIn("size=2.5000", result.liquidation_events[0])
        self.assertEqual(result.trade_count, 2)

    def test_simulator_explicit_liquidation_args_override_venue_profile_defaults(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            venue_profile=VenueProfile(
                venue=snapshot.venue,
                liquidation_mark_price_weight=1.0,
            ),
        )

        profile_default = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
        )
        explicit_override = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=0.0,
        )

        self.assertEqual(profile_default.liquidation_events, [])
        self.assertEqual(len(explicit_override.liquidation_events), 1)

    def test_simulator_uses_venue_profile_tier_schedules_when_args_omitted(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=82.5,
            close=82.5,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            venue_profile=VenueProfile(
                venue=snapshot.venue,
                liquidation_mark_price_weight=1.0,
                maintenance_margin_schedule=[
                    {"max_leverage": 3.0, "maintenance_margin_ratio": 0.01},
                    {"max_leverage": 10.0, "maintenance_margin_ratio": 0.03},
                ],
                liquidation_fee_schedule=[
                    {"max_leverage": 3.0, "liquidation_fee_bps": 0.0},
                    {"max_leverage": 10.0, "liquidation_fee_bps": 100.0},
                ],
            ),
        )

        profile_defaults = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
        )
        explicit_empty_override = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
        )

        self.assertEqual(len(profile_defaults.liquidation_events), 1)
        self.assertEqual(explicit_empty_override.liquidation_events, [])
        self.assertGreater(profile_defaults.fee_spend, explicit_empty_override.fee_spend)

    def test_simulator_uses_max_notional_tier_for_maintenance_margin_schedule(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=53.0,
            close=53.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        flat_margin = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=2.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=1.0,
        )
        scheduled_margin = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=2.0,
            maintenance_margin_ratio=0.01,
            maintenance_margin_schedule=[
                {"max_notional": 150.0, "maintenance_margin_ratio": 0.01},
                {"max_notional": 250.0, "maintenance_margin_ratio": 0.03},
            ],
            liquidation_mark_price_weight=1.0,
        )

        self.assertEqual(flat_margin.liquidation_events, [])
        self.assertEqual(len(scheduled_margin.liquidation_events), 1)
        self.assertLess(scheduled_margin.net_pnl, flat_margin.net_pnl)

    def test_simulator_uses_max_notional_tier_for_liquidation_fee_schedule(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        flat_fee = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
        )
        scheduled_fee = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_fee_schedule=[
                {"max_notional": 400.0, "liquidation_fee_bps": 0.0},
                {"max_notional": 600.0, "liquidation_fee_bps": 100.0},
            ],
        )

        self.assertEqual(len(flat_fee.liquidation_events), 1)
        self.assertEqual(len(scheduled_fee.liquidation_events), 1)
        self.assertGreater(scheduled_fee.fee_spend, flat_fee.fee_spend)
        self.assertLess(scheduled_fee.net_pnl, flat_fee.net_pnl)

    def test_simulator_without_venue_profile_matches_legacy_liquidation_defaults(self) -> None:
        snapshot = _snapshot()
        liquidation_candles = list(snapshot.candles)
        liquidation_candles[2] = Candle(
            timestamp=liquidation_candles[2].timestamp,
            open=102.0,
            high=103.0,
            low=80.0,
            close=101.0,
            volume=1_000.0,
        )
        liquidation_snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=liquidation_candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
        )

        implicit = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
        )
        explicit = simulate_strategy(
            snapshot=liquidation_snapshot,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_mark_price_weight=0.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
        )

        self.assertEqual(implicit.liquidation_events, explicit.liquidation_events)
        self.assertAlmostEqual(implicit.net_pnl, explicit.net_pnl)


class DynamicSlippageSimulatorTests(unittest.TestCase):
    """Phase 12 — slippage_model parameter on simulate_strategy."""

    def _snapshot_longer(self) -> DataSnapshot:
        """A 40-bar snapshot with realistic OI for dynamic slippage testing."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        n = 40
        closes = [100.0 + i * 0.5 for i in range(n)]
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
        return DataSnapshot(
            snapshot_id="snap-dynamic",
            symbol="BTCUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0001] * n,
            open_interest=[1_000_000.0] * n,
            liquidation_notional=[5_000.0] * n,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )

    def _snapshot_realistic(
        self,
        *,
        spread_bps: list[float] | None = None,
        depth_bid_1bp_usd: list[float] | None = None,
        depth_ask_1bp_usd: list[float] | None = None,
        latency_proxy_ms: list[float] | None = None,
        funding_rates: list[float] | None = None,
        open_interest: list[float] | None = None,
        liquidation_notional: list[float] | None = None,
    ) -> DataSnapshot:
        snapshot = self._snapshot_longer()
        n = len(snapshot.candles)
        return DataSnapshot(
            snapshot_id="snap-realistic",
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=snapshot.candles,
            funding_rates=funding_rates or [0.0001] * n,
            open_interest=open_interest or [1_000_000.0] * n,
            liquidation_notional=liquidation_notional or [5_000.0] * n,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            provenance={
                "microstructure": {
                    "spread_bps": spread_bps or [3.0] * n,
                    "depth_bid_1bp_usd": depth_bid_1bp_usd or [2_500_000.0] * n,
                    "depth_ask_1bp_usd": depth_ask_1bp_usd or [2_500_000.0] * n,
                    "latency_proxy_ms": latency_proxy_ms or [25.0] * n,
                }
            },
        )

    def test_omitting_slippage_model_equals_flat_default(self) -> None:
        snap = _snapshot()
        flat_explicit = simulate_strategy(
            snap,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            slippage_bps=10.0,
            slippage_model="flat",
        )
        flat_implicit = simulate_strategy(
            snap,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            slippage_bps=10.0,
        )
        self.assertAlmostEqual(flat_explicit.fee_spend, flat_implicit.fee_spend)
        self.assertAlmostEqual(flat_explicit.net_pnl, flat_implicit.net_pnl)
        self.assertAlmostEqual(flat_explicit.gross_pnl, flat_implicit.gross_pnl)

    def test_dynamic_slippage_model_does_not_raise(self) -> None:
        snap = self._snapshot_longer()
        n = len(snap.candles)
        entry = [False] * n
        exit_ = [False] * n
        entry[5] = True
        exit_[20] = True
        result = simulate_strategy(
            snap, entry, exit_,
            slippage_bps=5.0,
            slippage_model="dynamic",
        )
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.fee_spend, 0.0)

    def test_dynamic_slippage_produces_positive_fee_spend(self) -> None:
        snap = self._snapshot_longer()
        n = len(snap.candles)
        entry = [False] * n
        exit_ = [False] * n
        entry[5] = True
        exit_[20] = True
        result = simulate_strategy(
            snap, entry, exit_,
            slippage_bps=5.0,
            slippage_model="dynamic",
        )
        self.assertGreater(result.fee_spend, 0.0)

    def test_realistic_slippage_uses_depth_and_latency_inputs(self) -> None:
        low_cost_snapshot = self._snapshot_realistic(
            depth_bid_1bp_usd=[5_000_000.0] * 40,
            depth_ask_1bp_usd=[5_000_000.0] * 40,
            latency_proxy_ms=[10.0] * 40,
        )
        high_cost_snapshot = self._snapshot_realistic(
            depth_bid_1bp_usd=[120_000.0] * 40,
            depth_ask_1bp_usd=[120_000.0] * 40,
            latency_proxy_ms=[220.0] * 40,
        )
        entry = [False] * 40
        exit_ = [False] * 40
        entry[5] = True
        exit_[20] = True

        low_cost = simulate_strategy(
            low_cost_snapshot,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="realistic",
        )
        high_cost = simulate_strategy(
            high_cost_snapshot,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="realistic",
        )

        self.assertGreater(high_cost.fee_spend, low_cost.fee_spend)
        self.assertLess(high_cost.net_pnl, low_cost.net_pnl)

    def test_realistic_slippage_prefers_typed_microstructure_fields_over_provenance(self) -> None:
        snapshot = self._snapshot_longer()
        entry = [False] * 40
        exit_ = [False] * 40
        entry[5] = True
        exit_[20] = True
        typed_snapshot = DataSnapshot(
            snapshot_id="snap-typed-micro",
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=snapshot.candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            spread_bps=[2.0] * 40,
            depth_bid_1bp_usd=[4_000_000.0] * 40,
            depth_ask_1bp_usd=[4_000_000.0] * 40,
            latency_proxy_ms=[15.0] * 40,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            provenance={
                "microstructure": {
                    "spread_bps": [25.0] * 40,
                    "depth_bid_1bp_usd": [50_000.0] * 40,
                    "depth_ask_1bp_usd": [50_000.0] * 40,
                    "latency_proxy_ms": [300.0] * 40,
                }
            },
        )
        provenance_only_snapshot = DataSnapshot(
            snapshot_id="snap-provenance-micro",
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=snapshot.candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            quality_flags=snapshot.quality_flags,
            provenance=dict(typed_snapshot.provenance),
        )

        typed_result = simulate_strategy(
            typed_snapshot,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="realistic",
        )
        provenance_result = simulate_strategy(
            provenance_only_snapshot,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="realistic",
        )

        self.assertLess(typed_result.fee_spend, provenance_result.fee_spend)
        self.assertGreater(typed_result.net_pnl, provenance_result.net_pnl)

    def test_realistic_slippage_falls_back_to_dynamic_when_microstructure_missing(self) -> None:
        snap = self._snapshot_longer()
        entry = [False] * 40
        exit_ = [False] * 40
        entry[5] = True
        exit_[20] = True

        dynamic_result = simulate_strategy(
            snap,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="dynamic",
        )
        realistic_result = simulate_strategy(
            snap,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="realistic",
        )

        self.assertAlmostEqual(realistic_result.fee_spend, dynamic_result.fee_spend)
        self.assertAlmostEqual(realistic_result.net_pnl, dynamic_result.net_pnl)

    def test_realistic_slippage_widens_under_cascade_signals(self) -> None:
        baseline_snapshot = self._snapshot_realistic()
        stressed_snapshot = self._snapshot_realistic(
            funding_rates=([0.0001] * 5) + ([0.02] * 16) + ([0.0001] * 19),
            open_interest=([1_000_000.0] * 5) + ([5_000_000.0] * 16) + ([1_000_000.0] * 19),
            liquidation_notional=([5_000.0] * 5) + ([250_000.0] * 16) + ([5_000.0] * 19),
            depth_bid_1bp_usd=([2_500_000.0] * 5) + ([200_000.0] * 16) + ([2_500_000.0] * 19),
            depth_ask_1bp_usd=([2_500_000.0] * 5) + ([200_000.0] * 16) + ([2_500_000.0] * 19),
        )
        entry = [False] * 40
        exit_ = [False] * 40
        entry[5] = True
        exit_[20] = True

        baseline = simulate_strategy(
            baseline_snapshot,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="realistic",
        )
        stressed = simulate_strategy(
            stressed_snapshot,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="realistic",
        )

        # Under the corrected fee model, adverse-fill slippage is embedded in
        # the fill price (worse execution), not double-charged via fee_spend.
        # The net_pnl comparison captures the full execution cost difference.
        self.assertLess(stressed.net_pnl, baseline.net_pnl)

    def test_realistic_slippage_tracks_adverse_fill_pressure_under_stress(self) -> None:
        baseline_snapshot = self._snapshot_realistic(
            depth_bid_1bp_usd=[2_500_000.0] * 40,
            depth_ask_1bp_usd=[2_500_000.0] * 40,
            latency_proxy_ms=[25.0] * 40,
        )
        stressed_snapshot = self._snapshot_realistic(
            funding_rates=([0.0001] * 5) + ([0.02] * 16) + ([0.0001] * 19),
            open_interest=([1_000_000.0] * 5) + ([5_000_000.0] * 16) + ([1_000_000.0] * 19),
            liquidation_notional=([5_000.0] * 5) + ([250_000.0] * 16) + ([5_000.0] * 19),
            depth_bid_1bp_usd=([2_500_000.0] * 5) + ([120.0] * 16) + ([2_500_000.0] * 19),
            depth_ask_1bp_usd=([2_500_000.0] * 5) + ([120.0] * 16) + ([2_500_000.0] * 19),
            latency_proxy_ms=([25.0] * 5) + ([220.0] * 16) + ([25.0] * 19),
        )
        entry = [False] * 40
        exit_ = [False] * 40
        entry[5] = True
        exit_[20] = True

        baseline = simulate_strategy(
            baseline_snapshot,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="realistic",
        )
        stressed = simulate_strategy(
            stressed_snapshot,
            entry,
            exit_,
            slippage_bps=5.0,
            slippage_model="realistic",
        )

        self.assertEqual(baseline.execution_pressure_summary.get("adverse_fill_event_count", 0), 0)
        self.assertGreater(stressed.execution_pressure_summary["adverse_fill_event_count"], 0)
        self.assertGreater(stressed.execution_pressure_summary["average_adverse_fill_bps"], 0.0)
        self.assertGreaterEqual(
            stressed.execution_pressure_summary["max_adverse_fill_bps"],
            stressed.execution_pressure_summary["average_adverse_fill_bps"],
        )
        self.assertLess(stressed.net_pnl, baseline.net_pnl)

    def test_flat_slippage_zero_bps_produces_only_taker_fee(self) -> None:
        snap = _snapshot()
        result = simulate_strategy(
            snap,
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            slippage_bps=0.0,
            slippage_model="flat",
        )
        # With 0 slippage only taker fee applies
        expected_entry = snap.taker_fee_bps / 10_000.0 * snap.candles[1].close
        self.assertAlmostEqual(result.fee_spend, expected_entry * 2, delta=expected_entry * 0.05)

    def test_existing_simulator_tests_still_pass_with_default_slippage_model(self) -> None:
        """Regression guard: referencing the main test to ensure the default path is stable."""
        result = simulate_strategy(
            snapshot=_snapshot(),
            entry_signals=[False, True, False, False, False, False],
            exit_signals=[False, False, False, False, True, False],
            slippage_bps=10.0,
            latency_bars=0,
        )
        self.assertEqual(result.trade_count, 1)
        self.assertGreater(result.gross_pnl, result.net_pnl)


if __name__ == "__main__":
    unittest.main()
