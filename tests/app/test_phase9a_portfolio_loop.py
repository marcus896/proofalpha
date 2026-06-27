import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.memory.store import initialize_memory_db
from engine.portfolio.paper_loop import (
    PaperPortfolioLoopConfig,
    build_paper_portfolio_loop_input,
    run_paper_portfolio_allocator_tick,
)


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _seed_session(connection: sqlite3.Connection, session_id: str) -> None:
    connection.execute(
        """
        INSERT INTO paper_sessions (
            session_id, host_id, status, started_at_utc, heartbeat_at_utc,
            symbols_json, streams_json, code_hash, config_checksum, payload_json
        ) VALUES (?, 'host-a', 'running', '2026-04-29T00:00:00Z', '2026-04-29T00:00:00Z',
            '["BTCUSDT","ETHUSDT"]', '[]', 'code', 'config', '{}')
        """,
        (session_id,),
    )


def _seed_artifact(
    connection: sqlite3.Connection,
    session_id: str,
    artifact_id: str,
    *,
    symbol: str,
    role: str = "core",
    target_notional: float = 50_000.0,
    max_notional: float = 70_000.0,
    regime_scope: tuple[str, ...] = ("bull", "neutral"),
    correlation_by_artifact: dict[str, float] | None = None,
) -> None:
    payload = {
        "symbol_scope": [symbol],
        "regime_scope": list(regime_scope),
        "portfolio_role": role,
        "target_notional": target_notional,
        "max_notional": max_notional,
        "expected_return_bps": 14.0,
        "max_drawdown": 0.05,
        "correlation_by_artifact": dict(correlation_by_artifact or {}),
        "stress_loss_by_scenario": {"medium": 0.04},
    }
    connection.execute(
        """
        INSERT INTO artifacts (
            artifact_id, strategy_id, variant_id, family, venue, signal_tf,
            execution_tf, validation_report_id, code_sha, artifact_sha256,
            rollout_stage, approved, payload_json
        ) VALUES (?, ?, 'variant', 'momentum', 'binance_usdm', '1h', '15m',
            'validation', 'code', ?, 'paper', 1, ?)
        """,
        (artifact_id, f"strategy-{artifact_id}", f"sha-{artifact_id}", json.dumps(payload, sort_keys=True)),
    )
    connection.execute(
        """
        INSERT INTO paper_session_artifacts (
            session_id, artifact_id, artifact_sha256, lifecycle_state, status, payload_json
        ) VALUES (?, ?, ?, 'paper', 'active', ?)
        """,
        (session_id, artifact_id, f"sha-{artifact_id}", json.dumps(payload, sort_keys=True)),
    )


def _seed_metric(connection: sqlite3.Connection, artifact_id: str, metric_name: str, value: float) -> None:
    connection.execute(
        """
        INSERT INTO live_metrics (metric_id, artifact_id, ts_utc, metric_name, metric_value, payload_json)
        VALUES (?, ?, '2026-04-29T00:00:00Z', ?, ?, '{"source":"paper_executor"}')
        """,
        (f"{artifact_id}:{metric_name}", artifact_id, metric_name, value),
    )


def _seed_filled_exposure(connection: sqlite3.Connection, session_id: str, artifact_id: str, symbol: str, notional: float) -> None:
    connection.execute(
        """
        INSERT INTO order_telemetry (
            telemetry_id, symbol, side, qty_submitted, qty_filled, expected_price,
            live_vwap_price, slip_bps, was_rejected, risk_blocked, metadata_json
        ) VALUES (?, ?, 'BUY', 1, 1, ?, ?, 1.0, 0, 0, ?)
        """,
        (
            f"{artifact_id}:paper:exposure",
            symbol,
            notional,
            notional,
            json.dumps({"session_id": session_id, "raw": {"artifact_id": artifact_id}}, sort_keys=True),
        ),
    )


