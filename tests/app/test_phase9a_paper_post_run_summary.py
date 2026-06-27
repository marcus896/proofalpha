import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.agent.paper_post_run import (
    PaperPostRunSummaryConfig,
    build_paper_post_run_summary,
)
from engine.app.cli import main
from engine.memory.store import initialize_memory_db


def _clean_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _insert_session_fixture(db_path: Path) -> None:
    initialize_memory_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO paper_sessions (
                session_id, host_id, status, started_at_utc, stopped_at_utc,
                heartbeat_at_utc, portfolio_plan_id, symbols_json, streams_json,
                code_hash, config_checksum, payload_json
            ) VALUES (
                'postrun-session', 'oracle-a1-test', 'completed',
                '2026-04-29T00:00:00Z', '2026-04-29T01:00:00Z',
                '2026-04-29T01:00:00Z', 'portfolio-postrun',
                '["BTCUSDT"]', '["aggTrade", "depth"]', 'code-hash',
                'config-hash', '{}'
            )
            """
        )
        for artifact_id in ("weak-art", "steady-art"):
            connection.execute(
                """
                INSERT INTO paper_session_artifacts (
                    session_id, artifact_id, artifact_sha256, lifecycle_state, status, payload_json
                ) VALUES ('postrun-session', ?, ?, 'paper artifact', 'active', ?)
                """,
                (
                    artifact_id,
                    f"sha-{artifact_id}",
                    json.dumps(
                        {
                            "strategy_id": artifact_id,
                            "portfolio_role": "core",
                            "regime_scope": ["chop"],
                        },
                        sort_keys=True,
                    ),
                ),
            )
        connection.execute(
            """
            INSERT INTO paper_session_summaries (
                session_id, created_at_utc, status, uptime_seconds, artifact_count,
                symbol_count, order_count, filled_count, partial_count, rejected_count,
                risk_block_count, funding_fee, paper_pnl, drawdown, telemetry_quality_score,
                payload_json
            ) VALUES (
                'postrun-session', '2026-04-29T01:00:00Z', 'completed',
                3600, 2, 1, 4, 2, 1, 2, 3, 0.0, -12.5, 0.03, 0.44, '{}'
            )
            """
        )
        telemetry_rows = [
            ("t-weak-1", "weak-art", "chop", 50000.0, 50150.0, 30.0, 0, 0),
            ("t-weak-2", "weak-art", "chop", 50000.0, 50200.0, 40.0, 1, 1),
            ("t-weak-3", "weak-art", "trend", 50000.0, 49900.0, -20.0, 1, 1),
            ("t-steady-1", "steady-art", "chop", 50000.0, 50010.0, 2.0, 0, 0),
        ]
        for telemetry_id, artifact_id, regime, expected, live, slip_bps, was_rejected, risk_blocked in telemetry_rows:
            connection.execute(
                """
                INSERT INTO order_telemetry (
                    telemetry_id, symbol, side, qty_submitted, qty_filled,
                    expected_price, live_vwap_price, slip_bps, was_rejected,
                    risk_blocked, metadata_json
                ) VALUES (?, 'BTCUSDT', 'BUY', 1, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telemetry_id,
                    expected,
                    live,
                    slip_bps,
                    was_rejected,
                    risk_blocked,
                    json.dumps(
                        {
                            "session_id": "postrun-session",
                            "raw": {
                                "artifact_id": artifact_id,
                                "regime": regime,
                                "fill_model_v2": {"path": "passive"},
                            },
                        },
                        sort_keys=True,
                    ),
                ),
            )
        risk_events = [
            ("r1", "depth_too_thin", "weak-art"),
            ("r2", "depth_too_thin", "weak-art"),
            ("r3", "spread_too_wide", "steady-art"),
        ]
        for risk_event_id, reason, artifact_id in risk_events:
            connection.execute(
                """
                INSERT INTO risk_events (
                    risk_event_id, ts_utc, reason_code, severity, action, metadata_json
                ) VALUES (?, '2026-04-29T00:30:00Z', ?, 'block', 'block_intent', ?)
                """,
                (
                    risk_event_id,
                    reason,
                    json.dumps(
                        {
                            "session_id": "postrun-session",
                            "intent": {"artifact_id": artifact_id, "symbol": "BTCUSDT"},
                        },
                        sort_keys=True,
                    ),
                ),
            )
        feedback_payload = {
            "artifact_type": "paper_calibration_feedback",
            "status": "sample_guarded",
            "sample_count": 4,
            "guard_reasons": ["bucket BTCUSDT|chop has 3 samples; need 200"],
            "telemetry_quality": {"score": 0.41},
        }
        connection.execute(
            """
            INSERT INTO paper_calibration_feedback (
                artifact_id, session_id, source_model_version, created_at_utc, status,
                telemetry_quality_score, sample_count, artifact_sha256, payload_json
            ) VALUES (
                'paper-feedback-fixture', 'postrun-session', 'cost-v1',
                '2026-04-29T01:00:00Z', 'sample_guarded', 0.41, 4, 'sha-feedback', ?
            )
            """,
            (json.dumps(feedback_payload, sort_keys=True),),
        )
        connection.commit()
    finally:
        connection.close()


class Phase9APaperPostRunSummaryTest(unittest.TestCase):
    def test_builds_compact_agent_post_run_summary_from_session_telemetry(self) -> None:
        root = Path("test-phase9a-postrun")
        db_path = root / "memory.sqlite"
        try:
            _insert_session_fixture(db_path)

            summary = build_paper_post_run_summary(
                PaperPostRunSummaryConfig(db_path=db_path, session_id="postrun-session", max_items=2)
            )

            self.assertEqual(summary["artifact_type"], "paper_post_run_summary")
            self.assertEqual(summary["session_id"], "postrun-session")
            self.assertEqual(summary["status"], "actionable")
            self.assertEqual(summary["top_failure_reasons"][0], {"reason_code": "depth_too_thin", "count": 2})
            self.assertEqual(summary["weak_artifacts"][0]["artifact_id"], "weak-art")
            self.assertGreater(summary["fill_model_mismatch"]["max_abs_mismatch_bps"], 25.0)
            self.assertEqual(summary["risk_block_clusters"][0]["artifact_id"], "weak-art")
            self.assertEqual(summary["regime_performance"]["chop"]["order_count"], 3)
            self.assertFalse(summary["calibration_readiness"]["ready_for_model_update"])
            self.assertIn("collect_more_paper_samples", summary["suggested_next_experiments"])

            connection = sqlite3.connect(db_path)
            try:
                raw_payload = connection.execute(
                    "SELECT payload_json FROM paper_session_summaries WHERE session_id = 'postrun-session'"
                ).fetchone()[0]
            finally:
                connection.close()
            payload = json.loads(raw_payload)
            self.assertEqual(payload["agent_post_run_summary"]["artifact_id"], summary["artifact_id"])
        finally:
            _clean_tree(root)

    def test_cli_writes_post_run_summary_artifact(self) -> None:
        root = Path("test-phase9a-postrun-cli")
        db_path = root / "memory.sqlite"
        output_path = root / "postrun-summary.json"
        try:
            _insert_session_fixture(db_path)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "paper-post-run-summary",
                        "--db",
                        str(db_path),
                        "--session-id",
                        "postrun-session",
                        "--output",
                        str(output_path),
                        "--max-items",
                        "2",
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            artifact = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "actionable")
            self.assertEqual(printed["output"], str(output_path))
            self.assertEqual(artifact["artifact_type"], "paper_post_run_summary")
            self.assertEqual(artifact["suggested_next_experiments"][0], "investigate_depth_too_thin_blocks")
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
