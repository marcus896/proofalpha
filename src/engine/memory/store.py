from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3

from engine.io.sqlite import connect_sqlite
from engine.reporting.runcards import load_runcard
from engine.reporting.summary import load_dashboard_payload
from engine.validation.bundle import normalize_validation_bundle


ARTIFACT_INGESTION_SCHEMA_VERSION = 1


V3_EXECUTION_EVENT_TYPES = (
    "INTENT_CREATE",
    "ORDER_SUBMIT",
    "ORDER_ACK",
    "FILL",
    "ORDER_CANCEL_REQUEST",
    "ORDER_NEW_SUBMIT",
    "ORDER_NEW_ACK",
    "ORDER_PARTIAL_FILL",
    "ORDER_FILL",
    "ORDER_CANCEL_SUBMIT",
    "ORDER_CANCEL_ACK",
    "ORDER_CANCEL_REJECT",
    "ORDER_REJECT",
    "ACCOUNT_SNAPSHOT",
    "RISK_BLOCK",
    "POSITION_RECONCILE",
    "KILL_SWITCH_TRIGGER",
    "ENGINE_START",
    "ENGINE_STOP",
    "ENGINE_RECOVER_REPLAY",
)


def _connect_to_db(db_path: Path) -> sqlite3.Connection:
    return connect_sqlite(db_path, read_only=False, foreign_keys=True)


