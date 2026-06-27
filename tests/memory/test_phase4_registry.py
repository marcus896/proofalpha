import json
import sqlite3
import unittest
from pathlib import Path

from engine.memory.store import (
    V3_EXECUTION_EVENT_TYPES,
    append_execution_event,
    ingest_artifact_directory,
    initialize_memory_db,
    rebuild_execution_projections,
    reconcile_accounting_ledgers,
)
from engine.config.models import PromotionDecision, RunCard
from engine.reporting.runcards import save_runcard
from engine.reporting.results import V3_RESULTS_TSV_COLUMNS, append_results_tsv_row


def _clean_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


class Phase4RegistrySchemaTests(unittest.TestCase):
    def test_initialize_memory_db_creates_v3_registry_and_execution_tables(self) -> None:
        root = Path("test-phase4-registry-schema")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                    ).fetchall()
                }
                experiments_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(experiments)").fetchall()
                }
                variant_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(strategy_variants)").fetchall()
                }
                event_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(execution_events)").fetchall()
                }
            finally:
                connection.close()

            for table in (
                "datasets",
                "strategy_families",
                "strategy_variants",
                "artifacts",
                "experiments",
                "validations",
                "failures",
                "deployments",
                "live_metrics",
                "execution_events",
                "orders_live",
                "fills",
                "positions",
                "risk_state",
                "order_telemetry",
                "risk_events",
                "market_snapshots",
                "signal_snapshots",
                "position_snapshots",
                "funding_events",
                "executor_health",
                "cash_ledger",
                "pnl_attribution",
                "fee_ledger",
                "funding_ledger",
                "transfer_ledger",
                "equity_snapshots",
                "data_retention_policies",
                "backup_manifests",
                "restore_manifests",
                "replay_checkpoints",
            ):
                self.assertIn(table, tables)
            for column in (
                "experiment_id",
                "parent_experiment_id",
                "created_at_utc",
                "completed_at_utc",
                "repo_sha",
                "prompt_sha",
                "strategy_id",
                "variant_id",
                "family",
                "venue",
                "signal_tf",
                "execution_tf",
                "dataset_snapshot_id",
                "feature_version",
                "cost_model_version",
                "execution_model_version",
                "scenario_pack_version",
                "status",
                "fail_code_primary",
                "artifact_id",
            ):
                self.assertIn(column, experiments_columns)
            for column in (
                "strategy_id",
                "family",
                "entry_logic_hash",
                "exit_logic_hash",
                "feature_set_hash",
                "parameter_schema_hash",
                "symbol_scope_hash",
                "regime_scope_hash",
                "venue_model_id",
                "execution_model_id",
                "cost_model_id",
                "feature_version",
                "data_snapshot_id",
                "code_sha",
            ):
                self.assertIn(column, variant_columns)
            for column in (
                "event_id",
                "ts_exchange",
                "ts_gateway",
                "ts_engine",
                "source",
                "symbol",
                "side",
                "order_id_client",
                "order_id_exchange",
                "parent_intent_id",
                "event_type",
                "qty",
                "price",
                "status",
                "reason_code",
                "metadata_json",
                "schema_version",
                "previous_digest",
                "event_digest",
                "segment_digest",
            ):
                self.assertIn(column, event_columns)
        finally:
            _clean_tree(root)

    def test_runcard_ingest_materializes_v3_experiment_artifact_and_failure_rows(self) -> None:
        root = Path("test-phase4-ingest")
        artifacts_dir = root / "artifacts"
        db_path = root / "memory.sqlite"
        try:
            runcard = RunCard(
                run_id="run-phase4",
                strategy_hash="strategy-sha",
                phase="phase-4",
                split_id="snap:60-20-20",
                seed=11,
                decision=PromotionDecision(decision="blocked", reasons=["pbo_fail"]),
                metrics={
                    "selection_oos_sharpe": 1.2,
                    "selection_oos_net_pnl": 42.0,
                    "selection_oos_drawdown": -0.04,
                    "deflated_sharpe_ratio": 0.96,
                    "scenario_pass_rate": 1.0,
                    "accepted_layers": 1.0,
                },
                artifacts={
                    "snapshot_id": "snap-phase4",
                    "symbol": "BTCUSDT",
                    "venue": "binance",
                    "snapshot_quality_status": "clean",
                    "snapshot_quality_flag_count": "0",
                    "snapshot_quality_flags_json": "[]",
                    "snapshot_quality_report_json": "{}",
                    "snapshot_provenance_json": json.dumps(
                        {
                            "raw_source_id": "binance_archive",
                            "raw_source_hash": "raw-sha",
                            "parser_version": "parser-v1",
                            "normalization_version": "norm-v1",
                            "exchange_rules_version": "rules-v1",
                            "feature_version": "feat-v1",
                            "scenario_pack_version": "scenario-v1",
                            "cost_model_version": "cost-v1",
                            "dataset_version": "dataset-v1",
                        },
                        sort_keys=True,
                    ),
                    "family": "momentum",
                    "variant_id": "variant-phase4",
                    "entry_logic_hash": "entry-sha",
                    "exit_logic_hash": "exit-sha",
                    "feature_set_hash": "feature-set-sha",
                    "parameter_schema_hash": "param-schema-sha",
                    "symbol_scope_hash": "symbol-scope-sha",
                    "regime_scope_hash": "regime-scope-sha",
                    "venue_model_id": "binance_usdm",
                    "execution_model_id": "binance_usdm_v3",
                    "cost_model_id": "cost-v1",
                    "code_sha": "code-sha",
                    "artifact_id": "artifact-phase4",
                    "artifact_sha256": "artifact-sha",
                    "artifact_parent_id": "artifact-parent",
                    "validation_report_id": "validation-phase4",
                    "signal_tf": "1h",
                    "execution_tf": "15m",
                    "fail_code_primary": "pbo_fail",
                    "fail_codes_secondary_json": json.dumps(["dsr_fail"]),
                    "validation_protocol_json": json.dumps({"status": "failed", "pbo_score": 0.3}),
                    "validation_gate_results_json": json.dumps({"pbo": False}),
                    "runtime_settings_json": "{}",
                    "selected_parameters_json": "{}",
                    "parameter_search_json": "{}",
                },
            )
            save_runcard(artifacts_dir / "run-phase4.runcard.json", runcard)

            self.assertEqual(ingest_artifact_directory(db_path, artifacts_dir), 1)
            connection = sqlite3.connect(db_path)
            try:
                dataset = connection.execute(
                    "SELECT raw_source_id, dataset_version, feature_version, cost_model_version FROM datasets WHERE dataset_id = 'snap-phase4'"
                ).fetchone()
                variant = connection.execute(
                    "SELECT family, execution_model_id, data_snapshot_id, code_sha FROM strategy_variants WHERE variant_id = 'variant-phase4'"
                ).fetchone()
                artifact = connection.execute(
                    "SELECT parent_artifact_id, variant_id, artifact_sha256 FROM artifacts WHERE artifact_id = 'artifact-phase4'"
                ).fetchone()
                experiment = connection.execute(
                    "SELECT dataset_snapshot_id, feature_version, cost_model_version, execution_model_version, scenario_pack_version, artifact_id, fail_code_primary FROM experiments WHERE experiment_id = 'run-phase4'"
                ).fetchone()
                validation = connection.execute(
                    "SELECT status FROM validations WHERE validation_id = 'validation-phase4'"
                ).fetchone()
                failure = connection.execute(
                    "SELECT fail_code_primary, fail_codes_secondary_json FROM failures WHERE experiment_id = 'run-phase4'"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(dataset, ("binance_archive", "dataset-v1", "feat-v1", "cost-v1"))
            self.assertEqual(variant, ("momentum", "binance_usdm_v3", "snap-phase4", "code-sha"))
            self.assertEqual(artifact, ("artifact-parent", "variant-phase4", "artifact-sha"))
            self.assertEqual(
                experiment,
                ("snap-phase4", "feat-v1", "cost-v1", "binance_usdm_v3", "scenario-v1", "artifact-phase4", "pbo_fail"),
            )
            self.assertEqual(validation, ("failed",))
            self.assertEqual(failure[0], "pbo_fail")
            self.assertEqual(json.loads(failure[1]), ["dsr_fail"])
        finally:
            _clean_tree(root)

    def test_execution_events_are_append_only_and_type_checked(self) -> None:
        root = Path("test-phase4-append-only")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            event_id = append_execution_event(
                db_path,
                ts_exchange="2026-04-25T00:00:00Z",
                ts_gateway="2026-04-25T00:00:01Z",
                ts_engine="2026-04-25T00:00:00Z",
                source="ENGINE",
                symbol="BTCUSDT",
                side="BUY",
                event_type="INTENT_CREATE",
                qty=1.0,
                price=100.0,
            )
            connection = sqlite3.connect(db_path)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO execution_events (ts_exchange, ts_gateway, ts_engine, source, event_type, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                        ("t", "t", "t", "ENGINE", "NOT_ALLOWED", "{}"),
                    )
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute("UPDATE execution_events SET status = 'changed' WHERE event_id = ?", (event_id,))
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute("DELETE FROM execution_events WHERE event_id = ?", (event_id,))
            finally:
                connection.close()
            self.assertIn("ORDER_FILL", V3_EXECUTION_EVENT_TYPES)
        finally:
            _clean_tree(root)

    def test_replay_rebuilds_orders_fills_positions_and_deduplicates_fill_ids(self) -> None:
        root = Path("test-phase4-replay")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            append_execution_event(
                db_path,
                ts_exchange="2026-04-25T00:00:00Z",
                ts_gateway="2026-04-25T00:00:01Z",
                ts_engine="2026-04-25T00:00:00Z",
                source="ENGINE",
                symbol="BTCUSDT",
                side="BUY",
                order_id_client="c1",
                event_type="ORDER_NEW_ACK",
                qty=2.0,
                price=100.0,
                status="NEW",
            )
            fill_meta = {"fill_id": "f1", "fee": 0.01, "maker_taker": "maker"}
            append_execution_event(
                db_path,
                ts_exchange="2026-04-25T00:01:00Z",
                ts_gateway="2026-04-25T00:01:01Z",
                ts_engine="2026-04-25T00:00:00Z",
                source="EXCHANGE",
                symbol="BTCUSDT",
                side="BUY",
                order_id_client="c1",
                event_type="ORDER_PARTIAL_FILL",
                qty=1.0,
                price=101.0,
                status="PARTIALLY_FILLED",
                metadata=fill_meta,
            )
            append_execution_event(
                db_path,
                ts_exchange="2026-04-25T00:01:00Z",
                ts_gateway="2026-04-25T00:01:02Z",
                ts_engine="2026-04-25T00:00:00Z",
                source="EXCHANGE",
                symbol="BTCUSDT",
                side="BUY",
                order_id_client="c1",
                event_type="ORDER_PARTIAL_FILL",
                qty=1.0,
                price=101.0,
                status="PARTIALLY_FILLED",
                metadata=fill_meta,
            )
            append_execution_event(
                db_path,
                ts_exchange="2026-04-25T00:02:00Z",
                ts_gateway="2026-04-25T00:02:01Z",
                ts_engine="2026-04-25T00:00:00Z",
                source="EXCHANGE",
                symbol="BTCUSDT",
                side="BUY",
                order_id_client="c1",
                event_type="ORDER_FILL",
                qty=1.0,
                price=102.0,
                status="FILLED",
                metadata={"fill_id": "f2", "fee": 0.02, "maker_taker": "taker"},
            )

            summary = rebuild_execution_projections(db_path)
            connection = sqlite3.connect(db_path)
            try:
                order = connection.execute("SELECT filled_qty, status FROM orders_live WHERE order_id_client = 'c1'").fetchone()
                fills = connection.execute("SELECT COUNT(*), SUM(qty) FROM fills").fetchone()
                position = connection.execute("SELECT net_qty, entry_price FROM positions WHERE symbol = 'BTCUSDT'").fetchone()
            finally:
                connection.close()

            self.assertEqual(summary["last_event_id"], 4)
            self.assertEqual(order, (2.0, "FILLED"))
            self.assertEqual(fills, (2, 2.0))
            self.assertEqual(position, (2.0, 101.5))
        finally:
            _clean_tree(root)

    def test_accounting_reconciliation_separates_pnl_fees_funding_transfers_cash_and_equity(self) -> None:
        root = Path("test-phase4-accounting")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    "INSERT INTO cash_ledger (ts_utc, account_id, currency, amount, reason, reference_id, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("2026-04-25T00:00:00Z", "paper", "USDT", 1000.0, "deposit", "t1", "{}"),
                )
                connection.execute(
                    "INSERT INTO pnl_attribution (ts_utc, run_id, symbol, realized_strategy_pnl, unrealized_pnl, fees, funding, slippage, transfers, cash_balance_delta, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("2026-04-25T00:00:00Z", "run1", "BTCUSDT", 10.0, 2.0, -1.0, -0.5, -0.25, 1000.0, 1010.25, "{}"),
                )
                connection.execute(
                    "INSERT INTO fee_ledger (ts_utc, run_id, symbol, order_id_client, fee_quote, fee_rate, maker_taker, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("2026-04-25T00:00:00Z", "run1", "BTCUSDT", "c1", 1.0, 0.0001, "maker", "{}"),
                )
                connection.execute(
                    "INSERT INTO funding_ledger (ts_utc, run_id, symbol, position_notional, funding_rate, funding_fee, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("2026-04-25T00:00:00Z", "run1", "BTCUSDT", 100.0, 0.001, 0.1, "{}"),
                )
                connection.execute(
                    "INSERT INTO transfer_ledger (ts_utc, account_id, currency, amount, transfer_type, reference_id, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("2026-04-25T00:00:00Z", "paper", "USDT", 1000.0, "deposit", "t1", "{}"),
                )
                connection.execute(
                    "INSERT INTO equity_snapshots (ts_utc, account_id, equity, cash_balance, unrealized_pnl, realized_pnl, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("2026-04-25T00:00:00Z", "paper", 1012.0, 1010.0, 2.0, 10.0, "{}"),
                )
                connection.commit()
            finally:
                connection.close()

            summary = reconcile_accounting_ledgers(db_path)
            self.assertEqual(summary["cash_balance_delta"], 1000.0)
            self.assertEqual(summary["realized_strategy_pnl"], 10.0)
            self.assertEqual(summary["unrealized_pnl"], 2.0)
            self.assertEqual(summary["fees"], -1.0)
            self.assertEqual(summary["funding"], -0.5)
            self.assertEqual(summary["slippage"], -0.25)
            self.assertEqual(summary["transfers"], 1000.0)
            self.assertEqual(summary["latest_equity"], 1012.0)
        finally:
            _clean_tree(root)


