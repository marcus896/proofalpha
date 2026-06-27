import json
import shutil
import sqlite3
import unittest
from pathlib import Path

from engine.app.cli import main
from engine.memory.store import append_execution_event


TS = "2026-05-01T00:00:00Z"


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _append_order_fill_events(db_path: Path, *, order_id: str = "phase3-order-1", qty: float = 2.0) -> None:
    append_execution_event(
        db_path,
        ts_exchange=TS,
        ts_gateway=TS,
        ts_engine=TS,
        source="phase3-test",
        event_type="ORDER_SUBMIT",
        symbol="BTCUSDT",
        side="BUY",
        order_id_client=order_id,
        qty=qty,
        price=100.0,
        status="SUBMITTED",
        metadata={"reduce_only": False},
    )
    append_execution_event(
        db_path,
        ts_exchange=TS,
        ts_gateway=TS,
        ts_engine=TS,
        source="phase3-test",
        event_type="ORDER_ACK",
        symbol="BTCUSDT",
        side="BUY",
        order_id_client=order_id,
        order_id_exchange="fake-3001",
        qty=qty,
        price=100.0,
        status="ACKED",
        metadata={"reduce_only": False},
    )
    append_execution_event(
        db_path,
        ts_exchange=TS,
        ts_gateway=TS,
        ts_engine=TS,
        source="phase3-test",
        event_type="FILL",
        symbol="BTCUSDT",
        side="BUY",
        order_id_client=order_id,
        order_id_exchange="fake-3001",
        qty=qty,
        price=100.0,
        status="FILLED",
        metadata={
            "fill_id": f"{order_id}:fill:1",
            "fee": 0.10,
            "fee_rate": 0.0005,
            "maker_taker": "TAKER",
            "liquidity_flag": "taker",
            "realized_pnl": 1.25,
            "unrealized_pnl": 3.5,
            "funding_fee": -0.02,
            "funding_rate": -0.0001,
            "position_notional": 200.0,
            "cash_balance_delta": -200.10,
            "equity": 10003.5,
            "cash_balance": 9800.0,
            "margin_usage": 0.02,
            "drawdown": 0.01,
        },
    )
    append_execution_event(
        db_path,
        ts_exchange=TS,
        ts_gateway=TS,
        ts_engine=TS,
        source="phase3-test",
        event_type="POSITION_RECONCILE",
        symbol="BTCUSDT",
        qty=qty,
        price=100.0,
        status="RECONCILED",
        metadata={
            "account_id": "fake-account",
            "equity": 10003.5,
            "cash_balance": 9800.0,
            "exposure": 200.0,
            "margin_usage": 0.02,
            "realized_pnl": 1.25,
            "unrealized_pnl": 3.5,
            "drawdown": 0.01,
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "net_qty": qty,
                    "entry_price": 100.0,
                    "mark_price": 101.75,
                    "unrealized_pnl": 3.5,
                }
            ],
        },
    )