def initialize_memory_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect_to_db(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_runs (
                run_id TEXT PRIMARY KEY,
                strategy_hash TEXT NOT NULL,
                phase TEXT NOT NULL,
                split_id TEXT NOT NULL,
                seed INTEGER NOT NULL,
                decision TEXT NOT NULL,
                symbol TEXT,
                venue TEXT,
                snapshot_id TEXT,
                final_status TEXT,
                selection_oos_sharpe REAL,
                selection_oos_net_pnl REAL,
                selection_oos_drawdown REAL,
                scenario_pass_rate REAL,
                accepted_layers REAL,
                probabilistic_sharpe_ratio REAL,
                deflated_sharpe_ratio REAL,
                in_sample_permutation_pvalue REAL,
                walk_forward_permutation_pvalue REAL,
                validation_trial_count INTEGER,
                validation_status TEXT,
                validation_protocol_json TEXT,
                validation_gate_results_json TEXT,
                snapshot_quality_status TEXT,
                snapshot_quality_flag_count INTEGER,
                snapshot_quality_flags_json TEXT,
                snapshot_quality_report_json TEXT,
                snapshot_provenance_json TEXT,
                snapshot_build_version TEXT,
                snapshot_source_hash TEXT,
                study_signature TEXT,
                selected_variant TEXT,
                parent_batch_run_id TEXT,
                parent_batch_report_path TEXT,
                source_config_path TEXT,
                accepted_duplicate_match_run_id TEXT,
                accepted_duplicate_match_type TEXT,
                accepted_duplicate_source_config_path TEXT,
                accepted_duplicate_source_report_path TEXT,
                scenario_profiles_json TEXT,
                regime_summary_json TEXT,
                bootstrap_summary_json TEXT,
                runtime_settings_json TEXT,
                selected_parameters_json TEXT NOT NULL,
                parameter_search_json TEXT NOT NULL,
                agent_loop_metadata_json TEXT DEFAULT '{}',
                research_program_version TEXT DEFAULT ''
            )
            """
        )
        _ensure_run_column(connection, "selected_variant", "TEXT")
        _ensure_run_column(connection, "parent_batch_run_id", "TEXT")
        _ensure_run_column(connection, "parent_batch_report_path", "TEXT")
        _ensure_run_column(connection, "source_config_path", "TEXT")
        _ensure_run_column(connection, "accepted_duplicate_match_run_id", "TEXT")
        _ensure_run_column(connection, "accepted_duplicate_match_type", "TEXT")
        _ensure_run_column(connection, "accepted_duplicate_source_config_path", "TEXT")
        _ensure_run_column(connection, "accepted_duplicate_source_report_path", "TEXT")
        _ensure_run_column(connection, "scenario_profiles_json", "TEXT")
        _ensure_run_column(connection, "regime_summary_json", "TEXT")
        _ensure_run_column(connection, "bootstrap_summary_json", "TEXT")
        _ensure_run_column(connection, "runtime_settings_json", "TEXT")
        _ensure_run_column(connection, "probabilistic_sharpe_ratio", "REAL")
        _ensure_run_column(connection, "deflated_sharpe_ratio", "REAL")
        _ensure_run_column(connection, "in_sample_permutation_pvalue", "REAL")
        _ensure_run_column(connection, "walk_forward_permutation_pvalue", "REAL")
        _ensure_run_column(connection, "validation_trial_count", "INTEGER")
        _ensure_run_column(connection, "validation_status", "TEXT")
        _ensure_run_column(connection, "validation_protocol_json", "TEXT")
        _ensure_run_column(connection, "validation_gate_results_json", "TEXT")
        _ensure_run_column(connection, "snapshot_quality_status", "TEXT")
        _ensure_run_column(connection, "snapshot_quality_flag_count", "INTEGER")
        _ensure_run_column(connection, "snapshot_quality_flags_json", "TEXT")
        _ensure_run_column(connection, "snapshot_quality_report_json", "TEXT")
        _ensure_run_column(connection, "snapshot_provenance_json", "TEXT")
        _ensure_run_column(connection, "snapshot_build_version", "TEXT")
        _ensure_run_column(connection, "snapshot_source_hash", "TEXT")
        _ensure_run_column(connection, "study_signature", "TEXT")
        _ensure_run_column(connection, "agent_loop_metadata_json", "TEXT")
        _ensure_run_column(connection, "research_program_version", "TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_phases (
                run_id TEXT NOT NULL,
                phase_name TEXT NOT NULL,
                layer_name TEXT NOT NULL,
                decision TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                selected_parameters_json TEXT NOT NULL,
                permutation_count INTEGER NOT NULL,
                search_summary_json TEXT NOT NULL,
                PRIMARY KEY (run_id, phase_name, layer_name),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_decisions (
                run_id TEXT NOT NULL,
                decision_family TEXT NOT NULL,
                iteration INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT,
                validation_status TEXT,
                metric_name TEXT,
                metric_value REAL,
                candidate_run_ids_json TEXT NOT NULL,
                kept_run_ids_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, decision_family, iteration, ordinal),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS validation_runs (
                run_id TEXT PRIMARY KEY,
                validation_status TEXT,
                probabilistic_sharpe_ratio REAL,
                deflated_sharpe_ratio REAL,
                pbo_score REAL,
                spa_pvalue REAL,
                min_backtest_length INTEGER,
                min_trade_count INTEGER,
                trial_count INTEGER,
                failed_gates_json TEXT NOT NULL,
                gate_results_json TEXT NOT NULL,
                validation_bundle_json TEXT NOT NULL,
                validation_protocol_json TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS stress_runs (
                run_id TEXT NOT NULL,
                scenario_name TEXT NOT NULL,
                severity REAL,
                passed INTEGER NOT NULL,
                failure_reasons_json TEXT NOT NULL,
                sharpe REAL,
                max_drawdown REAL,
                resolved_profile_json TEXT NOT NULL,
                stress_metrics_json TEXT NOT NULL,
                target_regimes_json TEXT NOT NULL,
                PRIMARY KEY (run_id, scenario_name),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS candidate_trials (
                run_id TEXT NOT NULL,
                phase_name TEXT NOT NULL,
                layer_name TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                decision TEXT NOT NULL,
                oos_sharpe REAL,
                parameters_json TEXT NOT NULL,
                permutation_count INTEGER NOT NULL,
                fill_event_count INTEGER,
                partial_fill_event_count INTEGER,
                average_fill_ratio REAL,
                min_fill_ratio REAL,
                search_source TEXT,
                seed_evidence_json TEXT NOT NULL DEFAULT '{}',
                regime_similarity_json TEXT NOT NULL DEFAULT '{}',
                payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, phase_name, layer_name, ordinal),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id) ON DELETE CASCADE
            )
            """
        )
        _ensure_table_column(connection, "candidate_trials", "fill_event_count", "INTEGER")
        _ensure_table_column(connection, "candidate_trials", "partial_fill_event_count", "INTEGER")
        _ensure_table_column(connection, "candidate_trials", "average_fill_ratio", "REAL")
        _ensure_table_column(connection, "candidate_trials", "min_fill_ratio", "REAL")
        _ensure_table_column(connection, "candidate_trials", "search_source", "TEXT")
        _ensure_table_column(connection, "candidate_trials", "seed_evidence_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_table_column(connection, "candidate_trials", "regime_similarity_json", "TEXT NOT NULL DEFAULT '{}'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS data_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                symbol TEXT,
                venue TEXT,
                build_version TEXT,
                source_hash TEXT,
                raw_source_id TEXT,
                raw_source_hash TEXT,
                parser_version TEXT,
                normalization_version TEXT,
                exchange_rules_version TEXT,
                feature_version TEXT,
                scenario_pack_version TEXT,
                cost_model_version TEXT,
                dataset_version TEXT,
                quality_status TEXT,
                quality_flag_count INTEGER NOT NULL,
                feature_quality_status TEXT,
                feature_quality_issue_count INTEGER NOT NULL DEFAULT 0,
                feature_quality_report_json TEXT NOT NULL DEFAULT '{}',
                snapshot_quality_flags_json TEXT NOT NULL,
                snapshot_quality_report_json TEXT NOT NULL,
                snapshot_provenance_json TEXT NOT NULL,
                provider TEXT,
                build_mode TEXT,
                first_seen_run_id TEXT,
                last_seen_run_id TEXT,
                usage_count INTEGER NOT NULL
            )
            """
        )
        _ensure_table_column(connection, "data_snapshots", "raw_source_id", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "raw_source_hash", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "parser_version", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "normalization_version", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "exchange_rules_version", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "feature_version", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "scenario_pack_version", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "cost_model_version", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "dataset_version", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "feature_quality_status", "TEXT")
        _ensure_table_column(connection, "data_snapshots", "feature_quality_issue_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_table_column(connection, "data_snapshots", "feature_quality_report_json", "TEXT NOT NULL DEFAULT '{}'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS meta_policies (
                run_id TEXT NOT NULL,
                policy_id TEXT NOT NULL,
                policy_family TEXT NOT NULL,
                status TEXT,
                action_map_json TEXT NOT NULL,
                training_stats_json TEXT NOT NULL,
                eval_validation_run_id TEXT,
                eval_stress_summary_json TEXT NOT NULL,
                artifact_path TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, policy_id),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_index (
                resource_id TEXT PRIMARY KEY,
                resource_group TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT,
                license TEXT,
                status TEXT,
                intended_usage TEXT,
                local_destination TEXT,
                pinned_ref TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS run_resource_links (
                run_id TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                link_role TEXT NOT NULL,
                evidence_source TEXT NOT NULL,
                rationale TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, resource_id, link_role),
                FOREIGN KEY (run_id) REFERENCES research_runs(run_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS artifact_ingestion_manifest (
                artifact_path TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                group_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                ingested_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        _initialize_v3_registry_schema(connection)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_research_runs_symbol ON research_runs(symbol)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_research_runs_decision ON research_runs(decision)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_research_phases_layer_name ON research_phases(layer_name)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_decisions_run_iteration ON agent_decisions(run_id, iteration)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_decisions_family_decision ON agent_decisions(decision_family, decision)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_validation_runs_status ON validation_runs(validation_status)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_validation_runs_pbo_spa ON validation_runs(pbo_score, spa_pvalue)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_stress_runs_run_passed ON stress_runs(run_id, passed)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_stress_runs_scenario_name ON stress_runs(scenario_name)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidate_trials_run_layer ON candidate_trials(run_id, layer_name)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidate_trials_decision_oos ON candidate_trials(decision, oos_sharpe)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_data_snapshots_build_hash ON data_snapshots(build_version, source_hash)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_data_snapshots_quality ON data_snapshots(quality_status)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_data_snapshots_dataset_version ON data_snapshots(dataset_version)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_meta_policies_family_status ON meta_policies(policy_family, status)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_meta_policies_eval_validation ON meta_policies(eval_validation_run_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_resource_index_group_status ON resource_index(resource_group, status)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_resource_index_license ON resource_index(license)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_resource_links_run_role ON run_resource_links(run_id, link_role)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_resource_links_resource ON run_resource_links(resource_id)"
        )
        connection.commit()
    finally:
        connection.close()


def _initialize_v3_registry_schema(connection: sqlite3.Connection) -> None:
    event_types_sql = ", ".join(f"'{event_type}'" for event_type in V3_EXECUTION_EVENT_TYPES)
    connection.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS datasets (
            dataset_id TEXT PRIMARY KEY,
            snapshot_id TEXT,
            raw_source_id TEXT,
            raw_source_hash TEXT,
            parser_version TEXT,
            normalization_version TEXT,
            exchange_rules_version TEXT,
            feature_version TEXT,
            scenario_pack_version TEXT,
            cost_model_version TEXT,
            dataset_version TEXT,
            venue TEXT,
            symbols_json TEXT NOT NULL DEFAULT '[]',
            created_at_utc TEXT,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS strategy_families (
            family TEXT PRIMARY KEY,
            description TEXT,
            allowed_signal_tf TEXT NOT NULL DEFAULT '1h',
            allowed_execution_tf TEXT NOT NULL DEFAULT '15m',
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS strategy_variants (
            variant_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            family TEXT NOT NULL,
            entry_logic_hash TEXT NOT NULL,
            exit_logic_hash TEXT NOT NULL,
            feature_set_hash TEXT NOT NULL,
            parameter_schema_hash TEXT NOT NULL,
            symbol_scope_hash TEXT NOT NULL,
            regime_scope_hash TEXT NOT NULL,
            venue_model_id TEXT NOT NULL,
            execution_model_id TEXT NOT NULL,
            cost_model_id TEXT NOT NULL,
            feature_version TEXT NOT NULL,
            data_snapshot_id TEXT NOT NULL,
            code_sha TEXT NOT NULL,
            parameters_json TEXT NOT NULL DEFAULT '{{}}',
            created_at_utc TEXT,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            parent_artifact_id TEXT,
            strategy_id TEXT NOT NULL,
            variant_id TEXT NOT NULL,
            family TEXT,
            venue TEXT,
            signal_tf TEXT,
            execution_tf TEXT,
            validation_report_id TEXT,
            code_sha TEXT,
            artifact_sha256 TEXT NOT NULL,
            artifact_path TEXT,
            rollout_stage TEXT,
            approved INTEGER NOT NULL DEFAULT 0,
            created_at_utc TEXT,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS experiments (
            experiment_id TEXT PRIMARY KEY,
            parent_experiment_id TEXT,
            created_at_utc TEXT,
            completed_at_utc TEXT,
            repo_sha TEXT,
            prompt_sha TEXT,
            strategy_id TEXT,
            variant_id TEXT,
            family TEXT,
            venue TEXT,
            signal_tf TEXT,
            execution_tf TEXT,
            symbol_scope_json TEXT NOT NULL DEFAULT '[]',
            regime_scope_json TEXT NOT NULL DEFAULT '{{}}',
            dataset_snapshot_id TEXT,
            feature_version TEXT,
            cost_model_version TEXT,
            execution_model_version TEXT,
            scenario_pack_version TEXT,
            search_budget_bucket TEXT,
            optimizer_name TEXT,
            optimizer_budget REAL,
            net_return REAL,
            net_pnl_quote REAL,
            sharpe REAL,
            calmar REAL,
            max_dd REAL,
            turnover REAL,
            capacity_usd REAL,
            dsr REAL,
            pbo REAL,
            spa_pvalue REAL,
            cpcv_median_sharpe REAL,
            cpcv_p10_sharpe REAL,
            holdout_pass_bool INTEGER,
            status TEXT,
            fail_code_primary TEXT,
            fail_codes_secondary_json TEXT NOT NULL DEFAULT '[]',
            artifact_id TEXT,
            notes TEXT,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS validations (
            validation_id TEXT PRIMARY KEY,
            experiment_id TEXT,
            run_id TEXT,
            status TEXT,
            validation_bundle_json TEXT NOT NULL DEFAULT '{{}}',
            created_at_utc TEXT,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS failures (
            failure_id TEXT PRIMARY KEY,
            experiment_id TEXT,
            run_id TEXT,
            fail_code_primary TEXT NOT NULL,
            fail_codes_secondary_json TEXT NOT NULL DEFAULT '[]',
            reason TEXT,
            created_at_utc TEXT,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS deployments (
            deployment_id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            rollout_stage TEXT NOT NULL,
            venue TEXT,
            status TEXT,
            started_at_utc TEXT,
            ended_at_utc TEXT,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS scenario_packs (
            scenario_pack_id TEXT PRIMARY KEY,
            scenario_pack_version TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            approved_by TEXT,
            approved_at_utc TEXT,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS alert_runbooks (
            alert_code TEXT PRIMARY KEY,
            severity TEXT NOT NULL,
            owner_action TEXT NOT NULL,
            default_automation TEXT NOT NULL,
            required_evidence_json TEXT NOT NULL DEFAULT '[]',
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS lifecycle_journal (
            lifecycle_event_id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            source_state TEXT,
            target_state TEXT NOT NULL,
            revalidation_required INTEGER NOT NULL DEFAULT 0,
            reason_code TEXT NOT NULL,
            runbook_code TEXT NOT NULL,
            automation TEXT NOT NULL,
            severity TEXT NOT NULL,
            ts_utc TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS live_metrics (
            metric_id TEXT PRIMARY KEY,
            deployment_id TEXT,
            artifact_id TEXT,
            ts_utc TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value REAL,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS portfolio_plans (
            plan_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS paper_portfolio_decisions (
            decision_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            portfolio_plan_id TEXT NOT NULL,
            ts_utc TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL DEFAULT 900,
            status TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS paper_calibration_feedback (
            artifact_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            source_model_version TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            status TEXT NOT NULL,
            telemetry_quality_score REAL NOT NULL DEFAULT 0,
            sample_count INTEGER NOT NULL DEFAULT 0,
            artifact_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS human_override_journal (
            override_event_id TEXT PRIMARY KEY,
            ts_utc TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            action TEXT NOT NULL,
            artifact_id TEXT,
            confirmation TEXT,
            status TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS execution_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_exchange TEXT NOT NULL,
            ts_gateway TEXT NOT NULL,
            ts_engine TEXT NOT NULL,
            source TEXT NOT NULL,
            symbol TEXT,
            side TEXT,
            order_id_client TEXT,
            order_id_exchange TEXT,
            parent_intent_id TEXT,
            event_type TEXT NOT NULL CHECK (event_type IN ({event_types_sql})),
            qty REAL,
            price REAL,
            status TEXT,
            reason_code TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            schema_version INTEGER NOT NULL DEFAULT 1,
            previous_digest TEXT,
            event_digest TEXT NOT NULL,
            segment_digest TEXT NOT NULL
        );

        CREATE TRIGGER IF NOT EXISTS execution_events_no_update
        BEFORE UPDATE ON execution_events
        BEGIN
            SELECT RAISE(ABORT, 'execution_events is append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS execution_events_no_delete
        BEFORE DELETE ON execution_events
        BEGIN
            SELECT RAISE(ABORT, 'execution_events is append-only');
        END;

        CREATE TABLE IF NOT EXISTS orders_live (
            order_id_client TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            price REAL,
            qty REAL,
            filled_qty REAL NOT NULL DEFAULT 0,
            status TEXT,
            order_id_exchange TEXT,
            parent_intent_id TEXT,
            last_event_id INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS fills (
            fill_id TEXT PRIMARY KEY,
            order_id_client TEXT,
            ts_exchange TEXT,
            symbol TEXT,
            side TEXT,
            price REAL,
            qty REAL,
            fee REAL,
            maker_taker TEXT,
            liquidity_flag TEXT,
            source_event_id INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY,
            net_qty REAL NOT NULL,
            entry_price REAL,
            unrealized_pnl REAL NOT NULL DEFAULT 0,
            margin_mode TEXT,
            leverage REAL,
            last_event_id INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS risk_state (
            scope_id TEXT PRIMARY KEY,
            exposure REAL NOT NULL DEFAULT 0,
            margin_usage REAL NOT NULL DEFAULT 0,
            realized_pnl REAL NOT NULL DEFAULT 0,
            unrealized_pnl REAL NOT NULL DEFAULT 0,
            drawdown REAL NOT NULL DEFAULT 0,
            last_event_id INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS order_telemetry (
            telemetry_id TEXT PRIMARY KEY,
            order_id_client TEXT,
            intent_id TEXT,
            symbol TEXT,
            side TEXT,
            ts_signal TEXT,
            ts_send TEXT,
            ts_ack TEXT,
            ts_last_fill TEXT,
            qty_submitted REAL,
            qty_filled REAL,
            qty_canceled REAL,
            price_limit REAL,
            mid_at_send REAL,
            mid_at_ack REAL,
            expected_price REAL,
            live_vwap_price REAL,
            fee_quote REAL,
            fee_rate REAL,
            slip_bps REAL,
            effective_spread_bps REAL,
            spread_bps REAL,
            depth_at_price REAL,
            topn_depth REAL,
            vol_1m REAL,
            vol_15m REAL,
            latency_rtt_ms REAL,
            maker_ratio REAL,
            was_canceled_by_engine INTEGER,
            was_rejected INTEGER,
            risk_blocked INTEGER,
            drift_bps REAL,
            impact_bps REAL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS risk_events (
            risk_event_id TEXT PRIMARY KEY,
            ts_utc TEXT NOT NULL,
            source_event_id INTEGER,
            reason_code TEXT,
            severity TEXT,
            action TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS market_snapshots (
            market_snapshot_id TEXT PRIMARY KEY,
            ts_exchange TEXT NOT NULL,
            venue TEXT,
            symbol TEXT,
            bid REAL,
            ask REAL,
            mid REAL,
            spread_bps REAL,
            depth_json TEXT NOT NULL DEFAULT '{{}}',
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS signal_snapshots (
            signal_snapshot_id TEXT PRIMARY KEY,
            ts_signal TEXT NOT NULL,
            artifact_id TEXT,
            symbol TEXT,
            signal_json TEXT NOT NULL DEFAULT '{{}}',
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS position_snapshots (
            position_snapshot_id TEXT PRIMARY KEY,
            ts_utc TEXT NOT NULL,
            account_id TEXT,
            symbol TEXT,
            net_qty REAL,
            entry_price REAL,
            mark_price REAL,
            unrealized_pnl REAL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS funding_events (
            funding_event_id TEXT PRIMARY KEY,
            ts_utc TEXT NOT NULL,
            symbol TEXT,
            position_notional REAL,
            funding_rate REAL,
            funding_fee REAL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS executor_health (
            health_id TEXT PRIMARY KEY,
            ts_utc TEXT NOT NULL,
            executor_id TEXT,
            status TEXT,
            websocket_lag_ms REAL,
            order_ack_latency_ms REAL,
            clock_drift_ms REAL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS paper_sessions (
            session_id TEXT PRIMARY KEY,
            host_id TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at_utc TEXT NOT NULL,
            stopped_at_utc TEXT,
            heartbeat_at_utc TEXT,
            portfolio_plan_id TEXT,
            symbols_json TEXT NOT NULL DEFAULT '[]',
            streams_json TEXT NOT NULL DEFAULT '[]',
            code_hash TEXT,
            config_checksum TEXT,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS paper_session_artifacts (
            session_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            artifact_sha256 TEXT,
            lifecycle_state TEXT,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{{}}',
            PRIMARY KEY (session_id, artifact_id)
        );

        CREATE TABLE IF NOT EXISTS paper_stream_events (
            stream_event_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            received_at_utc TEXT NOT NULL,
            exchange_event_time TEXT,
            stream_name TEXT NOT NULL,
            symbol TEXT,
            sequence_id TEXT,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{{}}',
            parse_status TEXT NOT NULL,
            lag_ms REAL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS paper_session_summaries (
            session_id TEXT PRIMARY KEY,
            created_at_utc TEXT NOT NULL,
            status TEXT NOT NULL,
            uptime_seconds REAL NOT NULL DEFAULT 0,
            artifact_count INTEGER NOT NULL DEFAULT 0,
            symbol_count INTEGER NOT NULL DEFAULT 0,
            order_count INTEGER NOT NULL DEFAULT 0,
            filled_count INTEGER NOT NULL DEFAULT 0,
            partial_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0,
            risk_block_count INTEGER NOT NULL DEFAULT 0,
            funding_fee REAL NOT NULL DEFAULT 0,
            paper_pnl REAL NOT NULL DEFAULT 0,
            drawdown REAL NOT NULL DEFAULT 0,
            telemetry_quality_score REAL NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS replay_checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            created_at_utc TEXT,
            last_event_id INTEGER NOT NULL,
            projection_digest TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS cash_ledger (
            ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            account_id TEXT,
            currency TEXT,
            amount REAL NOT NULL,
            reason TEXT,
            reference_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS pnl_attribution (
            pnl_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            run_id TEXT,
            symbol TEXT,
            realized_strategy_pnl REAL NOT NULL DEFAULT 0,
            unrealized_pnl REAL NOT NULL DEFAULT 0,
            fees REAL NOT NULL DEFAULT 0,
            funding REAL NOT NULL DEFAULT 0,
            slippage REAL NOT NULL DEFAULT 0,
            transfers REAL NOT NULL DEFAULT 0,
            cash_balance_delta REAL NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS fee_ledger (
            fee_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            run_id TEXT,
            symbol TEXT,
            order_id_client TEXT,
            fee_quote REAL NOT NULL,
            fee_rate REAL,
            maker_taker TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS funding_ledger (
            funding_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            run_id TEXT,
            symbol TEXT,
            position_notional REAL,
            funding_rate REAL,
            funding_fee REAL NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS transfer_ledger (
            transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            account_id TEXT,
            currency TEXT,
            amount REAL NOT NULL,
            transfer_type TEXT,
            reference_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS equity_snapshots (
            equity_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            account_id TEXT,
            equity REAL NOT NULL,
            cash_balance REAL,
            unrealized_pnl REAL,
            realized_pnl REAL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS data_retention_policies (
            policy_id TEXT PRIMARY KEY,
            table_name TEXT NOT NULL,
            storage_tier TEXT NOT NULL,
            compression TEXT,
            snapshot_digest TEXT,
            backup_location TEXT,
            restore_status TEXT,
            retention_expires_at_utc TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS backup_manifests (
            backup_id TEXT PRIMARY KEY,
            created_at_utc TEXT,
            backup_location TEXT,
            snapshot_digest TEXT,
            table_count INTEGER,
            status TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE TABLE IF NOT EXISTS restore_manifests (
            restore_id TEXT PRIMARY KEY,
            backup_id TEXT,
            restored_at_utc TEXT,
            restore_status TEXT,
            verification_digest TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );

        CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);
        CREATE INDEX IF NOT EXISTS idx_experiments_artifact ON experiments(artifact_id);
        CREATE INDEX IF NOT EXISTS idx_execution_events_type ON execution_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_execution_events_order ON execution_events(order_id_client);
        CREATE INDEX IF NOT EXISTS idx_fills_order ON fills(order_id_client);
        CREATE INDEX IF NOT EXISTS idx_order_telemetry_symbol ON order_telemetry(symbol);
        CREATE INDEX IF NOT EXISTS idx_lifecycle_journal_artifact ON lifecycle_journal(artifact_id);
        CREATE INDEX IF NOT EXISTS idx_portfolio_plans_status ON portfolio_plans(status);
        CREATE INDEX IF NOT EXISTS idx_human_override_journal_artifact ON human_override_journal(artifact_id);
        CREATE INDEX IF NOT EXISTS idx_human_override_journal_action ON human_override_journal(action);
        CREATE INDEX IF NOT EXISTS idx_paper_portfolio_decisions_session ON paper_portfolio_decisions(session_id);
        CREATE INDEX IF NOT EXISTS idx_paper_calibration_feedback_session ON paper_calibration_feedback(session_id);
        CREATE INDEX IF NOT EXISTS idx_paper_sessions_status ON paper_sessions(status);
        CREATE INDEX IF NOT EXISTS idx_paper_stream_events_session ON paper_stream_events(session_id);
        CREATE INDEX IF NOT EXISTS idx_paper_session_artifacts_session ON paper_session_artifacts(session_id);
        """
    )


