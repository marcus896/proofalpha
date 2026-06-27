import json
import os
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.config.models import PromotionDecision, RunCard
from engine.memory.query import query_data_snapshots, query_run_memory
from engine.memory.store import _build_candidate_trial_rows, ingest_artifact_directory, initialize_memory_db
from engine.reporting.runcards import save_runcard


def _make_runcard(run_id: str, symbol: str, decision: str, quality_status: str = "clean") -> RunCard:
    return RunCard(
        run_id=run_id,
        strategy_hash=f"{run_id}-hash",
        phase="phase-5",
        split_id="snap:60-20-20",
        seed=7,
        decision=PromotionDecision(decision=decision, reasons=[]),
        metrics={
            "selection_oos_sharpe": 0.42,
            "selection_oos_net_pnl": 145.0,
            "selection_oos_drawdown": -0.12,
            "scenario_pass_rate": 0.75,
            "accepted_layers": 1.0,
        },
        artifacts={
            "snapshot_id": f"{run_id}-snap",
            "final_status": decision,
            "symbol": symbol,
            "venue": "binance",
            "runtime_settings_json": json.dumps(
                {
                    "bootstrap_method": "moving_block",
                    "slippage_bps": 5.0,
                    "search_summary_limit": 3,
                },
                sort_keys=True,
            ),
            "snapshot_quality_status": quality_status,
            "snapshot_quality_flag_count": "0" if quality_status == "clean" else "1",
            "snapshot_quality_flags_json": "[]" if quality_status == "clean" else '["missing_funding_rate_count=4"]',
            "scenario_profiles_json": json.dumps(
                {
                    "outage-shock": {
                        "name": "outage-shock",
                        "latency_delta_bars": 3,
                        "liquidity_penalty_bps": 65.0,
                    }
                },
                sort_keys=True,
            ),
            "regime_summary_json": json.dumps(
                {
                    "regime_coverage": {"bull": 0.5, "crash": 0.1},
                    "crisis_window_coverage": {"crash": 0.1},
                    "crisis_windows": [{"name": "crash-1", "regime_label": "crash"}],
                },
                sort_keys=True,
            ),
            "bootstrap_summary_json": json.dumps(
                {
                    "bootstrap_method": "moving_block",
                    "bootstrap_regime_summary": {
                        "average_regime_coverage": {"bull": 0.45},
                        "crisis_sample_frequency": {"crash": 0.25},
                        "dominant_regimes": ["bull"],
                        "sample_count": 8,
                    },
                },
                sort_keys=True,
            ),
            "selected_parameters_json": json.dumps({"kama": {"aggressiveness": 2}}, sort_keys=True),
            "parameter_search_json": json.dumps(
                {
                    "kama": {
                        "permutation_count": 4,
                        "search_summary": [
                            {"decision": "accept", "oos_sharpe": 0.42, "parameters": {"aggressiveness": 2}},
                        ],
                    }
                },
                sort_keys=True,
            ),
        },
    )


