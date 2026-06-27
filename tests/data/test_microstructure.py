import csv
import json
import shutil
import unittest
from pathlib import Path

from engine.data.microstructure import (
    build_microstructure_features,
    export_force_order_liquidation_sidecar,
    fetch_binance_microstructure_snapshot,
)
from engine.execution.paper_streams import record_binance_ws_payload


class BinanceMicrostructureTests(unittest.TestCase):
    def test_build_microstructure_features_derives_phase5_fields(self) -> None:
        depth_snapshots = [
            {
                "lastUpdateId": 10,
                "E": 1_000,
                "T": 1_000,
                "bids": [["100.00", "8"], ["99.99", "4"]],
                "asks": [["100.02", "8"], ["100.03", "4"]],
            },
            {
                "lastUpdateId": 11,
                "E": 2_000,
                "T": 2_000,
                "bids": [["99.95", "20"], ["99.94", "15"]],
                "asks": [["100.05", "5"], ["100.06", "4"]],
            },
        ]
        agg_trades = [
            {"T": 1_500, "p": "100.00", "q": "2", "m": False},
            {"T": 1_900, "p": "100.00", "q": "1", "m": True},
        ]

        rows = build_microstructure_features(
            symbol="BTCUSDT",
            depth_snapshots=depth_snapshots,
            agg_trades=agg_trades,
            open_interest={"openInterest": "123.45", "time": 2_000},
            spread_spike_multiplier=2.0,
        )

        self.assertEqual(len(rows), 2)
        latest = rows[-1]
        self.assertEqual(latest["symbol"], "BTCUSDT")
        self.assertAlmostEqual(float(latest["signed_trade_delta_usd"]), 100.0)
        self.assertEqual(int(latest["stacked_imbalance_count"]), 2)
        self.assertGreater(float(latest["absorption_score"]), 0.0)
        self.assertGreater(float(latest["depth_replenishment_rate"]), 0.8)
        self.assertEqual(int(latest["spread_spike_flag"]), 1)
        self.assertEqual(float(latest["open_interest"]), 123.45)

    def test_fetch_binance_microstructure_snapshot_writes_raw_features_and_manifest(self) -> None:
        root = Path("test-output-microstructure-fetch")
        if root.exists():
            shutil.rmtree(root)
        payloads: dict[str, object] = {}
        depth_count = 0

        def fake_getter(url: str) -> object:
            nonlocal depth_count
            if "/depth?" in url:
                depth_count += 1
                if depth_count == 1:
                    payload = {
                        "lastUpdateId": 21,
                        "E": 1_000,
                        "T": 1_000,
                        "bids": [["100.00", "8"], ["99.99", "4"]],
                        "asks": [["100.02", "8"], ["100.03", "4"]],
                    }
                else:
                    payload = {
                        "lastUpdateId": 22,
                        "E": 2_000,
                        "T": 2_000,
                        "bids": [["99.95", "20"], ["99.94", "15"]],
                        "asks": [["100.05", "5"], ["100.06", "4"]],
                    }
            elif "/aggTrades?" in url:
                payload = [
                    {"T": 1_900, "p": "100.00", "q": "2", "m": False},
                    {"T": 1_950, "p": "100.00", "q": "1", "m": True},
                ]
            elif "/openInterest?" in url:
                payload = {"openInterest": "123.45", "time": 2_000}
            else:
                raise AssertionError(f"unexpected url: {url}")
            payloads[url] = payload
            return payload

        try:
            paths = fetch_binance_microstructure_snapshot(
                output_dir=root,
                symbol="BTC/USDT",
                depth_limit=5,
                agg_trade_limit=2,
                samples=2,
                sample_interval_seconds=0.0,
                retention_hours=1,
                max_raw_events=20,
                json_getter=fake_getter,
            )

            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["provider"], "binance_futures_microstructure")
            self.assertEqual(manifest["symbol"], "BTCUSDT")
            self.assertEqual(manifest["retention_policy"]["retention_hours"], 1)
            self.assertEqual(manifest["retention_policy"]["max_raw_events"], 20)
            self.assertEqual(manifest["feature_schema"]["phase5_features"][0], "signed_trade_delta_usd")
            self.assertEqual(depth_count, 2)
            self.assertEqual(len(payloads), 3)

            raw_lines = paths["raw_events"].read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(raw_lines), 5)
            self.assertIn('"event_type": "depth_snapshot"', raw_lines[0])

            with paths["features"].open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["symbol"], "BTCUSDT")
            self.assertEqual(rows[-1]["trade_count"], "2")
            self.assertGreater(float(rows[-1]["depth_replenishment_rate"]), 0.8)
            self.assertEqual(rows[-1]["open_interest"], "123.4500000000")
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_export_force_order_liquidation_sidecar_writes_sparse_observed_buckets(self) -> None:
        root = Path("test-output-forceorder-liquidations")
        if root.exists():
            shutil.rmtree(root)
        db_path = root / "memory.sqlite"
        output_path = root / "liquidation_notional.csv"
        try:
            session_id = "forceorder-session"
            record_binance_ws_payload(
                db_path,
                session_id=session_id,
                stream_name="btcusdt@forceOrder",
                received_at_utc="2026-04-26T00:05:00Z",
                payload={
                    "e": "forceOrder",
                    "E": 1777161900000,
                    "o": {"s": "BTCUSDT", "q": "0.014", "p": "99.00", "ap": "99.00", "z": "0.014", "T": 1777161900000},
                },
            )
            record_binance_ws_payload(
                db_path,
                session_id=session_id,
                stream_name="btcusdt@forceOrder",
                received_at_utc="2026-04-26T00:20:00Z",
                payload={
                    "e": "forceOrder",
                    "E": 1777162800000,
                    "o": {"s": "BTCUSDT", "q": "0.1", "p": "100.00", "ap": "100.00", "z": "0.1", "T": 1777162800000},
                },
            )
            record_binance_ws_payload(
                db_path,
                session_id=session_id,
                stream_name="btcusdt@aggTrade",
                received_at_utc="2026-04-26T00:25:00Z",
                payload={"e": "aggTrade", "E": 1777163100000, "s": "BTCUSDT", "T": 1777163100000},
            )

            summary = export_force_order_liquidation_sidecar(
                db_path=db_path,
                session_id=session_id,
                output_path=output_path,
                timeframe="1Hour",
            )

            with output_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(summary["status"], "exported")
            self.assertEqual(summary["event_count"], 2)
            self.assertEqual(summary["bucket_count"], 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["timestamp"], "2026-04-26T00:00:00+00:00")
            self.assertAlmostEqual(float(rows[0]["liquidation_notional"]), 11.386)
            self.assertTrue(summary["data_policy"]["missing_buckets_are_not_zero"])
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_export_force_order_liquidation_sidecar_can_include_observed_zero_buckets(self) -> None:
        root = Path("test-output-forceorder-observed-zero-buckets")
        if root.exists():
            shutil.rmtree(root)
        db_path = root / "memory.sqlite"
        output_path = root / "liquidation_notional.csv"
        try:
            session_id = "forceorder-observed-session"
            record_binance_ws_payload(
                db_path,
                session_id=session_id,
                stream_name="btcusdt@aggTrade",
                received_at_utc="2026-04-26T00:05:00Z",
                payload={"e": "aggTrade", "E": 1777161900000, "s": "BTCUSDT", "T": 1777161900000},
            )
            record_binance_ws_payload(
                db_path,
                session_id=session_id,
                stream_name="btcusdt@forceOrder",
                received_at_utc="2026-04-26T01:10:00Z",
                payload={
                    "e": "forceOrder",
                    "E": 1777165800000,
                    "o": {"s": "BTCUSDT", "q": "0.2", "p": "100.00", "ap": "100.00", "z": "0.2", "T": 1777165800000},
                },
            )

            summary = export_force_order_liquidation_sidecar(
                db_path=db_path,
                session_id=session_id,
                output_path=output_path,
                timeframe="1Hour",
                include_observed_zero_buckets=True,
            )

            with output_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(summary["status"], "exported")
            self.assertEqual(summary["event_count"], 1)
            self.assertEqual(summary["bucket_count"], 2)
            self.assertEqual(summary["observed_zero_bucket_count"], 1)
            self.assertEqual(rows[0], {"timestamp": "2026-04-26T00:00:00+00:00", "liquidation_notional": "0.0000000000"})
            self.assertEqual(rows[1], {"timestamp": "2026-04-26T01:00:00+00:00", "liquidation_notional": "20.0000000000"})
            self.assertTrue(summary["data_policy"]["observed_zero_buckets_enabled"])
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_export_force_order_liquidation_sidecar_supports_one_minute_buckets(self) -> None:
        root = Path("test-output-forceorder-one-minute-buckets")
        if root.exists():
            shutil.rmtree(root)
        db_path = root / "memory.sqlite"
        output_path = root / "liquidation_notional.csv"
        try:
            session_id = "forceorder-one-minute-session"
            for minute in range(5):
                event_time_ms = 1777161600000 + minute * 60_000
                record_binance_ws_payload(
                    db_path,
                    session_id=session_id,
                    stream_name="btcusdt@aggTrade",
                    received_at_utc=f"2026-04-26T00:0{minute}:05Z",
                    payload={"e": "aggTrade", "E": event_time_ms, "s": "BTCUSDT", "T": event_time_ms},
                )

            summary = export_force_order_liquidation_sidecar(
                db_path=db_path,
                session_id=session_id,
                output_path=output_path,
                timeframe="1Min",
                include_observed_zero_buckets=True,
            )

            with output_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(summary["status"], "no_events")
            self.assertEqual(summary["bucket_count"], 5)
            self.assertEqual(summary["observed_zero_bucket_count"], 5)
            self.assertEqual(rows[0], {"timestamp": "2026-04-26T00:00:00+00:00", "liquidation_notional": "0.0000000000"})
            self.assertEqual(rows[-1], {"timestamp": "2026-04-26T00:04:00+00:00", "liquidation_notional": "0.0000000000"})
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_export_force_order_liquidation_sidecar_uses_mark_price_event_time_for_observed_buckets(self) -> None:
        root = Path("test-output-forceorder-mark-price-observed-buckets")
        if root.exists():
            shutil.rmtree(root)
        db_path = root / "memory.sqlite"
        output_path = root / "liquidation_notional.csv"
        try:
            session_id = "forceorder-mark-price-observed-session"
            next_funding_time_ms = 1777248000000
            for minute in range(5):
                event_time_ms = 1777161600000 + minute * 60_000
                record_binance_ws_payload(
                    db_path,
                    session_id=session_id,
                    stream_name="btcusdt@markPrice@1s",
                    received_at_utc=f"2026-04-26T00:0{minute}:05Z",
                    payload={
                        "e": "markPriceUpdate",
                        "E": event_time_ms,
                        "s": "BTCUSDT",
                        "p": "100.00",
                        "i": "100.00",
                        "P": "100.00",
                        "r": "0.00001000",
                        "T": next_funding_time_ms,
                    },
                )

            summary = export_force_order_liquidation_sidecar(
                db_path=db_path,
                session_id=session_id,
                output_path=output_path,
                timeframe="1Min",
                include_observed_zero_buckets=True,
            )

            with output_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(summary["status"], "no_events")
            self.assertEqual(summary["bucket_count"], 5)
            self.assertEqual(rows[0], {"timestamp": "2026-04-26T00:00:00+00:00", "liquidation_notional": "0.0000000000"})
            self.assertEqual(rows[-1], {"timestamp": "2026-04-26T00:04:00+00:00", "liquidation_notional": "0.0000000000"})
        finally:
            if root.exists():
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
