import unittest
from datetime import UTC, datetime

from engine.app.config import _parse_snapshot
from engine.app.examples import _serialize_snapshot
from engine.app.schema import build_study_schema


class SnapshotPhase1ContractTests(unittest.TestCase):
    def test_parse_snapshot_supports_phase1_metadata_contracts(self) -> None:
        raw = {
            "snapshot_id": "phase1-snapshot",
            "symbol": "BTCUSDT",
            "venue": "binance",
            "timeframe": "1h",
            "contract_type": "perpetual",
            "candles": [
                {
                    "timestamp": datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000.0,
                    "trade_count": 42,
                }
            ],
            "funding_rates": [0.0001],
            "open_interest": [1000000.0],
            "liquidation_notional": [25000.0],
            "mark_price": [100.45],
            "index_price": [100.40],
            "next_funding_ts": [datetime(2024, 1, 1, 8, tzinfo=UTC).isoformat()],
            "open_interest_usd": [100400000.0],
            "basis_bps": [4.98],
            "liq_long_usd": [14000.0],
            "liq_short_usd": [11000.0],
            "spread_bps": [3.5],
            "depth_bid_1bp_usd": [1500000.0],
            "depth_ask_1bp_usd": [1400000.0],
            "latency_proxy_ms": [25.0],
            "ret_1": [0.0],
            "ret_24": [0.0],
            "rv_24h": [0.0],
            "funding_z": [0.0],
            "d_oi": [0.0],
            "d_oi_z": [0.0],
            "liq_intensity_z": [0.0],
            "vol_regime": ["medium"],
            "regime_id": ["unassigned"],
            "regime_probabilities": [{"unassigned": 1.0}],
            "maker_fee_bps": 2.0,
            "taker_fee_bps": 5.0,
            "quality_flags": ["missing_sidecar_gap_fill"],
            "venue_profile": {
                "venue": "binance",
                "contract_type": "perpetual",
                "quote_currency": "USDT",
                "settlement_currency": "USDT",
                "funding_interval_h": 8,
                "mark_price_source": "fair_price",
                "liquidation_style": "partial",
                "partial_liquidation_ratio": 0.5,
                "liquidation_cooldown_bars": 2,
                "liquidation_mark_price_weight": 0.35,
                "liquidation_mark_premium_bps": 12.0,
                "maintenance_margin_schedule": [
                    {"max_leverage": 5.0, "maintenance_margin_ratio": 0.01}
                ],
                "liquidation_fee_schedule": [
                    {"max_leverage": 5.0, "liquidation_fee_bps": 0.0}
                ],
                "notes": ["phase-1-test"],
            },
            "quality_report": {
                "report_id": "quality-phase1",
                "snapshot_id": "phase1-snapshot",
                "quality_score": 0.92,
                "passed": False,
                "issues": ["missing_sidecar_gap_fill"],
                "metrics": {"missing_candle_count": 1},
                "source_checks": {"funding_rates_present": True},
                "generated_at": "2026-04-19T11:00:00+00:00",
            },
            "provenance": {
                "build_version": "phase1-alpha",
                "source_hash": "abc123",
            },
        }

        snapshot = _parse_snapshot(raw)

        self.assertIsNotNone(snapshot.venue_profile)
        self.assertEqual(snapshot.venue_profile.venue, "binance")
        self.assertEqual(snapshot.venue_profile.funding_interval_h, 8)
        self.assertEqual(snapshot.venue_profile.liquidation_style, "partial")
        self.assertEqual(snapshot.contract_type, "perpetual")
        self.assertEqual(snapshot.candles[0].trade_count, 42)
        self.assertEqual(snapshot.quality_report.report_id, "quality-phase1")
        self.assertFalse(snapshot.quality_report.passed)
        self.assertEqual(snapshot.mark_price, [100.45])
        self.assertEqual(snapshot.index_price, [100.40])
        self.assertEqual(snapshot.next_funding_ts[0], datetime(2024, 1, 1, 8, tzinfo=UTC).isoformat())
        self.assertEqual(snapshot.open_interest_usd, [100400000.0])
        self.assertEqual(snapshot.basis_bps, [4.98])
        self.assertEqual(snapshot.liq_long_usd, [14000.0])
        self.assertEqual(snapshot.liq_short_usd, [11000.0])
        self.assertEqual(snapshot.spread_bps, [3.5])
        self.assertEqual(snapshot.depth_bid_1bp_usd, [1500000.0])
        self.assertEqual(snapshot.depth_ask_1bp_usd, [1400000.0])
        self.assertEqual(snapshot.latency_proxy_ms, [25.0])
        self.assertEqual(snapshot.vol_regime, ["medium"])
        self.assertEqual(snapshot.regime_id, ["unassigned"])
        self.assertEqual(snapshot.regime_probabilities, [{"unassigned": 1.0}])
        self.assertEqual(snapshot.provenance["build_version"], "phase1-alpha")

    def test_serialize_snapshot_emits_phase1_metadata_contracts(self) -> None:
        raw = {
            "snapshot_id": "phase1-snapshot",
            "symbol": "BTCUSDT",
            "venue": "binance",
            "timeframe": "1h",
            "contract_type": "perpetual",
            "candles": [
                {
                    "timestamp": datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000.0,
                    "trade_count": 42,
                }
            ],
            "funding_rates": [0.0001],
            "open_interest": [1000000.0],
            "liquidation_notional": [25000.0],
            "mark_price": [100.45],
            "index_price": [100.40],
            "next_funding_ts": [datetime(2024, 1, 1, 8, tzinfo=UTC).isoformat()],
            "open_interest_usd": [100400000.0],
            "basis_bps": [4.98],
            "liq_long_usd": [14000.0],
            "liq_short_usd": [11000.0],
            "spread_bps": [3.5],
            "depth_bid_1bp_usd": [1500000.0],
            "depth_ask_1bp_usd": [1400000.0],
            "latency_proxy_ms": [25.0],
            "ret_1": [0.0],
            "ret_24": [0.0],
            "rv_24h": [0.0],
            "funding_z": [0.0],
            "d_oi": [0.0],
            "d_oi_z": [0.0],
            "liq_intensity_z": [0.0],
            "vol_regime": ["medium"],
            "regime_id": ["unassigned"],
            "regime_probabilities": [{"unassigned": 1.0}],
            "maker_fee_bps": 2.0,
            "taker_fee_bps": 5.0,
            "venue_profile": {
                "venue": "binance",
                "contract_type": "perpetual",
                "quote_currency": "USDT",
                "settlement_currency": "USDT",
                "funding_interval_h": 8,
            },
            "quality_report": {
                "report_id": "quality-phase1",
                "snapshot_id": "phase1-snapshot",
                "quality_score": 1.0,
                "passed": True,
            },
            "provenance": {"build_version": "phase1-alpha"},
        }

        snapshot = _parse_snapshot(raw)
        serialized = _serialize_snapshot(snapshot)

        self.assertIn("venue_profile", serialized)
        self.assertEqual(serialized["contract_type"], "perpetual")
        self.assertEqual(serialized["candles"][0]["trade_count"], 42)
        self.assertEqual(serialized["venue_profile"]["quote_currency"], "USDT")
        self.assertIn("quality_report", serialized)
        self.assertEqual(serialized["quality_report"]["report_id"], "quality-phase1")
        self.assertEqual(serialized["mark_price"], [100.45])
        self.assertEqual(serialized["index_price"], [100.40])
        self.assertEqual(serialized["next_funding_ts"], [datetime(2024, 1, 1, 8, tzinfo=UTC).isoformat()])
        self.assertEqual(serialized["open_interest_usd"], [100400000.0])
        self.assertEqual(serialized["basis_bps"], [4.98])
        self.assertEqual(serialized["liq_long_usd"], [14000.0])
        self.assertEqual(serialized["liq_short_usd"], [11000.0])
        self.assertEqual(serialized["spread_bps"], [3.5])
        self.assertEqual(serialized["depth_bid_1bp_usd"], [1500000.0])
        self.assertEqual(serialized["depth_ask_1bp_usd"], [1400000.0])
        self.assertEqual(serialized["latency_proxy_ms"], [25.0])
        self.assertEqual(serialized["vol_regime"], ["medium"])
        self.assertEqual(serialized["regime_id"], ["unassigned"])
        self.assertEqual(serialized["regime_probabilities"], [{"unassigned": 1.0}])
        self.assertEqual(serialized["provenance"]["build_version"], "phase1-alpha")

    def test_parse_snapshot_remains_backward_compatible_without_phase1_fields(self) -> None:
        raw = {
            "snapshot_id": "legacy-snapshot",
            "symbol": "SOLUSDT",
            "venue": "binance",
            "timeframe": "1h",
            "candles": [
                {
                    "timestamp": datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 500.0,
                }
            ],
            "funding_rates": [0.0],
            "open_interest": [100.0],
            "liquidation_notional": [0.0],
            "maker_fee_bps": 2.0,
            "taker_fee_bps": 5.0,
        }

        snapshot = _parse_snapshot(raw)

        self.assertIsNone(snapshot.venue_profile)
        self.assertIsNone(snapshot.quality_report)
        self.assertEqual(snapshot.spread_bps, [])
        self.assertEqual(snapshot.depth_bid_1bp_usd, [])
        self.assertEqual(snapshot.depth_ask_1bp_usd, [])
        self.assertEqual(snapshot.latency_proxy_ms, [])
        self.assertEqual(snapshot.mark_price, [])
        self.assertEqual(snapshot.index_price, [])
        self.assertEqual(snapshot.next_funding_ts, [])
        self.assertEqual(snapshot.regime_probabilities, [])
        self.assertEqual(snapshot.provenance, {})

    def test_study_schema_includes_phase1_snapshot_metadata_fields(self) -> None:
        snapshot_schema = build_study_schema()["properties"]["snapshot"]["properties"]

        self.assertIn("venue_profile", snapshot_schema)
        self.assertIn("quality_report", snapshot_schema)
        self.assertIn("provenance", snapshot_schema)
        self.assertIn("contract_type", snapshot_schema)
        self.assertIn("mark_price", snapshot_schema)
        self.assertIn("index_price", snapshot_schema)
        self.assertIn("next_funding_ts", snapshot_schema)
        self.assertIn("open_interest_usd", snapshot_schema)
        self.assertIn("basis_bps", snapshot_schema)
        self.assertIn("liq_long_usd", snapshot_schema)
        self.assertIn("liq_short_usd", snapshot_schema)
        self.assertIn("spread_bps", snapshot_schema)
        self.assertIn("depth_bid_1bp_usd", snapshot_schema)
        self.assertIn("depth_ask_1bp_usd", snapshot_schema)
        self.assertIn("latency_proxy_ms", snapshot_schema)
        self.assertIn("ret_1", snapshot_schema)
        self.assertIn("ret_24", snapshot_schema)
        self.assertIn("rv_24h", snapshot_schema)
        self.assertIn("funding_z", snapshot_schema)
        self.assertIn("d_oi", snapshot_schema)
        self.assertIn("d_oi_z", snapshot_schema)
        self.assertIn("liq_intensity_z", snapshot_schema)
        self.assertIn("vol_regime", snapshot_schema)
        self.assertIn("regime_id", snapshot_schema)
        self.assertIn("regime_probabilities", snapshot_schema)


if __name__ == "__main__":
    unittest.main()
