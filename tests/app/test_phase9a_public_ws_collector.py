import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.memory.store import initialize_memory_db
from engine.strategy.artifacts import build_strategy_artifact, write_strategy_artifact


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _valid_artifact_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "strategy_id": "strategy-ws-collector",
        "family": "momentum",
        "variant_id": "variant-ws-collector",
        "venue": "binance_usdm",
        "signal_timeframe": "1h",
        "execution_timeframe": "15m",
        "symbol_scope": ["BTCUSDT"],
        "regime_scope": ["trend", "neutral"],
        "feature_version": "feature-v1",
        "data_snapshot_ids": ["snapshot-v1"],
        "execution_model": "binance_usdm_v3",
        "cost_model": "cost-v1",
        "scenario_pack": "scenario-v1",
        "parameters": {"lookback": 48},
        "risk_limits": {"max_notional": 1000.0, "max_drawdown": 0.2},
        "order_policy": {"order_type": "limit", "time_in_force": "GTX", "post_only": True},
        "validation_report_id": "validation-v1",
        "code_sha": "code-sha",
        "rollout_stage": "paper",
        "promotion_approved": True,
        "validation_status": "passed",
        "created_at_utc": "2026-04-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _write_artifact(root: Path, **overrides: object) -> Path:
    artifact = build_strategy_artifact(_valid_artifact_payload(**overrides))
    path = root / "collector.strategy-artifact.json"
    if overrides.get("promotion_approved") is False:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
        return path
    return write_strategy_artifact(path, artifact)


def _write_fixture(root: Path) -> Path:
    fixture_path = root / "ws-fixture.json"
    payload = {
        "items": [
            {
                "type": "message",
                "stream_name": "btcusdt@aggTrade",
                "received_at_utc": "2026-04-30T00:00:01Z",
                "payload": {
                    "e": "aggTrade",
                    "E": 1777507200000,
                    "s": "BTCUSDT",
                    "a": 1,
                    "p": "100.10",
                    "q": "2.5",
                    "T": 1777507200000,
                },
            },
            {
                "type": "message",
                "stream_name": "btcusdt@aggTrade",
                "received_at_utc": "2026-04-30T00:00:02Z",
                "payload": {
                    "e": "aggTrade",
                    "E": 1777507200000,
                    "s": "BTCUSDT",
                    "a": 1,
                    "p": "100.10",
                    "q": "2.5",
                    "T": 1777507200000,
                },
            },
            {
                "type": "message",
                "stream_name": "btcusdt@depth",
                "received_at_utc": "2026-04-30T00:00:03Z",
                "payload": {
                    "e": "depthUpdate",
                    "E": 1777507202000,
                    "s": "BTCUSDT",
                    "U": 10,
                    "u": 12,
                    "pu": 9,
                    "b": [["100.00", "3"]],
                    "a": [["100.20", "4"]],
                },
            },
            {"type": "reconnect", "at_utc": "2026-04-30T00:00:04Z", "reason": "fixture_disconnect", "backoff_seconds": 2.5},
            {
                "type": "message",
                "stream_name": "btcusdt@depth",
                "received_at_utc": "2026-04-30T00:05:30Z",
                "payload": {
                    "e": "depthUpdate",
                    "E": 1777507530000,
                    "s": "BTCUSDT",
                    "U": 14,
                    "u": 15,
                    "pu": 13,
                    "b": [["100.01", "1"]],
                    "a": [["100.21", "5"]],
                },
            },
            {"type": "shutdown", "at_utc": "2026-04-30T00:05:31Z", "reason": "fixture_complete"},
        ]
    }
    fixture_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return fixture_path


