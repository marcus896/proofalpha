import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.execution.paper_streams import (
    LocalOrderBookSnapshot,
    PaperBookStateBuilder,
    build_binance_usdm_stream_url,
    normalize_binance_usdm_ws_event,
    record_binance_ws_payload,
    rebuild_and_record_paper_book_state,
    replay_paper_stream_events,
)
from engine.memory.store import initialize_memory_db


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


class Phase9AStreamReplayTests(unittest.TestCase):
    def test_builds_routed_public_and_market_stream_urls(self) -> None:
        public = build_binance_usdm_stream_url(["BTCUSDT"], ["bookTicker", "depth"])
        market = build_binance_usdm_stream_url(["BTCUSDT"], ["aggTrade", "markPrice@1s", "forceOrder"])
        mixed = build_binance_usdm_stream_url(["BTCUSDT"], ["markPrice@1s", "forceOrder", "bookTicker"])

        self.assertEqual(public["route"], "public")
        self.assertEqual(public["url"], "wss://fstream.binance.com/public/stream?streams=btcusdt@bookTicker/btcusdt@depth")
        self.assertEqual(market["route"], "market")
        self.assertIn("btcusdt@markPrice@1s", market["stream_names"])
        self.assertEqual(mixed["route"], "mixed")
        self.assertEqual(
            mixed["url"],
            "wss://fstream.binance.com/stream?streams=btcusdt@markPrice@1s/btcusdt@forceOrder/btcusdt@bookTicker",
        )
        self.assertEqual([item["route"] for item in mixed["route_urls"]], ["public", "market"])
        self.assertEqual(
            [item["url"] for item in mixed["route_urls"]],
            [
                "wss://fstream.binance.com/public/stream?streams=btcusdt@bookTicker",
                "wss://fstream.binance.com/market/stream?streams=btcusdt@markPrice@1s/btcusdt@forceOrder",
            ],
        )

    def test_normalizes_combined_binance_ws_payloads_with_lag_and_hash(self) -> None:
        event = normalize_binance_usdm_ws_event(
            session_id="paper-stream-session",
            stream_name="btcusdt@aggTrade",
            received_at_utc="2026-04-26T00:00:01Z",
            payload={
                "stream": "btcusdt@aggTrade",
                "data": {
                    "e": "aggTrade",
                    "E": 1777161600000,
                    "s": "BTCUSDT",
                    "a": 5933014,
                    "p": "100.10",
                    "q": "2.5",
                    "T": 1777161600000,
                    "m": True,
                },
            },
        )

        self.assertEqual(event.symbol, "BTCUSDT")
        self.assertEqual(event.sequence_id, "5933014")
        self.assertEqual(event.exchange_event_time, "2026-04-26T00:00:00Z")
        self.assertEqual(event.lag_ms, 1000.0)
        self.assertEqual(event.parse_status, "parsed")
        self.assertEqual(len(event.payload_hash), 64)

    def test_records_and_replays_book_trade_mark_depth_and_force_order_events(self) -> None:
        root = Path("test-phase9a-streams")
        db_path = root / "memory.sqlite"
        session_id = "paper-stream-session"
        try:
            initialize_memory_db(db_path)
            payloads = [
                (
                    "btcusdt@bookTicker",
                    {
                        "e": "bookTicker",
                        "u": 400900217,
                        "E": 1777161600000,
                        "T": 1777161600000,
                        "s": "BTCUSDT",
                        "b": "100.00",
                        "B": "4.0",
                        "a": "100.20",
                        "A": "5.0",
                    },
                ),
                (
                    "btcusdt@aggTrade",
                    {
                        "e": "aggTrade",
                        "E": 1777161600100,
                        "s": "BTCUSDT",
                        "a": 1,
                        "p": "100.10",
                        "q": "2.5",
                        "T": 1777161600100,
                        "m": False,
                    },
                ),
                (
                    "btcusdt@markPrice@1s",
                    {
                        "e": "markPriceUpdate",
                        "E": 1777161600200,
                        "s": "BTCUSDT",
                        "p": "100.12",
                        "i": "100.00",
                        "r": "0.0001",
                        "T": 1777180800000,
                    },
                ),
                (
                    "btcusdt@depth",
                    {
                        "e": "depthUpdate",
                        "E": 1777161600300,
                        "T": 1777161600300,
                        "s": "BTCUSDT",
                        "U": 10,
                        "u": 12,
                        "pu": 9,
                        "b": [["100.00", "3"]],
                        "a": [["100.20", "4"]],
                    },
                ),
                (
                    "btcusdt@depth",
                    {
                        "e": "depthUpdate",
                        "E": 1777161600400,
                        "T": 1777161600400,
                        "s": "BTCUSDT",
                        "U": 14,
                        "u": 15,
                        "pu": 13,
                        "b": [["100.01", "2"]],
                        "a": [["100.21", "5"]],
                    },
                ),
                (
                    "btcusdt@forceOrder",
                    {
                        "e": "forceOrder",
                        "E": 1777161600500,
                        "o": {
                            "s": "BTCUSDT",
                            "S": "SELL",
                            "o": "LIMIT",
                            "f": "IOC",
                            "q": "0.014",
                            "p": "99.00",
                            "ap": "99.00",
                            "X": "FILLED",
                            "l": "0.014",
                            "z": "0.014",
                            "T": 1777161600500,
                        },
                    },
                ),
            ]

            for stream_name, payload in payloads:
                record_binance_ws_payload(
                    db_path,
                    session_id=session_id,
                    stream_name=stream_name,
                    payload=payload,
                    received_at_utc="2026-04-26T00:00:02Z",
                )

            replay = replay_paper_stream_events(db_path, session_id=session_id)
            repeat = replay_paper_stream_events(db_path, session_id=session_id)
            btc_state = replay["symbol_state"]["BTCUSDT"]

            self.assertEqual(replay["event_count"], 6)
            self.assertEqual(replay["gap_count"], 1)
            self.assertEqual(replay["duplicate_count"], 0)
            self.assertEqual(btc_state["best_bid"], 100.0)
            self.assertEqual(btc_state["best_ask"], 100.2)
            self.assertEqual(btc_state["last_trade_price"], 100.1)
            self.assertEqual(btc_state["mark_price"], 100.12)
            self.assertEqual(btc_state["funding_rate"], 0.0001)
            self.assertEqual(btc_state["last_depth_update_id"], 15)
            self.assertEqual(btc_state["depth_gap_count"], 1)
            self.assertEqual(btc_state["force_order_count"], 1)
            self.assertEqual(replay["replay_checksum"], repeat["replay_checksum"])

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    "SELECT stream_name, symbol, parse_status FROM paper_stream_events ORDER BY stream_name"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(len(rows), 6)
            self.assertTrue(all(row[2] == "parsed" for row in rows))
        finally:
            _clean_tree(root)

    def test_cli_paper_replay_outputs_checksum_and_optional_file(self) -> None:
        root = Path("test-phase9a-replay-cli")
        db_path = root / "memory.sqlite"
        output_path = root / "replay.json"
        try:
            initialize_memory_db(db_path)
            record_binance_ws_payload(
                db_path,
                session_id="paper-cli-replay",
                stream_name="btcusdt@bookTicker",
                payload={
                    "e": "bookTicker",
                    "u": 1,
                    "E": 1777161600000,
                    "s": "BTCUSDT",
                    "b": "100.00",
                    "B": "1.0",
                    "a": "100.10",
                    "A": "1.5",
                },
                received_at_utc="2026-04-26T00:00:01Z",
            )

            with mock.patch("builtins.print") as print_mock:
                self.assertEqual(
                    main(
                        [
                            "paper-replay",
                            "--db",
                            str(db_path),
                            "--session-id",
                            "paper-cli-replay",
                            "--output",
                            str(output_path),
                        ]
                    ),
                    0,
                )
            payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(payload["event_count"], 1)
            self.assertEqual(payload["symbol_state"]["BTCUSDT"]["best_bid"], 100.0)
            self.assertEqual(payload["output"], str(output_path))
            self.assertTrue(output_path.exists())
        finally:
            _clean_tree(root)

    def test_book_state_builder_applies_binance_snapshot_rules_and_marks_resync(self) -> None:
        builder = PaperBookStateBuilder(max_staleness_ms=750)
        builder.seed_snapshot(
            LocalOrderBookSnapshot(
                symbol="BTCUSDT",
                last_update_id=12,
                bids=[["100.00", "3.0"], ["99.50", "2.0"]],
                asks=[["100.20", "4.0"], ["100.50", "1.0"]],
                received_at_utc="2026-04-26T00:00:00Z",
            )
        )

        stale = builder.apply_depth_payload(
            {
                "e": "depthUpdate",
                "s": "BTCUSDT",
                "U": 1,
                "u": 11,
                "pu": 10,
                "b": [["100.00", "8.0"]],
                "a": [],
            },
            received_at_utc="2026-04-26T00:00:00.100Z",
        )
        self.assertEqual(stale["action"], "dropped_stale")

        bridged = builder.apply_depth_payload(
            {
                "e": "depthUpdate",
                "s": "BTCUSDT",
                "U": 10,
                "u": 13,
                "pu": 12,
                "b": [["100.00", "0"], ["100.10", "1.5"]],
                "a": [["100.20", "3.0"]],
            },
            received_at_utc="2026-04-26T00:00:00.250Z",
        )
        self.assertEqual(bridged["action"], "applied")

        state = builder.snapshot("BTCUSDT", now_utc="2026-04-26T00:00:00.500Z")
        self.assertEqual(state["best_bid"], 100.1)
        self.assertEqual(state["best_ask"], 100.2)
        self.assertEqual(state["last_depth_update_id"], 13)
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["visible_depth_qty"], 4.5)
        self.assertFalse(state["stale"])

        gap = builder.apply_depth_payload(
            {
                "e": "depthUpdate",
                "s": "BTCUSDT",
                "U": 15,
                "u": 16,
                "pu": 14,
                "b": [["100.11", "1.0"]],
                "a": [],
            },
            received_at_utc="2026-04-26T00:00:00.600Z",
        )
        self.assertEqual(gap["action"], "resync_required")

        stale_state = builder.snapshot("BTCUSDT", now_utc="2026-04-26T00:00:02Z")
        self.assertEqual(stale_state["status"], "resync_required")
        self.assertEqual(stale_state["depth_gap_count"], 1)
        self.assertTrue(stale_state["stale"])

    def test_rebuild_and_record_book_state_writes_market_snapshot_and_health(self) -> None:
        root = Path("test-phase9a-book-state")
        db_path = root / "memory.sqlite"
        session_id = "paper-book-session"
        try:
            initialize_memory_db(db_path)
            for payload in [
                {
                    "e": "depthUpdate",
                    "E": 1777161600000,
                    "T": 1777161600000,
                    "s": "BTCUSDT",
                    "U": 10,
                    "u": 12,
                    "pu": 9,
                    "b": [["100.00", "0"], ["100.10", "1.5"]],
                    "a": [["100.20", "3.0"]],
                },
                {
                    "e": "depthUpdate",
                    "E": 1777161600100,
                    "T": 1777161600100,
                    "s": "BTCUSDT",
                    "U": 13,
                    "u": 14,
                    "pu": 12,
                    "b": [["100.12", "2.0"]],
                    "a": [["100.20", "0"], ["100.30", "3.5"]],
                },
            ]:
                record_binance_ws_payload(
                    db_path,
                    session_id=session_id,
                    stream_name="btcusdt@depth",
                    payload=payload,
                    received_at_utc="2026-04-26T00:00:01Z",
                )

            result = rebuild_and_record_paper_book_state(
                db_path,
                session_id=session_id,
                snapshots=[
                    LocalOrderBookSnapshot(
                        symbol="BTCUSDT",
                        last_update_id=12,
                        bids=[["100.00", "3.0"]],
                        asks=[["100.20", "4.0"]],
                        received_at_utc="2026-04-26T00:00:00Z",
                    )
                ],
                now_utc="2026-04-26T00:00:01Z",
            )

            state = result["books"]["BTCUSDT"]
            self.assertEqual(result["status"], "active")
            self.assertEqual(state["best_bid"], 100.12)
            self.assertEqual(state["best_ask"], 100.3)
            self.assertEqual(state["last_depth_update_id"], 14)
            self.assertEqual(state["depth_gap_count"], 0)

            connection = sqlite3.connect(db_path)
            try:
                market_rows = connection.execute(
                    "SELECT symbol, bid, ask, spread_bps FROM market_snapshots WHERE metadata_json LIKE ?",
                    (f"%{session_id}%",),
                ).fetchall()
                health_rows = connection.execute(
                    "SELECT status, websocket_lag_ms FROM executor_health WHERE executor_id = ?",
                    (session_id,),
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(market_rows, [("BTCUSDT", 100.12, 100.3, state["spread_bps"])])
            self.assertEqual(health_rows, [("active", 0.0)])
        finally:
            _clean_tree(root)

    def test_cli_paper_book_replay_uses_snapshot_file_and_writes_output(self) -> None:
        root = Path("test-phase9a-book-cli")
        db_path = root / "memory.sqlite"
        snapshot_path = root / "depth_snapshot.json"
        output_path = root / "book_state.json"
        try:
            initialize_memory_db(db_path)
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "symbol": "BTCUSDT",
                                "last_update_id": 12,
                                "bids": [["100.00", "3.0"]],
                                "asks": [["100.20", "4.0"]],
                                "received_at_utc": "2026-04-26T00:00:00Z",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            record_binance_ws_payload(
                db_path,
                session_id="paper-book-cli",
                stream_name="btcusdt@depth",
                payload={
                    "e": "depthUpdate",
                    "E": 1777161600000,
                    "T": 1777161600000,
                    "s": "BTCUSDT",
                    "U": 10,
                    "u": 13,
                    "pu": 12,
                    "b": [["100.10", "1.5"]],
                    "a": [["100.20", "3.0"]],
                },
                received_at_utc="2026-04-26T00:00:01Z",
            )

            with mock.patch("builtins.print") as print_mock:
                self.assertEqual(
                    main(
                        [
                            "paper-book-replay",
                            "--db",
                            str(db_path),
                            "--session-id",
                            "paper-book-cli",
                            "--snapshot",
                            str(snapshot_path),
                            "--now",
                            "2026-04-26T00:00:01Z",
                            "--output",
                            str(output_path),
                        ]
                    ),
                    0,
                )

            payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(payload["status"], "active")
            self.assertEqual(payload["books"]["BTCUSDT"]["best_bid"], 100.1)
            self.assertEqual(payload["output"], str(output_path))
            self.assertTrue(output_path.exists())
        finally:
            _clean_tree(root)