class Phase3ProjectionReconciliationTests(unittest.TestCase):
    def test_rebuild_projection_recreates_accounting_ledgers_from_append_only_events(self) -> None:
        from engine.execution.reconciliation import rebuild_phase3_execution_projection

        root = Path("test-phase3-projection")
        db_path = root / "memory.sqlite"
        try:
            _append_order_fill_events(db_path)

            result = rebuild_phase3_execution_projection(db_path)

            connection = sqlite3.connect(db_path)
            try:
                order_row = connection.execute(
                    "SELECT status, filled_qty FROM orders_live WHERE order_id_client = 'phase3-order-1'"
                ).fetchone()
                fill_row = connection.execute(
                    "SELECT fill_id, qty, fee FROM fills WHERE order_id_client = 'phase3-order-1'"
                ).fetchone()
                position_row = connection.execute(
                    "SELECT symbol, net_qty, entry_price, unrealized_pnl FROM positions WHERE symbol = 'BTCUSDT'"
                ).fetchone()
                fee_row = connection.execute("SELECT symbol, order_id_client, fee_quote FROM fee_ledger").fetchone()
                funding_row = connection.execute("SELECT symbol, funding_fee FROM funding_ledger").fetchone()
                pnl_row = connection.execute(
                    "SELECT realized_strategy_pnl, unrealized_pnl, fees, funding, cash_balance_delta FROM pnl_attribution"
                ).fetchone()
                cash_row = connection.execute("SELECT amount, reason FROM cash_ledger").fetchone()
                equity_row = connection.execute(
                    "SELECT equity, cash_balance, unrealized_pnl, realized_pnl FROM equity_snapshots"
                ).fetchone()
                risk_row = connection.execute(
                    "SELECT exposure, margin_usage, realized_pnl, unrealized_pnl, drawdown FROM risk_state WHERE scope_id = 'account'"
                ).fetchone()
            finally:
                connection.close()

            self.assertTrue(result["replay_deterministic"])
            self.assertEqual(order_row, ("FILLED", 2.0))
            self.assertEqual(fill_row, ("phase3-order-1:fill:1", 2.0, 0.10))
            self.assertEqual(position_row, ("BTCUSDT", 2.0, 100.0, 3.5))
            self.assertEqual(fee_row, ("BTCUSDT", "phase3-order-1", 0.10))
            self.assertEqual(funding_row, ("BTCUSDT", -0.02))
            self.assertEqual(pnl_row, (1.25, 3.5, 0.10, -0.02, -200.10))
            self.assertEqual(cash_row, (-200.10, "execution_fill"))
            self.assertEqual(equity_row, (10003.5, 9800.0, 3.5, 1.25))
            self.assertEqual(risk_row, (200.0, 0.02, 1.25, 3.5, 0.01))
        finally:
            _clean_tree(root)

    def test_reconcile_projection_detects_gateway_drift_and_journals_safe_actions(self) -> None:
        from engine.execution.reconciliation import (
            GatewayAccountSnapshot,
            GatewayOrderSnapshot,
            GatewayPositionSnapshot,
            GatewayStateSnapshot,
            reconcile_projection_with_gateway,
        )

        root = Path("test-phase3-reconcile")
        db_path = root / "memory.sqlite"
        try:
            _append_order_fill_events(db_path)
            append_execution_event(
                db_path,
                ts_exchange=TS,
                ts_gateway=TS,
                ts_engine=TS,
                source="phase3-test",
                event_type="FILL",
                symbol="BTCUSDT",
                side="BUY",
                order_id_client="phase3-order-1",
                order_id_exchange="fake-3001",
                qty=2.0,
                price=100.0,
                status="FILLED",
                metadata={"fill_id": "phase3-order-1:fill:1"},
            )
            snapshot = GatewayStateSnapshot(
                account=GatewayAccountSnapshot(
                    account_id="fake-account",
                    stale=True,
                    equity=9999.0,
                    cash_balance=9700.0,
                    realized_pnl=-4.0,
                    unrealized_pnl=-1.0,
                    margin_usage=0.40,
                    exposure=600.0,
                ),
                open_orders=[
                    GatewayOrderSnapshot(
                        order_id_client="phase3-orphan-order",
                        symbol="BTCUSDT",
                        side="SELL",
                        qty=1.0,
                        filled_qty=0.0,
                        status="NEW",
                        reduce_only=True,
                    )
                ],
                fills=[
                    {"fill_id": "phase3-order-1:fill:1", "order_id_client": "phase3-order-1", "qty": 2.0},
                    {"fill_id": "phase3-missing-fill", "order_id_client": "phase3-order-1", "qty": 1.0},
                    {"fill_id": "phase3-missing-fill", "order_id_client": "phase3-order-1", "qty": 1.0},
                ],
                positions=[GatewayPositionSnapshot(symbol="BTCUSDT", net_qty=6.0, entry_price=100.0)],
                funding=[{"symbol": "BTCUSDT", "funding_fee": -1.0}],
            )

            report = reconcile_projection_with_gateway(
                db_path,
                snapshot,
                operator_id="phase3-operator",
                artifact_id="phase3-artifact",
            )

            connection = sqlite3.connect(db_path)
            try:
                journal_actions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT action FROM human_override_journal ORDER BY rowid"
                    ).fetchall()
                ]
            finally:
                connection.close()

            expected_blockers = {
                "orphan_order_detected",
                "missing_fill_detected",
                "duplicate_fill_detected",
                "stale_account_snapshot_detected",
                "symbol_exposure_drift",
                "risk_state_mismatch",
                "funding_mismatch",
                "cash_equity_mismatch",
                "pnl_mismatch",
            }
            self.assertTrue(expected_blockers.issubset(set(report["blocker_codes"])))
            self.assertEqual(report["status"], "blocked")
            self.assertIn("pause_artifact", report["safe_actions"])
            self.assertIn("cancel_all", report["safe_actions"])
            self.assertIn("flatten_all", report["safe_actions"])
            self.assertIn("force_reconcile", report["safe_actions"])
            self.assertEqual(journal_actions, ["pause_artifact", "cancel_all", "flatten_all", "force_reconcile"])
            self.assertTrue(all(item["status"] == "applied" for item in report["operator_journal"]))
        finally:
            _clean_tree(root)

    def test_cli_writes_phase3_reconciliation_report(self) -> None:
        root = Path("test-phase3-cli")
        db_path = root / "memory.sqlite"
        snapshot_path = root / "gateway-snapshot.json"
        report_path = root / "phase3-reconcile.json"
        try:
            _append_order_fill_events(db_path)
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(
                json.dumps(
                    {
                        "account": {
                            "account_id": "fake-account",
                            "stale": False,
                            "equity": 10003.5,
                            "cash_balance": 9800.0,
                            "realized_pnl": 1.25,
                            "unrealized_pnl": 3.5,
                            "margin_usage": 0.02,
                            "exposure": 200.0,
                        },
                        "open_orders": [],
                        "fills": [{"fill_id": "phase3-order-1:fill:1", "order_id_client": "phase3-order-1", "qty": 2.0}],
                        "positions": [{"symbol": "BTCUSDT", "net_qty": 2.0, "entry_price": 100.0}],
                        "funding": [{"symbol": "BTCUSDT", "funding_fee": -0.02}],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "phase3-reconcile",
                    "--db",
                    str(db_path),
                    "--snapshot",
                    str(snapshot_path),
                    "--operator-id",
                    "phase3-cli",
                    "--artifact-id",
                    "phase3-artifact",
                    "--output",
                    str(report_path),
                ]
            )

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["artifact_type"], "phase3_projection_reconciliation_report")
            self.assertEqual(report["status"], "matched")
            self.assertEqual(report["blocker_codes"], [])
            self.assertTrue(report["projection"]["replay_deterministic"])
        finally:
            _clean_tree(root)