def append_execution_event(
    db_path: Path,
    *,
    ts_exchange: str,
    ts_gateway: str,
    ts_engine: str,
    source: str,
    event_type: str,
    symbol: str | None = None,
    side: str | None = None,
    order_id_client: str | None = None,
    order_id_exchange: str | None = None,
    parent_intent_id: str | None = None,
    qty: float | None = None,
    price: float | None = None,
    status: str | None = None,
    reason_code: str | None = None,
    metadata: dict[str, object] | None = None,
    schema_version: int = 1,
) -> int:
    initialize_memory_db(db_path)
    metadata_json = json.dumps(metadata or {}, sort_keys=True)
    connection = _connect_to_db(db_path)
    try:
        previous = connection.execute(
            "SELECT event_digest FROM execution_events ORDER BY event_id DESC LIMIT 1"
        ).fetchone()
        previous_digest = str(previous[0]) if previous and previous[0] is not None else ""
        digest_payload = {
            "previous_digest": previous_digest,
            "ts_exchange": ts_exchange,
            "ts_gateway": ts_gateway,
            "ts_engine": ts_engine,
            "source": source,
            "symbol": symbol,
            "side": side,
            "order_id_client": order_id_client,
            "order_id_exchange": order_id_exchange,
            "parent_intent_id": parent_intent_id,
            "event_type": event_type,
            "qty": qty,
            "price": price,
            "status": status,
            "reason_code": reason_code,
            "metadata_json": metadata_json,
            "schema_version": schema_version,
        }
        event_digest = hashlib.sha256(json.dumps(digest_payload, sort_keys=True).encode("utf-8")).hexdigest()
        segment_digest = hashlib.sha256(f"{previous_digest}:{event_digest}".encode("utf-8")).hexdigest()
        cursor = connection.execute(
            """
            INSERT INTO execution_events (
                ts_exchange,
                ts_gateway,
                ts_engine,
                source,
                symbol,
                side,
                order_id_client,
                order_id_exchange,
                parent_intent_id,
                event_type,
                qty,
                price,
                status,
                reason_code,
                metadata_json,
                schema_version,
                previous_digest,
                event_digest,
                segment_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts_exchange,
                ts_gateway,
                ts_engine,
                source,
                symbol,
                side,
                order_id_client,
                order_id_exchange,
                parent_intent_id,
                event_type,
                qty,
                price,
                status,
                reason_code,
                metadata_json,
                schema_version,
                previous_digest or None,
                event_digest,
                segment_digest,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def rebuild_execution_projections(db_path: Path) -> dict[str, object]:
    initialize_memory_db(db_path)
    connection = _connect_to_db(db_path)
    try:
        for table_name in ("orders_live", "fills", "positions", "risk_state"):
            connection.execute(f"DELETE FROM {table_name}")

        rows = connection.execute(
            """
            SELECT
                event_id,
                ts_exchange,
                symbol,
                side,
                order_id_client,
                order_id_exchange,
                parent_intent_id,
                event_type,
                qty,
                price,
                status,
                reason_code,
                metadata_json
            FROM execution_events
            ORDER BY event_id ASC
            """
        ).fetchall()
        position_qty: dict[str, float] = {}
        position_cost: dict[str, float] = {}
        seen_fill_ids: set[str] = set()
        for row in rows:
            (
                event_id,
                ts_exchange,
                symbol,
                side,
                order_id_client,
                order_id_exchange,
                parent_intent_id,
                event_type,
                qty,
                price,
                status,
                reason_code,
                metadata_json,
            ) = row
            metadata = _load_json_dict(metadata_json)
            signed_qty = _signed_quantity(side, qty)
            if event_type in {
                "INTENT_CREATE",
                "ORDER_SUBMIT",
                "ORDER_ACK",
                "FILL",
                "ORDER_CANCEL_REQUEST",
                "ORDER_NEW_SUBMIT",
                "ORDER_NEW_ACK",
                "ORDER_PARTIAL_FILL",
                "ORDER_FILL",
                "ORDER_CANCEL_SUBMIT",
                "ORDER_CANCEL_ACK",
                "ORDER_CANCEL_REJECT",
                "ORDER_REJECT",
            } and order_id_client:
                existing = connection.execute(
                    "SELECT qty, filled_qty FROM orders_live WHERE order_id_client = ?",
                    (order_id_client,),
                ).fetchone()
                order_qty = float(existing[0]) if existing and existing[0] is not None else (float(qty) if qty else 0.0)
                filled_qty = float(existing[1]) if existing and existing[1] is not None else 0.0
                if event_type in {"ORDER_PARTIAL_FILL", "ORDER_FILL", "FILL"}:
                    fill_id = str(metadata.get("fill_id") or f"event:{event_id}")
                    if fill_id not in seen_fill_ids:
                        seen_fill_ids.add(fill_id)
                        filled_qty += abs(float(qty) if qty is not None else 0.0)
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO fills (
                                fill_id,
                                order_id_client,
                                ts_exchange,
                                symbol,
                                side,
                                price,
                                qty,
                                fee,
                                maker_taker,
                                liquidity_flag,
                                source_event_id,
                                metadata_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                fill_id,
                                order_id_client,
                                ts_exchange,
                                symbol,
                                side,
                                price,
                                abs(float(qty) if qty is not None else 0.0),
                                _float_or_none(metadata.get("fee")),
                                str(metadata.get("maker_taker")) if metadata.get("maker_taker") is not None else None,
                                str(metadata.get("liquidity_flag")) if metadata.get("liquidity_flag") is not None else None,
                                event_id,
                                metadata_json,
                            ),
                        )
                        if symbol:
                            position_qty[symbol] = position_qty.get(symbol, 0.0) + signed_qty
                            position_cost[symbol] = position_cost.get(symbol, 0.0) + signed_qty * float(price or 0.0)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO orders_live (
                        order_id_client,
                        symbol,
                        side,
                        price,
                        qty,
                        filled_qty,
                        status,
                        order_id_exchange,
                        parent_intent_id,
                        last_event_id,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id_client,
                        symbol,
                        side,
                        price,
                        order_qty,
                        filled_qty,
                        status or event_type,
                        order_id_exchange,
                        parent_intent_id,
                        event_id,
                        metadata_json,
                    ),
                )
            if event_type == "RISK_BLOCK":
                connection.execute(
                    """
                    INSERT OR REPLACE INTO risk_state (
                        scope_id,
                        last_event_id,
                        metadata_json
                    ) VALUES (?, ?, ?)
                    """,
                    (reason_code or "risk_block", event_id, metadata_json),
                )

        for symbol, net_qty in position_qty.items():
            entry_price = abs(position_cost.get(symbol, 0.0) / net_qty) if net_qty else None
            connection.execute(
                """
                INSERT OR REPLACE INTO positions (
                    symbol,
                    net_qty,
                    entry_price,
                    last_event_id,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    net_qty,
                    entry_price,
                    rows[-1][0] if rows else None,
                    json.dumps({"source": "execution_event_replay"}, sort_keys=True),
                ),
            )

        last_event_id = int(rows[-1][0]) if rows else 0
        projection_digest = _projection_digest(connection)
        connection.execute(
            """
            INSERT OR REPLACE INTO replay_checkpoints (
                checkpoint_id,
                created_at_utc,
                last_event_id,
                projection_digest,
                metadata_json
            ) VALUES (?, datetime('now'), ?, ?, ?)
            """,
            (
                f"replay:{last_event_id}",
                last_event_id,
                projection_digest,
                json.dumps({"event_count": len(rows)}, sort_keys=True),
            ),
        )
        connection.commit()
        return {
            "event_count": len(rows),
            "last_event_id": last_event_id,
            "projection_digest": projection_digest,
            "fill_count": len(seen_fill_ids),
        }
    finally:
        connection.close()


