import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.memory.store import initialize_memory_db


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _seed_dashboard_fixture(db_path: Path) -> None:
    initialize_memory_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        artifact_payload = {
            "portfolio_role": "core",
            "regime_scope": ["trend"],
            "promotion_manifest": {
                "paper_eligibility": True,
                "expiry_time_utc": "2099-01-01T00:00:00Z",
            },
        }
        connection.execute(
            """
            INSERT INTO paper_sessions (
                session_id, host_id, status, started_at_utc, stopped_at_utc,
                heartbeat_at_utc, portfolio_plan_id, symbols_json, streams_json,
                code_hash, config_checksum, payload_json
            ) VALUES (
                'dashboard-session', 'oracle-a1-test', 'completed',
                '2026-04-30T00:00:00Z', '2026-04-30T01:00:00Z',
                '2026-04-30T01:00:00Z', 'portfolio-dashboard',
                '["BTCUSDT"]', '["aggTrade", "bookTicker", "depth"]',
                'code-hash', 'config-hash', '{}'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO paper_session_artifacts (
                session_id, artifact_id, artifact_sha256, lifecycle_state, status, payload_json
            ) VALUES (
                'dashboard-session', 'artifact-core', 'sha-core',
                'paper artifact', 'active',
                ?
            )
            """,
            (json.dumps(artifact_payload, sort_keys=True),),
        )
        connection.execute(
            """
            INSERT INTO paper_session_summaries (
                session_id, created_at_utc, status, uptime_seconds, artifact_count,
                symbol_count, order_count, filled_count, partial_count, rejected_count,
                risk_block_count, funding_fee, paper_pnl, drawdown,
                telemetry_quality_score, payload_json
            ) VALUES (
                'dashboard-session', '2026-04-30T01:00:00Z', 'completed',
                3600, 1, 1, 3, 2, 1, 1, 2, -0.25, 18.5, 0.04, 0.72, '{}'
            )
            """
        )
        stream_rows = [
            ("s1", "aggTrade", 10.0, {}),
            ("s2", "bookTicker", 20.0, {"duplicate_count": 1}),
            ("s3", "depth", 80.0, {"gap_count": 2, "dropped_count": 1}),
        ]
        for stream_event_id, stream_name, lag_ms, metadata in stream_rows:
            connection.execute(
                """
                INSERT INTO paper_stream_events (
                    stream_event_id, session_id, received_at_utc, exchange_event_time,
                    stream_name, symbol, sequence_id, payload_hash, payload_json,
                    parse_status, lag_ms, metadata_json
                ) VALUES (?, 'dashboard-session', '2026-04-30T01:00:00Z',
                    '2026-04-30T00:59:59Z', ?, 'BTCUSDT', '1', ?,
                    '{}', 'parsed', ?, ?)
                """,
                (
                    stream_event_id,
                    stream_name,
                    f"hash-{stream_event_id}",
                    lag_ms,
                    json.dumps(metadata, sort_keys=True),
                ),
            )
        telemetry_rows = [
            ("t1", "BUY", 1.0, 1.0, 100.0, 101.0, 5.0, 0, 0),
            ("t2", "SELL", 0.4, 0.2, 100.0, 99.0, 12.0, 0, 0),
            ("t3", "BUY", 0.5, 0.0, 100.0, None, None, 1, 1),
        ]
        for telemetry_id, side, qty_submitted, qty_filled, expected, live, slip_bps, was_rejected, risk_blocked in telemetry_rows:
            connection.execute(
                """
                INSERT INTO order_telemetry (
                    telemetry_id, symbol, side, qty_submitted, qty_filled,
                    expected_price, live_vwap_price, slip_bps, fee_quote,
                    latency_rtt_ms, maker_ratio, was_rejected, risk_blocked,
                    metadata_json
                ) VALUES (?, 'BTCUSDT', ?, ?, ?, ?, ?, ?, 0.05, 40.0,
                    0.5, ?, ?, '{"session_id": "dashboard-session", "raw": {"artifact_id": "artifact-core"}}')
                """,
                (
                    telemetry_id,
                    side,
                    qty_submitted,
                    qty_filled,
                    expected,
                    live,
                    slip_bps,
                    was_rejected,
                    risk_blocked,
                ),
            )
        for risk_event_id, reason_code in (("r1", "depth_too_thin"), ("r2", "spread_too_wide")):
            connection.execute(
                """
                INSERT INTO risk_events (
                    risk_event_id, ts_utc, reason_code, severity, action, metadata_json
                ) VALUES (?, '2026-04-30T00:30:00Z', ?, 'block', 'block_intent',
                    '{"session_id": "dashboard-session", "intent": {"artifact_id": "artifact-core", "symbol": "BTCUSDT"}}')
                """,
                (risk_event_id, reason_code),
            )
        connection.execute(
            """
            INSERT INTO backup_manifests (
                backup_id, created_at_utc, backup_location, snapshot_digest,
                table_count, status, metadata_json
            ) VALUES ('backup-1', '2026-04-30T00:30:00Z', 'bundle-dir',
                'digest', 6, 'exported', '{"session_id": "dashboard-session"}')
            """
        )
        feedback_payload = {
            "status": "sample_guarded",
            "guard_reasons": ["insufficient_bucket_sample:BTCUSDT|trend"],
        }
        connection.execute(
            """
            INSERT INTO paper_calibration_feedback (
                artifact_id, session_id, source_model_version, created_at_utc,
                status, telemetry_quality_score, sample_count, artifact_sha256, payload_json
            ) VALUES (
                'feedback-1', 'dashboard-session', 'cost-v1',
                '2026-04-30T01:00:00Z', 'sample_guarded',
                0.65, 3, 'sha-feedback', ?
            )
            """,
            (json.dumps(feedback_payload, sort_keys=True),),
        )
        connection.commit()
    finally:
        connection.close()