class MemoryStoreTests(unittest.TestCase):
    def test_initialize_memory_db_enables_wal_and_busy_timeout(self) -> None:
        root = Path("test-memory-store-pragmas")
        db_path = root / "research-memory.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
                busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
            finally:
                connection.close()

            self.assertEqual(journal_mode[0].lower(), "wal")
            self.assertEqual(busy_timeout[0], 5000)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_initialize_memory_db_creates_agent_decisions_table(self) -> None:
        root = Path("test-memory-store-agent-decisions-schema")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertIn("agent_decisions", tables)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_initialize_memory_db_creates_validation_runs_table(self) -> None:
        root = Path("test-memory-store-validation-runs-schema")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertIn("validation_runs", tables)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_initialize_memory_db_creates_stress_runs_table(self) -> None:
        root = Path("test-memory-store-stress-runs-schema")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertIn("stress_runs", tables)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_initialize_memory_db_creates_candidate_trials_table(self) -> None:
        root = Path("test-memory-store-candidate-trials-schema")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(candidate_trials)").fetchall()
                }
            finally:
                connection.close()

            self.assertIn("candidate_trials", tables)
            self.assertIn("fill_event_count", columns)
            self.assertIn("partial_fill_event_count", columns)
            self.assertIn("average_fill_ratio", columns)
            self.assertIn("min_fill_ratio", columns)
            self.assertIn("search_source", columns)
            self.assertIn("seed_evidence_json", columns)
            self.assertIn("regime_similarity_json", columns)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_data_snapshot_ingest_persists_v3_source_metadata(self) -> None:
        root = Path("test-memory-store-data-snapshot-source-metadata")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            runcard = _make_runcard("run-phase1", "BTCUSDT", "promoted")
            provenance = {
                "provider": "binance_public_archive",
                "build_mode": "archive_bundle",
                "build_version": "phase1_snapshot_builder_v1",
                "source_hash": "normalized-hash",
                "raw_source_id": "binance_public_archive:futures/um:daily:klines:BTCUSDT:1h:2024-01-01:2024-01-01",
                "raw_source_hash": "a" * 64,
                "parser_version": "binance_public_archive_parser_v1",
                "normalization_version": "v3_phase1_binance_archive_normalization_v1",
                "exchange_rules_version": "runtime_venue_preset_v1",
                "feature_version": "phase1_snapshot_features_v1",
                "scenario_pack_version": "not_applied",
                "cost_model_version": "not_applied",
                "dataset_version": "b" * 64,
            }
            runcard.artifacts["snapshot_provenance_json"] = json.dumps(provenance, sort_keys=True)
            runcard.artifacts["snapshot_build_version"] = provenance["build_version"]
            runcard.artifacts["snapshot_source_hash"] = provenance["source_hash"]
            save_runcard(artifacts_dir / "run-phase1.runcard.json", runcard)

            ingested = ingest_artifact_directory(db_path, artifacts_dir)
            rows = query_data_snapshots(db_path, snapshot_id="run-phase1-snap")

            self.assertEqual(ingested, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["provider"], "binance_public_archive")
            self.assertEqual(rows[0]["build_mode"], "archive_bundle")
            self.assertEqual(rows[0]["raw_source_hash"], "a" * 64)
            self.assertEqual(rows[0]["dataset_version"], "b" * 64)
            self.assertEqual(rows[0]["parser_version"], "binance_public_archive_parser_v1")
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_candidate_trial_rows_prefer_full_candidate_trials_with_seed_evidence(self) -> None:
        rows = _build_candidate_trial_rows(
            "run-a",
            {
                "phases": [
                    {
                        "phase_name": "phase-2",
                        "layer_name": "kama",
                        "decision": "accept",
                        "permutation_count": 4,
                        "search_summary": [
                            {"parameters": {"aggressiveness": 2}, "decision": "accept", "oos_sharpe": 0.42}
                        ],
                        "candidate_trials": [
                            {
                                "parameters": {"aggressiveness": 1},
                                "decision": "reject",
                                "oos_sharpe": 0.12,
                                "search_source": "grid",
                                "seed_evidence": {"source": "parameter_grid", "seed_count": 0},
                                "regime_similarity": {"dominant_regime": "bull"},
                            },
                            {
                                "parameters": {"aggressiveness": 2},
                                "decision": "accept",
                                "oos_sharpe": 0.42,
                                "search_source": "grid",
                                "seed_evidence": {"source": "parameter_grid", "seed_count": 0},
                                "regime_similarity": {"dominant_regime": "bull"},
                            },
                        ],
                    }
                ]
            },
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(json.loads(rows[0]["parameters_json"]), {"aggressiveness": 1})
        self.assertEqual(rows[0]["search_source"], "grid")
        self.assertEqual(json.loads(rows[0]["seed_evidence_json"])["source"], "parameter_grid")
        self.assertEqual(json.loads(rows[0]["regime_similarity_json"])["dominant_regime"], "bull")

    def test_initialize_memory_db_creates_data_snapshots_table(self) -> None:
        root = Path("test-memory-store-data-snapshots-schema")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(data_snapshots)").fetchall()
                }
            finally:
                connection.close()

            self.assertIn("data_snapshots", tables)
            self.assertIn("feature_quality_status", columns)
            self.assertIn("feature_quality_issue_count", columns)
            self.assertIn("feature_quality_report_json", columns)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_initialize_memory_db_creates_resource_index_table(self) -> None:
        root = Path("test-memory-store-resource-index-schema")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertIn("resource_index", tables)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_initialize_memory_db_creates_run_resource_links_table(self) -> None:
        root = Path("test-memory-store-run-resource-links-schema")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertIn("run_resource_links", tables)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_initialize_memory_db_creates_meta_policies_table(self) -> None:
        root = Path("test-memory-store-meta-policies-schema")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertIn("meta_policies", tables)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_persists_agent_decisions_from_karpathy_ledger(self) -> None:
        root = Path("test-memory-store-agent-decisions")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            save_runcard(artifacts_dir / "run-sol.runcard.json", _make_runcard("run-sol", "SOLUSDT", "promoted"))
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps({"run_id": "run-sol", "strategy": {"layers": ["kama"]}, "phases": []}, sort_keys=True),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.karpathy-ledger.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-sol",
                        "entries": [
                            {
                                "iteration": 1,
                                "decision": "keep",
                                "reason": "improved_objective",
                                "validation_status": "passed",
                                "metric_name": "selection_oos_sharpe",
                                "metric_value": 0.84,
                                "candidate_run_ids": ["run-sol-1"],
                                "kept_run_ids": ["run-sol-1"],
                            },
                            {
                                "iteration": 2,
                                "decision": "discard",
                                "reason": "objective_not_improved",
                                "validation_status": "failed",
                                "metric_name": "selection_oos_sharpe",
                                "metric_value": 0.52,
                                "candidate_run_ids": ["run-sol-2"],
                                "kept_run_ids": ["run-sol-1"],
                            },
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    """
                    SELECT decision_family, iteration, ordinal, decision, reason, validation_status,
                           metric_name, metric_value, candidate_run_ids_json, kept_run_ids_json
                    FROM agent_decisions
                    WHERE run_id = ?
                    ORDER BY iteration ASC, ordinal ASC
                    """,
                    ("run-sol",),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "karpathy")
            self.assertEqual(rows[0][1], 1)
            self.assertEqual(rows[0][3], "keep")
            self.assertEqual(json.loads(rows[0][8]), ["run-sol-1"])
            self.assertEqual(json.loads(rows[1][9]), ["run-sol-1"])
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_persists_validation_runs_row(self) -> None:
        root = Path("test-memory-store-validation-runs")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            runcard = _make_runcard("run-sol", "SOLUSDT", "promoted")
            runcard.metrics["probabilistic_sharpe_ratio"] = 0.93
            runcard.metrics["deflated_sharpe_ratio"] = 0.81
            runcard.metrics["validation_trial_count"] = 24
            runcard.artifacts["validation_protocol_json"] = json.dumps(
                {
                    "status": "failed",
                    "deflated_sharpe_ratio": 0.79,
                    "probabilistic_sharpe_ratio": 0.88,
                    "pbo_score": 0.24,
                    "spa_pvalue": 0.11,
                    "validation_gate_results": {
                        "deflated_sharpe_ratio": False,
                        "pbo": False,
                        "spa": True,
                    },
                    "min_backtest_length": 180,
                    "min_trade_count": 40,
                },
                sort_keys=True,
            )
            runcard.artifacts["validation_gate_results_json"] = json.dumps(
                {
                    "deflated_sharpe_ratio": False,
                    "pbo": False,
                    "spa": True,
                },
                sort_keys=True,
            )
            save_runcard(artifacts_dir / "run-sol.runcard.json", runcard)
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps({"run_id": "run-sol", "strategy": {"layers": ["kama"]}, "phases": []}, sort_keys=True),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    """
                    SELECT
                        validation_status,
                        probabilistic_sharpe_ratio,
                        deflated_sharpe_ratio,
                        pbo_score,
                        spa_pvalue,
                        min_backtest_length,
                        min_trade_count,
                        trial_count,
                        failed_gates_json,
                        validation_bundle_json
                    FROM validation_runs
                    WHERE run_id = ?
                    """,
                    ("run-sol",),
                ).fetchone()
            finally:
                connection.close()

            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row[0], "failed")
            self.assertAlmostEqual(float(row[1]), 0.93)
            self.assertAlmostEqual(float(row[2]), 0.81)
            self.assertAlmostEqual(float(row[3]), 0.24)
            self.assertAlmostEqual(float(row[4]), 0.11)
            self.assertEqual(int(row[5]), 180)
            self.assertEqual(int(row[6]), 40)
            self.assertEqual(int(row[7]), 24)
            self.assertEqual(json.loads(row[8]), ["deflated_sharpe_ratio", "pbo"])
            self.assertEqual(json.loads(row[9])["status"], "failed")
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_replaces_validation_runs_row_on_reingest(self) -> None:
        root = Path("test-memory-store-validation-runs-reingest")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            runcard = _make_runcard("run-sol", "SOLUSDT", "promoted")
            runcard.artifacts["validation_protocol_json"] = json.dumps(
                {
                    "status": "failed",
                    "deflated_sharpe_ratio": 0.61,
                    "probabilistic_sharpe_ratio": 0.72,
                    "pbo_score": 0.31,
                    "spa_pvalue": 0.17,
                    "validation_gate_results": {
                        "deflated_sharpe_ratio": False,
                        "pbo": False,
                    },
                },
                sort_keys=True,
            )
            runcard.artifacts["validation_gate_results_json"] = json.dumps(
                {"deflated_sharpe_ratio": False, "pbo": False},
                sort_keys=True,
            )
            save_runcard(artifacts_dir / "run-sol.runcard.json", runcard)
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps({"run_id": "run-sol", "strategy": {"layers": ["kama"]}, "phases": []}, sort_keys=True),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            updated = json.loads(runcard.artifacts["validation_protocol_json"])
            updated["status"] = "passed"
            updated["pbo_score"] = 0.08
            updated["spa_pvalue"] = 0.03
            updated["validation_gate_results"] = {
                "deflated_sharpe_ratio": True,
                "pbo": True,
                "spa": True,
            }
            runcard.artifacts["validation_protocol_json"] = json.dumps(updated, sort_keys=True)
            runcard.artifacts["validation_gate_results_json"] = json.dumps(updated["validation_gate_results"], sort_keys=True)
            save_runcard(artifacts_dir / "run-sol.runcard.json", runcard)

            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    """
                    SELECT validation_status, pbo_score, spa_pvalue, failed_gates_json
                    FROM validation_runs
                    WHERE run_id = ?
                    """,
                    ("run-sol",),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "passed")
            self.assertAlmostEqual(float(rows[0][1]), 0.08)
            self.assertAlmostEqual(float(rows[0][2]), 0.03)
            self.assertEqual(json.loads(rows[0][3]), [])
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_persists_stress_runs_rows_from_dashboard(self) -> None:
        root = Path("test-memory-store-stress-runs")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            save_runcard(artifacts_dir / "run-sol.runcard.json", _make_runcard("run-sol", "SOLUSDT", "promoted"))
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-sol",
                        "strategy": {"layers": ["kama"]},
                        "phases": [],
                        "scenarios": [
                            {
                                "scenario_name": "outage-shock",
                                "severity": 1.3,
                                "passed": False,
                                "failure_reasons": ["drawdown_kill_switch"],
                                "sharpe": 0.22,
                                "max_drawdown": -0.31,
                                "resolved_profile": {"target_regimes": ["crash"], "severity": 1.3},
                                "stress_metrics": {"liquidity_stress_score": 0.9, "cascade_liquidation_count": 2},
                            },
                            {
                                "scenario_name": "attention-burst",
                                "severity": 0.8,
                                "passed": True,
                                "failure_reasons": [],
                                "sharpe": 0.41,
                                "max_drawdown": -0.18,
                                "resolved_profile": {"target_regimes": ["bull"], "severity": 0.8},
                                "stress_metrics": {"liquidity_stress_score": 0.4, "cascade_liquidation_count": 0},
                            },
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    """
                    SELECT scenario_name, severity, passed, failure_reasons_json, max_drawdown, target_regimes_json
                    FROM stress_runs
                    WHERE run_id = ?
                    ORDER BY scenario_name ASC
                    """,
                    ("run-sol",),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "attention-burst")
            self.assertEqual(rows[1][0], "outage-shock")
            self.assertEqual(int(rows[1][2]), 0)
            self.assertEqual(json.loads(rows[1][3]), ["drawdown_kill_switch"])
            self.assertAlmostEqual(float(rows[1][4]), -0.31)
            self.assertEqual(json.loads(rows[1][5]), ["crash"])
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_replaces_stress_runs_rows_on_reingest(self) -> None:
        root = Path("test-memory-store-stress-runs-reingest")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            save_runcard(artifacts_dir / "run-sol.runcard.json", _make_runcard("run-sol", "SOLUSDT", "promoted"))
            dashboard_path = artifacts_dir / "run-sol.dashboard.json"
            dashboard_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-sol",
                        "strategy": {"layers": ["kama"]},
                        "phases": [],
                        "scenarios": [
                            {
                                "scenario_name": "outage-shock",
                                "severity": 1.3,
                                "passed": False,
                                "failure_reasons": ["drawdown_kill_switch"],
                                "sharpe": 0.22,
                                "max_drawdown": -0.31,
                                "resolved_profile": {"target_regimes": ["crash"], "severity": 1.3},
                                "stress_metrics": {"liquidity_stress_score": 0.9},
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            dashboard_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-sol",
                        "strategy": {"layers": ["kama"]},
                        "phases": [],
                        "scenarios": [
                            {
                                "scenario_name": "outage-shock",
                                "severity": 1.1,
                                "passed": True,
                                "failure_reasons": [],
                                "sharpe": 0.36,
                                "max_drawdown": -0.19,
                                "resolved_profile": {"target_regimes": ["crash", "bear"], "severity": 1.1},
                                "stress_metrics": {"liquidity_stress_score": 0.5},
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    """
                    SELECT passed, failure_reasons_json, target_regimes_json
                    FROM stress_runs
                    WHERE run_id = ?
                    """,
                    ("run-sol",),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(len(rows), 1)
            self.assertEqual(int(rows[0][0]), 1)
            self.assertEqual(json.loads(rows[0][1]), [])
            self.assertEqual(json.loads(rows[0][2]), ["crash", "bear"])
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_persists_candidate_trials_from_phase_search_summary(self) -> None:
        root = Path("test-memory-store-candidate-trials")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            save_runcard(artifacts_dir / "run-sol.runcard.json", _make_runcard("run-sol", "SOLUSDT", "promoted"))
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-sol",
                        "strategy": {"layers": ["kama", "ema"]},
                        "phases": [
                            {
                                "phase_name": "phase-2",
                                "layer_name": "kama",
                                "decision": "accept",
                                "accepted": True,
                                "selected_parameters": {"aggressiveness": 2},
                                "permutation_count": 4,
                                "search_summary": [
                                    {
                                        "decision": "accept",
                                        "oos_sharpe": 0.42,
                                        "parameters": {"aggressiveness": 2},
                                        "execution_pressure_summary": {
                                            "fill_event_count": 2,
                                            "partial_fill_event_count": 1,
                                            "average_fill_ratio": 0.72,
                                            "min_fill_ratio": 0.44,
                                        },
                                    },
                                    {
                                        "decision": "reject",
                                        "oos_sharpe": 0.17,
                                        "parameters": {"aggressiveness": 1},
                                    },
                                ],
                            },
                            {
                                "phase_name": "phase-3",
                                "layer_name": "ema",
                                "decision": "reject",
                                "accepted": False,
                                "selected_parameters": {"fast": 9, "slow": 21},
                                "permutation_count": 3,
                                "search_summary": [
                                    {
                                        "decision": "reject",
                                        "oos_sharpe": 0.05,
                                        "parameters": {"fast": 9, "slow": 21},
                                    }
                                ],
                            },
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    """
                    SELECT
                        phase_name,
                        layer_name,
                        ordinal,
                        decision,
                        oos_sharpe,
                        parameters_json,
                        permutation_count,
                        fill_event_count,
                        partial_fill_event_count,
                        average_fill_ratio,
                        min_fill_ratio
                    FROM candidate_trials
                    WHERE run_id = ?
                    ORDER BY phase_name ASC, layer_name ASC, ordinal ASC
                    """,
                    ("run-sol",),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0][0], "phase-2")
            self.assertEqual(rows[0][1], "kama")
            self.assertEqual(rows[0][2], 0)
            self.assertEqual(rows[0][3], "accept")
            self.assertEqual(rows[0][4], 0.42)
            self.assertEqual(json.loads(rows[0][5]), {"aggressiveness": 2})
            self.assertEqual(rows[0][6], 4)
            self.assertEqual(rows[0][7], 2)
            self.assertEqual(rows[0][8], 1)
            self.assertEqual(rows[0][9], 0.72)
            self.assertEqual(rows[0][10], 0.44)
            self.assertEqual(rows[2][1], "ema")
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_replaces_candidate_trials_on_reingest(self) -> None:
        root = Path("test-memory-store-candidate-trials-reingest")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            save_runcard(artifacts_dir / "run-sol.runcard.json", _make_runcard("run-sol", "SOLUSDT", "promoted"))
            dashboard_path = artifacts_dir / "run-sol.dashboard.json"
            dashboard_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-sol",
                        "strategy": {"layers": ["kama"]},
                        "phases": [
                            {
                                "phase_name": "phase-2",
                                "layer_name": "kama",
                                "decision": "accept",
                                "accepted": True,
                                "selected_parameters": {"aggressiveness": 2},
                                "permutation_count": 4,
                                "search_summary": [
                                    {
                                        "decision": "accept",
                                        "oos_sharpe": 0.42,
                                        "parameters": {"aggressiveness": 2},
                                    },
                                    {
                                        "decision": "reject",
                                        "oos_sharpe": 0.17,
                                        "parameters": {"aggressiveness": 1},
                                    },
                                ],
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            dashboard_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-sol",
                        "strategy": {"layers": ["kama"]},
                        "phases": [
                            {
                                "phase_name": "phase-2",
                                "layer_name": "kama",
                                "decision": "accept",
                                "accepted": True,
                                "selected_parameters": {"aggressiveness": 3},
                                "permutation_count": 2,
                                "search_summary": [
                                    {
                                        "decision": "accept",
                                        "oos_sharpe": 0.61,
                                        "parameters": {"aggressiveness": 3},
                                    }
                                ],
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    """
                    SELECT ordinal, decision, oos_sharpe, parameters_json, permutation_count
                    FROM candidate_trials
                    WHERE run_id = ?
                    ORDER BY ordinal ASC
                    """,
                    ("run-sol",),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(rows, [(0, "accept", 0.61, '{"aggressiveness": 3}', 2)])
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_persists_data_snapshots_rows(self) -> None:
        root = Path("test-memory-store-data-snapshots")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            runcard = _make_runcard("run-sol", "SOLUSDT", "promoted")
            runcard.artifacts["snapshot_provenance_json"] = json.dumps(
                {
                    "provider": "csv",
                    "build_mode": "bundle_csv",
                    "build_version": "phase1_snapshot_builder_v2",
                    "source_hash": "hash-123",
                },
                sort_keys=True,
            )
            runcard.artifacts["snapshot_build_version"] = "phase1_snapshot_builder_v2"
            runcard.artifacts["snapshot_source_hash"] = "hash-123"
            runcard.artifacts["snapshot_quality_report_json"] = json.dumps(
                {
                    "snapshot_id": "run-sol-snap",
                    "report_id": "run-sol-snap:quality",
                    "passed": True,
                    "quality_score": 0.91,
                },
                sort_keys=True,
            )
            runcard.artifacts["feature_quality_report_json"] = json.dumps(
                {
                    "snapshot_id": "run-sol-snap",
                    "report_id": "run-sol-snap:feature-quality",
                    "status": "failed",
                    "passed": False,
                    "issues": ["future_open_interest_value_row=0"],
                },
                sort_keys=True,
            )
            save_runcard(artifacts_dir / "run-sol.runcard.json", runcard)
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps({"run_id": "run-sol", "strategy": {"layers": ["kama"]}, "phases": []}, sort_keys=True),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    """
                    SELECT
                        symbol,
                        venue,
                        build_version,
                        source_hash,
                        quality_status,
                        feature_quality_status,
                        feature_quality_issue_count,
                        provider,
                        build_mode,
                        first_seen_run_id,
                        last_seen_run_id,
                        usage_count
                    FROM data_snapshots
                    WHERE snapshot_id = ?
                    """,
                    ("run-sol-snap",),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(
                row,
                (
                    "SOLUSDT",
                    "binance",
                    "phase1_snapshot_builder_v2",
                    "hash-123",
                    "clean",
                    "failed",
                    1,
                    "csv",
                    "bundle_csv",
                    "run-sol",
                    "run-sol",
                    1,
                ),
            )
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_updates_data_snapshots_usage_count(self) -> None:
        root = Path("test-memory-store-data-snapshots-usage")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            first = _make_runcard("run-sol-a", "SOLUSDT", "promoted")
            first.artifacts["snapshot_id"] = "shared-snap"
            first.artifacts["snapshot_provenance_json"] = json.dumps(
                {"provider": "csv", "build_mode": "bundle_csv", "build_version": "v1", "source_hash": "same-hash"},
                sort_keys=True,
            )
            first.artifacts["snapshot_build_version"] = "v1"
            first.artifacts["snapshot_source_hash"] = "same-hash"
            second = _make_runcard("run-sol-b", "SOLUSDT", "blocked")
            second.artifacts["snapshot_id"] = "shared-snap"
            second.artifacts["snapshot_provenance_json"] = json.dumps(
                {"provider": "csv", "build_mode": "bundle_csv", "build_version": "v1", "source_hash": "same-hash"},
                sort_keys=True,
            )
            second.artifacts["snapshot_build_version"] = "v1"
            second.artifacts["snapshot_source_hash"] = "same-hash"
            save_runcard(artifacts_dir / "run-sol-a.runcard.json", first)
            save_runcard(artifacts_dir / "run-sol-b.runcard.json", second)
            for run_id in ("run-sol-a", "run-sol-b"):
                (artifacts_dir / f"{run_id}.dashboard.json").write_text(
                    json.dumps({"run_id": run_id, "strategy": {"layers": ["kama"]}, "phases": []}, sort_keys=True),
                    encoding="utf-8",
                )
                (artifacts_dir / f"{run_id}.autoresearch.json").write_text(
                    json.dumps({"run_id": run_id, "research_lineage": {}}, sort_keys=True),
                    encoding="utf-8",
                )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)
            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    """
                    SELECT first_seen_run_id, last_seen_run_id, usage_count
                    FROM data_snapshots
                    WHERE snapshot_id = ?
                    """,
                    ("shared-snap",),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(row, ("run-sol-a", "run-sol-b", 2))
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_syncs_resource_index_from_ledger(self) -> None:
        root = Path("test-memory-store-resource-index")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        ledger_path = root / "resource-ledger.json"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            save_runcard(artifacts_dir / "run-sol.runcard.json", _make_runcard("run-sol", "SOLUSDT", "promoted"))
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps({"run_id": "run-sol", "strategy": {"layers": ["kama"]}, "phases": []}, sort_keys=True),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )
            ledger_path.write_text(
                json.dumps(
                    {
                        "required_repos": [
                            {
                                "id": "finrl_crypto",
                                "repo_full_name": "berendgort/FinRL_Crypto",
                                "url": "https://github.com/berendgort/FinRL_Crypto",
                                "license": "MIT",
                                "status": "cloned_pinned",
                                "intended_usage": "adapter_only",
                                "local_destination": "references/upstream/FinRL_Crypto",
                                "pinned_ref": "abc123",
                            }
                        ],
                        "conditional_repos": [
                            {
                                "id": "openbb",
                                "repo_full_name": "OpenBB-finance/OpenBB",
                                "url": "https://github.com/OpenBB-finance/OpenBB",
                                "license": "AGPL-3.0",
                                "status": "blocked_license_review",
                                "intended_usage": "reference_only",
                                "local_destination": None,
                                "pinned_ref": None,
                            }
                        ],
                        "required_non_repo_sources": [
                            {
                                "id": "ccxt_manual",
                                "title": "CCXT Manual",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [{"title": "CCXT Manual", "url": "https://github.com/ccxt/ccxt/wiki/Manual"}],
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            with mock.patch.dict(os.environ, {"ENGINE_RESOURCE_LEDGER_PATH": str(ledger_path)}):
                ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    """
                    SELECT resource_id, resource_group, title, url, license, status, intended_usage, local_destination, pinned_ref
                    FROM resource_index
                    ORDER BY resource_id ASC
                    """
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(
                rows,
                [
                    (
                        "ccxt_manual",
                        "non_repo_source",
                        "CCXT Manual",
                        "https://github.com/ccxt/ccxt/wiki/Manual",
                        None,
                        "indexed_not_yet_reviewed",
                        "reference_only",
                        None,
                        None,
                    ),
                    (
                        "finrl_crypto",
                        "required_repo",
                        "berendgort/FinRL_Crypto",
                        "https://github.com/berendgort/FinRL_Crypto",
                        "MIT",
                        "cloned_pinned",
                        "adapter_only",
                        "references/upstream/FinRL_Crypto",
                        "abc123",
                    ),
                    (
                        "openbb",
                        "conditional_repo",
                        "OpenBB-finance/OpenBB",
                        "https://github.com/OpenBB-finance/OpenBB",
                        "AGPL-3.0",
                        "blocked_license_review",
                        "reference_only",
                        None,
                        None,
                    ),
                ],
            )
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_persists_run_resource_links_from_payloads(self) -> None:
        root = Path("test-memory-store-run-resource-links")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        ledger_path = root / "resource-ledger.json"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            runcard = _make_runcard("run-sol", "SOLUSDT", "promoted")
            runcard.artifacts["snapshot_provenance_json"] = json.dumps(
                {
                    "provider": "csv",
                    "build_mode": "bundle_csv",
                    "build_version": "phase1_snapshot_builder_v2",
                    "source_hash": "hash-123",
                },
                sort_keys=True,
            )
            runcard.artifacts["snapshot_build_version"] = "phase1_snapshot_builder_v2"
            runcard.artifacts["snapshot_source_hash"] = "hash-123"
            runcard.artifacts["validation_protocol_json"] = json.dumps(
                {
                    "status": "failed",
                    "probabilistic_sharpe_ratio": 0.88,
                    "deflated_sharpe_ratio": 0.79,
                    "pbo_score": 0.24,
                    "spa_pvalue": 0.11,
                    "validation_gate_results": {
                        "deflated_sharpe_ratio": False,
                        "pbo": False,
                        "spa": True,
                    },
                },
                sort_keys=True,
            )
            runcard.artifacts["validation_gate_results_json"] = json.dumps(
                {
                    "deflated_sharpe_ratio": False,
                    "pbo": False,
                    "spa": True,
                },
                sort_keys=True,
            )
            runcard.artifacts["regime_summary_json"] = json.dumps(
                {"regime_coverage": {"bull": 0.5, "crash": 0.1}},
                sort_keys=True,
            )
            runcard.artifacts["bootstrap_summary_json"] = json.dumps(
                {"bootstrap_method": "moving_block"},
                sort_keys=True,
            )
            runcard.artifacts["scenario_profiles_json"] = json.dumps(
                {
                    "outage-shock": {
                        "name": "outage-shock",
                        "liquidity_penalty_bps": 65.0,
                    }
                },
                sort_keys=True,
            )
            save_runcard(artifacts_dir / "run-sol.runcard.json", runcard)
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps({"run_id": "run-sol", "strategy": {"layers": ["kama"]}, "phases": []}, sort_keys=True),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )
            ledger_path.write_text(
                json.dumps(
                    {
                        "required_repos": [],
                        "conditional_repos": [],
                        "required_non_repo_sources": [
                            {
                                "id": "ccxt_manual_and_exchange_capability_docs",
                                "title": "CCXT manual and exchange capability docs",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [{"title": "CCXT Manual", "url": "https://github.com/ccxt/ccxt/wiki/Manual"}],
                            },
                            {
                                "id": "pbo_cscv_references",
                                "title": "PBO / CSCV references",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [{"title": "PBO", "url": "https://example.com/pbo"}],
                            },
                            {
                                "id": "psr_dsr_references",
                                "title": "PSR and DSR references",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [{"title": "DSR", "url": "https://example.com/dsr"}],
                            },
                            {
                                "id": "spa_and_arch_bootstrap_spa_docs",
                                "title": "SPA references and arch.bootstrap.SPA docs",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [{"title": "SPA", "url": "https://example.com/spa"}],
                            },
                            {
                                "id": "bootstrap_and_dependent_wild_bootstrap_references",
                                "title": "Bootstrap and dependent wild bootstrap references",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [{"title": "Bootstrap", "url": "https://example.com/bootstrap"}],
                            },
                            {
                                "id": "hmm_hsmm_references",
                                "title": "HMM / HSMM references",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [{"title": "HSMM", "url": "https://example.com/hsmm"}],
                            },
                            {
                                "id": "crypto_latency_slippage_market_depth_research",
                                "title": "Crypto latency / slippage / market-depth research",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [{"title": "Latency", "url": "https://example.com/latency"}],
                            },
                            {
                                "id": "amberdata_liquidation_open_interest_reports",
                                "title": "Amberdata liquidation/open-interest reports",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [{"title": "Amberdata", "url": "https://example.com/amberdata"}],
                            },
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            with mock.patch.dict(os.environ, {"ENGINE_RESOURCE_LEDGER_PATH": str(ledger_path)}):
                ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    """
                    SELECT resource_id, link_role, evidence_source
                    FROM run_resource_links
                    WHERE run_id = ?
                    ORDER BY resource_id ASC, link_role ASC
                    """,
                    ("run-sol",),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(
                rows,
                [
                    ("amberdata_liquidation_open_interest_reports", "stress", "scenario_profiles"),
                    ("bootstrap_and_dependent_wild_bootstrap_references", "stress", "bootstrap_summary"),
                    ("ccxt_manual_and_exchange_capability_docs", "snapshot", "snapshot_provenance"),
                    ("crypto_latency_slippage_market_depth_research", "stress", "scenario_profiles"),
                    ("hmm_hsmm_references", "regime", "regime_summary"),
                    ("pbo_cscv_references", "validation", "validation_protocol"),
                    ("psr_dsr_references", "validation", "validation_protocol"),
                    ("spa_and_arch_bootstrap_spa_docs", "validation", "validation_protocol"),
                ],
            )
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_leaves_meta_policies_empty_without_explicit_artifact(self) -> None:
        root = Path("test-memory-store-meta-policies-empty")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            save_runcard(artifacts_dir / "run-sol.runcard.json", _make_runcard("run-sol", "SOLUSDT", "promoted"))
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps({"run_id": "run-sol", "strategy": {"layers": ["kama"]}, "phases": []}, sort_keys=True),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute("SELECT COUNT(*) FROM meta_policies").fetchone()
            finally:
                connection.close()

            self.assertEqual(row, (0,))
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_persists_meta_policies_from_explicit_artifact(self) -> None:
        root = Path("test-memory-store-meta-policies")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            runcard = _make_runcard("run-sol", "SOLUSDT", "promoted")
            runcard.artifacts["meta_policies_json"] = json.dumps(
                [
                    {
                        "policy_id": "meta-bandit-v1",
                        "policy_family": "bandit",
                        "status": "trained",
                        "action_map": {"balanced": 0, "conservative": 1},
                        "training_stats": {"episodes": 24, "best_reward": 1.7},
                        "eval_validation_run_id": "run-sol",
                        "eval_stress_summary": {"failed_scenarios": 0, "scenario_count": 3},
                        "artifact_path": "outputs/policies/meta-bandit-v1.json",
                    }
                ],
                sort_keys=True,
            )
            save_runcard(artifacts_dir / "run-sol.runcard.json", runcard)
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps({"run_id": "run-sol", "strategy": {"layers": ["kama"]}, "phases": []}, sort_keys=True),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps({"run_id": "run-sol", "research_lineage": {}}, sort_keys=True),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    """
                    SELECT
                        policy_id,
                        policy_family,
                        status,
                        action_map_json,
                        training_stats_json,
                        eval_validation_run_id,
                        eval_stress_summary_json,
                        artifact_path
                    FROM meta_policies
                    WHERE run_id = ?
                    """,
                    ("run-sol",),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(
                row,
                (
                    "meta-bandit-v1",
                    "bandit",
                    "trained",
                    '{"balanced": 0, "conservative": 1}',
                    '{"best_reward": 1.7, "episodes": 24}',
                    "run-sol",
                    '{"failed_scenarios": 0, "scenario_count": 3}',
                    "outputs/policies/meta-bandit-v1.json",
                ),
            )
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_supports_phase_layer_queries_and_is_idempotent(self) -> None:
        root = Path("test-memory-store")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            save_runcard(artifacts_dir / "run-sol.runcard.json", _make_runcard("run-sol", "SOLUSDT", "promoted"))
            (artifacts_dir / "run-sol.dashboard.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-sol",
                        "strategy": {"backbone": "mom_squeeze", "layers": ["kama"], "risk_guards": []},
                        "phases": [
                            {
                                "phase_name": "phase-2",
                                "layer_name": "kama",
                                "decision": "accept",
                                "accepted": True,
                                "selected_parameters": {"aggressiveness": 2},
                            },
                            {
                                "phase_name": "phase-3",
                                "layer_name": "flat9",
                                "decision": "reject",
                                "accepted": False,
                                "selected_parameters": {},
                            },
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "run-sol.autoresearch.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-sol",
                        "status": "promoted",
                        "research_lineage": {
                            "selected_variant": "balanced",
                            "parent_batch_run_id": "batch-run",
                            "parent_batch_report_path": "test-memory-store/artifacts/batch-run.variant-batch.json",
                            "source_config_path": "test-memory-store/artifacts/run-sol.continued-study.json",
                            "accepted_duplicate_match_run_id": "prior-same-study",
                            "accepted_duplicate_match_type": "duplicate_match",
                            "accepted_duplicate_source_config_path": "test-memory-store/artifacts/run-sol.accepted-duplicate.json",
                            "accepted_duplicate_source_report_path": "test-memory-store/artifacts/run-sol.autoresearch.json",
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            initialize_memory_db(db_path)
            self.assertEqual(ingest_artifact_directory(db_path, artifacts_dir), 1)
            self.assertEqual(ingest_artifact_directory(db_path, artifacts_dir), 0)

            promoted = query_run_memory(db_path, symbol="SOLUSDT", decision="promoted")
            self.assertEqual(len(promoted), 1)
            self.assertEqual(promoted[0]["run_id"], "run-sol")
            self.assertEqual(promoted[0]["accepted_layers"], ["kama"])
            self.assertEqual(promoted[0]["phase_layers"], ["flat9", "kama"])
            self.assertEqual(promoted[0]["selected_parameters"]["kama"]["aggressiveness"], 2)
            self.assertEqual(promoted[0]["selected_variant"], "balanced")
            self.assertEqual(promoted[0]["parent_batch_run_id"], "batch-run")
            self.assertEqual(promoted[0]["accepted_duplicate_match_run_id"], "prior-same-study")
            self.assertEqual(promoted[0]["scenario_profiles"]["outage-shock"]["latency_delta_bars"], 3)
            self.assertEqual(promoted[0]["regime_summary"]["regime_coverage"]["bull"], 0.5)
            self.assertEqual(promoted[0]["bootstrap_summary"]["bootstrap_regime_summary"]["sample_count"], 8)
            self.assertEqual(promoted[0]["runtime_settings"]["bootstrap_method"], "moving_block")
            self.assertEqual(promoted[0]["runtime_settings"]["slippage_bps"], 5.0)
            self.assertEqual(promoted[0]["runtime_settings"]["search_summary_limit"], 3)

            flat9_matches = query_run_memory(db_path, layer="flat9")
            self.assertEqual(len(flat9_matches), 1)
            self.assertEqual(flat9_matches[0]["run_id"], "run-sol")

            balanced_matches = query_run_memory(db_path, selected_variant="balanced")
            self.assertEqual(len(balanced_matches), 1)
            self.assertEqual(balanced_matches[0]["run_id"], "run-sol")
            self.assertEqual(balanced_matches[0]["snapshot_quality_status"], "clean")

            batch_matches = query_run_memory(db_path, parent_batch_run_id="batch-run")
            self.assertEqual(len(batch_matches), 1)
            self.assertEqual(batch_matches[0]["run_id"], "run-sol")

            accepted_duplicate_matches = query_run_memory(db_path, accepted_duplicate_match_run_id="prior-same-study")
            self.assertEqual(len(accepted_duplicate_matches), 1)
            self.assertEqual(accepted_duplicate_matches[0]["run_id"], "run-sol")

            dirty_dir = artifacts_dir / "dirty"
            dirty_dir.mkdir(exist_ok=True)
            save_runcard(dirty_dir / "run-dirty.runcard.json", _make_runcard("run-dirty", "SOLUSDT", "promoted", quality_status="dirty"))
            (dirty_dir / "run-dirty.dashboard.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-dirty",
                        "strategy": {"backbone": "mom_squeeze", "layers": ["kama"], "risk_guards": []},
                        "phases": [
                            {
                                "phase_name": "phase-2",
                                "layer_name": "kama",
                                "decision": "accept",
                                "accepted": True,
                                "selected_parameters": {"aggressiveness": 2},
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            self.assertEqual(ingest_artifact_directory(db_path, dirty_dir), 1)
            dirty_matches = query_run_memory(db_path, quality_status="dirty")
            self.assertEqual(len(dirty_matches), 1)
            self.assertEqual(dirty_matches[0]["run_id"], "run-dirty")

            missing = query_run_memory(db_path, layer="hull")
            self.assertEqual(missing, [])
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()


if __name__ == "__main__":
    unittest.main()