def reconcile_accounting_ledgers(db_path: Path) -> dict[str, float | None]:
    initialize_memory_db(db_path)
    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        pnl = connection.execute(
            """
            SELECT
                COALESCE(SUM(realized_strategy_pnl), 0),
                COALESCE(SUM(unrealized_pnl), 0),
                COALESCE(SUM(fees), 0),
                COALESCE(SUM(funding), 0),
                COALESCE(SUM(slippage), 0),
                COALESCE(SUM(transfers), 0),
                COALESCE(SUM(cash_balance_delta), 0)
            FROM pnl_attribution
            """
        ).fetchone()
        cash = connection.execute("SELECT COALESCE(SUM(amount), 0) FROM cash_ledger").fetchone()
        transfers = connection.execute("SELECT COALESCE(SUM(amount), 0) FROM transfer_ledger").fetchone()
        latest_equity = connection.execute(
            "SELECT equity FROM equity_snapshots ORDER BY ts_utc DESC, equity_snapshot_id DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    return {
        "realized_strategy_pnl": float(pnl[0]),
        "unrealized_pnl": float(pnl[1]),
        "fees": float(pnl[2]),
        "funding": float(pnl[3]),
        "slippage": float(pnl[4]),
        "transfers": float(transfers[0]),
        "cash_balance_delta": float(cash[0]),
        "pnl_cash_balance_delta": float(pnl[6]),
        "latest_equity": float(latest_equity[0]) if latest_equity and latest_equity[0] is not None else None,
    }


def _signed_quantity(side: object, qty: object) -> float:
    if qty is None:
        return 0.0
    sign = -1.0 if str(side or "").upper() == "SELL" else 1.0
    return sign * abs(float(qty))


def _projection_digest(connection: sqlite3.Connection) -> str:
    payload: dict[str, object] = {}
    for table_name in ("orders_live", "fills", "positions", "risk_state"):
        rows = connection.execute(f"SELECT * FROM {table_name} ORDER BY 1 ASC").fetchall()
        payload[table_name] = [tuple(row) for row in rows]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def ingest_artifact_directory(db_path: Path, artifacts_dir: Path) -> int:
    initialize_memory_db(db_path)
    if not artifacts_dir.exists():
        return 0

    ingested = 0
    connection = _connect_to_db(db_path)
    try:
        resource_rows = _load_resource_index_rows(_resource_ledger_path())
        _replace_resource_index_rows(connection, rows=resource_rows)
        available_resource_ids = {
            str(row["resource_id"])
            for row in resource_rows
            if isinstance(row.get("resource_id"), str) and str(row["resource_id"])
        }
        for runcard_path in sorted(artifacts_dir.glob("*.runcard.json")):
            ingestion_metadata = _build_artifact_ingestion_metadata(runcard_path)
            if _artifact_group_unchanged(connection, ingestion_metadata):
                continue
            runcard = load_runcard(runcard_path)
            dashboard_path = _paired_dashboard_path(runcard_path)
            autoresearch_report_path = _paired_autoresearch_report_path(runcard_path)
            karpathy_ledger_path = _paired_karpathy_ledger_path(runcard_path)
            dashboard_payload = load_dashboard_payload(dashboard_path) if dashboard_path.exists() else {}
            _upsert_run(connection, runcard, autoresearch_report_path)
            _upsert_data_snapshot_row(connection, run_id=runcard.run_id, runcard=runcard)
            _replace_validation_run_row(
                connection,
                run_id=runcard.run_id,
                row=_build_validation_run_row(runcard),
            )
            _upsert_v3_registry_rows(connection, run_id=runcard.run_id, runcard=runcard)
            _replace_stress_run_rows(
                connection,
                run_id=runcard.run_id,
                rows=_build_stress_run_rows(runcard.run_id, dashboard_payload),
            )
            _replace_candidate_trial_rows(
                connection,
                run_id=runcard.run_id,
                rows=_build_candidate_trial_rows(runcard.run_id, dashboard_payload),
            )
            _replace_phase_rows(connection, runcard.run_id, dashboard_payload, runcard.phase, runcard.artifacts.get("selected_parameters_json", "{}"))
            _replace_agent_decision_rows(
                connection,
                run_id=runcard.run_id,
                decision_rows=_load_agent_decision_rows(karpathy_ledger_path, run_id=runcard.run_id),
            )
            _replace_meta_policy_rows(
                connection,
                run_id=runcard.run_id,
                rows=_build_meta_policy_rows(run_id=runcard.run_id, runcard=runcard),
            )
            _replace_run_resource_link_rows(
                connection,
                run_id=runcard.run_id,
                rows=_build_run_resource_link_rows(
                    run_id=runcard.run_id,
                    runcard=runcard,
                    available_resource_ids=available_resource_ids,
                ),
            )
            _record_artifact_ingestion(connection, run_id=runcard.run_id, metadata=ingestion_metadata)
            ingested += 1
        connection.commit()
    finally:
        connection.close()
    return ingested


def _paired_dashboard_path(runcard_path: Path) -> Path:
    return runcard_path.with_name(runcard_path.name.replace(".runcard.json", ".dashboard.json"))


def _paired_autoresearch_report_path(runcard_path: Path) -> Path:
    return runcard_path.with_name(runcard_path.name.replace(".runcard.json", ".autoresearch.json"))


def _paired_karpathy_ledger_path(runcard_path: Path) -> Path:
    return runcard_path.with_name(runcard_path.name.replace(".runcard.json", ".karpathy-ledger.json"))


def _build_artifact_ingestion_metadata(runcard_path: Path) -> dict[str, object]:
    files = [
        _artifact_file_metadata(path)
        for path in (
            runcard_path,
            _paired_dashboard_path(runcard_path),
            _paired_autoresearch_report_path(runcard_path),
            _paired_karpathy_ledger_path(runcard_path),
        )
    ]
    group_hash = hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema_version": ARTIFACT_INGESTION_SCHEMA_VERSION,
        "artifact_path": str(runcard_path.resolve()),
        "group_hash": group_hash,
        "files": files,
    }