class Phase9APaperSessionDashboardTests(unittest.TestCase):
    def test_builds_dashboard_artifact_and_persists_into_session_summary(self) -> None:
        from engine.execution.paper_dashboard import (
            PaperSessionDashboardConfig,
            build_paper_session_dashboard,
        )

        root = Path("test-phase9a-dashboard")
        db_path = root / "memory.sqlite"
        try:
            _seed_dashboard_fixture(db_path)

            dashboard = build_paper_session_dashboard(
                PaperSessionDashboardConfig(
                    db_path=db_path,
                    session_id="dashboard-session",
                    now_utc="2026-04-30T01:05:00Z",
                    max_stream_staleness_seconds=120,
                )
            )

            self.assertEqual(dashboard["artifact_type"], "paper_session_dashboard")
            self.assertEqual(dashboard["session"]["session_id"], "dashboard-session")
            self.assertEqual(dashboard["status"], "attention")
            self.assertEqual(dashboard["streams"]["lag_ms"], {"p50": 20.0, "p95": 80.0, "max": 80.0})
            self.assertEqual(dashboard["streams"]["gap_count"], 2)
            self.assertEqual(dashboard["streams"]["duplicate_count"], 1)
            self.assertEqual(dashboard["streams"]["stale_streams"], ["aggTrade", "bookTicker", "depth"])
            self.assertEqual(dashboard["orders"]["filled_count"], 2)
            self.assertEqual(dashboard["orders"]["partial_count"], 1)
            self.assertEqual(dashboard["risk"]["blocks_by_reason"]["depth_too_thin"], 1)
            self.assertEqual(dashboard["positions"]["simulated_positions"]["BTCUSDT"]["net_qty"], 0.8)
            self.assertTrue(dashboard["artifacts"][0]["promotion_manifest_present"])
            self.assertTrue(dashboard["artifacts"][0]["promotion_manifest_paper_eligibility"])
            self.assertEqual(
                dashboard["artifacts"][0]["promotion_manifest_expiry_time_utc"],
                "2099-01-01T00:00:00Z",
            )
            self.assertEqual(dashboard["storage"]["latest_backup"]["backup_id"], "backup-1")
            self.assertFalse(dashboard["calibration"]["ready_for_model_update"])
            self.assertEqual(len(dashboard["artifact_sha256"]), 64)

            connection = sqlite3.connect(db_path)
            try:
                raw_payload = connection.execute(
                    "SELECT payload_json FROM paper_session_summaries WHERE session_id = 'dashboard-session'"
                ).fetchone()[0]
            finally:
                connection.close()
            payload = json.loads(raw_payload)
            self.assertEqual(payload["paper_session_dashboard"]["artifact_id"], dashboard["artifact_id"])
        finally:
            _clean_tree(root)

    def test_cli_writes_dashboard_artifact(self) -> None:
        root = Path("test-phase9a-dashboard-cli")
        db_path = root / "memory.sqlite"
        output_path = root / "dashboard.json"
        try:
            _seed_dashboard_fixture(db_path)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "paper-session-dashboard",
                        "--db",
                        str(db_path),
                        "--session-id",
                        "dashboard-session",
                        "--output",
                        str(output_path),
                        "--now",
                        "2026-04-30T01:05:00Z",
                        "--max-stream-staleness-seconds",
                        "120",
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            artifact = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "attention")
            self.assertEqual(printed["output"], str(output_path))
            self.assertEqual(artifact["artifact_type"], "paper_session_dashboard")
            self.assertEqual(artifact["session"]["portfolio_plan_id"], "portfolio-dashboard")
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
