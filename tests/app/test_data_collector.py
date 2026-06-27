import csv
import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.execution.paper_streams import record_binance_ws_payload
from engine.memory.store import initialize_memory_db


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _write_archive_bundle(root: Path, *, symbol: str, timeframe: str, rows: int) -> Path:
    bundle = root / f"{symbol}-{timeframe}-bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    candles_path = bundle / "candles.csv"
    with candles_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "open", "high", "low", "close", "volume", "trade_count"],
        )
        writer.writeheader()
        for index in range(rows):
            writer.writerow(
                {
                    "timestamp": f"2026-01-01T{index:02d}:00:00+00:00",
                    "open": "100.00000000",
                    "high": "101.00000000",
                    "low": "99.00000000",
                    "close": "100.50000000",
                    "volume": "10.00000000",
                    "trade_count": "5",
                }
            )
    (bundle / "fetch_manifest.json").write_text(
        json.dumps(
            {
                "provider": "binance_public_archive",
                "venue": "binance",
                "symbol": symbol,
                "timeframe": timeframe,
                "raw_source_hash": "a" * 64,
                "field_confidence": {
                    "liquidation_notional": "unavailable_archive_sidecar_empty_do_not_treat_zero_as_truth"
                },
                "row_count": rows,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return bundle


def _write_public_ws_session(
    db_path: Path,
    *,
    session_id: str,
    hours: int,
    hour_points: tuple[int, ...] | None = None,
) -> None:
    initialize_memory_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO paper_sessions (
                session_id, host_id, status, started_at_utc, stopped_at_utc, heartbeat_at_utc,
                symbols_json, streams_json, payload_json
            ) VALUES (?, 'test-host', 'running', '2026-01-01T00:00:00Z', NULL, ?, ?, ?, ?)
            """,
            (
                session_id,
                f"2026-01-01T{hours:02d}:00:00Z",
                json.dumps(["BTCUSDT", "ETHUSDT"]),
                json.dumps(["markPrice@1s", "forceOrder", "bookTicker"]),
                json.dumps({"private_keys_required": False, "mode": "live_public_ws"}),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    for hour in (hour_points if hour_points is not None else tuple(range(hours + 1))):
        for symbol in ("btcusdt", "ethusdt"):
            record_binance_ws_payload(
                db_path,
                session_id=session_id,
                stream_name=f"{symbol}@bookTicker",
                received_at_utc=f"2026-01-01T{hour:02d}:00:00Z",
                payload={
                    "stream": f"{symbol}@bookTicker",
                    "data": {
                        "e": "bookTicker",
                        "E": 1767225600000 + (hour * 60 * 60 * 1000),
                        "s": symbol.upper(),
                        "u": hour + 1,
                        "b": "100.00",
                        "B": "2",
                        "a": "100.10",
                        "A": "3",
                    },
                },
            )
            record_binance_ws_payload(
                db_path,
                session_id=session_id,
                stream_name=f"{symbol}@markPrice@1s",
                received_at_utc=f"2026-01-01T{hour:02d}:00:01Z",
                payload={
                    "stream": f"{symbol}@markPrice@1s",
                    "data": {
                        "e": "markPriceUpdate",
                        "E": 1767225601000 + (hour * 60 * 60 * 1000),
                        "s": symbol.upper(),
                        "p": "100.05",
                        "i": "100.04",
                        "r": "0.0001",
                        "T": 1767254400000,
                    },
                },
            )


class StrictDataCollectorTests(unittest.TestCase):
    def test_reuses_archive_bundles_and_reports_forward_window_ready(self) -> None:
        from engine.app.data_collector import StrictDataCollectorSettings, run_strict_data_collector

        root = Path("test-output-data-collector-ready")
        try:
            data_root = root / "data"
            for symbol in ("BTCUSDT", "ETHUSDT"):
                for timeframe in ("1Hour", "15Min"):
                    _write_archive_bundle(data_root, symbol=symbol, timeframe=timeframe, rows=2)
            db_path = root / "public_stream.sqlite"
            _write_public_ws_session(db_path, session_id="strict-test-session", hours=9)

            report = run_strict_data_collector(
                StrictDataCollectorSettings(
                    data_root=data_root,
                    public_ws_db=db_path,
                    session_id="strict-test-session",
                    inventory_output=root / "strict-v3-data-inventory.json",
                    minimum_bars={"1Hour": 2, "15Min": 2},
                    min_forward_seconds=8 * 60 * 60,
                    max_observed_gap_seconds=2 * 60 * 60,
                    export_liquidations_when_ready=False,
                )
            )

            self.assertEqual(report["status"], "ready_for_sidecar_export")
            self.assertTrue(report["archive"]["ready"])
            self.assertTrue(all(item["action"] == "reuse_existing" for item in report["archive"]["bundles"]))
            self.assertTrue(report["forward_public_ws_capture"]["first_window_ready"])
            self.assertGreaterEqual(report["forward_public_ws_capture"]["observed_seconds"], 8 * 60 * 60)
            self.assertEqual(report["next_action"]["id"], "export_observed_liquidation_sidecar")
            self.assertTrue((root / "strict-v3-data-inventory.json").exists())
        finally:
            _clean_tree(root)

    def test_sparse_forward_span_does_not_count_as_continuous_observed_window(self) -> None:
        from engine.app.data_collector import StrictDataCollectorSettings, run_strict_data_collector

        root = Path("test-output-data-collector-sparse")
        try:
            data_root = root / "data"
            for symbol in ("BTCUSDT", "ETHUSDT"):
                for timeframe in ("1Hour", "15Min"):
                    _write_archive_bundle(data_root, symbol=symbol, timeframe=timeframe, rows=2)
            db_path = root / "public_stream.sqlite"
            _write_public_ws_session(db_path, session_id="sparse-session", hours=9, hour_points=(0, 9))

            report = run_strict_data_collector(
                StrictDataCollectorSettings(
                    data_root=data_root,
                    public_ws_db=db_path,
                    session_id="sparse-session",
                    inventory_output=root / "strict-v3-data-inventory.json",
                    minimum_bars={"1Hour": 2, "15Min": 2},
                    min_forward_seconds=8 * 60 * 60,
                    max_observed_gap_seconds=2 * 60 * 60,
                    now=lambda: "2026-01-01T09:30:00Z",
                )
            )

            self.assertFalse(report["forward_public_ws_capture"]["continuous_window_ready"])
            self.assertFalse(report["forward_public_ws_capture"]["first_window_ready"])
            self.assertEqual(report["next_action"]["id"], "continue_public_ws_capture")
        finally:
            _clean_tree(root)

    def test_does_not_export_liquidation_sidecar_before_observed_window(self) -> None:
        from engine.app.data_collector import StrictDataCollectorSettings, run_strict_data_collector

        root = Path("test-output-data-collector-blocked")
        try:
            data_root = root / "data"
            for symbol in ("BTCUSDT", "ETHUSDT"):
                for timeframe in ("1Hour", "15Min"):
                    _write_archive_bundle(data_root, symbol=symbol, timeframe=timeframe, rows=2)
            db_path = root / "public_stream.sqlite"
            _write_public_ws_session(db_path, session_id="short-session", hours=2)
            sidecar = root / "liquidation_notional.csv"

            report = run_strict_data_collector(
                StrictDataCollectorSettings(
                    data_root=data_root,
                    public_ws_db=db_path,
                    session_id="short-session",
                    inventory_output=root / "strict-v3-data-inventory.json",
                    liquidation_output=sidecar,
                    minimum_bars={"1Hour": 2, "15Min": 2},
                    min_forward_seconds=8 * 60 * 60,
                    max_observed_gap_seconds=2 * 60 * 60,
                    export_liquidations_when_ready=True,
                    now=lambda: "2026-01-01T02:30:00Z",
                )
            )

            self.assertFalse(sidecar.exists())
            self.assertEqual(report["status"], "monitor_forward_capture")
            self.assertEqual(report["sidecar_export"]["status"], "blocked_min_window")
            self.assertEqual(report["next_action"]["id"], "continue_public_ws_capture")
            self.assertTrue(report["data_policy"]["missing_historical_liquidation_is_unavailable"])
        finally:
            _clean_tree(root)

    def test_stale_running_capture_requires_clean_restart(self) -> None:
        from engine.app.data_collector import StrictDataCollectorSettings, run_strict_data_collector

        root = Path("test-output-data-collector-stale")
        try:
            data_root = root / "data"
            for symbol in ("BTCUSDT", "ETHUSDT"):
                for timeframe in ("1Hour", "15Min"):
                    _write_archive_bundle(data_root, symbol=symbol, timeframe=timeframe, rows=2)
            db_path = root / "public_stream.sqlite"
            _write_public_ws_session(db_path, session_id="stale-session", hours=2)

            report = run_strict_data_collector(
                StrictDataCollectorSettings(
                    data_root=data_root,
                    public_ws_db=db_path,
                    session_id="stale-session",
                    inventory_output=root / "strict-v3-data-inventory.json",
                    minimum_bars={"1Hour": 2, "15Min": 2},
                    min_forward_seconds=8 * 60 * 60,
                    max_observed_gap_seconds=2 * 60 * 60,
                    now=lambda: "2026-01-01T05:00:00Z",
                )
            )

            self.assertEqual(report["status"], "start_forward_capture")
            self.assertEqual(report["forward_public_ws_capture"]["status"], "stale_incomplete")
            self.assertTrue(report["forward_public_ws_capture"]["stale"])
            self.assertEqual(report["next_action"]["id"], "restart_public_ws_capture")
        finally:
            _clean_tree(root)

    def test_exports_observed_zero_liquidation_buckets_only_after_window(self) -> None:
        from engine.app.data_collector import StrictDataCollectorSettings, run_strict_data_collector

        root = Path("test-output-data-collector-export")
        try:
            data_root = root / "data"
            for symbol in ("BTCUSDT", "ETHUSDT"):
                for timeframe in ("1Hour", "15Min"):
                    _write_archive_bundle(data_root, symbol=symbol, timeframe=timeframe, rows=2)
            db_path = root / "public_stream.sqlite"
            _write_public_ws_session(db_path, session_id="export-session", hours=9)
            sidecar = root / "liquidation_notional.csv"

            report = run_strict_data_collector(
                StrictDataCollectorSettings(
                    data_root=data_root,
                    public_ws_db=db_path,
                    session_id="export-session",
                    inventory_output=root / "strict-v3-data-inventory.json",
                    liquidation_output=sidecar,
                    minimum_bars={"1Hour": 2, "15Min": 2},
                    min_forward_seconds=8 * 60 * 60,
                    max_observed_gap_seconds=2 * 60 * 60,
                    export_liquidations_when_ready=True,
                )
            )

            self.assertTrue(sidecar.exists())
            self.assertEqual(report["sidecar_export"]["status"], "no_events")
            self.assertGreater(report["sidecar_export"]["observed_zero_bucket_count"], 0)
            self.assertTrue(report["sidecar_export"]["data_policy"]["missing_buckets_are_not_zero"])
            self.assertEqual(report["next_action"]["id"], "start_72h_forward_capture")
        finally:
            _clean_tree(root)

    def test_terminal_required_stream_gap_blocks_continuous_window(self) -> None:
        from engine.app.data_collector import StrictDataCollectorSettings, run_strict_data_collector

        root = Path("test-output-data-collector-terminal-gap")
        try:
            data_root = root / "data"
            for symbol in ("BTCUSDT", "ETHUSDT"):
                for timeframe in ("1Hour", "15Min"):
                    _write_archive_bundle(data_root, symbol=symbol, timeframe=timeframe, rows=2)
            db_path = root / "public_stream.sqlite"
            _write_public_ws_session(db_path, session_id="terminal-gap-session", hours=9)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "DELETE FROM paper_stream_events WHERE session_id=? AND stream_name LIKE '%@markPrice@1s' AND received_at_utc > ?",
                    ("terminal-gap-session", "2026-01-01T01:00:01Z"),
                )
                connection.commit()
            finally:
                connection.close()

            report = run_strict_data_collector(
                StrictDataCollectorSettings(
                    data_root=data_root,
                    public_ws_db=db_path,
                    session_id="terminal-gap-session",
                    inventory_output=root / "strict-v3-data-inventory.json",
                    minimum_bars={"1Hour": 2, "15Min": 2},
                    min_forward_seconds=8 * 60 * 60,
                    max_observed_gap_seconds=2 * 60 * 60,
                    now=lambda: "2026-01-01T09:30:00Z",
                )
            )

            capture = report["forward_public_ws_capture"]
            self.assertFalse(capture["continuous_window_ready"])
            self.assertGreater(capture["max_required_stream_gap_seconds"], 2 * 60 * 60)
        finally:
            _clean_tree(root)

    def test_latest_session_selection_uses_actual_start_time_not_stale_running_status(self) -> None:
        from engine.app.data_collector import _latest_public_ws_session

        root = Path("test-output-data-collector-latest-session")
        db_path = root / "public_stream.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "INSERT INTO paper_sessions (session_id, host_id, status, started_at_utc, heartbeat_at_utc, symbols_json, streams_json, payload_json) VALUES (?, 'host', 'running', ?, ?, '[]', '[]', '{}')",
                    ("old-running", "2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z"),
                )
                connection.execute(
                    "INSERT INTO paper_sessions (session_id, host_id, status, started_at_utc, stopped_at_utc, heartbeat_at_utc, symbols_json, streams_json, payload_json) VALUES (?, 'host', 'completed', ?, ?, ?, '[]', '[]', '{}')",
                    (
                        "new-completed",
                        "2026-01-02T00:00:00Z",
                        "2026-01-02T12:00:00Z",
                        "2026-01-02T12:00:00Z",
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            self.assertEqual(_latest_public_ws_session(db_path), "new-completed")
        finally:
            _clean_tree(root)

    def test_cli_strict_data_collect_dispatches_supervisor(self) -> None:
        from engine.app.cli import main

        with mock.patch(
            "engine.app.cli.run_strict_data_collector",
            return_value={"status": "monitor_forward_capture"},
        ) as run_mock:
            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "strict-data-collect",
                        "--data-root",
                        "outputs/data",
                        "--public-ws-db",
                        "outputs/public-ws/public_stream.sqlite",
                        "--session-id",
                        "strict-session",
                        "--inventory-output",
                        "outputs/data/strict-v3-data-inventory.json",
                        "--export-liquidations-when-ready",
                    ]
                )

        self.assertEqual(exit_code, 0)
        settings = run_mock.call_args.args[0]
        self.assertEqual(settings.session_id, "strict-session")
        self.assertTrue(settings.export_liquidations_when_ready)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["status"], "monitor_forward_capture")


if __name__ == "__main__":
    unittest.main()
