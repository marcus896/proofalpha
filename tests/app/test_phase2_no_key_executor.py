import json
import shutil
import sqlite3
import unittest
from pathlib import Path

from engine.app.cli import main


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


class Phase2NoKeyExecutorTests(unittest.TestCase):
    def test_fake_gateway_records_required_private_execution_events_without_keys(self) -> None:
        from engine.execution.no_key_executor import (
            NoKeyExecutorConfig,
            NoKeyOrderRequest,
            run_no_key_executor_fixture,
        )

        root = Path("test-phase2-no-key-normal")
        db_path = root / "memory.sqlite"
        try:
            result = run_no_key_executor_fixture(
                NoKeyExecutorConfig(db_path=db_path, scenario_id="normal", session_id="phase2-normal"),
                order_requests=[
                    NoKeyOrderRequest(
                        symbol="BTCUSDT",
                        side="BUY",
                        qty=2.0,
                        price=100.0,
                        client_order_id="phase2-order-1",
                    )
                ],
            )

            connection = sqlite3.connect(db_path)
            try:
                event_types = [
                    row[0]
                    for row in connection.execute(
                        "SELECT event_type FROM execution_events ORDER BY event_id"
                    ).fetchall()
                ]
                order_row = connection.execute(
                    "SELECT status, filled_qty, order_id_exchange FROM orders_live WHERE order_id_client = ?",
                    ("phase2-order-1",),
                ).fetchone()
                position_row = connection.execute(
                    "SELECT symbol, net_qty, entry_price FROM positions WHERE symbol = 'BTCUSDT'"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(result["status"], "completed")
            self.assertFalse(result["private_keys_required"])
            self.assertFalse(result["live_order_path_enabled"])
            self.assertTrue(result["projection"]["replay_deterministic"])
            self.assertIn("ENGINE_START", event_types)
            self.assertIn("ORDER_SUBMIT", event_types)
            self.assertIn("ORDER_ACK", event_types)
            self.assertIn("FILL", event_types)
            self.assertIn("POSITION_RECONCILE", event_types)
            self.assertIn("ENGINE_STOP", event_types)
            self.assertEqual(order_row, ("FILLED", 2.0, "fake-1001"))
            self.assertEqual(position_row, ("BTCUSDT", 2.0, 100.0))
        finally:
            _clean_tree(root)

    def test_chaos_replay_covers_required_cases_and_dedupes_duplicate_fills(self) -> None:
        from engine.execution.no_key_executor import (
            NoKeyExecutorConfig,
            NoKeyOrderRequest,
            run_phase2_chaos_replay,
        )

        root = Path("test-phase2-chaos")
        db_path = root / "memory.sqlite"
        try:
            result = run_phase2_chaos_replay(
                NoKeyExecutorConfig(db_path=db_path, scenario_id="phase2-chaos", session_id="phase2-chaos"),
                order_request=NoKeyOrderRequest(
                    symbol="ETHUSDT",
                    side="SELL",
                    qty=3.0,
                    price=200.0,
                    client_order_id="phase2-chaos-order",
                ),
            )

            scenario_ids = {scenario["scenario_id"] for scenario in result["scenarios"]}
            required = {
                "mid_order_crash",
                "stale_websocket",
                "duplicate_fill",
                "orphan_order",
                "partial_fill_restart",
                "corrupted_projection",
                "disk_full",
                "db_lock_retry",
                "network_partition",
                "clock_drift",
                "reduce_only_reject",
                "exchange_error_storm",
            }
            self.assertTrue(required.issubset(scenario_ids))
            self.assertTrue(all(scenario["replay_deterministic"] for scenario in result["scenarios"]))
            self.assertTrue(all(scenario["private_keys_required"] is False for scenario in result["scenarios"]))
            duplicate = next(scenario for scenario in result["scenarios"] if scenario["scenario_id"] == "duplicate_fill")
            self.assertEqual(duplicate["projection"]["fill_count"], 1)
            self.assertIn("duplicate_fill_ignored", duplicate["blocker_codes"])
            self.assertIn("cancel_all_simulated", result["safe_actions"])
            self.assertIn("kill_switch_simulated", result["safe_actions"])
        finally:
            _clean_tree(root)

    def test_cli_writes_no_key_executor_chaos_report_and_never_enables_live_path(self) -> None:
        root = Path("test-phase2-cli")
        db_path = root / "memory.sqlite"
        report_path = root / "phase2-chaos.json"
        try:
            exit_code = main(
                [
                    "no-key-executor-chaos",
                    "--db",
                    str(db_path),
                    "--scenario",
                    "duplicate_fill",
                    "--symbol",
                    "SOLUSDT",
                    "--side",
                    "BUY",
                    "--qty",
                    "4",
                    "--price",
                    "50",
                    "--client-order-id",
                    "phase2-cli-order",
                    "--output",
                    str(report_path),
                ]
            )

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["artifact_type"], "phase2_no_key_executor_chaos_report")
            self.assertFalse(report["private_keys_required"])
            self.assertFalse(report["live_order_path_enabled"])
            self.assertEqual(report["scenario_id"], "duplicate_fill")
            self.assertEqual(report["projection"]["fill_count"], 1)
        finally:
            _clean_tree(root)
