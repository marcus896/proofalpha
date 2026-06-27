from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.memory.query import (
    query_agent_decisions,
    query_bayesian_seed_trials,
    query_candidate_trials,
    query_data_snapshots,
    query_meta_policies,
    query_resource_index,
    query_run_resource_links,
    query_run_memory,
    query_stress_runs,
    query_validation_runs,
    render_meta_policy_query,
)
from engine.memory.store import initialize_memory_db


class MemoryQueryTests(unittest.TestCase):
    def test_query_run_memory_batches_phase_lookup(self) -> None:
        root = Path("test-memory-batch-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.executemany(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES (?, 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', ?, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """,
                    [
                        ("run-a", 2.0),
                        ("run-b", 1.0),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO research_phases (
                        run_id,
                        phase_name,
                        layer_name,
                        decision,
                        accepted,
                        selected_parameters_json,
                        permutation_count,
                        search_summary_json
                    ) VALUES (?, 'phase', ?, 'accept', ?, '{}', 1, '[]')
                    """,
                    [
                        ("run-a", "kama", 1),
                        ("run-a", "ema", 0),
                        ("run-b", "rsi", 1),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            real_connect = sqlite3.connect
            execute_count = 0

            class CountingConnection(sqlite3.Connection):
                def execute(self, sql: str, parameters=(), /):
                    nonlocal execute_count
                    execute_count += 1
                    return super().execute(sql, parameters)

            def connect_with_counter(path: Path, **_: object) -> sqlite3.Connection:
                return real_connect(path, factory=CountingConnection)

            with mock.patch("engine.memory.query.connect_sqlite", side_effect=connect_with_counter):
                results = query_run_memory(db_path)

            self.assertEqual([row["run_id"] for row in results], ["run-a", "run-b"])
            self.assertEqual(results[0]["accepted_layers"], ["kama"])
            self.assertEqual(results[0]["rejected_layers"], ["ema"])
            self.assertEqual(results[1]["accepted_layers"], ["rsi"])
            self.assertLessEqual(execute_count, 11)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_agent_decisions_returns_parsed_rows_in_stable_order(self) -> None:
        root = Path("test-memory-agent-decision-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES ('run-a', 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', 1.0, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO agent_decisions (
                        run_id,
                        decision_family,
                        iteration,
                        ordinal,
                        decision,
                        reason,
                        validation_status,
                        metric_name,
                        metric_value,
                        candidate_run_ids_json,
                        kept_run_ids_json,
                        payload_json
                    ) VALUES (?, 'karpathy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-a",
                            2,
                            0,
                            "discard",
                            "objective_not_improved",
                            "failed",
                            "selection_oos_sharpe",
                            0.52,
                            '["run-a-2"]',
                            '["run-a-1"]',
                            '{"decision":"discard","iteration":2}',
                        ),
                        (
                            "run-a",
                            1,
                            0,
                            "keep",
                            "improved_objective",
                            "passed",
                            "selection_oos_sharpe",
                            0.84,
                            '["run-a-1"]',
                            '["run-a-1"]',
                            '{"decision":"keep","iteration":1}',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_agent_decisions(db_path, run_id="run-a")

            self.assertEqual([row["iteration"] for row in rows], [1, 2])
            self.assertEqual(rows[0]["candidate_run_ids"], ["run-a-1"])
            self.assertEqual(rows[1]["decision"], "discard")
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_run_memory_attaches_agent_decision_summary(self) -> None:
        root = Path("test-memory-agent-decision-summary")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES ('run-a', 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', 1.0, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO agent_decisions (
                        run_id, decision_family, iteration, ordinal, decision, reason,
                        validation_status, metric_name, metric_value,
                        candidate_run_ids_json, kept_run_ids_json, payload_json
                    ) VALUES (?, 'karpathy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-a",
                            1,
                            0,
                            "keep",
                            "improved_objective",
                            "passed",
                            "selection_oos_sharpe",
                            0.84,
                            '["run-a-1"]',
                            '["run-a-1"]',
                            "{}",
                        ),
                        (
                            "run-a",
                            2,
                            0,
                            "discard",
                            "objective_not_improved",
                            "failed",
                            "selection_oos_sharpe",
                            0.52,
                            '["run-a-2"]',
                            '["run-a-1"]',
                            "{}",
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_run_memory(db_path, run_id="run-a")

            self.assertEqual(rows[0]["agent_decision_summary"]["decision_count"], 2)
            self.assertEqual(rows[0]["agent_decision_summary"]["latest_iteration"], 2)
            self.assertEqual(rows[0]["agent_decision_summary"]["latest_decision"], "discard")
            self.assertEqual(rows[0]["agent_decision_summary"]["decision_family"], "karpathy")
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_candidate_trials_returns_parsed_rows_in_rank_order(self) -> None:
        root = Path("test-memory-candidate-trial-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.executemany(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES (?, 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', ?, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """,
                    [
                        ("run-a", 1.5),
                        ("run-b", 0.9),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO candidate_trials (
                        run_id,
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
                        min_fill_ratio,
                        search_source,
                        seed_evidence_json,
                        regime_similarity_json,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-a",
                            "phase-2",
                            "kama",
                            1,
                            "reject",
                            0.22,
                            '{"aggressiveness": 1}',
                            4,
                            None,
                            None,
                            None,
                            None,
                            "grid",
                            '{"source":"parameter_grid","seed_count":0}',
                            '{"dominant_regime":"bull"}',
                            '{"decision":"reject"}',
                        ),
                        (
                            "run-a",
                            "phase-2",
                            "kama",
                            0,
                            "accept",
                            0.42,
                            '{"aggressiveness": 2}',
                            4,
                            2,
                            1,
                            0.72,
                            0.44,
                            "grid",
                            '{"source":"parameter_grid","seed_count":0}',
                            '{"dominant_regime":"bull"}',
                            '{"decision":"accept","execution_pressure_summary":{"fill_event_count":2,"partial_fill_event_count":1,"average_fill_ratio":0.72,"min_fill_ratio":0.44}}',
                        ),
                        (
                            "run-b",
                            "phase-3",
                            "ema",
                            0,
                            "reject",
                            0.05,
                            '{"fast": 9, "slow": 21}',
                            3,
                            None,
                            None,
                            None,
                            None,
                            "optuna",
                            '{"source":"bayesian_memory","seed_count":2}',
                            '{"dominant_regime":"crash"}',
                            '{"decision":"reject"}',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_candidate_trials(db_path, run_id="run-a")

            self.assertEqual([row["ordinal"] for row in rows], [0, 1])
            self.assertEqual(rows[0]["decision"], "accept")
            self.assertEqual(rows[0]["parameters"], {"aggressiveness": 2})
            self.assertEqual(rows[0]["execution_pressure_summary"]["partial_fill_event_count"], 1)
            self.assertEqual(rows[0]["execution_pressure_summary"]["min_fill_ratio"], 0.44)
            self.assertEqual(rows[0]["search_source"], "grid")
            self.assertEqual(rows[0]["seed_evidence"]["source"], "parameter_grid")
            self.assertEqual(rows[0]["regime_similarity"]["dominant_regime"], "bull")
            self.assertEqual(rows[1]["permutation_count"], 4)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_candidate_trials_can_filter_to_pressured_rows_and_rank_by_worst_fill(self) -> None:
        root = Path("test-memory-candidate-trial-pressure-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES ('run-a', 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', 1.0, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO candidate_trials (
                        run_id,
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
                        min_fill_ratio,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-a",
                            "phase-2",
                            "kama",
                            0,
                            "accept",
                            0.52,
                            '{"aggressiveness": 2}',
                            4,
                            3,
                            2,
                            0.68,
                            0.31,
                            '{"execution_pressure_summary":{"fill_event_count":3,"partial_fill_event_count":2,"average_fill_ratio":0.68,"min_fill_ratio":0.31}}',
                        ),
                        (
                            "run-a",
                            "phase-2",
                            "ema",
                            1,
                            "accept",
                            0.61,
                            '{"fast": 9, "slow": 21}',
                            4,
                            2,
                            1,
                            0.81,
                            0.57,
                            '{"execution_pressure_summary":{"fill_event_count":2,"partial_fill_event_count":1,"average_fill_ratio":0.81,"min_fill_ratio":0.57}}',
                        ),
                        (
                            "run-a",
                            "phase-2",
                            "hull",
                            2,
                            "reject",
                            0.20,
                            '{"length": 34}',
                            4,
                            None,
                            None,
                            None,
                            None,
                            '{"decision":"reject"}',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_candidate_trials(
                db_path,
                run_id="run-a",
                pressured_only=True,
                sort_by="worst_fill",
            )

            self.assertEqual([row["layer_name"] for row in rows], ["kama", "ema"])
            self.assertEqual(rows[0]["execution_pressure_summary"]["min_fill_ratio"], 0.31)
            self.assertEqual(rows[1]["execution_pressure_summary"]["min_fill_ratio"], 0.57)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_run_memory_attaches_candidate_trial_summary(self) -> None:
        root = Path("test-memory-candidate-trial-summary")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES ('run-a', 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', 1.0, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO candidate_trials (
                        run_id,
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
                        min_fill_ratio,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-a",
                            "phase-2",
                            "kama",
                            0,
                            "accept",
                            0.42,
                            '{"aggressiveness": 2}',
                            4,
                            2,
                            1,
                            0.72,
                            0.44,
                            '{"decision":"accept","execution_pressure_summary":{"fill_event_count":2,"partial_fill_event_count":1,"average_fill_ratio":0.72,"min_fill_ratio":0.44}}',
                        ),
                        (
                            "run-a",
                            "phase-3",
                            "ema",
                            0,
                            "reject",
                            0.05,
                            '{"fast": 9, "slow": 21}',
                            3,
                            None,
                            None,
                            None,
                            None,
                            '{"decision":"reject"}',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_run_memory(db_path, run_id="run-a")

            self.assertEqual(rows[0]["candidate_trial_summary"]["trial_count"], 2)
            self.assertEqual(rows[0]["candidate_trial_summary"]["top_decision"], "accept")
            self.assertEqual(rows[0]["candidate_trial_summary"]["top_oos_sharpe"], 0.42)
            self.assertEqual(rows[0]["candidate_trial_summary"]["layer_count"], 2)
            self.assertEqual(rows[0]["candidate_trial_summary"]["pressured_trial_count"], 1)
            self.assertEqual(rows[0]["candidate_trial_summary"]["worst_min_fill_ratio"], 0.44)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_run_memory_can_filter_and_rank_by_candidate_pressure(self) -> None:
        root = Path("test-memory-run-pressure-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.executemany(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES (?, 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', ?, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """,
                    [
                        ("run-a", 1.2),
                        ("run-b", 2.1),
                        ("run-c", 1.8),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO candidate_trials (
                        run_id,
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
                        min_fill_ratio,
                        payload_json
                    ) VALUES (?, 'phase-2', ?, 0, 'accept', ?, '{}', 3, ?, ?, ?, ?, '{}')
                    """,
                    [
                        ("run-a", "kama", 0.45, 3, 2, 0.70, 0.28),
                        ("run-b", "ema", 0.66, None, None, None, None),
                        ("run-c", "hull", 0.55, 2, 1, 0.83, 0.49),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_run_memory(
                db_path,
                candidate_pressure_only=True,
                sort_by="candidate_worst_fill",
            )

            self.assertEqual([row["run_id"] for row in rows], ["run-a", "run-c"])
            self.assertEqual(rows[0]["candidate_trial_summary"]["worst_min_fill_ratio"], 0.28)
            self.assertEqual(rows[1]["candidate_trial_summary"]["worst_min_fill_ratio"], 0.49)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_data_snapshots_returns_parsed_rows_in_stable_order(self) -> None:
        root = Path("test-memory-data-snapshot-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.executemany(
                    """
                    INSERT INTO data_snapshots (
                        snapshot_id,
                        symbol,
                        venue,
                        build_version,
                        source_hash,
                        quality_status,
                        quality_flag_count,
                        snapshot_quality_flags_json,
                        snapshot_quality_report_json,
                        snapshot_provenance_json,
                        provider,
                        build_mode,
                        first_seen_run_id,
                        last_seen_run_id,
                        usage_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "snap-b",
                            "BTCUSDT",
                            "binance",
                            "v2",
                            "hash-b",
                            "dirty",
                            1,
                            '["missing_funding_rate_count=4"]',
                            '{"quality_score":0.76}',
                            '{"provider":"csv","build_mode":"bundle_csv"}',
                            "csv",
                            "bundle_csv",
                            "run-b",
                            "run-b",
                            1,
                        ),
                        (
                            "snap-a",
                            "SOLUSDT",
                            "binance",
                            "v1",
                            "hash-a",
                            "clean",
                            0,
                            "[]",
                            '{"quality_score":0.92}',
                            '{"provider":"csv","build_mode":"bundle_csv"}',
                            "csv",
                            "bundle_csv",
                            "run-a",
                            "run-c",
                            2,
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_data_snapshots(db_path, venue="binance")

            self.assertEqual([row["snapshot_id"] for row in rows], ["snap-a", "snap-b"])
            self.assertEqual(rows[0]["provider"], "csv")
            self.assertEqual(rows[0]["usage_count"], 2)
            self.assertEqual(rows[1]["quality_status"], "dirty")
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_resource_index_returns_parsed_rows_in_stable_order(self) -> None:
        root = Path("test-memory-resource-index-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.executemany(
                    """
                    INSERT INTO resource_index (
                        resource_id,
                        resource_group,
                        title,
                        url,
                        license,
                        status,
                        intended_usage,
                        local_destination,
                        pinned_ref,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
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
                            '{"license":"AGPL-3.0"}',
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
                            '{"license":"MIT"}',
                        ),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO run_resource_links (
                        run_id,
                        resource_id,
                        link_role,
                        evidence_source,
                        rationale,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-a",
                            "finrl_crypto",
                            "design",
                            "manual",
                            "used for a design slice",
                            '{"source":"manual"}',
                        ),
                        (
                            "run-b",
                            "finrl_crypto",
                            "design",
                            "manual",
                            "used for another design slice",
                            '{"source":"manual"}',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_resource_index(db_path, status="cloned_pinned")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["resource_id"], "finrl_crypto")
            self.assertEqual(rows[0]["resource_group"], "required_repo")
            self.assertEqual(rows[0]["license"], "MIT")
            self.assertEqual(rows[0]["linked_run_count"], 2)
            self.assertEqual(rows[0]["link_count"], 2)
            self.assertEqual(rows[0]["linked_run_ids"], ["run-a", "run-b"])
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_run_resource_links_returns_parsed_rows_in_stable_order(self) -> None:
        root = Path("test-memory-run-resource-link-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO resource_index (
                        resource_id,
                        resource_group,
                        title,
                        url,
                        license,
                        status,
                        intended_usage,
                        local_destination,
                        pinned_ref,
                        payload_json
                    ) VALUES (
                        'psr_dsr_references',
                        'non_repo_source',
                        'PSR and DSR references',
                        'https://example.com/dsr',
                        NULL,
                        'indexed_not_yet_reviewed',
                        'reference_only',
                        NULL,
                        NULL,
                        '{}'
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO resource_index (
                        resource_id,
                        resource_group,
                        title,
                        url,
                        license,
                        status,
                        intended_usage,
                        local_destination,
                        pinned_ref,
                        payload_json
                    ) VALUES (
                        'ccxt_manual_and_exchange_capability_docs',
                        'non_repo_source',
                        'CCXT manual and exchange capability docs',
                        'https://github.com/ccxt/ccxt/wiki/Manual',
                        NULL,
                        'indexed_not_yet_reviewed',
                        'reference_only',
                        NULL,
                        NULL,
                        '{}'
                    )
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO run_resource_links (
                        run_id,
                        resource_id,
                        link_role,
                        evidence_source,
                        rationale,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-a",
                            "psr_dsr_references",
                            "validation",
                            "validation_protocol",
                            "validation payload includes PSR/DSR",
                            '{"matched_fields":["probabilistic_sharpe_ratio","deflated_sharpe_ratio"]}',
                        ),
                        (
                            "run-a",
                            "ccxt_manual_and_exchange_capability_docs",
                            "snapshot",
                            "snapshot_provenance",
                            "snapshot provenance captured exchange adapter lineage",
                            '{"matched_fields":["snapshot_build_version","snapshot_source_hash"]}',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_run_resource_links(db_path, run_id="run-a")

            self.assertEqual([row["resource_id"] for row in rows], ["ccxt_manual_and_exchange_capability_docs", "psr_dsr_references"])
            self.assertEqual(rows[0]["resource_group"], "non_repo_source")
            self.assertEqual(rows[0]["link_role"], "snapshot")
            self.assertEqual(rows[1]["evidence_source"], "validation_protocol")
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_meta_policies_returns_parsed_rows_in_stable_order(self) -> None:
        root = Path("test-memory-meta-policy-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.executemany(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES (?, 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', ?, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """,
                    [
                        ("run-a", 1.5),
                        ("run-b", 0.9),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO meta_policies (
                        run_id,
                        policy_id,
                        policy_family,
                        status,
                        action_map_json,
                        training_stats_json,
                        eval_validation_run_id,
                        eval_stress_summary_json,
                        artifact_path,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-b",
                            "meta-rl-v2",
                            "reinforcement_learning",
                            "evaluated",
                            '{"balanced": 0}',
                            '{"episodes": 12}',
                            "run-b",
                            '{"scenario_count": 2}',
                            "outputs/policies/meta-rl-v2.json",
                            '{"policy_family":"reinforcement_learning"}',
                        ),
                        (
                            "run-a",
                            "meta-bandit-v1",
                            "bandit",
                            "trained",
                            '{"balanced": 0, "conservative": 1}',
                            '{"best_reward": 1.7, "episodes": 24, "selected_action": "conservative", "training_example_count": 6}',
                            "run-a",
                            '{"failed_scenarios": 0, "scenario_count": 3}',
                            "outputs/policies/meta-bandit-v1.json",
                            '{"policy_family":"bandit","offline_evaluation":{"method":"logged_bandit_mean_reward_v1","best_observed_action":"conservative","regret_to_best_observed":0.0}}',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_meta_policies(db_path)

            self.assertEqual([row["policy_id"] for row in rows], ["meta-bandit-v1", "meta-rl-v2"])
            self.assertEqual(rows[0]["policy_family"], "bandit")
            self.assertEqual(rows[0]["action_map"], {"balanced": 0, "conservative": 1})
            self.assertEqual(rows[1]["training_stats"], {"episodes": 12})
            rendered = render_meta_policy_query(rows[:1], "text")
            self.assertIn("selected=conservative", rendered)
            self.assertIn("train_examples=6", rendered)
            self.assertIn("offline_eval=logged_bandit_mean_reward_v1", rendered)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_run_memory_attaches_data_snapshot_and_resource_link_summaries(self) -> None:
        root = Path("test-memory-snapshot-resource-summary")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        snapshot_id,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES ('run-a', 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', 'snap-a', 1.0, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO data_snapshots (
                        snapshot_id,
                        symbol,
                        venue,
                        build_version,
                        source_hash,
                        quality_status,
                        quality_flag_count,
                        snapshot_quality_flags_json,
                        snapshot_quality_report_json,
                        snapshot_provenance_json,
                        provider,
                        build_mode,
                        first_seen_run_id,
                        last_seen_run_id,
                        usage_count
                    ) VALUES (
                        'snap-a',
                        'SOLUSDT',
                        'binance',
                        'v1',
                        'hash-a',
                        'clean',
                        0,
                        '[]',
                        '{"quality_score":0.92}',
                        '{"provider":"csv","build_mode":"bundle_csv"}',
                        'csv',
                        'bundle_csv',
                        'run-a',
                        'run-b',
                        2
                    )
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO resource_index (
                        resource_id,
                        resource_group,
                        title,
                        url,
                        license,
                        status,
                        intended_usage,
                        local_destination,
                        pinned_ref,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
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
                            "{}",
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
                            "{}",
                        ),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO run_resource_links (
                        run_id,
                        resource_id,
                        link_role,
                        evidence_source,
                        rationale,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-a",
                            "finrl_crypto",
                            "design",
                            "manual",
                            "design reference",
                            '{"source":"manual"}',
                        ),
                        (
                            "run-a",
                            "openbb",
                            "provider",
                            "manual",
                            "provider reference",
                            '{"source":"manual"}',
                        ),
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO meta_policies (
                        run_id,
                        policy_id,
                        policy_family,
                        status,
                        action_map_json,
                        training_stats_json,
                        eval_validation_run_id,
                        eval_stress_summary_json,
                        artifact_path,
                        payload_json
                    ) VALUES (
                        'run-a',
                        'meta-bandit-v1',
                        'bandit',
                        'trained',
                        '{"balanced": 0, "conservative": 1}',
                        '{"best_reward": 1.7, "episodes": 24, "selected_action": "conservative", "training_example_count": 6}',
                        'run-a',
                        '{"failed_scenarios": 0, "scenario_count": 3}',
                        'outputs/policies/meta-bandit-v1.json',
                        '{"offline_evaluation":{"method":"logged_bandit_mean_reward_v1","best_observed_action":"conservative"}}'
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_run_memory(db_path, run_id="run-a")

            self.assertEqual(rows[0]["data_snapshot_summary"]["usage_count"], 2)
            self.assertEqual(rows[0]["data_snapshot_summary"]["provider"], "csv")
            self.assertEqual(rows[0]["data_snapshot_summary"]["build_mode"], "bundle_csv")
            self.assertEqual(rows[0]["resource_link_summary"]["link_count"], 2)
            self.assertEqual(rows[0]["resource_link_summary"]["linked_resource_count"], 2)
            self.assertEqual(rows[0]["resource_link_summary"]["blocked_link_count"], 1)
            self.assertEqual(rows[0]["resource_link_summary"]["resource_groups"], ["conditional_repo", "required_repo"])
            self.assertEqual(rows[0]["meta_policy_summary"]["policy_count"], 1)
            self.assertEqual(rows[0]["meta_policy_summary"]["policy_family"], "bandit")
            self.assertEqual(rows[0]["meta_policy_summary"]["latest_policy_id"], "meta-bandit-v1")
            self.assertEqual(rows[0]["meta_policy_summary"]["status"], "trained")
            self.assertEqual(rows[0]["meta_policy_summary"]["selected_action"], "conservative")
            self.assertEqual(rows[0]["meta_policy_summary"]["training_example_count"], 6)
            self.assertEqual(rows[0]["meta_policy_summary"]["offline_eval_method"], "logged_bandit_mean_reward_v1")
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_validation_runs_returns_parsed_rows_in_stable_order(self) -> None:
        root = Path("test-memory-validation-run-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.executemany(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES (?, 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', ?, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """,
                    [
                        ("run-a", 1.5),
                        ("run-b", 0.9),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO validation_runs (
                        run_id,
                        validation_status,
                        probabilistic_sharpe_ratio,
                        deflated_sharpe_ratio,
                        pbo_score,
                        spa_pvalue,
                        min_backtest_length,
                        min_trade_count,
                        trial_count,
                        failed_gates_json,
                        gate_results_json,
                        validation_bundle_json,
                        validation_protocol_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-b",
                            "failed",
                            0.82,
                            0.61,
                            0.21,
                            0.13,
                            180,
                            40,
                            12,
                            '["pbo"]',
                            '{"pbo": false}',
                            '{"status":"failed","failed_gates":["pbo"]}',
                            '{"status":"failed"}',
                        ),
                        (
                            "run-a",
                            "passed",
                            0.95,
                            0.84,
                            0.08,
                            0.03,
                            240,
                            60,
                            24,
                            "[]",
                            '{"pbo": true, "spa": true}',
                            '{"status":"passed","failed_gates":[]}',
                            '{"status":"passed"}',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_validation_runs(
                db_path,
                max_pbo_score=0.21,
                min_deflated_sharpe_ratio=0.61,
            )

            self.assertEqual([row["run_id"] for row in rows], ["run-a", "run-b"])
            self.assertEqual(rows[0]["failed_gates"], [])
            self.assertEqual(rows[1]["failed_gates"], ["pbo"])
            self.assertEqual(rows[1]["gate_results"]["pbo"], False)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_run_memory_attaches_validation_run_summary(self) -> None:
        root = Path("test-memory-validation-run-summary")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES ('run-a', 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', 1.0, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO validation_runs (
                        run_id,
                        validation_status,
                        probabilistic_sharpe_ratio,
                        deflated_sharpe_ratio,
                        pbo_score,
                        spa_pvalue,
                        min_backtest_length,
                        min_trade_count,
                        trial_count,
                        failed_gates_json,
                        gate_results_json,
                        validation_bundle_json,
                        validation_protocol_json
                    ) VALUES (
                        'run-a',
                        'failed',
                        0.89,
                        0.74,
                        0.24,
                        0.11,
                        180,
                        40,
                        24,
                        '["pbo","spa"]',
                        '{"pbo": false, "spa": false}',
                        '{"status":"failed","failed_gates":["pbo","spa"]}',
                        '{"status":"failed"}'
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_run_memory(db_path, run_id="run-a")

            self.assertEqual(rows[0]["validation_run_summary"]["status"], "failed")
            self.assertEqual(rows[0]["validation_run_summary"]["pbo_score"], 0.24)
            self.assertEqual(rows[0]["validation_run_summary"]["spa_pvalue"], 0.11)
            self.assertEqual(rows[0]["validation_run_summary"]["failed_gate_count"], 2)
            self.assertEqual(rows[0]["validation_run_summary"]["trial_count"], 24)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_stress_runs_returns_parsed_rows_in_stable_order(self) -> None:
        root = Path("test-memory-stress-run-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.executemany(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES (?, 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', ?, 0.0, 0.0, 1.0, 1.0, '{}', '{}')
                    """,
                    [
                        ("run-a", 1.5),
                        ("run-b", 0.9),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO stress_runs (
                        run_id,
                        scenario_name,
                        severity,
                        passed,
                        failure_reasons_json,
                        sharpe,
                        max_drawdown,
                        resolved_profile_json,
                        stress_metrics_json,
                        target_regimes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-b",
                            "outage-shock",
                            1.3,
                            0,
                            '["drawdown_kill_switch"]',
                            0.22,
                            -0.31,
                            '{"target_regimes":["crash"]}',
                            '{"liquidity_stress_score":0.9}',
                            '["crash"]',
                        ),
                        (
                            "run-a",
                            "attention-burst",
                            0.8,
                            1,
                            "[]",
                            0.41,
                            -0.18,
                            '{"target_regimes":["bull"]}',
                            '{"liquidity_stress_score":0.4}',
                            '["bull"]',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_stress_runs(db_path, target_regime="crash")

            self.assertEqual([row["run_id"] for row in rows], ["run-b"])
            self.assertEqual(rows[0]["scenario_name"], "outage-shock")
            self.assertEqual(rows[0]["failure_reasons"], ["drawdown_kill_switch"])
            self.assertEqual(rows[0]["target_regimes"], ["crash"])
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_run_memory_attaches_stress_run_summary(self) -> None:
        root = Path("test-memory-stress-run-summary")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json
                    ) VALUES ('run-a', 'hash', 'phase', 'split', 7, 'promoted', 'SOLUSDT', 'binance', 1.0, 0.0, 0.0, 0.5, 1.0, '{}', '{}')
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO stress_runs (
                        run_id,
                        scenario_name,
                        severity,
                        passed,
                        failure_reasons_json,
                        sharpe,
                        max_drawdown,
                        resolved_profile_json,
                        stress_metrics_json,
                        target_regimes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "run-a",
                            "outage-shock",
                            1.3,
                            0,
                            '["drawdown_kill_switch"]',
                            0.22,
                            -0.31,
                            '{"target_regimes":["crash"]}',
                            '{"liquidity_stress_score":0.9}',
                            '["crash"]',
                        ),
                        (
                            "run-a",
                            "attention-burst",
                            0.8,
                            1,
                            "[]",
                            0.41,
                            -0.18,
                            '{"target_regimes":["bull"]}',
                            '{"liquidity_stress_score":0.4}',
                            '["bull"]',
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            rows = query_run_memory(db_path, run_id="run-a")

            self.assertEqual(rows[0]["stress_run_summary"]["scenario_count"], 2)
            self.assertEqual(rows[0]["stress_run_summary"]["failed_scenario_count"], 1)
            self.assertEqual(rows[0]["stress_run_summary"]["worst_scenario"], "outage-shock")
            self.assertEqual(rows[0]["stress_run_summary"]["target_regime_count"], 2)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_query_bayesian_seed_trials_ranks_exact_symbol_regime_and_scenario_matches(self) -> None:
        root = Path("test-memory-query")
        db_path = root / "research-memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                rows = [
                    (
                        "run-sol-exact",
                        "promoted",
                        "SOLUSDT",
                        "binance",
                        1.6,
                        json.dumps({"kama": {"aggressiveness": 3}}, sort_keys=True),
                        json.dumps({"liquidation_cascade": {"severity": 0.9}}, sort_keys=True),
                        json.dumps({"regime_coverage": {"crash": 0.45, "bull": 0.2}}, sort_keys=True),
                    ),
                    (
                        "run-sol-venue-only",
                        "promoted",
                        "BTCUSDT",
                        "binance",
                        1.4,
                        json.dumps({"kama": {"aggressiveness": 2}}, sort_keys=True),
                        json.dumps({"attention-burst": {"severity": 0.4}}, sort_keys=True),
                        json.dumps({"regime_coverage": {"bull": 0.7}}, sort_keys=True),
                    ),
                    (
                        "run-sol-duplicate-params",
                        "promoted",
                        "SOLUSDT",
                        "binance",
                        1.2,
                        json.dumps({"kama": {"aggressiveness": 3}}, sort_keys=True),
                        json.dumps({"liquidation_cascade": {"severity": 0.8}}, sort_keys=True),
                        json.dumps({"regime_coverage": {"crash": 0.25}}, sort_keys=True),
                    ),
                ]
                connection.executemany(
                    """
                    INSERT INTO research_runs (
                        run_id,
                        strategy_hash,
                        phase,
                        split_id,
                        seed,
                        decision,
                        symbol,
                        venue,
                        selection_oos_sharpe,
                        selection_oos_net_pnl,
                        selection_oos_drawdown,
                        scenario_pass_rate,
                        accepted_layers,
                        selected_parameters_json,
                        parameter_search_json,
                        scenario_profiles_json,
                        regime_summary_json,
                        runtime_settings_json
                    ) VALUES (?, 'hash', 'phase', 'split', 7, ?, ?, ?, ?, 0.0, 0.0, 0.0, 1.0, ?, '{}', ?, ?, '{}')
                    """,
                    rows,
                )
                connection.executemany(
                    """
                    INSERT INTO research_phases (
                        run_id,
                        phase_name,
                        layer_name,
                        decision,
                        accepted,
                        selected_parameters_json,
                        permutation_count,
                        search_summary_json
                    ) VALUES (?, 'phase', 'kama', 'accept', 1, ?, 1, '[]')
                    """,
                    [
                        ("run-sol-exact", json.dumps({"aggressiveness": 3}, sort_keys=True)),
                        ("run-sol-venue-only", json.dumps({"aggressiveness": 2}, sort_keys=True)),
                        ("run-sol-duplicate-params", json.dumps({"aggressiveness": 3}, sort_keys=True)),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            results = query_bayesian_seed_trials(
                db_path,
                layer_name="kama",
                symbol="SOLUSDT",
                venue="binance",
                regime_label="crash",
                scenario_names=["liquidation_cascade"],
                limit=3,
            )

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["run_id"], "run-sol-exact")
            self.assertEqual(results[0]["parameters"]["aggressiveness"], 3)
            self.assertEqual(results[0]["match_details"]["exact_symbol"], 1.0)
            self.assertGreater(results[0]["rank_score"], results[1]["rank_score"])
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
