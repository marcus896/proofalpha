import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.calibration.paper_feedback import (
    PaperCalibrationFeedbackConfig,
    build_paper_calibration_feedback,
    write_paper_calibration_feedback_artifact,
)
from engine.memory.store import initialize_memory_db


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _seed_session(connection: sqlite3.Connection, session_id: str) -> None:
    connection.execute(
        """
        INSERT INTO paper_sessions (
            session_id, host_id, status, started_at_utc, heartbeat_at_utc,
            symbols_json, streams_json, code_hash, config_checksum, payload_json
        ) VALUES (?, 'host-a', 'completed', '2026-04-29T00:00:00Z', '2026-04-29T00:10:00Z',
            '["BTCUSDT"]', '["aggTrade","bookTicker","depth"]', 'code', 'config', '{}')
        """,
        (session_id,),
    )


def _seed_order(
    connection: sqlite3.Connection,
    telemetry_id: str,
    *,
    session_id: str,
    symbol: str = "BTCUSDT",
    regime: str = "trend",
    qty_submitted: float = 2.0,
    qty_filled: float = 1.5,
    expected_price: float = 100.0,
    live_vwap_price: float = 100.12,
    slip_bps: float = 12.0,
    spread_bps: float = 3.0,
    latency_ms: float = 40.0,
    topn_depth: float = 25.0,
    adv_notional: float = 50_000.0,
) -> None:
    connection.execute(
        """
        INSERT INTO order_telemetry (
            telemetry_id, symbol, side, qty_submitted, qty_filled, qty_canceled,
            expected_price, live_vwap_price, slip_bps, spread_bps, topn_depth,
            latency_rtt_ms, maker_ratio, was_rejected, risk_blocked, metadata_json
        ) VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.25, 0, 0, ?)
        """,
        (
            telemetry_id,
            symbol,
            qty_submitted,
            qty_filled,
            max(0.0, qty_submitted - qty_filled),
            expected_price,
            live_vwap_price,
            slip_bps,
            spread_bps,
            topn_depth,
            latency_ms,
            json.dumps(
                {
                    "session_id": session_id,
                    "regime": regime,
                    "adv_notional": adv_notional,
                    "modeled_fill_price": expected_price,
                    "opportunity_loss_bps": 2.0,
                    "funding_window": False,
                },
                sort_keys=True,
            ),
        ),
    )


