import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.execution.paper_hosting import write_hosted_paper_ops_templates
from engine.memory.store import initialize_memory_db
from tests.app.test_phase9a_public_ws_collector import _write_artifact


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _seed_soak_closeout_evidence(root: Path, db_path: Path, session_id: str) -> None:
    initialize_memory_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO order_telemetry (
                telemetry_id, symbol, side, qty_submitted, qty_filled, qty_canceled,
                expected_price, live_vwap_price, slip_bps, spread_bps, topn_depth,
                latency_rtt_ms, maker_ratio, was_rejected, risk_blocked, metadata_json
            ) VALUES ('soak-telemetry-1', 'BTCUSDT', 'BUY', 1, 1, 0, 100.0,
                100.04, 4.0, 2.0, 20.0, 40.0, 0.5, 0, 0, ?)
            """,
            (
                json.dumps(
                    {
                        "session_id": session_id,
                        "artifact_id": "collector",
                        "raw": {"artifact_id": "collector", "regime": "trend"},
                        "regime": "trend",
                        "adv_notional": 100000.0,
                        "modeled_fill_price": 100.0,
                        "opportunity_loss_bps": 1.0,
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO paper_calibration_feedback (
                artifact_id, session_id, source_model_version, created_at_utc, status,
                telemetry_quality_score, sample_count, artifact_sha256, payload_json
            ) VALUES ('phase1-feedback', ?, 'cost-v1', '2026-04-30T00:10:00Z',
                'feedback_ready', 1.0, 1, 'feedback-sha', ?)
            """,
            (
                session_id,
                json.dumps(
                    {
                        "live_promotion_allowed": False,
                        "can_lower_live_costs": False,
                        "model_update_allowed": True,
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.execute(
            """
            UPDATE paper_sessions
            SET portfolio_plan_id = 'phase1-portfolio'
            WHERE session_id = ?
            """,
            (session_id,),
        )
        connection.execute(
            """
            INSERT INTO paper_portfolio_decisions (
                decision_id, session_id, portfolio_plan_id, ts_utc, interval_seconds,
                status, reason_code, payload_json
            ) VALUES ('phase1-decision', ?, 'phase1-portfolio', '2026-04-30T00:10:00Z',
                900, 'accepted', 'paper_portfolio_loop_tick', ?)
            """,
            (session_id, json.dumps({"status": "accepted"}, sort_keys=True)),
        )
        connection.commit()
    finally:
        connection.close()

    for key in ("repo", "state", "logs", "backups", "deploy"):
        (root / key).mkdir(parents=True, exist_ok=True)
    write_hosted_paper_ops_templates(root / "deploy")


class Phase1PublicWsSoakTests(unittest.TestCase):
    def test_live_public_ws_collector_summary_records_soak_uptime_and_metadata(self) -> None:
        from engine.execution.paper_collector import PaperWsLiveCollectorConfig, run_paper_ws_collector_live

        root = Path("test-phase1-soak-summary")
        db_path = root / "state" / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root, artifact_id="collector")

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
                    "received_at_utc": "2026-04-30T00:00:02Z",
                }
                yield {
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "e": "bookTicker",
                        "E": 1777507202000,
                        "s": "BTCUSDT",
                        "u": 102,
                        "b": "100.00",
                        "B": "3",
                        "a": "100.20",
                        "A": "4",
                    },
                    "received_at_utc": "2026-04-30T00:00:03Z",
                }
                yield {
                    "stream": "btcusdt@depth",
                    "data": {
                        "e": "depthUpdate",
                        "E": 1777507203000,
                        "s": "BTCUSDT",
                        "U": 10,
                        "u": 12,
                        "pu": 9,
                        "b": [["100.00", "3"]],
                        "a": [["100.20", "4"]],
                    },
                    "received_at_utc": "2026-04-30T00:00:04Z",
                }
                yield {
                    "stream": "btcusdt@depth",
                    "data": {
                        "e": "depthUpdate",
                        "E": 1777507203000,
                        "s": "BTCUSDT",
                        "U": 13,
                        "u": 14,
                        "pu": 12,
                        "b": [["100.00", "3"]],
                        "a": [["100.20", "4"]],
                    },
                    "received_at_utc": "2026-04-30T00:10:01Z",
                }

            result = run_paper_ws_collector_live(
                PaperWsLiveCollectorConfig(
                    db_path=db_path,
                    artifact_paths=(artifact_path,),
                    session_id="phase1-soak-summary",
                    host_id="oracle-a1-soak",
                    symbols=("BTCUSDT",),
                    stream_kinds=("aggTrade", "bookTicker", "depth"),
                    max_stream_staleness_seconds=60,
                    max_messages=5,
                    message_source=fake_connector,
                )
            )

            self.assertEqual(result["status"], "completed")
            connection = sqlite3.connect(db_path)
            try:
                summary = connection.execute(
                    "SELECT uptime_seconds, payload_json FROM paper_session_summaries WHERE session_id = ?",
                    ("phase1-soak-summary",),
                ).fetchone()
                session = connection.execute(
                    "SELECT host_id, config_checksum FROM paper_sessions WHERE session_id = ?",
                    ("phase1-soak-summary",),
                ).fetchone()
            finally:
                connection.close()

            payload = json.loads(summary[1])
            soak = payload["public_ws_soak"]
            self.assertGreaterEqual(summary[0], 600.0)
            self.assertEqual(soak["stream_source"], "live_public_ws")
            self.assertEqual(soak["host_id"], "oracle-a1-soak")
            self.assertEqual(soak["artifact_ids"], ["collector"])
            self.assertEqual(soak["config_checksum"], session[1])
            self.assertEqual(soak["counters"]["message_count"], 5)
            self.assertEqual(soak["counters"]["duplicate_count"], 1)
            self.assertEqual(soak["counters"]["stale_stream_count"], 1)
            self.assertGreaterEqual(soak["heartbeat_cadence_seconds"], 0.0)
        finally:
            _clean_tree(root)

    def test_public_ws_soak_closeout_report_wraps_strict_phase9a_evidence(self) -> None:
        from engine.execution.paper_collector import PaperWsLiveCollectorConfig, run_paper_ws_collector_live
        from engine.execution.paper_soak import PaperSoakCloseoutConfig, build_public_ws_soak_closeout_report

        root = Path("test-phase1-soak-closeout")
        db_path = root / "state" / "memory.sqlite"
        try:
            artifact_path = _write_artifact(root, artifact_id="collector")

            def fake_connector(_url: str):
                yield {
                    "stream": "btcusdt@aggTrade",
                    "data": {"e": "aggTrade", "E": 1777507200000, "s": "BTCUSDT", "a": 1, "p": "100.10", "q": "2.5"},
                    "received_at_utc": "2026-04-30T00:00:01Z",
                }
                yield {
                    "stream": "btcusdt@bookTicker",
                    "data": {"e": "bookTicker", "E": 1777507201000, "s": "BTCUSDT", "u": 2, "b": "100.00", "B": "3", "a": "100.20", "A": "4"},
                    "received_at_utc": "2026-04-30T00:00:02Z",
                }
                yield {
                    "stream": "btcusdt@depth",
                    "data": {"e": "depthUpdate", "E": 1777507801000, "s": "BTCUSDT", "U": 10, "u": 12, "pu": 9, "b": [["100.00", "3"]], "a": [["100.20", "4"]]},
                    "received_at_utc": "2026-04-30T00:10:01Z",
                }

            run_paper_ws_collector_live(
                PaperWsLiveCollectorConfig(
                    db_path=db_path,
                    artifact_paths=(artifact_path,),
                    session_id="phase1-soak-closeout",
                    host_id="oracle-a1-soak",
                    symbols=("BTCUSDT",),
                    stream_kinds=("aggTrade", "bookTicker", "depth"),
                    max_messages=3,
                    message_source=fake_connector,
                )
            )
            _seed_soak_closeout_evidence(root, db_path, "phase1-soak-closeout")

            report = build_public_ws_soak_closeout_report(
                PaperSoakCloseoutConfig(
                    db_path=db_path,
                    session_id="phase1-soak-closeout",
                    export_dir=root / "backups",
                    restore_db_path=root / "restore" / "memory.sqlite",
                    hosted_repo_dir=root / "repo",
                    hosted_state_dir=root / "state",
                    hosted_log_dir=root / "logs",
                    hosted_backup_dir=root / "backups",
                    hosted_template_root=root / "deploy",
                    minimum_soak_seconds=600,
                )
            )

            self.assertEqual(report["status"], "ready_to_close")
            self.assertEqual(report["artifact_type"], "public_ws_soak_closeout")
            self.assertFalse(report["requires_private_keys"])
            self.assertFalse(report["live_order_path_enabled"])
            self.assertEqual(report["soak"]["stream_source"], "live_public_ws")
            self.assertGreaterEqual(report["soak"]["uptime_seconds"], 600.0)
            self.assertEqual(report["soak"]["host_id"], "oracle-a1-soak")
            self.assertEqual(report["soak"]["artifact_ids"], ["collector"])
            self.assertEqual(report["phase9a_closeout"]["status"], "ready_to_close")
            self.assertEqual(report["phase9a_closeout"]["checks"]["live_network_soak"]["status"], "pass")
            self.assertEqual(report["blockers"], [])
        finally:
            _clean_tree(root)

    def test_cli_writes_public_ws_soak_closeout_report(self) -> None:
        from engine.execution.paper_collector import PaperWsLiveCollectorConfig, run_paper_ws_collector_live

        root = Path("test-phase1-soak-closeout-cli")
        db_path = root / "state" / "memory.sqlite"
        output_path = root / "soak-closeout.json"
        try:
            artifact_path = _write_artifact(root, artifact_id="collector")

            def fake_connector(_url: str):
                yield {
                    "stream": "btcusdt@aggTrade",
                    "data": {"e": "aggTrade", "E": 1777507200000, "s": "BTCUSDT", "a": 1, "p": "100.10", "q": "2.5"},
                    "received_at_utc": "2026-04-30T00:00:01Z",
                }
                yield {
                    "stream": "btcusdt@bookTicker",
                    "data": {"e": "bookTicker", "E": 1777507201000, "s": "BTCUSDT", "u": 2, "b": "100.00", "B": "3", "a": "100.20", "A": "4"},
                    "received_at_utc": "2026-04-30T00:00:02Z",
                }
                yield {
                    "stream": "btcusdt@depth",
                    "data": {"e": "depthUpdate", "E": 1777507801000, "s": "BTCUSDT", "U": 10, "u": 12, "pu": 9, "b": [["100.00", "3"]], "a": [["100.20", "4"]]},
                    "received_at_utc": "2026-04-30T00:10:01Z",
                }

            run_paper_ws_collector_live(
                PaperWsLiveCollectorConfig(
                    db_path=db_path,
                    artifact_paths=(artifact_path,),
                    session_id="phase1-soak-closeout-cli",
                    host_id="oracle-a1-soak",
                    symbols=("BTCUSDT",),
                    stream_kinds=("aggTrade", "bookTicker", "depth"),
                    max_messages=3,
                    message_source=fake_connector,
                )
            )
            _seed_soak_closeout_evidence(root, db_path, "phase1-soak-closeout-cli")

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "paper-soak-closeout",
                        "--db",
                        str(db_path),
                        "--session-id",
                        "phase1-soak-closeout-cli",
                        "--export-dir",
                        str(root / "backups"),
                        "--restore-db",
                        str(root / "restore" / "memory.sqlite"),
                        "--hosted-repo-dir",
                        str(root / "repo"),
                        "--hosted-state-dir",
                        str(root / "state"),
                        "--hosted-log-dir",
                        str(root / "logs"),
                        "--hosted-backup-dir",
                        str(root / "backups"),
                        "--hosted-template-root",
                        str(root / "deploy"),
                        "--minimum-soak-seconds",
                        "600",
                        "--output",
                        str(output_path),
                    ]
                )

            payload = json.loads(print_mock.call_args.args[0])
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ready_to_close")
            self.assertEqual(report["artifact_type"], "public_ws_soak_closeout")
            self.assertEqual(report["soak"]["stream_source"], "live_public_ws")
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