def _artifact_file_metadata(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if not path.exists():
        return {
            "path": str(resolved),
            "exists": False,
            "size": None,
            "mtime_ns": None,
            "sha256": None,
        }
    stat = path.stat()
    return {
        "path": str(resolved),
        "exists": True,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _artifact_group_unchanged(connection: sqlite3.Connection, metadata: dict[str, object]) -> bool:
    row = connection.execute(
        """
        SELECT schema_version, group_hash
        FROM artifact_ingestion_manifest
        WHERE artifact_path = ?
        """,
        (metadata["artifact_path"],),
    ).fetchone()
    if row is None:
        return False
    return (
        int(row["schema_version"]) == ARTIFACT_INGESTION_SCHEMA_VERSION
        and str(row["group_hash"]) == str(metadata["group_hash"])
    )


def _record_artifact_ingestion(connection: sqlite3.Connection, *, run_id: str, metadata: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO artifact_ingestion_manifest (
            artifact_path,
            run_id,
            schema_version,
            group_hash,
            metadata_json,
            ingested_at_utc
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            metadata["artifact_path"],
            run_id,
            ARTIFACT_INGESTION_SCHEMA_VERSION,
            metadata["group_hash"],
            json.dumps(metadata, sort_keys=True),
        ),
    )


def _resource_ledger_path() -> Path:
    raw_path = os.environ.get("ENGINE_RESOURCE_LEDGER_PATH", "").strip()
    if raw_path:
        return Path(raw_path)
    return Path("references/upstream/PROVENANCE_LEDGER.json")


def _upsert_run(connection: sqlite3.Connection, runcard, autoresearch_report_path: Path) -> None:
    lineage = _load_lineage_from_report(autoresearch_report_path)
    validation_protocol_json = runcard.artifacts.get("validation_protocol_json", "{}")
    validation_protocol = _load_json_dict(validation_protocol_json)
    validation_bundle = normalize_validation_bundle(
        validation_protocol,
        dsr_override=_float_or_none(runcard.metrics.get("deflated_sharpe_ratio")),
        psr_override=_float_or_none(runcard.metrics.get("probabilistic_sharpe_ratio")),
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO research_runs (
            run_id,
            strategy_hash,
            phase,
            split_id,
            seed,
            decision,
            symbol,
            venue,
            snapshot_id,
            final_status,
            selection_oos_sharpe,
            selection_oos_net_pnl,
            selection_oos_drawdown,
            scenario_pass_rate,
            accepted_layers,
            probabilistic_sharpe_ratio,
            deflated_sharpe_ratio,
            in_sample_permutation_pvalue,
            walk_forward_permutation_pvalue,
            validation_trial_count,
            validation_status,
            validation_protocol_json,
            validation_gate_results_json,
            snapshot_quality_status,
            snapshot_quality_flag_count,
            snapshot_quality_flags_json,
            snapshot_quality_report_json,
            snapshot_provenance_json,
            snapshot_build_version,
            snapshot_source_hash,
            study_signature,
            selected_variant,
            parent_batch_run_id,
            parent_batch_report_path,
            source_config_path,
            accepted_duplicate_match_run_id,
            accepted_duplicate_match_type,
            accepted_duplicate_source_config_path,
            accepted_duplicate_source_report_path,
            scenario_profiles_json,
            regime_summary_json,
            bootstrap_summary_json,
            runtime_settings_json,
            selected_parameters_json,
            parameter_search_json,
            agent_loop_metadata_json,
            research_program_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            runcard.run_id,
            runcard.strategy_hash,
            runcard.phase,
            runcard.split_id,
            runcard.seed,
            runcard.decision.decision,
            runcard.artifacts.get("symbol"),
            runcard.artifacts.get("venue"),
            runcard.artifacts.get("snapshot_id"),
            runcard.artifacts.get("final_status"),
            float(runcard.metrics.get("selection_oos_sharpe", 0.0)),
            float(runcard.metrics.get("selection_oos_net_pnl", 0.0)),
            float(runcard.metrics.get("selection_oos_drawdown", 0.0)),
            float(runcard.metrics.get("scenario_pass_rate", 0.0)),
            float(runcard.metrics.get("accepted_layers", 0.0)),
            _float_or_none(validation_bundle.get("probabilistic_sharpe_ratio")),
            _float_or_none(validation_bundle.get("deflated_sharpe_ratio")),
            _float_or_none(runcard.metrics.get("in_sample_permutation_pvalue")),
            _float_or_none(runcard.metrics.get("walk_forward_permutation_pvalue")),
            int(runcard.metrics.get("validation_trial_count", 0)),
            validation_bundle.get("status") or runcard.artifacts.get("validation_status"),
            validation_protocol_json,
            runcard.artifacts.get("validation_gate_results_json", "{}"),
            runcard.artifacts.get("snapshot_quality_status"),
            int(runcard.artifacts.get("snapshot_quality_flag_count", 0)),
            runcard.artifacts.get("snapshot_quality_flags_json", "[]"),
            runcard.artifacts.get("snapshot_quality_report_json", "{}"),
            runcard.artifacts.get("snapshot_provenance_json", "{}"),
            runcard.artifacts.get("snapshot_build_version", ""),
            runcard.artifacts.get("snapshot_source_hash", ""),
            runcard.artifacts.get("study_signature"),
            lineage.get("selected_variant"),
            lineage.get("parent_batch_run_id"),
            lineage.get("parent_batch_report_path"),
            lineage.get("source_config_path"),
            lineage.get("accepted_duplicate_match_run_id"),
            lineage.get("accepted_duplicate_match_type"),
            lineage.get("accepted_duplicate_source_config_path"),
            lineage.get("accepted_duplicate_source_report_path"),
            runcard.artifacts.get("scenario_profiles_json", "{}"),
            runcard.artifacts.get("regime_summary_json", "{}"),
            runcard.artifacts.get("bootstrap_summary_json", "{}"),
            runcard.artifacts.get("runtime_settings_json", "{}"),
            runcard.artifacts.get("selected_parameters_json", "{}"),
            runcard.artifacts.get("parameter_search_json", "{}"),
            runcard.artifacts.get("agent_loop_metadata_json", "{}"),
            runcard.artifacts.get("research_program_version", ""),
        ),
    )


def _load_lineage_from_report(report_path: Path) -> dict[str, object]:
    if not report_path.exists():
        return {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    lineage = payload.get("research_lineage", {})
    return lineage if isinstance(lineage, dict) else {}


def _load_agent_decision_rows(report_path: Path, *, run_id: str) -> list[dict[str, object]]:
    if not report_path.exists():
        return []
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return []

    rows: list[dict[str, object]] = []
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        decision = entry.get("decision")
        if not isinstance(decision, str) or not decision:
            continue
        iteration = entry.get("iteration", 0)
        if not isinstance(iteration, int):
            continue
        candidate_run_ids = entry.get("candidate_run_ids", [])
        kept_run_ids = entry.get("kept_run_ids", [])
        rows.append(
            {
                "run_id": run_id,
                "decision_family": "karpathy",
                "iteration": iteration,
                "ordinal": ordinal,
                "decision": decision,
                "reason": str(entry.get("reason", "")) if entry.get("reason") is not None else None,
                "validation_status": (
                    str(entry.get("validation_status")) if entry.get("validation_status") is not None else None
                ),
                "metric_name": str(entry.get("metric_name")) if entry.get("metric_name") is not None else None,
                "metric_value": _float_or_none(entry.get("metric_value")),
                "candidate_run_ids_json": json.dumps(
                    list(candidate_run_ids) if isinstance(candidate_run_ids, list) else [],
                    sort_keys=True,
                ),
                "kept_run_ids_json": json.dumps(
                    list(kept_run_ids) if isinstance(kept_run_ids, list) else [],
                    sort_keys=True,
                ),
                "payload_json": json.dumps(entry, sort_keys=True),
            }
        )
    return rows


def _load_json_dict(raw: object) -> dict[str, object]:
    if not isinstance(raw, str):
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _ensure_run_column(connection: sqlite3.Connection, column_name: str, column_type: str) -> None:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(research_runs)").fetchall()
    }
    if column_name in columns:
        return
    connection.execute(f"ALTER TABLE research_runs ADD COLUMN {column_name} {column_type}")


def _ensure_table_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name in columns:
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _float_or_none(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _build_validation_run_row(runcard) -> dict[str, object] | None:
    validation_protocol_json = runcard.artifacts.get("validation_protocol_json", "{}")
    validation_protocol = _load_json_dict(validation_protocol_json)
    validation_bundle = normalize_validation_bundle(
        validation_protocol,
        dsr_override=_float_or_none(runcard.metrics.get("deflated_sharpe_ratio")),
        psr_override=_float_or_none(runcard.metrics.get("probabilistic_sharpe_ratio")),
    )
    validation_status = validation_bundle.get("status") or runcard.artifacts.get("validation_status")
    trial_count = _int_or_none(runcard.metrics.get("validation_trial_count"))
    if trial_count is None:
        trial_count = _int_or_none(validation_protocol.get("validation_trial_count"))
    failed_gates = validation_bundle.get("failed_gates", [])
    if not isinstance(failed_gates, list):
        failed_gates = []
    gate_results_json = runcard.artifacts.get("validation_gate_results_json", "{}")
    gate_results = _load_json_dict(gate_results_json)

    has_payload = any(
        value is not None and value != {}
        for value in (
            validation_status,
            validation_bundle.get("probabilistic_sharpe_ratio"),
            validation_bundle.get("deflated_sharpe_ratio"),
            validation_bundle.get("pbo_score"),
            validation_bundle.get("spa_pvalue"),
            validation_protocol if validation_protocol else None,
            gate_results if gate_results else None,
        )
    )
    if not has_payload:
        return None

    return {
        "run_id": runcard.run_id,
        "validation_status": str(validation_status) if validation_status is not None else None,
        "probabilistic_sharpe_ratio": _float_or_none(validation_bundle.get("probabilistic_sharpe_ratio")),
        "deflated_sharpe_ratio": _float_or_none(validation_bundle.get("deflated_sharpe_ratio")),
        "pbo_score": _float_or_none(validation_bundle.get("pbo_score")),
        "spa_pvalue": _float_or_none(validation_bundle.get("spa_pvalue")),
        "min_backtest_length": _int_or_none(validation_protocol.get("min_backtest_length")),
        "min_trade_count": _int_or_none(validation_protocol.get("min_trade_count")),
        "trial_count": trial_count,
        "failed_gates_json": json.dumps(list(failed_gates), sort_keys=True),
        "gate_results_json": json.dumps(gate_results, sort_keys=True),
        "validation_bundle_json": json.dumps(validation_bundle, sort_keys=True),
        "validation_protocol_json": json.dumps(validation_protocol, sort_keys=True),
    }


def _replace_validation_run_row(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    row: dict[str, object] | None,
) -> None:
    connection.execute("DELETE FROM validation_runs WHERE run_id = ?", (run_id,))
    if row is None:
        return
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["run_id"],
            row["validation_status"],
            row["probabilistic_sharpe_ratio"],
            row["deflated_sharpe_ratio"],
            row["pbo_score"],
            row["spa_pvalue"],
            row["min_backtest_length"],
            row["min_trade_count"],
            row["trial_count"],
            row["failed_gates_json"],
            row["gate_results_json"],
            row["validation_bundle_json"],
            row["validation_protocol_json"],
        ),
    )


def _build_stress_run_rows(run_id: str, dashboard_payload: dict[str, object]) -> list[dict[str, object]]:
    scenarios = dashboard_payload.get("scenarios", [])
    if not isinstance(scenarios, list):
        return []

    rows: list[dict[str, object]] = []
    for entry in scenarios:
        if not isinstance(entry, dict):
            continue
        scenario_name = entry.get("scenario_name")
        if not isinstance(scenario_name, str) or not scenario_name:
            continue
        resolved_profile = entry.get("resolved_profile", {})
        if not isinstance(resolved_profile, dict):
            resolved_profile = {}
        stress_metrics = entry.get("stress_metrics", {})
        if not isinstance(stress_metrics, dict):
            stress_metrics = {}
        raw_target_regimes = resolved_profile.get("target_regimes", [])
        target_regimes = (
            [str(item) for item in raw_target_regimes if isinstance(item, str)]
            if isinstance(raw_target_regimes, list)
            else []
        )
        failure_reasons = entry.get("failure_reasons", [])
        if not isinstance(failure_reasons, list):
            failure_reasons = []
        rows.append(
            {
                "run_id": run_id,
                "scenario_name": scenario_name,
                "severity": _float_or_none(entry.get("severity")),
                "passed": 1 if bool(entry.get("passed")) else 0,
                "failure_reasons_json": json.dumps(
                    [str(item) for item in failure_reasons if isinstance(item, str)],
                    sort_keys=True,
                ),
                "sharpe": _float_or_none(entry.get("sharpe")),
                "max_drawdown": _float_or_none(entry.get("max_drawdown")),
                "resolved_profile_json": json.dumps(resolved_profile, sort_keys=True),
                "stress_metrics_json": json.dumps(stress_metrics, sort_keys=True),
                "target_regimes_json": json.dumps(target_regimes, sort_keys=True),
            }
        )
    return rows


def _build_candidate_trial_rows(run_id: str, dashboard_payload: dict[str, object]) -> list[dict[str, object]]:
    phases = dashboard_payload.get("phases", [])
    if not isinstance(phases, list):
        return []

    rows: list[dict[str, object]] = []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        layer_name = phase.get("layer_name")
        if not isinstance(layer_name, str) or not layer_name:
            continue
        candidate_trials = phase.get("candidate_trials", [])
        source_label = "candidate_trials"
        if not isinstance(candidate_trials, list) or not candidate_trials:
            candidate_trials = phase.get("search_summary", [])
            source_label = "search_summary"
        if not isinstance(candidate_trials, list):
            continue
        for ordinal, candidate in enumerate(candidate_trials):
            if not isinstance(candidate, dict):
                continue
            parameters = candidate.get("parameters", {})
            if not isinstance(parameters, dict):
                parameters = {}
            decision = candidate.get("decision", phase.get("decision", "unknown"))
            execution_pressure_summary = candidate.get("execution_pressure_summary", {})
            if not isinstance(execution_pressure_summary, dict):
                execution_pressure_summary = {}
            search_source = candidate.get("search_source", source_label)
            seed_evidence = candidate.get("seed_evidence", {})
            if not isinstance(seed_evidence, dict):
                seed_evidence = {}
            regime_similarity = candidate.get("regime_similarity", seed_evidence.get("regime_similarity", {}))
            if not isinstance(regime_similarity, dict):
                regime_similarity = {}
            rows.append(
                {
                    "run_id": run_id,
                    "phase_name": str(phase.get("phase_name", "unknown")),
                    "layer_name": layer_name,
                    "ordinal": ordinal,
                    "decision": str(decision),
                    "oos_sharpe": _float_or_none(candidate.get("oos_sharpe")),
                    "parameters_json": json.dumps(parameters, sort_keys=True),
                    "permutation_count": int(phase.get("permutation_count", 1)),
                    "fill_event_count": _int_or_none(execution_pressure_summary.get("fill_event_count")),
                    "partial_fill_event_count": _int_or_none(execution_pressure_summary.get("partial_fill_event_count")),
                    "average_fill_ratio": _float_or_none(execution_pressure_summary.get("average_fill_ratio")),
                    "min_fill_ratio": _float_or_none(execution_pressure_summary.get("min_fill_ratio")),
                    "search_source": str(search_source) if search_source not in (None, "") else source_label,
                    "seed_evidence_json": json.dumps(seed_evidence, sort_keys=True),
                    "regime_similarity_json": json.dumps(regime_similarity, sort_keys=True),
                    "payload_json": json.dumps(candidate, sort_keys=True),
                }
            )
    return rows


def _load_resource_index_rows(ledger_path: Path) -> list[dict[str, object]]:
    if not ledger_path.exists():
        return []
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    rows: list[dict[str, object]] = []
    group_map = {
        "required_repos": "required_repo",
        "conditional_repos": "conditional_repo",
        "required_non_repo_sources": "non_repo_source",
    }
    for key, group_name in group_map.items():
        entries = payload.get(key, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            resource_id = entry.get("id")
            if not isinstance(resource_id, str) or not resource_id:
                continue
            sources = entry.get("sources", [])
            first_source = sources[0] if isinstance(sources, list) and sources and isinstance(sources[0], dict) else {}
            title = entry.get("repo_full_name") or entry.get("title") or resource_id
            url = entry.get("url") or first_source.get("url")
            rows.append(
                {
                    "resource_id": resource_id,
                    "resource_group": group_name,
                    "title": str(title),
                    "url": str(url) if isinstance(url, str) and url else None,
                    "license": str(entry.get("license")) if isinstance(entry.get("license"), str) else None,
                    "status": str(entry.get("status")) if isinstance(entry.get("status"), str) else None,
                    "intended_usage": (
                        str(entry.get("intended_usage")) if isinstance(entry.get("intended_usage"), str) else None
                    ),
                    "local_destination": (
                        str(entry.get("local_destination")) if isinstance(entry.get("local_destination"), str) else None
                    ),
                    "pinned_ref": str(entry.get("pinned_ref")) if isinstance(entry.get("pinned_ref"), str) else None,
                    "payload_json": json.dumps(entry, sort_keys=True),
                }
            )
    return rows


def _replace_stress_run_rows(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    rows: list[dict[str, object]],
) -> None:
    connection.execute("DELETE FROM stress_runs WHERE run_id = ?", (run_id,))
    if not rows:
        return
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
                row["run_id"],
                row["scenario_name"],
                row["severity"],
                row["passed"],
                row["failure_reasons_json"],
                row["sharpe"],
                row["max_drawdown"],
                row["resolved_profile_json"],
                row["stress_metrics_json"],
                row["target_regimes_json"],
            )
            for row in rows
        ],
    )