class Phase9APublicWsCollectorTests(unittest.TestCase):
    def test_merged_source_fairly_yields_low_rate_route(self) -> None:
        from engine.execution.paper_collector import _merged_websocket_json_message_source

        fast_url = "wss://example.test/fast"
        slow_url = "wss://example.test/slow"

        def fake_source(url: str, *, recv_timeout_seconds: float | None = None):
            del recv_timeout_seconds
            if url == fast_url:
                for ordinal in range(500):
                    yield {"stream": "fast", "ordinal": ordinal}
                return
            yield {"stream": "slow", "ordinal": 1}

        with mock.patch(
            "engine.execution.paper_collector._websocket_json_message_source",
            side_effect=fake_source,
        ):
            merged = _merged_websocket_json_message_source(
                [fast_url, slow_url],
                recv_timeout_seconds=5.0,
            )
            try:
                first_messages = [next(merged) for _ in range(33)]
            finally:
                merged.close()

        self.assertTrue(any(item.get("stream") == "slow" for item in first_messages))

    def test_live_collector_uses_injected_public_ws_connector_without_private_keys(self) -> None:
        from engine.execution.paper_collector import PaperWsLiveCollectorConfig, run_paper_ws_collector_live

        root = Path("test-phase9a-ws-live-collector")
        db_path = root / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root)
            seen_urls: list[str] = []

            def fake_connector(url: str):
                seen_urls.append(url)
                yield {
                    "stream": "btcusdt@aggTrade",
                    "data": {
                        "e": "aggTrade",
                        "E": 1777507200000,
                        "s": "BTCUSDT",
                        "a": 101,
                        "p": "100.10",
                        "q": "2.5",
                        "T": 1777507200000,
                    },
                    "received_at_utc": "2026-04-30T00:00:01Z",
                }
                yield {
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "e": "bookTicker",
                        "E": 1777507201000,
                        "s": "BTCUSDT",
                        "u": 102,
                        "b": "100.00",
                        "B": "3",
                        "a": "100.20",
                        "A": "4",
                    },
                    "received_at_utc": "2026-04-30T00:00:02Z",
                }

            result = run_paper_ws_collector_live(
                PaperWsLiveCollectorConfig(
                    db_path=db_path,
                    artifact_paths=(artifact_path,),
                    session_id="collector-live-session",
                    host_id="oracle-a1-test",
                    symbols=("BTCUSDT",),
                    stream_kinds=("aggTrade", "bookTicker"),
                    max_messages=2,
                    message_source=fake_connector,
                )
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["mode"], "live_public_ws")
            self.assertFalse(result["private_keys_required"])
            self.assertEqual(result["counters"]["message_count"], 2)
            self.assertEqual(result["counters"]["connection_attempt_count"], 1)
            self.assertEqual(result["counters"]["shutdown_marker_count"], 1)
            self.assertEqual(len(seen_urls), 1)
            self.assertIn("btcusdt@aggTrade", seen_urls[0])

            connection = sqlite3.connect(db_path)
            try:
                events = connection.execute(
                    "SELECT stream_name, parse_status FROM paper_stream_events WHERE session_id = 'collector-live-session' ORDER BY received_at_utc, stream_event_id"
                ).fetchall()
                session_payload = connection.execute(
                    "SELECT status, payload_json FROM paper_sessions WHERE session_id = 'collector-live-session'"
                ).fetchone()
                health_statuses = [
                    row[0]
                    for row in connection.execute(
                        "SELECT status FROM executor_health WHERE executor_id = 'collector-live-session' ORDER BY ts_utc"
                    ).fetchall()
                ]
            finally:
                connection.close()

            self.assertEqual(events[:2], [("btcusdt@aggTrade", "parsed"), ("btcusdt@bookTicker", "parsed")])
            self.assertEqual(events[-1], ("collector:shutdown", "marker"))
            self.assertEqual(session_payload[0], "completed")
            self.assertFalse(json.loads(session_payload[1])["private_keys_required"])
            self.assertIn("connecting", health_statuses)
            self.assertIn("completed", health_statuses)
        finally:
            _clean_tree(root)

    def test_live_collector_records_reconnect_and_continues_after_public_ws_drop(self) -> None:
        from engine.execution.paper_collector import PaperWsLiveCollectorConfig, run_paper_ws_collector_live

        root = Path("test-phase9a-ws-live-reconnect")
        db_path = root / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root)
            attempts = {"count": 0}

            def fake_connector(_url: str):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    yield {
                        "stream": "btcusdt@depth",
                        "data": {
                            "e": "depthUpdate",
                            "E": 1777507200000,
                            "s": "BTCUSDT",
                            "U": 10,
                            "u": 12,
                            "pu": 9,
                            "b": [["100.00", "3"]],
                            "a": [["100.20", "4"]],
                        },
                        "received_at_utc": "2026-04-30T00:00:01Z",
                    }
                    raise ConnectionError("fixture public ws drop")
                yield {
                    "stream": "btcusdt@depth",
                    "data": {
                        "e": "depthUpdate",
                        "E": 1777507202000,
                        "s": "BTCUSDT",
                        "U": 14,
                        "u": 15,
                        "pu": 13,
                        "b": [["100.01", "1"]],
                        "a": [["100.21", "5"]],
                    },
                    "received_at_utc": "2026-04-30T00:00:03Z",
                }

            result = run_paper_ws_collector_live(
                PaperWsLiveCollectorConfig(
                    db_path=db_path,
                    artifact_paths=(artifact_path,),
                    session_id="collector-live-reconnect",
                    symbols=("BTCUSDT",),
                    stream_kinds=("depth",),
                    max_messages=2,
                    reconnect_attempts=1,
                    backoff_seconds=0.0,
                    message_source=fake_connector,
                )
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["counters"]["message_count"], 2)
            self.assertEqual(result["counters"]["reconnect_count"], 1)
            self.assertEqual(result["counters"]["connection_attempt_count"], 2)
            self.assertEqual(result["counters"]["gap_count"], 1)

            connection = sqlite3.connect(db_path)
            try:
                reconnect_rows = connection.execute(
                    "SELECT metadata_json FROM executor_health WHERE executor_id = 'collector-live-reconnect' AND status = 'reconnecting'"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(len(reconnect_rows), 1)
            reconnect_payload = json.loads(reconnect_rows[0][0])
            self.assertEqual(reconnect_payload["reason"], "fixture public ws drop")
            self.assertEqual(reconnect_payload["backoff_seconds"], 0.0)
        finally:
            _clean_tree(root)

    def test_live_collector_stops_at_max_duration_and_records_heartbeat(self) -> None:
        from engine.execution.paper_collector import PaperWsLiveCollectorConfig, run_paper_ws_collector_live

        root = Path("test-phase9a-ws-live-max-duration")
        db_path = root / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root)
            now_values = iter(
                [
                    "2026-04-30T00:00:00Z",
                    "2026-04-30T00:00:00Z",
                    "2026-04-30T00:00:01Z",
                    "2026-04-30T00:00:01Z",
                    "2026-04-30T00:00:06Z",
                    "2026-04-30T00:00:06Z",
                    "2026-04-30T00:00:06Z",
                    "2026-04-30T00:00:06Z",
                ]
            )

            def fake_now() -> str:
                return next(now_values, "2026-04-30T00:00:06Z")

            def fake_connector(_url: str):
                yield {
                    "stream": "btcusdt@aggTrade",
                    "data": {
                        "e": "aggTrade",
                        "E": 1777507200000,
                        "s": "BTCUSDT",
                        "a": 101,
                        "p": "100.10",
                        "q": "2.5",
                        "T": 1777507200000,
                    },
                    "received_at_utc": "2026-04-30T00:00:01Z",
                }
                yield {
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "e": "bookTicker",
                        "E": 1777507206000,
                        "s": "BTCUSDT",
                        "u": 102,
                        "b": "100.00",
                        "B": "3",
                        "a": "100.20",
                        "A": "4",
                    },
                    "received_at_utc": "2026-04-30T00:00:06Z",
                }

            result = run_paper_ws_collector_live(
                PaperWsLiveCollectorConfig(
                    db_path=db_path,
                    artifact_paths=(artifact_path,),
                    session_id="collector-live-max-duration",
                    symbols=("BTCUSDT",),
                    stream_kinds=("aggTrade", "bookTicker"),
                    max_duration_seconds=3.0,
                    heartbeat_interval_seconds=1.0,
                    reconnect_attempts=2,
                    message_source=fake_connector,
                    now=fake_now,
                )
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["stop_reason"], "max_duration_reached")
            self.assertEqual(result["counters"]["message_count"], 2)
            self.assertGreaterEqual(result["counters"]["heartbeat_count"], 1)

            connection = sqlite3.connect(db_path)
            try:
                health_rows = connection.execute(
                    "SELECT status, metadata_json FROM executor_health WHERE executor_id = 'collector-live-max-duration' ORDER BY ts_utc, health_id"
                ).fetchall()
                session_payload = connection.execute(
                    "SELECT payload_json FROM paper_sessions WHERE session_id = 'collector-live-max-duration'"
                ).fetchone()[0]
            finally:
                connection.close()

            heartbeat_payloads = [json.loads(row[1]) for row in health_rows if row[0] == "heartbeat"]
            self.assertTrue(heartbeat_payloads)
            self.assertEqual(heartbeat_payloads[-1]["message_count"], 2)
            self.assertEqual(heartbeat_payloads[-1]["reconnect_budget_remaining"], 2)
            self.assertEqual(json.loads(session_payload)["max_duration_seconds"], 3.0)
            self.assertEqual(json.loads(session_payload)["heartbeat_interval_seconds"], 1.0)
        finally:
            _clean_tree(root)

    def test_live_collector_exits_when_source_is_silent_past_no_message_timeout(self) -> None:
        from engine.execution.paper_collector import PaperWsLiveCollectorConfig, run_paper_ws_collector_live

        root = Path("test-phase9a-ws-live-no-message-timeout")
        db_path = root / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root)
            now_values = iter(
                [
                    "2026-04-30T00:00:00Z",
                    "2026-04-30T00:00:00Z",
                    "2026-04-30T00:00:07Z",
                    "2026-04-30T00:00:07Z",
                    "2026-04-30T00:00:07Z",
                ]
            )

            def fake_now() -> str:
                return next(now_values, "2026-04-30T00:00:07Z")

            def silent_connector(_url: str):
                if False:
                    yield {}

            result = run_paper_ws_collector_live(
                PaperWsLiveCollectorConfig(
                    db_path=db_path,
                    artifact_paths=(artifact_path,),
                    session_id="collector-live-no-message",
                    symbols=("BTCUSDT",),
                    stream_kinds=("aggTrade",),
                    no_message_timeout_seconds=5.0,
                    reconnect_attempts=3,
                    message_source=silent_connector,
                    now=fake_now,
                )
            )

            self.assertEqual(result["status"], "stale_incomplete")
            self.assertEqual(result["stop_reason"], "no_message_timeout")
            self.assertEqual(result["counters"]["message_count"], 0)

            connection = sqlite3.connect(db_path)
            try:
                timeout_rows = connection.execute(
                    "SELECT metadata_json FROM executor_health WHERE executor_id = 'collector-live-no-message' AND status = 'stale_incomplete'"
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(len(timeout_rows), 1)
            self.assertEqual(json.loads(timeout_rows[0][0])["reason"], "no_message_timeout")

            connection = sqlite3.connect(db_path)
            try:
                session_status = connection.execute(
                    "SELECT status FROM paper_sessions WHERE session_id = 'collector-live-no-message'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(session_status, "stale_incomplete")
        finally:
            _clean_tree(root)

    def test_fixture_collector_records_public_ws_events_counters_and_markers(self) -> None:
        from engine.execution.paper_collector import PaperWsCollectorConfig, run_paper_ws_collector_fixture

        root = Path("test-phase9a-ws-collector")
        db_path = root / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root)
            fixture_path = _write_fixture(root)

            result = run_paper_ws_collector_fixture(
                PaperWsCollectorConfig(
                    db_path=db_path,
                    artifact_paths=(artifact_path,),
                    fixture_path=fixture_path,
                    session_id="collector-session",
                    host_id="oracle-a1-test",
                    symbols=("BTCUSDT",),
                    stream_kinds=("aggTrade", "depth"),
                    max_stream_staleness_seconds=60,
                )
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["session_id"], "collector-session")
            self.assertEqual(result["stream_url"]["route"], "mixed")
            self.assertEqual(result["counters"]["message_count"], 4)
            self.assertEqual(result["counters"]["recorded_event_count"], 4)
            self.assertEqual(result["counters"]["duplicate_count"], 1)
            self.assertEqual(result["counters"]["gap_count"], 1)
            self.assertEqual(result["counters"]["reconnect_count"], 1)
            self.assertEqual(result["counters"]["shutdown_marker_count"], 1)
            self.assertEqual(result["counters"]["stale_stream_count"], 1)

            connection = sqlite3.connect(db_path)
            try:
                session = connection.execute(
                    "SELECT status, host_id, heartbeat_at_utc FROM paper_sessions WHERE session_id = 'collector-session'"
                ).fetchone()
                artifact_row = connection.execute(
                    "SELECT status FROM paper_session_artifacts WHERE session_id = 'collector-session'"
                ).fetchone()
                rows = connection.execute(
                    "SELECT stream_name, parse_status, metadata_json FROM paper_stream_events WHERE session_id = 'collector-session' ORDER BY received_at_utc, stream_event_id"
                ).fetchall()
                health_statuses = [
                    row[0]
                    for row in connection.execute(
                        "SELECT status FROM executor_health WHERE executor_id = 'collector-session' ORDER BY ts_utc"
                    ).fetchall()
                ]
            finally:
                connection.close()

            self.assertEqual(session, ("completed", "oracle-a1-test", "2026-04-30T00:05:31Z"))
            self.assertEqual(artifact_row, ("active",))
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[-1][0], "collector:shutdown")
            self.assertEqual(rows[-1][1], "marker")
            depth_metadata = json.loads(rows[3][2])
            self.assertEqual(depth_metadata["gap_count"], 1)
            self.assertTrue(depth_metadata["stale_stream_state"])
            self.assertIn("reconnecting", health_statuses)
            self.assertIn("completed", health_statuses)
        finally:
            _clean_tree(root)

    def test_cli_runs_fixture_collector_without_private_keys(self) -> None:
        root = Path("test-phase9a-ws-collector-cli")
        db_path = root / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root)
            fixture_path = _write_fixture(root)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "paper-ws-collect",
                        "--db",
                        str(db_path),
                        "--artifact",
                        str(artifact_path),
                        "--fixture",
                        str(fixture_path),
                        "--session-id",
                        "collector-cli-session",
                        "--host-id",
                        "oracle-a1-test",
                        "--symbol",
                        "BTCUSDT",
                        "--stream-kind",
                        "aggTrade",
                        "--stream-kind",
                        "depth",
                        "--max-stream-staleness-seconds",
                        "60",
                    ]
                )

            payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["counters"]["message_count"], 4)
            self.assertFalse(payload["private_keys_required"])

            connection = sqlite3.connect(db_path)
            try:
                event_count = connection.execute(
                    "SELECT COUNT(*) FROM paper_stream_events WHERE session_id = 'collector-cli-session'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(event_count, 5)
        finally:
            _clean_tree(root)

    def test_cli_live_collector_passes_bounds_and_heartbeat_options(self) -> None:
        root = Path("test-phase9a-ws-run-cli-bounds")
        db_path = root / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root)
            with mock.patch(
                "engine.app.cli.run_paper_ws_collector_live",
                return_value={"status": "completed", "private_keys_required": False},
            ) as run_mock:
                with mock.patch("builtins.print"):
                    exit_code = main(
                        [
                            "paper-ws-run",
                            "--db",
                            str(db_path),
                            "--artifact",
                            str(artifact_path),
                            "--session-id",
                            "collector-cli-live-bounds",
                            "--max-duration-seconds",
                            "30",
                            "--no-message-timeout-seconds",
                            "5",
                            "--heartbeat-interval-seconds",
                            "2",
                            "--reconnect-attempts",
                            "4",
                        ]
                    )

            config = run_mock.call_args.args[0]
            self.assertEqual(exit_code, 0)
            self.assertEqual(config.max_duration_seconds, 30.0)
            self.assertEqual(config.no_message_timeout_seconds, 5.0)
            self.assertEqual(config.heartbeat_interval_seconds, 2.0)
            self.assertEqual(config.reconnect_attempts, 4)
        finally:
            _clean_tree(root)

    def test_cli_live_collector_allows_capture_only_without_strategy_artifact(self) -> None:
        root = Path("test-phase9a-ws-run-cli-capture-only")
        db_path = root / "memory.sqlite"
        try:
            with mock.patch(
                "engine.app.cli.run_paper_ws_collector_live",
                return_value={"status": "completed", "private_keys_required": False},
            ) as run_mock:
                with mock.patch("builtins.print"):
                    exit_code = main(
                        [
                            "paper-ws-run",
                            "--db",
                            str(db_path),
                            "--session-id",
                            "collector-cli-capture-only",
                            "--capture-only",
                            "--symbol",
                            "BTCUSDT",
                            "--stream-kind",
                            "forceOrder",
                            "--max-messages",
                            "1",
                        ]
                    )

            config = run_mock.call_args.args[0]
            self.assertEqual(exit_code, 0)
            self.assertEqual(config.artifact_paths, ())
            self.assertTrue(config.capture_only)
            self.assertEqual(config.stream_kinds, ("forceOrder",))
        finally:
            _clean_tree(root)

    def test_live_collector_capture_only_records_public_force_order_without_artifacts(self) -> None:
        from engine.execution.paper_collector import PaperWsLiveCollectorConfig, run_paper_ws_collector_live

        root = Path("test-phase9a-ws-live-capture-only")
        db_path = root / "memory.sqlite"
        try:
            def source(_url: str):
                yield {
                    "stream": "btcusdt@forceOrder",
                    "data": {
                        "e": "forceOrder",
                        "E": 1777161600500,
                        "o": {
                            "s": "BTCUSDT",
                            "q": "0.014",
                            "p": "99.00",
                            "ap": "99.00",
                            "z": "0.014",
                            "T": 1777161600500,
                        },
                    },
                }

            result = run_paper_ws_collector_live(
                PaperWsLiveCollectorConfig(
                    db_path=db_path,
                    artifact_paths=(),
                    session_id="capture-only-session",
                    symbols=("BTCUSDT",),
                    stream_kinds=("forceOrder",),
                    max_messages=1,
                    capture_only=True,
                    message_source=source,
                    now=lambda: "2026-04-26T00:00:02Z",
                )
            )

            connection = sqlite3.connect(db_path)
            try:
                artifact_count = connection.execute("SELECT COUNT(*) FROM paper_session_artifacts").fetchone()[0]
                event_count = connection.execute(
                    "SELECT COUNT(*) FROM paper_stream_events WHERE session_id = 'capture-only-session'"
                ).fetchone()[0]
                session_payload = json.loads(
                    connection.execute(
                        "SELECT payload_json FROM paper_sessions WHERE session_id = 'capture-only-session'"
                    ).fetchone()[0]
                )
            finally:
                connection.close()

            self.assertEqual(result["status"], "completed")
            self.assertFalse(result["private_keys_required"])
            self.assertEqual(artifact_count, 0)
            self.assertEqual(event_count, 2)
            self.assertTrue(session_payload["capture_only"])
        finally:
            _clean_tree(root)

    def test_fixture_collector_rejects_unapproved_artifact(self) -> None:
        from engine.execution.paper_collector import PaperWsCollectorConfig, run_paper_ws_collector_fixture

        root = Path("test-phase9a-ws-collector-unapproved")
        db_path = root / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root, promotion_approved=False)
            fixture_path = _write_fixture(root)

            with self.assertRaises(ValueError) as raised:
                run_paper_ws_collector_fixture(
                    PaperWsCollectorConfig(
                        db_path=db_path,
                        artifact_paths=(artifact_path,),
                        fixture_path=fixture_path,
                        session_id="bad-artifact-session",
                    )
                )

            self.assertIn("approved immutable artifact", str(raised.exception))
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
