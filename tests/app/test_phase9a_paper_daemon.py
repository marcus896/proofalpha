import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.execution.paper_daemon import (
    PaperDaemonDryRunConfig,
    PaperRiskLimits,
    load_paper_status,
    run_paper_daemon_dry_run,
)
from engine.memory.store import initialize_memory_db
from engine.strategy.artifacts import build_strategy_artifact, write_strategy_artifact


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _valid_artifact_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "strategy_id": "strategy-phase9a",
        "family": "momentum",
        "variant_id": "variant-phase9a",
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
        "created_at_utc": "2026-04-26T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _write_fixture(root: Path) -> Path:
    fixture_path = root / "market-fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "order_intents": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "qty": 1.0,
                        "expected_price": 100.0,
                        "limit_price": 100.5,
                        "order_type": "limit",
                        "post_only": True,
                    },
                    {
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "qty": 50.0,
                        "expected_price": 100.0,
                        "order_type": "market",
                    },
                ],
                "market_snapshots": [
                    {
                        "ts": "2026-04-26T00:00:00Z",
                        "symbol": "BTCUSDT",
                        "bid": 99.9,
                        "ask": 100.1,
                        "last_trade_price": 100.0,
                        "traded_qty_at_price": 2.0,
                        "canceled_ahead_qty": 0.0,
                        "depth_ahead_qty": 0.0,
                        "visible_depth_qty": 5.0,
                        "topn_depth_qty": 10.0,
                        "funding_rate": 0.0001,
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return fixture_path


class Phase9APaperDaemonTests(unittest.TestCase):
    def test_memory_schema_adds_paper_session_tables(self) -> None:
        root = Path("test-phase9a-schema")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertIn("paper_sessions", tables)
            self.assertIn("paper_session_artifacts", tables)
            self.assertIn("paper_stream_events", tables)
            self.assertIn("paper_session_summaries", tables)
        finally:
            _clean_tree(root)

    def test_paper_daemon_dry_run_records_session_status_and_risk_events(self) -> None:
        root = Path("test-phase9a-daemon")
        db_path = root / "memory.sqlite"
        try:
            artifact = build_strategy_artifact(_valid_artifact_payload())
            artifact_path = write_strategy_artifact(root / "artifact.strategy-artifact.json", artifact)
            fixture_path = _write_fixture(root)

            status = run_paper_daemon_dry_run(
                PaperDaemonDryRunConfig(
                    db_path=db_path,
                    artifact_paths=(artifact_path,),
                    market_fixture_path=fixture_path,
                    session_id="paper-test-session",
                    host_id="oracle-a1-test",
                    risk_limits=PaperRiskLimits(max_per_symbol_notional=200.0, max_spread_bps=25.0),
                )
            )

            connection = sqlite3.connect(db_path)
            try:
                events = [
                    row[0]
                    for row in connection.execute(
                        "SELECT event_type FROM execution_events ORDER BY event_id"
                    ).fetchall()
                ]
                risk = connection.execute(
                    "SELECT reason_code FROM risk_events"
                ).fetchall()
                session = connection.execute(
                    "SELECT status, host_id FROM paper_sessions WHERE session_id = 'paper-test-session'"
                ).fetchone()
                artifacts = connection.execute(
                    "SELECT artifact_id, status FROM paper_session_artifacts"
                ).fetchall()
                stream_count = connection.execute("SELECT COUNT(*) FROM paper_stream_events").fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["summary"]["risk_block_count"], 2)
            self.assertEqual(status["telemetry"]["order_rows"], 1)
            self.assertIn("ENGINE_START", events)
            self.assertIn("RISK_BLOCK", events)
            self.assertIn("ENGINE_STOP", events)
            self.assertEqual(risk, [("max_per_symbol_exposure",), ("depth_too_thin",)])
            self.assertEqual(session, ("completed", "oracle-a1-test"))
            self.assertEqual(artifacts, [(artifact["artifact_id"], "active")])
            self.assertEqual(stream_count, 1)

            loaded = load_paper_status(db_path, session_id="paper-test-session")
            self.assertEqual(loaded["risk"]["risk_block_count"], 2)
            self.assertEqual(loaded["calibration"]["sample_counts"], {"BTCUSDT": 1})
        finally:
            _clean_tree(root)

    def test_cli_paper_daemon_and_paper_status(self) -> None:
        root = Path("test-phase9a-cli")
        db_path = root / "memory.sqlite"
        try:
            artifact = build_strategy_artifact(_valid_artifact_payload())
            artifact_path = write_strategy_artifact(root / "artifact.strategy-artifact.json", artifact)
            fixture_path = _write_fixture(root)

            with mock.patch("builtins.print") as print_mock:
                self.assertEqual(
                    main(
                        [
                            "paper-daemon",
                            "--dry-run",
                            "--db",
                            str(db_path),
                            "--artifact",
                            str(artifact_path),
                            "--market-fixture",
                            str(fixture_path),
                            "--session-id",
                            "paper-cli-session",
                            "--max-per-symbol-notional",
                            "200",
                        ]
                    ),
                    0,
                )
            daemon_payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(daemon_payload["status"], "completed")

            with mock.patch("builtins.print") as print_mock:
                self.assertEqual(
                    main(["paper-status", "--db", str(db_path), "--session-id", "paper-cli-session"]),
                    0,
                )
            status_payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(status_payload["summary"]["risk_block_count"], 2)
            self.assertEqual(status_payload["session"]["session_id"], "paper-cli-session")
        finally:
            _clean_tree(root)
