import unittest
from datetime import UTC, datetime
from pathlib import Path
import shutil

from engine.config.models import DataSnapshot, SnapshotQualityReport, VenueProfile
from engine.data.schema import Candle
from engine.data.storage import list_stored_snapshots, load_snapshot, store_snapshot


class SnapshotStorageTests(unittest.TestCase):
    def test_store_snapshot_round_trips_duckdb_and_parquet(self) -> None:
        snapshot = DataSnapshot(
            snapshot_id="phase1-store",
            symbol="BTCUSDT",
            venue="binance",
            timeframe="1h",
            contract_type="perpetual",
            candles=[
                Candle(
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.5,
                    volume=1000.0,
                    trade_count=9,
                ),
                Candle(
                    timestamp=datetime(2024, 1, 1, 1, tzinfo=UTC),
                    open=100.5,
                    high=102.0,
                    low=100.0,
                    close=101.5,
                    volume=1100.0,
                    trade_count=11,
                ),
            ],
            funding_rates=[0.0001, 0.0002],
            open_interest=[2000.0, 2100.0],
            liquidation_notional=[40.0, 60.0],
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            mark_price=[100.4, 101.4],
            index_price=[100.3, 101.3],
            next_funding_ts=[
                datetime(2024, 1, 1, 8, tzinfo=UTC).isoformat(),
                datetime(2024, 1, 1, 9, tzinfo=UTC).isoformat(),
            ],
            open_interest_usd=[201000.0, 213150.0],
            basis_bps=[9.97, 9.87],
            liq_long_usd=[25.0, 35.0],
            liq_short_usd=[15.0, 25.0],
            spread_bps=[3.5, 3.8],
            depth_bid_1bp_usd=[1500000.0, 1400000.0],
            depth_ask_1bp_usd=[1450000.0, 1350000.0],
            latency_proxy_ms=[18.0, 22.0],
            ret_1=[0.0, (101.5 / 100.5) - 1.0],
            ret_24=[0.0, 0.0],
            rv_24h=[0.0, 0.01],
            funding_z=[-1.0, 1.0],
            d_oi=[0.0, 100.0],
            d_oi_z=[-1.0, 1.0],
            liq_intensity_z=[-1.0, 1.0],
            vol_regime=["low", "high"],
            regime_id=["calm", "stress"],
            regime_probabilities=[{"calm": 1.0}, {"stress": 1.0}],
            quality_flags=["phase1"],
            venue_profile=VenueProfile(
                venue="binance",
                contract_type="perpetual",
                funding_interval_h=8,
                liquidation_style="partial",
                partial_liquidation_ratio=0.5,
            ),
            quality_report=SnapshotQualityReport(
                report_id="phase1-store:quality",
                snapshot_id="phase1-store",
                quality_score=0.99,
                passed=True,
                metrics={"candle_count": 2},
                source_checks={"build_version": "phase1_snapshot_builder_v1"},
            ),
            provenance={"build_version": "phase1_snapshot_builder_v1", "source_hash": "abc123"},
        )

        root = Path("test-phase1-storage")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        try:
            stored_paths = store_snapshot(snapshot, root)

            self.assertTrue(stored_paths["duckdb_path"].exists())
            self.assertTrue(stored_paths["parquet_path"].exists())

            loaded = load_snapshot("phase1-store", root)
            listing = list_stored_snapshots(root)
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertEqual(loaded.snapshot_id, snapshot.snapshot_id)
        self.assertEqual(loaded.contract_type, "perpetual")
        self.assertEqual([candle.trade_count for candle in loaded.candles], [9, 11])
        self.assertEqual(loaded.mark_price, [100.4, 101.4])
        self.assertEqual(loaded.index_price, [100.3, 101.3])
        self.assertEqual(loaded.open_interest_usd, [201000.0, 213150.0])
        self.assertEqual(loaded.regime_probabilities, [{"calm": 1.0}, {"stress": 1.0}])
        self.assertEqual(loaded.quality_report.report_id, "phase1-store:quality")
        self.assertEqual(loaded.provenance["build_version"], "phase1_snapshot_builder_v1")
        self.assertEqual(
            listing,
            [
                {
                    "snapshot_id": "phase1-store",
                    "symbol": "BTCUSDT",
                    "venue": "binance",
                    "timeframe": "1h",
                    "contract_type": "perpetual",
                    "row_count": 2,
                    "parquet_path": str(stored_paths["parquet_path"]),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
