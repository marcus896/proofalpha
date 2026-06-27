import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.execution.paper_hosting import write_hosted_paper_ops_templates
from engine.memory.store import initialize_memory_db


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _seed_closeout_session(root: Path, db_path: Path, session_id: str = "phase9a-closeout-session") -> None:
    initialize_memory_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO paper_sessions (
                session_id, host_id, status, started_at_utc, stopped_at_utc, heartbeat_at_utc,
                portfolio_plan_id, symbols_json, streams_json, code_hash, config_checksum, payload_json
            ) VALUES (?, 'oracle-a1-closeout', 'completed', '2026-04-27T00:00:00Z',
                '2026-04-30T00:00:00Z', '2026-04-30T00:00:00Z', 'portfolio-closeout',
                '["BTCUSDT"]', '["btcusdt@aggTrade","btcusdt@bookTicker","btcusdt@depth"]',
                'code', 'config', ?)
            """,
            (
                session_id,
                json.dumps(
                    {
                        "mode": "fixture_public_ws",
                        "private_keys_required": False,
                        "live_order_path_enabled": False,
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO artifacts (
                artifact_id, strategy_id, variant_id, family, venue, signal_tf, execution_tf,
                validation_report_id, code_sha, artifact_sha256, rollout_stage, approved, payload_json
            ) VALUES ('artifact-closeout', 'strategy-closeout', 'variant-closeout', 'momentum',
                'binance_usdm', '1h', '15m', 'validation', 'code', 'artifact-sha',
                'paper', 1, ?)
            """,
            (
                json.dumps(
                    {
                        "symbol_scope": ["BTCUSDT"],
                        "regime_scope": ["trend", "neutral"],
                        "portfolio_role": "core",
                        "target_notional": 1000.0,
                        "max_notional": 1000.0,
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO paper_session_artifacts (
                session_id, artifact_id, artifact_sha256, lifecycle_state, status, payload_json
            ) VALUES (?, 'artifact-closeout', 'artifact-sha', 'paper', 'active', ?)
            """,
            (session_id, json.dumps({"portfolio_role": "core", "regime_scope": ["trend"]}, sort_keys=True)),
        )
        stream_rows = [
            (
                "s1",
                "btcusdt@aggTrade",
                "101",
                {"e": "aggTrade", "E": 1777507200000, "s": "BTCUSDT", "a": 101, "p": "100.10", "q": "2.0"},
            ),
            (
                "s2",
                "btcusdt@bookTicker",
                "102",
                {"e": "bookTicker", "E": 1777507201000, "s": "BTCUSDT", "u": 102, "b": "100.00", "B": "3", "a": "100.20", "A": "4"},
            ),
            (
                "s3",
                "btcusdt@depth",
                "103",
                {"e": "depthUpdate", "E": 1777507202000, "s": "BTCUSDT", "U": 101, "u": 103, "pu": 100, "b": [["100.00", "3"]], "a": [["100.20", "4"]]},
            ),
        ]
        for event_id, stream_name, sequence_id, payload in stream_rows:
            connection.execute(
                """
                INSERT INTO paper_stream_events (
                    stream_event_id, session_id, received_at_utc, exchange_event_time, stream_name,
                    symbol, sequence_id, payload_hash, payload_json, parse_status, lag_ms, metadata_json
                ) VALUES (?, ?, '2026-04-30T00:00:03Z', '2026-04-30T00:00:02Z',
                    ?, 'BTCUSDT', ?, ?, ?, 'parsed', 1000.0, ?)
                """,
                (
                    event_id,
                    session_id,
                    stream_name,
                    sequence_id,
                    f"hash-{event_id}",
                    json.dumps(payload, sort_keys=True),
                    json.dumps({"source": "paper_ws_collector"}, sort_keys=True),
                ),
            )
        for idx in range(3):
            connection.execute(
                """
                INSERT INTO order_telemetry (
                    telemetry_id, symbol, side, qty_submitted, qty_filled, qty_canceled,
                    expected_price, live_vwap_price, slip_bps, spread_bps, topn_depth,
                    latency_rtt_ms, maker_ratio, was_rejected, risk_blocked, metadata_json
                ) VALUES (?, 'BTCUSDT', 'BUY', 1, 1, 0, 100.0, 100.05, 5.0, 2.0,
                    20.0, 50.0, 0.5, 0, 0, ?)
                """,
                (
                    f"telemetry-{idx}",
                    json.dumps(
                        {
                            "session_id": session_id,
                            "artifact_id": "artifact-closeout",
                            "raw": {"artifact_id": "artifact-closeout", "regime": "trend"},
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
            INSERT INTO paper_session_summaries (
                session_id, created_at_utc, status, uptime_seconds, artifact_count, symbol_count,
                order_count, filled_count, partial_count, rejected_count, risk_block_count,
                funding_fee, paper_pnl, drawdown, telemetry_quality_score, payload_json
            ) VALUES (?, '2026-04-30T00:00:00Z', 'completed', 259200, 1, 1, 3, 3, 0, 0, 0, 0, 1.25, 0, 1.0, '{}')
            """,
            (session_id,),
        )
        connection.execute(
            """
            INSERT INTO paper_calibration_feedback (
                artifact_id, session_id, source_model_version, created_at_utc, status,
                telemetry_quality_score, sample_count, artifact_sha256, payload_json
            ) VALUES ('feedback-closeout', ?, 'cost-v1', '2026-04-30T00:00:00Z',
                'feedback_ready', 1.0, 3, 'feedback-sha', ?)
            """,
            (
                session_id,
                json.dumps(
                    {
                        "live_promotion_allowed": False,
                        "can_lower_live_costs": False,
                        "model_update_allowed": True,
                        "guard_reasons": [],
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO paper_portfolio_decisions (
                decision_id, session_id, portfolio_plan_id, ts_utc, interval_seconds,
                status, reason_code, payload_json
            ) VALUES ('decision-closeout', ?, 'portfolio-closeout', '2026-04-30T00:00:00Z',
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


class Phase9ACloseoutTests(unittest.TestCase):
    def test_closeout_report_validates_local_phase9a_proof_without_private_keys(self) -> None:
        from engine.execution.paper_closeout import Phase9ACloseoutConfig, build_phase9a_closeout_report

        root = Path("test-phase9a-closeout")
        db_path = root / "state" / "memory.sqlite"
        try:
            _seed_closeout_session(root, db_path)

            report = build_phase9a_closeout_report(
                Phase9ACloseoutConfig(
                    db_path=db_path,
                    session_id="phase9a-closeout-session",
                    export_dir=root / "backups",
                    restore_db_path=root / "restore" / "memory.sqlite",
                    hosted_repo_dir=root / "repo",
                    hosted_state_dir=root / "state",
                    hosted_log_dir=root / "logs",
                    hosted_backup_dir=root / "backups",
                    hosted_template_root=root / "deploy",
                    minimum_soak_seconds=0,
                    require_live_network_soak=False,
                )
            )

            self.assertEqual(report["status"], "ready_to_close")
            self.assertEqual(report["artifact_type"], "phase9a_closeout_report")
            self.assertFalse(report["requires_private_keys"])
            self.assertFalse(report["live_order_path_enabled"])
            self.assertEqual(report["checks"]["artifact_only"]["status"], "pass")
            self.assertEqual(report["checks"]["public_ws_recording"]["status"], "pass")
            self.assertEqual(report["checks"]["replay_determinism"]["status"], "pass")
            self.assertEqual(report["checks"]["export_restore"]["status"], "pass")
            self.assertEqual(report["checks"]["hosted_ops"]["status"], "pass")
            self.assertEqual(report["checks"]["paper_feedback_governance"]["status"], "pass")
            self.assertEqual(report["checks"]["portfolio_loop"]["status"], "pass")
            self.assertEqual(report["checks"]["live_network_soak"]["status"], "not_required")
            self.assertEqual(report["blockers"], [])
            self.assertTrue(Path(report["artifacts"]["export_manifest_path"]).exists())
            self.assertEqual(len(report["artifact_sha256"]), 64)
        finally:
            _clean_tree(root)

    def test_closeout_reports_blocker_when_real_live_network_soak_is_required_but_absent(self) -> None:
        from engine.execution.paper_closeout import Phase9ACloseoutConfig, build_phase9a_closeout_report

        root = Path("test-phase9a-closeout-blocked")
        db_path = root / "state" / "memory.sqlite"
        try:
            _seed_closeout_session(root, db_path)

            report = build_phase9a_closeout_report(
                Phase9ACloseoutConfig(
                    db_path=db_path,
                    session_id="phase9a-closeout-session",
                    export_dir=root / "backups",
                    restore_db_path=root / "restore" / "memory.sqlite",
                    hosted_repo_dir=root / "repo",
                    hosted_state_dir=root / "state",
                    hosted_log_dir=root / "logs",
                    hosted_backup_dir=root / "backups",
                    hosted_template_root=root / "deploy",
                    minimum_soak_seconds=259200,
                    require_live_network_soak=True,
                )
            )

            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["checks"]["live_network_soak"]["status"], "blocked")
            self.assertIn("real_live_public_ws_soak_not_observed", report["blockers"])
        finally:
            _clean_tree(root)

    def test_cli_writes_phase9a_closeout_report(self) -> None:
        root = Path("test-phase9a-closeout-cli")
        db_path = root / "state" / "memory.sqlite"
        output_path = root / "closeout.json"
        try:
            _seed_closeout_session(root, db_path, session_id="phase9a-closeout-cli")

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "paper-phase9a-closeout",
                        "--db",
                        str(db_path),
                        "--session-id",
                        "phase9a-closeout-cli",
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
                        "--output",
                        str(output_path),
                    ]
                )

            payload = json.loads(print_mock.call_args.args[0])
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ready_to_close")
            self.assertEqual(report["artifact_type"], "phase9a_closeout_report")
            self.assertEqual(report["session_id"], "phase9a-closeout-cli")
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