class Phase4ResultsTsvTests(unittest.TestCase):
    def test_results_tsv_writer_uses_exact_v3_columns_and_appends_rows(self) -> None:
        root = Path("test-phase4-results-tsv")
        path = root / "results.tsv"
        try:
            append_results_tsv_row(
                path,
                {
                    "experiment_id": "exp1",
                    "ts_start_utc": "2026-04-25T00:00:00Z",
                    "ts_end_utc": "2026-04-25T01:00:00Z",
                    "code_sha": "abc",
                    "artifact_parent_id": "",
                    "dataset_snapshot_id": "snap1",
                    "venue": "binance",
                    "symbols": json.dumps(["BTCUSDT"]),
                    "signal_tf": "1h",
                    "execution_tf": "15m",
                    "family": "momentum",
                    "variant_id": "var1",
                    "status": "blocked",
                    "fail_code": "pbo_fail",
                    "net_return": 0.01,
                    "net_pnl_quote": 10.0,
                    "sharpe": 1.1,
                    "calmar": 0.8,
                    "max_dd": -0.05,
                    "turnover": 2.0,
                    "capacity_usd": 10000.0,
                    "dsr": 0.96,
                    "pbo": 0.1,
                    "spa_pvalue": 0.04,
                    "holdout_pass": True,
                    "description": "fixture",
                },
            )
            append_results_tsv_row(path, {"experiment_id": "exp2"})

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0].split("\t"), V3_RESULTS_TSV_COLUMNS)
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[1].split("\t")[0], "exp1")
            self.assertEqual(lines[2].split("\t")[0], "exp2")
        finally:
            _clean_tree(root)