def _upsert_data_snapshot_row(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    runcard,
) -> None:
    snapshot_id = runcard.artifacts.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        return
    provenance_json = runcard.artifacts.get("snapshot_provenance_json", "{}")
    provenance = _load_json_dict(provenance_json)
    feature_quality_report_json = runcard.artifacts.get("feature_quality_report_json")
    feature_quality_report = _load_json_dict(feature_quality_report_json) if isinstance(feature_quality_report_json, str) else {}
    if not feature_quality_report:
        provenance_feature_quality = provenance.get("feature_quality_report")
        if isinstance(provenance_feature_quality, dict):
            feature_quality_report = provenance_feature_quality
            feature_quality_report_json = json.dumps(feature_quality_report, sort_keys=True)
    if not isinstance(feature_quality_report_json, str) or not feature_quality_report_json:
        feature_quality_report_json = "{}"
    feature_quality_status = (
        runcard.artifacts.get("feature_quality_status")
        or provenance.get("feature_quality_status")
        or feature_quality_report.get("status")
    )
    feature_quality_issues = feature_quality_report.get("issues", [])
    feature_quality_issue_count = runcard.artifacts.get("feature_quality_issue_count")
    if feature_quality_issue_count is None:
        feature_quality_issue_count = len(feature_quality_issues) if isinstance(feature_quality_issues, list) else 0
    existing = connection.execute(
        "SELECT first_seen_run_id FROM data_snapshots WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()
    usage_count = connection.execute(
        "SELECT COUNT(*) FROM research_runs WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()
    first_seen_run_id = str(existing[0]) if existing and existing[0] is not None else run_id
    connection.execute(
        """
        INSERT OR REPLACE INTO data_snapshots (
            snapshot_id,
            symbol,
            venue,
            build_version,
            source_hash,
            raw_source_id,
            raw_source_hash,
            parser_version,
            normalization_version,
            exchange_rules_version,
            feature_version,
            scenario_pack_version,
            cost_model_version,
            dataset_version,
            quality_status,
            quality_flag_count,
            feature_quality_status,
            feature_quality_issue_count,
            feature_quality_report_json,
            snapshot_quality_flags_json,
            snapshot_quality_report_json,
            snapshot_provenance_json,
            provider,
            build_mode,
            first_seen_run_id,
            last_seen_run_id,
            usage_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            str(runcard.artifacts.get("symbol")) if runcard.artifacts.get("symbol") is not None else None,
            str(runcard.artifacts.get("venue")) if runcard.artifacts.get("venue") is not None else None,
            str(provenance.get("build_version")) if isinstance(provenance.get("build_version"), str) else runcard.artifacts.get("snapshot_build_version"),
            str(provenance.get("source_hash")) if isinstance(provenance.get("source_hash"), str) else runcard.artifacts.get("snapshot_source_hash"),
            _string_or_none(provenance.get("raw_source_id")),
            _string_or_none(provenance.get("raw_source_hash")),
            _string_or_none(provenance.get("parser_version")),
            _string_or_none(provenance.get("normalization_version")),
            _string_or_none(provenance.get("exchange_rules_version")),
            _string_or_none(provenance.get("feature_version")),
            _string_or_none(provenance.get("scenario_pack_version")),
            _string_or_none(provenance.get("cost_model_version")),
            _string_or_none(provenance.get("dataset_version")),
            str(runcard.artifacts.get("snapshot_quality_status")) if runcard.artifacts.get("snapshot_quality_status") is not None else None,
            int(runcard.artifacts.get("snapshot_quality_flag_count", 0)),
            str(feature_quality_status) if feature_quality_status is not None else None,
            int(feature_quality_issue_count),
            feature_quality_report_json,
            runcard.artifacts.get("snapshot_quality_flags_json", "[]"),
            runcard.artifacts.get("snapshot_quality_report_json", "{}"),
            provenance_json,
            str(provenance.get("provider")) if isinstance(provenance.get("provider"), str) else None,
            str(provenance.get("build_mode")) if isinstance(provenance.get("build_mode"), str) else None,
            first_seen_run_id,
            run_id,
            int(usage_count[0]) if usage_count is not None and usage_count[0] is not None else 0,
        ),
    )


def _upsert_v3_registry_rows(connection: sqlite3.Connection, *, run_id: str, runcard) -> None:
    artifacts = runcard.artifacts
    metrics = runcard.metrics
    snapshot_id = str(artifacts.get("snapshot_id") or f"dataset:{run_id}")
    provenance = _load_json_dict(artifacts.get("snapshot_provenance_json", "{}"))
    symbol = str(artifacts.get("symbol") or "")
    venue = str(artifacts.get("venue") or "")
    family = str(artifacts.get("family") or runcard.phase or "unknown")
    strategy_id = str(artifacts.get("strategy_id") or runcard.strategy_hash)
    variant_id = str(artifacts.get("variant_id") or _stable_hash("variant", strategy_id, snapshot_id, family))
    feature_version = str(artifacts.get("feature_version") or provenance.get("feature_version") or "")
    cost_model_version = str(artifacts.get("cost_model_version") or provenance.get("cost_model_version") or "")
    execution_model_id = str(artifacts.get("execution_model_id") or artifacts.get("execution_model_version") or "")
    scenario_pack_version = str(artifacts.get("scenario_pack_version") or provenance.get("scenario_pack_version") or "")
    code_sha = str(artifacts.get("code_sha") or artifacts.get("repo_sha") or "")
    artifact_id = str(artifacts.get("artifact_id") or f"artifact:{run_id}")
    artifact_parent_id = _string_or_none(artifacts.get("artifact_parent_id") or artifacts.get("parent_artifact_id"))
    validation_id = str(artifacts.get("validation_report_id") or f"validation:{run_id}")
    validation_protocol = _load_json_dict(artifacts.get("validation_protocol_json", "{}"))
    validation_bundle = normalize_validation_bundle(
        validation_protocol,
        dsr_override=_float_or_none(metrics.get("deflated_sharpe_ratio")),
        psr_override=_float_or_none(metrics.get("probabilistic_sharpe_ratio")),
    )
    validation_status = str(validation_bundle.get("status") or artifacts.get("validation_status") or runcard.decision.decision)
    fail_code_primary = str(
        artifacts.get("fail_code_primary")
        or artifacts.get("fail_code")
        or (runcard.decision.reasons[0] if runcard.decision.reasons else "")
    )
    fail_codes_secondary_json = artifacts.get("fail_codes_secondary_json", "[]")
    if not isinstance(fail_codes_secondary_json, str):
        fail_codes_secondary_json = json.dumps(fail_codes_secondary_json, sort_keys=True)

    connection.execute(
        """
        INSERT OR REPLACE INTO datasets (
            dataset_id,
            snapshot_id,
            raw_source_id,
            raw_source_hash,
            parser_version,
            normalization_version,
            exchange_rules_version,
            feature_version,
            scenario_pack_version,
            cost_model_version,
            dataset_version,
            venue,
            symbols_json,
            payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            snapshot_id,
            _string_or_none(provenance.get("raw_source_id")),
            _string_or_none(provenance.get("raw_source_hash")),
            _string_or_none(provenance.get("parser_version")),
            _string_or_none(provenance.get("normalization_version")),
            _string_or_none(provenance.get("exchange_rules_version")),
            feature_version,
            scenario_pack_version,
            cost_model_version,
            _string_or_none(provenance.get("dataset_version")),
            venue,
            json.dumps([symbol] if symbol else [], sort_keys=True),
            json.dumps(provenance, sort_keys=True),
        ),
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO strategy_families (
            family,
            description,
            payload_json
        ) VALUES (?, ?, ?)
        """,
        (
            family,
            str(artifacts.get("family_description") or ""),
            json.dumps({"source_run_id": run_id}, sort_keys=True),
        ),
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO strategy_variants (
            variant_id,
            strategy_id,
            family,
            entry_logic_hash,
            exit_logic_hash,
            feature_set_hash,
            parameter_schema_hash,
            symbol_scope_hash,
            regime_scope_hash,
            venue_model_id,
            execution_model_id,
            cost_model_id,
            feature_version,
            data_snapshot_id,
            code_sha,
            parameters_json,
            payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            variant_id,
            strategy_id,
            family,
            str(artifacts.get("entry_logic_hash") or _stable_hash("entry", strategy_id)),
            str(artifacts.get("exit_logic_hash") or _stable_hash("exit", strategy_id)),
            str(artifacts.get("feature_set_hash") or _stable_hash("features", feature_version, snapshot_id)),
            str(artifacts.get("parameter_schema_hash") or _stable_hash("params", artifacts.get("selected_parameters_json", "{}"))),
            str(artifacts.get("symbol_scope_hash") or _stable_hash("symbols", symbol)),
            str(artifacts.get("regime_scope_hash") or _stable_hash("regimes", artifacts.get("regime_summary_json", "{}"))),
            str(artifacts.get("venue_model_id") or venue),
            execution_model_id,
            str(artifacts.get("cost_model_id") or cost_model_version),
            feature_version,
            snapshot_id,
            code_sha,
            artifacts.get("selected_parameters_json", "{}"),
            json.dumps({"source_run_id": run_id}, sort_keys=True),
        ),
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO artifacts (
            artifact_id,
            parent_artifact_id,
            strategy_id,
            variant_id,
            family,
            venue,
            signal_tf,
            execution_tf,
            validation_report_id,
            code_sha,
            artifact_sha256,
            artifact_path,
            rollout_stage,
            approved,
            payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            artifact_parent_id,
            strategy_id,
            variant_id,
            family,
            venue,
            str(artifacts.get("signal_tf") or "1h"),
            str(artifacts.get("execution_tf") or "15m"),
            validation_id,
            code_sha,
            str(artifacts.get("artifact_sha256") or _stable_hash("artifact", run_id, strategy_id, snapshot_id)),
            _string_or_none(artifacts.get("artifact_path")),
            str(artifacts.get("rollout_stage") or "research_candidate"),
            1 if runcard.decision.decision in {"promoted", "approved"} else 0,
            json.dumps({"source_run_id": run_id}, sort_keys=True),
        ),
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO experiments (
            experiment_id,
            parent_experiment_id,
            created_at_utc,
            completed_at_utc,
            repo_sha,
            prompt_sha,
            strategy_id,
            variant_id,
            family,
            venue,
            signal_tf,
            execution_tf,
            symbol_scope_json,
            regime_scope_json,
            dataset_snapshot_id,
            feature_version,
            cost_model_version,
            execution_model_version,
            scenario_pack_version,
            search_budget_bucket,
            optimizer_name,
            optimizer_budget,
            net_return,
            net_pnl_quote,
            sharpe,
            calmar,
            max_dd,
            turnover,
            capacity_usd,
            dsr,
            pbo,
            spa_pvalue,
            cpcv_median_sharpe,
            cpcv_p10_sharpe,
            holdout_pass_bool,
            status,
            fail_code_primary,
            fail_codes_secondary_json,
            artifact_id,
            notes,
            payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            _string_or_none(artifacts.get("parent_experiment_id")),
            _string_or_none(artifacts.get("created_at_utc")),
            _string_or_none(artifacts.get("completed_at_utc")),
            code_sha,
            _string_or_none(artifacts.get("prompt_sha")),
            strategy_id,
            variant_id,
            family,
            venue,
            str(artifacts.get("signal_tf") or "1h"),
            str(artifacts.get("execution_tf") or "15m"),
            json.dumps([symbol] if symbol else [], sort_keys=True),
            artifacts.get("regime_scope_json", artifacts.get("regime_summary_json", "{}")),
            snapshot_id,
            feature_version,
            cost_model_version,
            execution_model_id,
            scenario_pack_version,
            _string_or_none(artifacts.get("search_budget_bucket")),
            _string_or_none(artifacts.get("optimizer_name")),
            _float_or_none(artifacts.get("optimizer_budget")),
            _float_or_none(metrics.get("net_return")),
            _float_or_none(metrics.get("selection_oos_net_pnl")),
            _float_or_none(metrics.get("selection_oos_sharpe")),
            _float_or_none(metrics.get("calmar")),
            _float_or_none(metrics.get("selection_oos_drawdown")),
            _float_or_none(metrics.get("turnover")),
            _float_or_none(metrics.get("capacity_usd")),
            _float_or_none(validation_bundle.get("deflated_sharpe_ratio")),
            _float_or_none(validation_bundle.get("pbo_score")),
            _float_or_none(validation_bundle.get("spa_pvalue")),
            _float_or_none(validation_bundle.get("cpcv_median_sharpe")),
            _float_or_none(validation_bundle.get("cpcv_p10_sharpe")),
            1 if runcard.decision.decision in {"promoted", "approved"} else 0,
            runcard.decision.decision,
            fail_code_primary or None,
            fail_codes_secondary_json,
            artifact_id,
            str(artifacts.get("notes") or ""),
            json.dumps({"source_run_id": run_id, "split_id": runcard.split_id}, sort_keys=True),
        ),
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO validations (
            validation_id,
            experiment_id,
            run_id,
            status,
            validation_bundle_json,
            payload_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            validation_id,
            run_id,
            run_id,
            validation_status,
            json.dumps(validation_bundle, sort_keys=True),
            json.dumps(validation_protocol, sort_keys=True),
        ),
    )
    if fail_code_primary:
        connection.execute(
            """
            INSERT OR REPLACE INTO failures (
                failure_id,
                experiment_id,
                run_id,
                fail_code_primary,
                fail_codes_secondary_json,
                reason,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{run_id}:{fail_code_primary}",
                run_id,
                run_id,
                fail_code_primary,
                fail_codes_secondary_json,
                "; ".join(runcard.decision.reasons),
                json.dumps({"source_run_id": run_id}, sort_keys=True),
            ),
        )


def _stable_hash(*parts: object) -> str:
    payload = json.dumps([str(part) for part in parts], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _replace_candidate_trial_rows(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    rows: list[dict[str, object]],
) -> None:
    connection.execute("DELETE FROM candidate_trials WHERE run_id = ?", (run_id,))
    if not rows:
        return
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
                row["run_id"],
                row["phase_name"],
                row["layer_name"],
                row["ordinal"],
                row["decision"],
                row["oos_sharpe"],
                row["parameters_json"],
                row["permutation_count"],
                row["fill_event_count"],
                row["partial_fill_event_count"],
                row["average_fill_ratio"],
                row["min_fill_ratio"],
                row["search_source"],
                row["seed_evidence_json"],
                row["regime_similarity_json"],
                row["payload_json"],
            )
            for row in rows
        ],
    )