def _seed_stream(
    connection: sqlite3.Connection,
    stream_event_id: str,
    *,
    session_id: str,
    stream_name: str,
    symbol: str = "BTCUSDT",
    lag_ms: float = 25.0,
    parse_status: str = "parsed",
    metadata: dict[str, object] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO paper_stream_events (
            stream_event_id, session_id, received_at_utc, exchange_event_time, stream_name,
            symbol, sequence_id, payload_hash, payload_json, parse_status, lag_ms, metadata_json
        ) VALUES (?, ?, '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z', ?, ?, '1',
            ?, '{}', ?, ?, ?)
        """,
        (
            stream_event_id,
            session_id,
            stream_name,
            symbol,
            f"hash-{stream_event_id}",
            parse_status,
            lag_ms,
            json.dumps(metadata or {}, sort_keys=True),
        ),
    )


class Phase9APaperCalibrationFeedbackTests(unittest.TestCase):
    def test_feedback_builds_conservative_priors_quality_score_and_never_approves_live(self) -> None:
        root = Path("test-phase9a-paper-calibration")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                _seed_session(connection, "cal-session")
                for idx in range(6):
                    _seed_order(connection, f"t{idx}", session_id="cal-session", qty_filled=1.0 + (idx % 2) * 0.5)
                _seed_stream(connection, "s1", session_id="cal-session", stream_name="aggTrade")
                _seed_stream(connection, "s2", session_id="cal-session", stream_name="bookTicker")
                _seed_stream(connection, "s3", session_id="cal-session", stream_name="depth", metadata={"gap_count": 1})
                connection.execute(
                    """
                    INSERT INTO funding_events (
                        funding_event_id, ts_utc, symbol, position_notional, funding_rate, funding_fee, metadata_json
                    ) VALUES ('funding-1', '2026-04-29T00:00:00Z', 'BTCUSDT', 1000, 0.0002, 0.2, ?)
                    """,
                    (json.dumps({"session_id": "cal-session"}, sort_keys=True),),
                )
                connection.commit()
            finally:
                connection.close()

            feedback = build_paper_calibration_feedback(
                PaperCalibrationFeedbackConfig(
                    db_path=db_path,
                    session_id="cal-session",
                    source_model_version="cost-v1",
                    minimum_samples_per_bucket=3,
                    shrinkage_alpha=0.10,
                )
            )

            self.assertEqual(feedback["artifact_type"], "paper_calibration_feedback")
            self.assertEqual(feedback["status"], "feedback_ready")
            self.assertEqual(feedback["live_promotion_allowed"], False)
            self.assertEqual(feedback["can_lower_live_costs"], False)
            self.assertIn("paper_feedback_never_approves_live", feedback["governance_notes"])
            self.assertGreater(feedback["telemetry_quality"]["score"], 0.0)
            self.assertEqual(feedback["telemetry_quality"]["sample_count"], 6)
            self.assertEqual(feedback["priors"]["spread_bps"]["sample_mean"], 3.0)
            self.assertEqual(feedback["priors"]["latency_ms"]["sample_mean"], 40.0)
            self.assertLess(feedback["priors"]["queue_fill_probability"]["shrunk_value"], 1.0)
            self.assertGreater(feedback["priors"]["funding_shock_bps"]["sample_mean"], 0.0)
            self.assertIn("BTCUSDT|trend", feedback["bucket_counts"])
            self.assertEqual(len(feedback["artifact_sha256"]), 64)
        finally:
            _clean_tree(root)

    def test_feedback_sample_guard_blocks_model_update_questions_but_still_reports_quality(self) -> None:
        root = Path("test-phase9a-paper-calibration-guard")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                _seed_session(connection, "guard-session")
                _seed_order(connection, "t1", session_id="guard-session")
                _seed_stream(connection, "bad-stream", session_id="guard-session", stream_name="aggTrade", parse_status="error", lag_ms=500.0)
                connection.commit()
            finally:
                connection.close()

            feedback = build_paper_calibration_feedback(
                PaperCalibrationFeedbackConfig(
                    db_path=db_path,
                    session_id="guard-session",
                    source_model_version="cost-v1",
                    minimum_samples_per_bucket=5,
                )
            )

            self.assertEqual(feedback["status"], "sample_guarded")
            self.assertIn("insufficient_bucket_sample:BTCUSDT|trend", feedback["guard_reasons"])
            self.assertIn("missing_stream:bookTicker", feedback["telemetry_quality"]["issues"])
            self.assertFalse(feedback["model_update_allowed"])
            self.assertFalse(feedback["live_promotion_allowed"])
        finally:
            _clean_tree(root)

    def test_cli_writes_feedback_artifact_and_persists_manifest_row(self) -> None:
        root = Path("test-phase9a-paper-calibration-cli")
        db_path = root / "memory.sqlite"
        output_path = root / "paper-feedback.json"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                _seed_session(connection, "cli-session")
                for idx in range(4):
                    _seed_order(connection, f"t{idx}", session_id="cli-session")
                _seed_stream(connection, "s1", session_id="cli-session", stream_name="aggTrade")
                _seed_stream(connection, "s2", session_id="cli-session", stream_name="bookTicker")
                _seed_stream(connection, "s3", session_id="cli-session", stream_name="depth")
                connection.commit()
            finally:
                connection.close()

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "paper-calibration-feedback",
                        "--db",
                        str(db_path),
                        "--session-id",
                        "cli-session",
                        "--output",
                        str(output_path),
                        "--minimum-samples-per-bucket",
                        "3",
                    ]
                )

            payload = json.loads(print_mock.call_args.args[0])
            artifact = json.loads(output_path.read_text(encoding="utf-8"))
            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    "SELECT artifact_id, session_id, status FROM paper_calibration_feedback"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "feedback_ready")
            self.assertEqual(artifact["artifact_type"], "paper_calibration_feedback")
            self.assertEqual(row[0], artifact["artifact_id"])
            self.assertEqual(row[1], "cli-session")
            self.assertEqual(row[2], "feedback_ready")

            write_paper_calibration_feedback_artifact(output_path, artifact)
            self.assertTrue(output_path.exists())
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