class Phase9APortfolioPaperLoopTests(unittest.TestCase):
    def test_loop_resizes_targets_from_current_exposure_and_journals_decision(self) -> None:
        root = Path("test-phase9a-portfolio-loop")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                _seed_session(connection, "paper-loop-session")
                _seed_artifact(connection, "paper-loop-session", "core-btc", symbol="BTCUSDT", target_notional=50_000.0)
                _seed_metric(connection, "core-btc", "paper_live_sample_count", 20)
                _seed_metric(connection, "core-btc", "paper_live_max_abs_slip_bps", 4.0)
                _seed_filled_exposure(connection, "paper-loop-session", "core-btc", "BTCUSDT", 75_000.0)
                connection.commit()
            finally:
                connection.close()

            result = run_paper_portfolio_allocator_tick(
                PaperPortfolioLoopConfig(
                    db_path=db_path,
                    session_id="paper-loop-session",
                    constraints={
                        "equity": 150_000.0,
                        "max_per_symbol_exposure": 100_000.0,
                        "max_aggregate_leverage": 1.0,
                        "drawdown_budget": 0.20,
                        "max_pairwise_correlation": 0.75,
                    },
                    active_regimes={"BTCUSDT": "bull"},
                    min_calibration_samples=10,
                    max_paper_slip_bps=10.0,
                    interval_seconds=900,
                )
            )

            connection = sqlite3.connect(db_path)
            try:
                plan_row = connection.execute("SELECT status, payload_json FROM portfolio_plans").fetchone()
                decision_row = connection.execute(
                    "SELECT session_id, portfolio_plan_id, status, payload_json FROM paper_portfolio_decisions"
                ).fetchone()
                linked_plan = connection.execute(
                    "SELECT portfolio_plan_id FROM paper_sessions WHERE session_id = 'paper-loop-session'"
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(result["status"], "accepted")
            self.assertEqual(result["current_exposure_by_symbol"], {"BTCUSDT": 75_000.0})
            self.assertEqual(result["resized_targets"]["core-btc"], 25_000.0)
            self.assertEqual(plan_row[0], "accepted")
            self.assertEqual(json.loads(plan_row[1])["allocations"][0]["notional"], 25_000.0)
            self.assertEqual(decision_row[0], "paper-loop-session")
            self.assertEqual(decision_row[2], "accepted")
            self.assertEqual(linked_plan, result["portfolio_plan_id"])
        finally:
            _clean_tree(root)

    def test_loop_rejects_crowding_and_sample_guarded_artifacts(self) -> None:
        root = Path("test-phase9a-portfolio-loop-reject")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                _seed_session(connection, "paper-loop-reject")
                _seed_artifact(connection, "paper-loop-reject", "core-btc", symbol="BTCUSDT", role="core")
                _seed_artifact(
                    connection,
                    "paper-loop-reject",
                    "crowded-btc",
                    symbol="BTCUSDT",
                    role="opportunistic",
                    correlation_by_artifact={"core-btc": 0.95},
                )
                _seed_artifact(connection, "paper-loop-reject", "thin-eth", symbol="ETHUSDT", role="defensive")
                _seed_metric(connection, "core-btc", "paper_live_sample_count", 30)
                _seed_metric(connection, "core-btc", "paper_live_max_abs_slip_bps", 3.0)
                _seed_metric(connection, "crowded-btc", "paper_live_sample_count", 30)
                _seed_metric(connection, "crowded-btc", "paper_live_max_abs_slip_bps", 3.0)
                _seed_metric(connection, "thin-eth", "paper_live_sample_count", 2)
                _seed_metric(connection, "thin-eth", "paper_live_max_abs_slip_bps", 3.0)
                connection.commit()
            finally:
                connection.close()

            result = run_paper_portfolio_allocator_tick(
                PaperPortfolioLoopConfig(
                    db_path=db_path,
                    session_id="paper-loop-reject",
                    constraints={
                        "equity": 200_000.0,
                        "max_per_symbol_exposure": 120_000.0,
                        "max_aggregate_leverage": 1.0,
                        "drawdown_budget": 0.20,
                        "max_pairwise_correlation": 0.75,
                    },
                    active_regimes={"BTCUSDT": "bull", "ETHUSDT": "neutral"},
                    min_calibration_samples=10,
                    max_paper_slip_bps=10.0,
                )
            )

            rejection_reasons = {row["artifact_id"]: row["reason_code"] for row in result["rejections"]}
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(rejection_reasons["crowded-btc"], "correlation_crowding")
            self.assertEqual(rejection_reasons["thin-eth"], "artifact_not_active")
            self.assertIn("insufficient_paper_samples:2<10", result["loop_rejections"]["thin-eth"])
        finally:
            _clean_tree(root)

    def test_cli_paper_portfolio_loop_reads_input_persists_and_writes_output(self) -> None:
        root = Path("test-phase9a-portfolio-loop-cli")
        db_path = root / "memory.sqlite"
        input_path = root / "loop-input.json"
        output_path = root / "loop-output.json"
        try:
            root.mkdir(parents=True)
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                _seed_session(connection, "paper-loop-cli")
                _seed_artifact(connection, "paper-loop-cli", "core-btc", symbol="BTCUSDT")
                _seed_metric(connection, "core-btc", "paper_live_sample_count", 15)
                _seed_metric(connection, "core-btc", "paper_live_max_abs_slip_bps", 2.0)
                connection.commit()
            finally:
                connection.close()
            input_path.write_text(
                json.dumps(
                    {
                        "constraints": {
                            "equity": 100_000.0,
                            "max_per_symbol_exposure": 90_000.0,
                            "max_aggregate_leverage": 1.0,
                            "drawdown_budget": 0.20,
                            "max_pairwise_correlation": 0.75,
                        },
                        "active_regimes": {"BTCUSDT": "bull"},
                        "min_calibration_samples": 10,
                        "max_paper_slip_bps": 10.0,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "paper-portfolio-loop",
                        "--db",
                        str(db_path),
                        "--session-id",
                        "paper-loop-cli",
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                    ]
                )

            payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "accepted")
            self.assertTrue(output_path.exists())
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["portfolio_plan_id"], payload["portfolio_plan_id"])
            self.assertEqual(build_paper_portfolio_loop_input(input_path)["active_regimes"], {"BTCUSDT": "bull"})
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