def _replace_resource_index_rows(
    connection: sqlite3.Connection,
    *,
    rows: list[dict[str, object]],
) -> None:
    connection.execute("DELETE FROM resource_index")
    if not rows:
        return
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
                row["resource_id"],
                row["resource_group"],
                row["title"],
                row["url"],
                row["license"],
                row["status"],
                row["intended_usage"],
                row["local_destination"],
                row["pinned_ref"],
                row["payload_json"],
            )
            for row in rows
        ],
    )


def _build_run_resource_link_rows(
    *,
    run_id: str,
    runcard,
    available_resource_ids: set[str],
) -> list[dict[str, object]]:
    artifacts = runcard.artifacts
    links: dict[tuple[str, str], dict[str, object]] = {}

    def add_link(
        resource_id: str,
        link_role: str,
        evidence_source: str,
        rationale: str,
        matched_fields: list[str],
    ) -> None:
        if resource_id not in available_resource_ids:
            return
        key = (resource_id, link_role)
        if key in links:
            return
        links[key] = {
            "run_id": run_id,
            "resource_id": resource_id,
            "link_role": link_role,
            "evidence_source": evidence_source,
            "rationale": rationale,
            "payload_json": json.dumps({"matched_fields": matched_fields}, sort_keys=True),
        }

    provenance = _load_json_dict(artifacts.get("snapshot_provenance_json", "{}"))
    snapshot_fields = [
        name
        for name in ("provider", "build_mode", "build_version", "source_hash")
        if isinstance(provenance.get(name), str) and str(provenance.get(name))
    ]
    if not snapshot_fields:
        snapshot_fields = [
            name
            for name in ("snapshot_build_version", "snapshot_source_hash")
            if artifacts.get(name) not in (None, "")
        ]
    if snapshot_fields:
        add_link(
            "ccxt_manual_and_exchange_capability_docs",
            "snapshot",
            "snapshot_provenance",
            "run stores snapshot provenance/build metadata from the exchange adapter path",
            snapshot_fields,
        )

    venue = str(artifacts.get("venue", "")).strip().lower()
    if venue == "bybit":
        add_link(
            "bybit_funding_and_contract_rule_docs",
            "venue_rules",
            "snapshot_provenance",
            "run venue requires bybit contract and liquidation rule references",
            ["venue"],
        )

    validation_protocol = _load_json_dict(artifacts.get("validation_protocol_json", "{}"))
    validation_bundle = normalize_validation_bundle(
        validation_protocol,
        dsr_override=_float_or_none(runcard.metrics.get("deflated_sharpe_ratio")),
        psr_override=_float_or_none(runcard.metrics.get("probabilistic_sharpe_ratio")),
    )
    if validation_bundle.get("pbo_score") is not None:
        add_link(
            "pbo_cscv_references",
            "validation",
            "validation_protocol",
            "run stores PBO-backed validation evidence",
            ["pbo_score"],
        )
    psr_dsr_fields = [
        name
        for name in ("probabilistic_sharpe_ratio", "deflated_sharpe_ratio")
        if validation_bundle.get(name) is not None
    ]
    if psr_dsr_fields:
        add_link(
            "psr_dsr_references",
            "validation",
            "validation_protocol",
            "run stores PSR/DSR validation evidence",
            psr_dsr_fields,
        )
    if validation_bundle.get("spa_pvalue") is not None:
        add_link(
            "spa_and_arch_bootstrap_spa_docs",
            "validation",
            "validation_protocol",
            "run stores SPA validation evidence",
            ["spa_pvalue"],
        )
    cpcv_fields = [
        name
        for name in ("purge_bars", "embargo_bars", "n_blocks", "n_test_blocks", "cpcv")
        if validation_protocol.get(name) not in (None, "", [])
    ]
    if cpcv_fields:
        add_link(
            "cpcv_purged_cv_references",
            "validation",
            "validation_protocol",
            "run stores purge/embargo or CPCV validation configuration",
            cpcv_fields,
        )

    regime_summary = _load_json_dict(artifacts.get("regime_summary_json", "{}"))
    if regime_summary:
        add_link(
            "hmm_hsmm_references",
            "regime",
            "regime_summary",
            "run stores regime coverage metadata",
            sorted(str(key) for key in regime_summary.keys() if isinstance(key, str)),
        )
    regime_model = str(regime_summary.get("regime_model", "")).lower()
    regime_metadata = regime_summary.get("regime_metadata", {})
    if (
        regime_model == "bocpd"
        or any("changepoint" in str(key).lower() or "bocpd" in str(key).lower() for key in regime_summary)
        or (
            isinstance(regime_metadata, dict)
            and any("changepoint" in str(key).lower() or "bocpd" in str(key).lower() for key in regime_metadata)
        )
    ):
        add_link(
            "bocpd_reference",
            "regime",
            "regime_summary",
            "run stores changepoint-oriented regime metadata",
            sorted(str(key) for key in regime_summary.keys() if isinstance(key, str)),
        )

    bootstrap_summary = _load_json_dict(artifacts.get("bootstrap_summary_json", "{}"))
    if bootstrap_summary:
        add_link(
            "bootstrap_and_dependent_wild_bootstrap_references",
            "stress",
            "bootstrap_summary",
            "run stores bootstrap stress lineage",
            sorted(str(key) for key in bootstrap_summary.keys() if isinstance(key, str)),
        )

    scenario_profiles = _load_json_dict(artifacts.get("scenario_profiles_json", "{}"))
    if scenario_profiles:
        scenario_names = sorted(str(key) for key in scenario_profiles.keys() if isinstance(key, str))
        add_link(
            "crypto_latency_slippage_market_depth_research",
            "stress",
            "scenario_profiles",
            "run stores latency/liquidity-aware scenario profiles",
            scenario_names,
        )
        add_link(
            "amberdata_liquidation_open_interest_reports",
            "stress",
            "scenario_profiles",
            "run stores liquidation/open-interest aware scenario profiles",
            scenario_names,
        )

    return [links[key] for key in sorted(links)]


def _build_meta_policy_rows(
    *,
    run_id: str,
    runcard,
) -> list[dict[str, object]]:
    raw_payload = runcard.artifacts.get("meta_policies_json")
    entries: list[object]
    if isinstance(raw_payload, str) and raw_payload:
        try:
            parsed = json.loads(raw_payload)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, dict):
            entries = [parsed]
        elif isinstance(parsed, list):
            entries = list(parsed)
        else:
            entries = []
    else:
        fallback = runcard.artifacts.get("meta_policy_json")
        if isinstance(fallback, str) and fallback:
            try:
                parsed_fallback = json.loads(fallback)
            except json.JSONDecodeError:
                parsed_fallback = []
            if isinstance(parsed_fallback, dict):
                entries = [parsed_fallback]
            elif isinstance(parsed_fallback, list):
                entries = list(parsed_fallback)
            else:
                entries = []
        else:
            entries = []

    rows: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        policy_id = entry.get("policy_id") or entry.get("id")
        policy_family = entry.get("policy_family") or entry.get("family")
        if not isinstance(policy_id, str) or not policy_id:
            continue
        if not isinstance(policy_family, str) or not policy_family:
            continue
        action_map = entry.get("action_map", {})
        if not isinstance(action_map, dict):
            action_map = {}
        training_stats = entry.get("training_stats", {})
        if not isinstance(training_stats, dict):
            training_stats = {}
        eval_stress_summary = entry.get("eval_stress_summary", {})
        if not isinstance(eval_stress_summary, dict):
            eval_stress_summary = {}
        rows.append(
            {
                "run_id": run_id,
                "policy_id": policy_id,
                "policy_family": policy_family,
                "status": str(entry.get("status")) if entry.get("status") is not None else None,
                "action_map_json": json.dumps(action_map, sort_keys=True),
                "training_stats_json": json.dumps(training_stats, sort_keys=True),
                "eval_validation_run_id": (
                    str(entry.get("eval_validation_run_id"))
                    if entry.get("eval_validation_run_id") is not None
                    else None
                ),
                "eval_stress_summary_json": json.dumps(eval_stress_summary, sort_keys=True),
                "artifact_path": str(entry.get("artifact_path")) if entry.get("artifact_path") is not None else None,
                "payload_json": json.dumps(entry, sort_keys=True),
            }
        )
    return rows


def _replace_run_resource_link_rows(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    rows: list[dict[str, object]],
) -> None:
    connection.execute("DELETE FROM run_resource_links WHERE run_id = ?", (run_id,))
    if not rows:
        return
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
                row["run_id"],
                row["resource_id"],
                row["link_role"],
                row["evidence_source"],
                row["rationale"],
                row["payload_json"],
            )
            for row in rows
        ],
    )


def _replace_meta_policy_rows(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    rows: list[dict[str, object]],
) -> None:
    connection.execute("DELETE FROM meta_policies WHERE run_id = ?", (run_id,))
    if not rows:
        return
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
                row["run_id"],
                row["policy_id"],
                row["policy_family"],
                row["status"],
                row["action_map_json"],
                row["training_stats_json"],
                row["eval_validation_run_id"],
                row["eval_stress_summary_json"],
                row["artifact_path"],
                row["payload_json"],
            )
            for row in rows
        ],
    )


def _replace_agent_decision_rows(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    decision_rows: list[dict[str, object]],
) -> None:
    connection.execute("DELETE FROM agent_decisions WHERE run_id = ?", (run_id,))
    if not decision_rows:
        return
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["run_id"],
                row["decision_family"],
                row["iteration"],
                row["ordinal"],
                row["decision"],
                row["reason"],
                row["validation_status"],
                row["metric_name"],
                row["metric_value"],
                row["candidate_run_ids_json"],
                row["kept_run_ids_json"],
                row["payload_json"],
            )
            for row in decision_rows
        ],
    )


def _replace_phase_rows(
    connection: sqlite3.Connection,
    run_id: str,
    dashboard_payload: dict[str, object],
    fallback_phase: str,
    selected_parameters_json: str,
) -> None:
    connection.execute("DELETE FROM research_phases WHERE run_id = ?", (run_id,))

    phases = dashboard_payload.get("phases", [])
    inserted = False
    if isinstance(phases, list):
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            layer_name = str(phase.get("layer_name", "")).strip()
            if not layer_name:
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO research_phases (
                    run_id,
                    phase_name,
                    layer_name,
                    decision,
                    accepted,
                    selected_parameters_json,
                    permutation_count,
                    search_summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(phase.get("phase_name", fallback_phase)),
                    layer_name,
                    str(phase.get("decision", "unknown")),
                    1 if bool(phase.get("accepted")) else 0,
                    json.dumps(phase.get("selected_parameters", {}), sort_keys=True),
                    int(phase.get("permutation_count", 1)),
                    json.dumps(phase.get("search_summary", []), sort_keys=True),
                ),
            )
            inserted = True

    if inserted:
        return

    try:
        fallback_parameters = json.loads(selected_parameters_json)
    except json.JSONDecodeError:
        fallback_parameters = {}
    if not isinstance(fallback_parameters, dict):
        return

    for layer_name, parameters in fallback_parameters.items():
        if not isinstance(parameters, dict):
            continue
        connection.execute(
            """
            INSERT OR REPLACE INTO research_phases (
                run_id,
                phase_name,
                layer_name,
                decision,
                accepted,
                selected_parameters_json,
                permutation_count,
                search_summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                fallback_phase,
                str(layer_name),
                "accept",
                1,
                json.dumps(parameters, sort_keys=True),
                1,
                "[]",
            ),
        )
