import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from engine.config.models import PromotionDecision, RunCard
from engine.reporting.runcards import save_runcard


def _save_artifacts(
    artifacts_dir: Path,
    run_id: str,
    symbol: str,
    decision: str,
    accepted_layer: str,
    quality_status: str = "clean",
    *,
    build_version: str = "phase1_snapshot_builder_v1",
    source_hash: str = "abc123",
    quality_score: float = 0.92,
    agent_loop_metadata: dict[str, object] | None = None,
    validation_protocol: dict[str, object] | None = None,
    karpathy_entries: list[dict[str, object]] | None = None,
    dashboard_scenarios: list[dict[str, object]] | None = None,
    dashboard_phases: list[dict[str, object]] | None = None,
    meta_policies: list[dict[str, object]] | None = None,
) -> None:
    validation_payload = validation_protocol or {
        "status": "passed",
        "deflated_sharpe_ratio": 0.96,
        "probabilistic_sharpe_ratio": 0.98,
        "pbo_score": 0.08,
        "spa_pvalue": 0.03,
        "purge_bars": 5,
        "embargo_bars": 2,
        "n_blocks": 10,
        "n_test_blocks": 2,
        "cpcv_config": {
            "method": "combinatorial_purged_cv",
            "purge_bars": 5,
            "embargo_bars": 2,
            "n_blocks": 10,
            "n_test_blocks": 2,
        },
        "in_sample_summary": {"trade_count": 23, "sharpe": 1.12},
        "selection_oos_summary": {"trade_count": 11, "sharpe": 0.51},
        "holdout_summary": {"trade_count": 9, "sharpe": 0.27},
        "validation_gate_results": {
            "deflated_sharpe_ratio": True,
            "pbo": True,
            "spa": True,
        },
    }
    save_runcard(
        artifacts_dir / f"{run_id}.runcard.json",
        RunCard(
            run_id=run_id,
            strategy_hash=f"{run_id}-hash",
            phase="phase-5",
            split_id="snap:60-20-20",
            seed=13,
            decision=PromotionDecision(decision=decision, reasons=[]),
            metrics={
                "selection_oos_sharpe": 0.51 if decision == "promoted" else 0.18,
                "selection_oos_net_pnl": 175.0 if decision == "promoted" else 80.0,
                "selection_oos_drawdown": -0.11 if decision == "promoted" else -0.22,
                "scenario_pass_rate": 1.0 if decision == "promoted" else 0.5,
                "accepted_layers": 1.0,
            },
            artifacts={
                "snapshot_id": f"{run_id}-snap",
                "final_status": decision,
                "symbol": symbol,
                "venue": "binance",
                "runtime_settings_json": json.dumps(
                    {
                        "slippage_bps": 5.0 if decision == "promoted" else 7.0,
                        "search_summary_limit": 3 if decision == "promoted" else 5,
                    },
                    sort_keys=True,
                ),
                "snapshot_quality_status": quality_status,
                "snapshot_quality_flag_count": "0" if quality_status == "clean" else "1",
                "snapshot_quality_flags_json": "[]" if quality_status == "clean" else '["missing_funding_rate_count=4"]',
                "snapshot_quality_report_json": json.dumps(
                    {
                        "snapshot_id": f"{run_id}-snap",
                        "report_id": f"{run_id}-snap:quality",
                        "passed": quality_status == "clean",
                        "quality_score": quality_score,
                        "metrics": {
                            "funding_coverage_ratio": 1.0 if quality_status == "clean" else 0.96,
                        },
                    },
                    sort_keys=True,
                ),
                "snapshot_provenance_json": json.dumps(
                    {
                        "provider": "csv",
                        "build_mode": "bundle_csv",
                        "build_version": build_version,
                        "source_hash": source_hash,
                    },
                    sort_keys=True,
                ),
                "snapshot_build_version": build_version,
                "snapshot_source_hash": source_hash,
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
                "selected_parameters_json": json.dumps({accepted_layer: {"aggressiveness": 2}}, sort_keys=True),
                "parameter_search_json": "{}",
                "agent_loop_metadata_json": json.dumps(agent_loop_metadata or {}, sort_keys=True),
                "meta_policies_json": json.dumps(meta_policies or [], sort_keys=True),
                "validation_status": str(validation_payload.get("status", "unknown")),
                "validation_protocol_json": json.dumps(validation_payload, sort_keys=True),
                "validation_gate_results_json": json.dumps(
                    validation_payload.get("validation_gate_results", {}),
                    sort_keys=True,
                ),
            },
        ),
    )
    (artifacts_dir / f"{run_id}.dashboard.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "strategy": {"backbone": "mom_squeeze", "layers": [accepted_layer], "risk_guards": []},
                "phases": (
                    [dict(row) for row in dashboard_phases if isinstance(row, dict)]
                    if isinstance(dashboard_phases, list)
                    else [
                        {
                            "phase_name": "phase-2",
                            "layer_name": accepted_layer,
                            "decision": "accept",
                            "accepted": True,
                            "selected_parameters": {"aggressiveness": 2},
                        }
                    ]
                ),
                "scenarios": [dict(row) for row in dashboard_scenarios if isinstance(row, dict)] if isinstance(dashboard_scenarios, list) else [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    if run_id == "run-sol":
        (artifacts_dir / f"{run_id}.autoresearch.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": decision,
                    "research_lineage": {
                        "selected_variant": "balanced",
                        "parent_batch_run_id": "batch-run",
                        "parent_batch_report_path": "test-memory-cli/artifacts/batch-run.variant-batch.json",
                        "source_config_path": "test-memory-cli/artifacts/run-sol.continued-study.json",
                        "accepted_duplicate_match_run_id": "prior-same-study",
                        "accepted_duplicate_match_type": "duplicate_match",
                        "accepted_duplicate_source_config_path": "test-memory-cli/artifacts/run-sol.accepted-duplicate.json",
                        "accepted_duplicate_source_report_path": "test-memory-cli/artifacts/run-sol.autoresearch.json",
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    if isinstance(karpathy_entries, list):
        (artifacts_dir / f"{run_id}.karpathy-ledger.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "entries": [dict(entry) for entry in karpathy_entries if isinstance(entry, dict)],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )


class MemoryCliTests(unittest.TestCase):
    def test_cli_can_ingest_and_query_research_memory(self) -> None:
        root = Path("test-memory-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(artifacts_dir, "run-sol", "SOLUSDT", "promoted", "kama")
            _save_artifacts(artifacts_dir, "run-btc", "BTCUSDT", "blocked", "hull", quality_status="dirty")

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)
            ingest_payload = json.loads(ingest_completed.stdout)
            self.assertEqual(ingest_payload["ingested_runs"], 2)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--layer",
                    "kama",
                    "--decision",
                    "promoted",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            self.assertIn("run-sol", query_completed.stdout)
            self.assertIn("accepted=kama", query_completed.stdout)
            self.assertIn("variant=balanced", query_completed.stdout)
            self.assertIn("dup=prior-same-study", query_completed.stdout)
            self.assertIn("scenarios=outage-shock", query_completed.stdout)
            self.assertNotIn("run-btc", query_completed.stdout)
            self.assertIn("quality=clean", query_completed.stdout)

            lineage_query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--selected-variant",
                    "balanced",
                    "--parent-batch-run-id",
                    "batch-run",
                    "--format",
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(lineage_query_completed.returncode, 0, msg=lineage_query_completed.stderr)
            lineage_rows = json.loads(lineage_query_completed.stdout)
            self.assertEqual(len(lineage_rows), 1)
            self.assertEqual(lineage_rows[0]["run_id"], "run-sol")
            self.assertEqual(lineage_rows[0]["accepted_duplicate_match_run_id"], "prior-same-study")
            self.assertEqual(lineage_rows[0]["scenario_profiles"]["outage-shock"]["liquidity_penalty_bps"], 65.0)
            self.assertEqual(lineage_rows[0]["runtime_settings"]["slippage_bps"], 5.0)
            self.assertEqual(lineage_rows[0]["snapshot_provenance"]["build_version"], "phase1_snapshot_builder_v1")
            self.assertEqual(lineage_rows[0]["snapshot_provenance"]["source_hash"], "abc123")
            self.assertEqual(lineage_rows[0]["snapshot_quality_report"]["quality_score"], 0.92)
            self.assertTrue(lineage_rows[0]["snapshot_quality_report"]["passed"])

            duplicate_query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--accepted-duplicate-match-run-id",
                    "prior-same-study",
                    "--format",
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(duplicate_query_completed.returncode, 0, msg=duplicate_query_completed.stderr)
            duplicate_rows = json.loads(duplicate_query_completed.stdout)
            self.assertEqual(len(duplicate_rows), 1)
            self.assertEqual(duplicate_rows[0]["run_id"], "run-sol")

            dirty_query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--quality-status",
                    "dirty",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(dirty_query_completed.returncode, 0, msg=dirty_query_completed.stderr)
            self.assertIn("run-btc", dirty_query_completed.stdout)
            self.assertIn("quality=dirty", dirty_query_completed.stdout)
            self.assertIn("build=phase1_snapshot_builder_v1", dirty_query_completed.stdout)
            self.assertNotIn("run-sol", dirty_query_completed.stdout)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_phase3_direct_queries_cover_first_class_lineage_tables(self) -> None:
        root = Path("test-memory-phase3-direct-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        ledger_path = root / "PROVENANCE_LEDGER.json"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            json.dumps(
                {
                    "required_non_repo_sources": [
                        {"id": "ccxt_manual_and_exchange_capability_docs", "title": "CCXT Manual", "status": "reviewed", "intended_usage": "adapter_only"},
                        {"id": "pbo_cscv_references", "title": "PBO", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "psr_dsr_references", "title": "PSR DSR", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "spa_and_arch_bootstrap_spa_docs", "title": "SPA", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "cpcv_purged_cv_references", "title": "CPCV", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "crypto_latency_slippage_market_depth_research", "title": "Latency Slippage", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "amberdata_liquidation_open_interest_reports", "title": "Amberdata", "status": "reviewed", "intended_usage": "reference_only"},
                    ]
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["ENGINE_RESOURCE_LEDGER_PATH"] = str(ledger_path.resolve())
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol-phase3",
                "SOLUSDT",
                "promoted",
                "kama",
                validation_protocol={
                    "status": "passed",
                    "deflated_sharpe_ratio": 0.97,
                    "probabilistic_sharpe_ratio": 0.99,
                    "pbo_score": 0.06,
                    "spa_pvalue": 0.02,
                    "purge_bars": 5,
                    "embargo_bars": 2,
                    "n_blocks": 12,
                    "n_test_blocks": 3,
                    "cpcv_config": {
                        "method": "combinatorial_purged_cv",
                        "purge_bars": 5,
                        "embargo_bars": 2,
                        "n_blocks": 12,
                        "n_test_blocks": 3,
                    },
                    "in_sample_summary": {"trade_count": 18, "sharpe": 1.4},
                    "selection_oos_summary": {"trade_count": 9, "sharpe": 0.8},
                    "holdout_summary": {"trade_count": 7, "sharpe": 0.51},
                    "validation_gate_results": {
                        "deflated_sharpe_ratio": True,
                        "pbo": True,
                        "spa": True,
                    },
                },
                karpathy_entries=[
                    {
                        "decision_family": "karpathy",
                        "iteration": 2,
                        "ordinal": 1,
                        "decision": "promote_variant",
                        "reason": "holdout improved",
                        "validation_status": "passed",
                        "metric_name": "holdout_sharpe",
                        "metric_value": 0.51,
                        "candidate_run_ids": ["run-sol-phase3"],
                        "kept_run_ids": ["run-sol-phase3"],
                    }
                ],
                dashboard_scenarios=[
                    {
                        "scenario_name": "joint_crypto_dislocation",
                        "severity": 0.95,
                        "passed": False,
                        "failure_reasons": ["drawdown_limit"],
                        "sharpe": -0.41,
                        "max_drawdown": -0.34,
                        "stress_metrics": {"liquidation_events": 3},
                        "resolved_profile": {
                            "spread_multiplier": 2.5,
                            "latency_multiplier": 3.0,
                            "target_regimes": ["crash", "squeeze"],
                        },
                    }
                ],
                dashboard_phases=[
                    {
                        "phase_name": "phase-3",
                        "layer_name": "kama",
                        "decision": "accept",
                        "accepted": True,
                        "permutation_count": 9,
                        "selected_parameters": {"length": 21},
                        "search_summary": [
                            {
                                "decision": "accept",
                                "oos_sharpe": 0.63,
                                "parameters": {"length": 21},
                                "execution_pressure_summary": {
                                    "fill_event_count": 2,
                                    "partial_fill_event_count": 1,
                                    "average_fill_ratio": 0.83,
                                    "min_fill_ratio": 0.61,
                                },
                            }
                        ],
                    }
                ],
                meta_policies=[
                    {
                        "policy_id": "meta-bandit-v1",
                        "policy_family": "bandit",
                        "status": "trained",
                        "action_map": {"promote": 1, "reject": 0},
                        "training_stats": {"episodes": 12},
                        "eval_validation_run_id": "run-sol-phase3",
                        "eval_stress_summary": {"worst_scenario": "joint_crypto_dislocation"},
                        "artifact_path": "outputs/meta/meta-bandit-v1.json",
                    }
                ],
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            command_specs = [
                (
                    "query-validation-runs",
                    ["--run-id", "run-sol-phase3"],
                    ["run-sol-phase3", "status=passed", "pbo=0.06"],
                ),
                (
                    "query-stress-runs",
                    ["--run-id", "run-sol-phase3"],
                    ["run-sol-phase3", "joint_crypto_dislocation", "passed=False"],
                ),
                (
                    "query-agent-decisions",
                    ["--run-id", "run-sol-phase3"],
                    ["run-sol-phase3", "family=karpathy", "decision=promote_variant"],
                ),
                (
                    "query-data-snapshots",
                    ["--snapshot-id", "run-sol-phase3-snap"],
                    ["run-sol-phase3-snap", "usage=1", "provider=csv"],
                ),
                (
                    "query-resource-index",
                    ["--resource-group", "non_repo_source"],
                    ["ccxt_manual_and_exchange_capability_docs", "reviewed", "linked_runs=1"],
                ),
                (
                    "query-run-resource-links",
                    ["--run-id", "run-sol-phase3"],
                    ["run-sol-phase3", "resource=ccxt_manual_and_exchange_capability_docs", "role=snapshot"],
                ),
                (
                    "query-meta-policies",
                    ["--run-id", "run-sol-phase3"],
                    ["run-sol-phase3", "policy=meta-bandit-v1", "family=bandit"],
                ),
            ]
            for command_name, extra_args, expected_bits in command_specs:
                completed = subprocess.run(
                    [
                        "python",
                        "-m",
                        "engine.app.cli",
                        command_name,
                        "--db",
                        str(db_path),
                        *extra_args,
                        "--format",
                        "text",
                    ],
                    cwd=Path(__file__).resolve().parents[2],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                )
                self.assertEqual(completed.returncode, 0, msg=f"{command_name}: {completed.stderr}")
                for expected in expected_bits:
                    self.assertIn(expected, completed.stdout, msg=f"{command_name}: missing {expected!r} in {completed.stdout!r}")
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_phase3_mcp_tools_cover_first_class_lineage_tables(self) -> None:
        root = Path("test-memory-phase3-mcp")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        ledger_path = root / "PROVENANCE_LEDGER.json"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            json.dumps(
                {
                    "required_non_repo_sources": [
                        {"id": "ccxt_manual_and_exchange_capability_docs", "title": "CCXT Manual", "status": "reviewed", "intended_usage": "adapter_only"},
                        {"id": "pbo_cscv_references", "title": "PBO", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "psr_dsr_references", "title": "PSR DSR", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "spa_and_arch_bootstrap_spa_docs", "title": "SPA", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "cpcv_purged_cv_references", "title": "CPCV", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "crypto_latency_slippage_market_depth_research", "title": "Latency Slippage", "status": "reviewed", "intended_usage": "reference_only"},
                        {"id": "amberdata_liquidation_open_interest_reports", "title": "Amberdata", "status": "reviewed", "intended_usage": "reference_only"},
                    ]
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["ENGINE_RESOURCE_LEDGER_PATH"] = str(ledger_path.resolve())
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol-phase3-mcp",
                "SOLUSDT",
                "promoted",
                "kama",
                karpathy_entries=[
                    {
                        "decision_family": "karpathy",
                        "iteration": 1,
                        "ordinal": 1,
                        "decision": "promote_variant",
                        "reason": "best holdout",
                        "validation_status": "passed",
                        "metric_name": "holdout_sharpe",
                        "metric_value": 0.44,
                        "candidate_run_ids": ["run-sol-phase3-mcp"],
                        "kept_run_ids": ["run-sol-phase3-mcp"],
                    }
                ],
                dashboard_scenarios=[
                    {
                        "scenario_name": "joint_crypto_dislocation",
                        "severity": 0.8,
                        "passed": True,
                        "failure_reasons": [],
                        "sharpe": 0.12,
                        "max_drawdown": -0.18,
                        "stress_metrics": {"liquidation_events": 0},
                        "resolved_profile": {
                            "spread_multiplier": 1.8,
                            "target_regimes": ["crash"],
                        },
                    }
                ],
                dashboard_phases=[
                    {
                        "phase_name": "phase-3",
                        "layer_name": "kama",
                        "decision": "accept",
                        "accepted": True,
                        "permutation_count": 7,
                        "selected_parameters": {"length": 18},
                        "search_summary": [
                            {
                                "decision": "accept",
                                "oos_sharpe": 0.48,
                                "parameters": {"length": 18},
                            }
                        ],
                    }
                ],
                meta_policies=[
                    {
                        "policy_id": "meta-bandit-v2",
                        "policy_family": "bandit",
                        "status": "trained",
                        "action_map": {"promote": 1},
                        "training_stats": {"episodes": 4},
                        "eval_validation_run_id": "run-sol-phase3-mcp",
                        "eval_stress_summary": {"scenario_count": 1},
                    }
                ],
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            tools_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "mcp-list-tools",
                    "--profile",
                    "read_only",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(tools_completed.returncode, 0, msg=tools_completed.stderr)
            tool_names = {tool["name"] for tool in json.loads(tools_completed.stdout)["tools"]}
            for expected_name in {
                "query_validation_runs",
                "query_stress_runs",
                "query_agent_decisions",
                "query_data_snapshots",
                "query_resource_index",
                "query_run_resource_links",
                "query_meta_policies",
            }:
                self.assertIn(expected_name, tool_names)

            tool_expectations = [
                ("query_validation_runs", {"run_id": "run-sol-phase3-mcp"}, "validation_runs"),
                ("query_stress_runs", {"run_id": "run-sol-phase3-mcp"}, "stress_runs"),
                ("query_agent_decisions", {"run_id": "run-sol-phase3-mcp"}, "agent_decisions"),
                ("query_data_snapshots", {"snapshot_id": "run-sol-phase3-mcp-snap"}, "data_snapshots"),
                ("query_resource_index", {"resource_group": "non_repo_source"}, "resource_index"),
                ("query_run_resource_links", {"run_id": "run-sol-phase3-mcp"}, "run_resource_links"),
                ("query_meta_policies", {"run_id": "run-sol-phase3-mcp"}, "meta_policies"),
            ]
            for tool_name, params, payload_key in tool_expectations:
                completed = subprocess.run(
                    [
                        "python",
                        "-m",
                        "engine.app.cli",
                        "mcp-call",
                        "--profile",
                        "read_only",
                        "--output-dir",
                        str(root.resolve()),
                        "--db",
                        str(db_path),
                        "--tool",
                        tool_name,
                        "--params",
                        json.dumps(params, sort_keys=True),
                    ],
                    cwd=Path(__file__).resolve().parents[2],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                )
                self.assertEqual(completed.returncode, 0, msg=f"{tool_name}: {completed.stderr}")
                payload = json.loads(completed.stdout)
                self.assertIn(payload_key, payload, msg=f"{tool_name}: {payload}")
                self.assertGreaterEqual(len(payload[payload_key]), 1, msg=f"{tool_name}: {payload}")
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_and_summary_memory_surface_loop_pressure_and_next_actions(self) -> None:
        root = Path("test-memory-loop-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol-loop",
                "SOLUSDT",
                "promoted",
                "kama",
                agent_loop_metadata={
                    "loop_id": "loop-01",
                    "failure_taxonomy_counts": {"holdout_failure": 2, "stress_failure": 1},
                    "next_hypotheses": ["raise_holdout_robustness", "harden_stress_scenarios"],
                },
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            self.assertIn("loop=holdout_failure=2,stress_failure=1", query_completed.stdout)
            self.assertIn("next=raise_holdout_robustness", query_completed.stdout)

            summary_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(summary_completed.returncode, 0, msg=summary_completed.stderr)
            self.assertIn("Loop pressure: holdout_failure(2), stress_failure(1)", summary_completed.stdout)
            self.assertIn("Top next actions: raise_holdout_robustness(1), harden_stress_scenarios(1)", summary_completed.stdout)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_surfaces_validation_bundle_headline_fields(self) -> None:
        root = Path("test-memory-validation-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol-validation",
                "SOLUSDT",
                "blocked",
                "kama",
                validation_protocol={
                    "status": "failed",
                    "deflated_sharpe_ratio": 0.91,
                    "probabilistic_sharpe_ratio": 0.89,
                    "pbo_score": 0.24,
                    "spa_pvalue": 0.11,
                    "purge_bars": 5,
                    "embargo_bars": 2,
                    "n_blocks": 10,
                    "n_test_blocks": 2,
                    "cpcv_config": {
                        "method": "combinatorial_purged_cv",
                        "purge_bars": 5,
                        "embargo_bars": 2,
                        "n_blocks": 10,
                        "n_test_blocks": 2,
                    },
                    "in_sample_summary": {"trade_count": 23, "sharpe": 1.12},
                    "selection_oos_summary": {"trade_count": 11, "sharpe": 0.51},
                    "holdout_summary": {"trade_count": 9, "sharpe": 0.27},
                    "validation_gate_results": {
                        "deflated_sharpe_ratio": False,
                        "pbo": False,
                        "spa": False,
                        "final_holdout_excellence": True,
                    },
                },
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            self.assertIn("validation=failed", query_completed.stdout)
            self.assertIn("dsr=0.91", query_completed.stdout)
            self.assertIn("psr=0.89", query_completed.stdout)
            self.assertIn("pbo=0.24", query_completed.stdout)
            self.assertIn("spa=0.11", query_completed.stdout)
            self.assertIn("failed_gates=deflated_sharpe_ratio,pbo,spa", query_completed.stdout)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_json_falls_back_to_validation_protocol_headline_fields(self) -> None:
        root = Path("test-memory-validation-json-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol",
                "SOLUSDT",
                "promoted",
                "kama",
                validation_protocol={
                    "status": "failed",
                    "deflated_sharpe_ratio": 0.91,
                    "probabilistic_sharpe_ratio": 0.89,
                    "pbo_score": 0.24,
                    "spa_pvalue": 0.11,
                    "purge_bars": 5,
                    "embargo_bars": 2,
                    "n_blocks": 10,
                    "n_test_blocks": 2,
                    "cpcv_config": {
                        "method": "combinatorial_purged_cv",
                        "purge_bars": 5,
                        "embargo_bars": 2,
                        "n_blocks": 10,
                        "n_test_blocks": 2,
                    },
                    "in_sample_summary": {"trade_count": 23, "sharpe": 1.12},
                    "selection_oos_summary": {"trade_count": 11, "sharpe": 0.51},
                    "holdout_summary": {"trade_count": 9, "sharpe": 0.27},
                    "validation_gate_results": {
                        "deflated_sharpe_ratio": False,
                        "pbo": False,
                        "spa": False,
                    },
                },
            )
            runcard_path = artifacts_dir / "run-sol.runcard.json"
            runcard_payload = json.loads(runcard_path.read_text(encoding="utf-8"))
            runcard_payload["metrics"].pop("probabilistic_sharpe_ratio", None)
            runcard_payload["metrics"].pop("deflated_sharpe_ratio", None)
            runcard_path.write_text(json.dumps(runcard_payload, sort_keys=True), encoding="utf-8")

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--format",
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            payload = json.loads(query_completed.stdout)
            self.assertEqual(len(payload), 1)
            row = payload[0]
            self.assertEqual(row["validation_status"], "failed")
            self.assertEqual(row["deflated_sharpe_ratio"], 0.91)
            self.assertEqual(row["probabilistic_sharpe_ratio"], 0.89)
            self.assertEqual(row["validation_bundle"]["status"], "failed")
            self.assertEqual(row["validation_bundle"]["deflated_sharpe_ratio"], 0.91)
            self.assertEqual(row["validation_bundle"]["probabilistic_sharpe_ratio"], 0.89)
            self.assertEqual(row["validation_bundle"]["pbo_score"], 0.24)
            self.assertEqual(row["validation_bundle"]["spa_pvalue"], 0.11)
            self.assertEqual(row["validation_bundle"]["purge_bars"], 5)
            self.assertEqual(row["validation_bundle"]["embargo_bars"], 2)
            self.assertEqual(row["validation_bundle"]["n_blocks"], 10)
            self.assertEqual(row["validation_bundle"]["n_test_blocks"], 2)
            self.assertEqual(row["validation_bundle"]["cpcv_config"]["method"], "combinatorial_purged_cv")
            self.assertEqual(row["validation_bundle"]["selection_oos_summary"]["trade_count"], 11)
            self.assertEqual(row["validation_bundle"]["failed_gates"], ["deflated_sharpe_ratio", "pbo", "spa"])
            self.assertEqual(row["validation_protocol"]["pbo_score"], 0.24)
            self.assertEqual(row["validation_protocol"]["spa_pvalue"], 0.11)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_can_filter_and_rank_by_candidate_pressure(self) -> None:
        root = Path("test-memory-candidate-pressure-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol-pressure",
                "SOLUSDT",
                "promoted",
                "kama",
                dashboard_phases=[
                    {
                        "phase_name": "phase-2",
                        "layer_name": "kama",
                        "decision": "accept",
                        "accepted": True,
                        "selected_parameters": {"aggressiveness": 2},
                        "search_summary": [
                            {
                                "decision": "accept",
                                "oos_sharpe": 0.42,
                                "parameters": {"aggressiveness": 2},
                                "execution_pressure_summary": {
                                    "fill_event_count": 3,
                                    "partial_fill_event_count": 2,
                                    "average_fill_ratio": 0.74,
                                    "min_fill_ratio": 0.33,
                                },
                            }
                        ],
                    }
                ],
            )
            _save_artifacts(
                artifacts_dir,
                "run-btc-pressure",
                "BTCUSDT",
                "promoted",
                "ema",
                dashboard_phases=[
                    {
                        "phase_name": "phase-2",
                        "layer_name": "ema",
                        "decision": "accept",
                        "accepted": True,
                        "selected_parameters": {"fast": 9, "slow": 21},
                        "search_summary": [
                            {
                                "decision": "accept",
                                "oos_sharpe": 0.39,
                                "parameters": {"fast": 9, "slow": 21},
                                "execution_pressure_summary": {
                                    "fill_event_count": 2,
                                    "partial_fill_event_count": 1,
                                    "average_fill_ratio": 0.81,
                                    "min_fill_ratio": 0.58,
                                },
                            }
                        ],
                    }
                ],
            )
            _save_artifacts(artifacts_dir, "run-eth-clean", "ETHUSDT", "promoted", "hull")

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--candidate-pressure-only",
                    "--sort-by",
                    "candidate_worst_fill",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            rendered = query_completed.stdout
            self.assertIn("run-sol-pressure", rendered)
            self.assertIn("run-btc-pressure", rendered)
            self.assertNotIn("run-eth-clean", rendered)
            self.assertLess(rendered.find("run-sol-pressure"), rendered.find("run-btc-pressure"))
            self.assertIn("candidate_trials=count=1,top=accept,top_sharpe=0.42,layers=1,pressured=1,worst_fill=0.33", rendered)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_candidate_trials_can_filter_pressured_rows(self) -> None:
        root = Path("test-candidate-trials-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol-trials",
                "SOLUSDT",
                "promoted",
                "kama",
                dashboard_phases=[
                    {
                        "phase_name": "phase-2",
                        "layer_name": "kama",
                        "decision": "accept",
                        "accepted": True,
                        "selected_parameters": {"aggressiveness": 2},
                        "search_summary": [
                            {
                                "decision": "accept",
                                "oos_sharpe": 0.42,
                                "parameters": {"aggressiveness": 2},
                                "execution_pressure_summary": {
                                    "fill_event_count": 3,
                                    "partial_fill_event_count": 2,
                                    "average_fill_ratio": 0.74,
                                    "min_fill_ratio": 0.33,
                                },
                            },
                            {
                                "decision": "reject",
                                "oos_sharpe": 0.29,
                                "parameters": {"aggressiveness": 1},
                            },
                        ],
                    },
                    {
                        "phase_name": "phase-3",
                        "layer_name": "ema",
                        "decision": "accept",
                        "accepted": True,
                        "selected_parameters": {"fast": 9, "slow": 21},
                        "search_summary": [
                            {
                                "decision": "accept",
                                "oos_sharpe": 0.38,
                                "parameters": {"fast": 9, "slow": 21},
                                "execution_pressure_summary": {
                                    "fill_event_count": 2,
                                    "partial_fill_event_count": 1,
                                    "average_fill_ratio": 0.81,
                                    "min_fill_ratio": 0.58,
                                },
                            }
                        ],
                    },
                ],
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-candidate-trials",
                    "--db",
                    str(db_path),
                    "--run-id",
                    "run-sol-trials",
                    "--pressured-only",
                    "--sort-by",
                    "worst_fill",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            rendered = query_completed.stdout
            self.assertIn("run-sol-trials", rendered)
            self.assertIn("layer=kama", rendered)
            self.assertIn("layer=ema", rendered)
            self.assertNotIn("aggressiveness=1", rendered)
            self.assertLess(rendered.find("layer=kama"), rendered.find("layer=ema"))
            self.assertIn("pressure=fill_events=3,partial=2,avg_fill=0.74,min_fill=0.33", rendered)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_can_filter_by_snapshot_provenance(self) -> None:
        root = Path("test-memory-query-provenance-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol-v1",
                "SOLUSDT",
                "promoted",
                "kama",
                build_version="phase1_snapshot_builder_v1",
                source_hash="abc123",
            )
            _save_artifacts(
                artifacts_dir,
                "run-sol-v2",
                "SOLUSDT",
                "promoted",
                "flat9",
                build_version="phase1_snapshot_builder_v2",
                source_hash="def456",
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            build_query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--build-version",
                    "phase1_snapshot_builder_v2",
                    "--format",
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(build_query_completed.returncode, 0, msg=build_query_completed.stderr)
            build_rows = json.loads(build_query_completed.stdout)
            self.assertEqual([row["run_id"] for row in build_rows], ["run-sol-v2"])

            hash_query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--source-hash",
                    "abc123",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(hash_query_completed.returncode, 0, msg=hash_query_completed.stderr)
            self.assertIn("run-sol-v1", hash_query_completed.stdout)
            self.assertIn("build=phase1_snapshot_builder_v1", hash_query_completed.stdout)
            self.assertNotIn("run-sol-v2", hash_query_completed.stdout)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_surfaces_validation_run_summary(self) -> None:
        root = Path("test-memory-validation-summary-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol",
                "SOLUSDT",
                "promoted",
                "kama",
                validation_protocol={
                    "status": "failed",
                    "deflated_sharpe_ratio": 0.91,
                    "probabilistic_sharpe_ratio": 0.89,
                    "pbo_score": 0.24,
                    "spa_pvalue": 0.11,
                    "validation_trial_count": 24,
                    "validation_gate_results": {
                        "deflated_sharpe_ratio": False,
                        "pbo": False,
                        "spa": False,
                    },
                },
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            self.assertIn("validation=failed", query_completed.stdout)
            self.assertIn("validation_lineage=status=failed,pbo=0.24,spa=0.11,failed_gates=3,trials=24", query_completed.stdout)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_surfaces_stress_run_summary(self) -> None:
        root = Path("test-memory-stress-summary-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol",
                "SOLUSDT",
                "promoted",
                "kama",
                dashboard_scenarios=[
                    {
                        "scenario_name": "outage-shock",
                        "severity": 1.3,
                        "passed": False,
                        "failure_reasons": ["drawdown_kill_switch"],
                        "sharpe": 0.22,
                        "max_drawdown": -0.31,
                        "resolved_profile": {"target_regimes": ["crash"], "severity": 1.3},
                        "stress_metrics": {"liquidity_stress_score": 0.9},
                    },
                    {
                        "scenario_name": "attention-burst",
                        "severity": 0.8,
                        "passed": True,
                        "failure_reasons": [],
                        "sharpe": 0.41,
                        "max_drawdown": -0.18,
                        "resolved_profile": {"target_regimes": ["bull"], "severity": 0.8},
                        "stress_metrics": {"liquidity_stress_score": 0.4},
                    },
                ],
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            self.assertIn("stress_lineage=scenarios=2,failed=1,worst=outage-shock,regimes=2", query_completed.stdout)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_surfaces_candidate_trial_summary(self) -> None:
        root = Path("test-memory-candidate-trial-summary-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol",
                "SOLUSDT",
                "promoted",
                "kama",
                dashboard_phases=[
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
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            self.assertIn(
                "candidate_trials=count=3,top=accept,top_sharpe=0.42,layers=2,pressured=1,worst_fill=0.44",
                query_completed.stdout,
            )
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_surfaces_data_snapshot_and_resource_link_summaries(self) -> None:
        root = Path("test-memory-snapshot-resource-summary-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        ledger_path = root / "resource-ledger.json"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol-a",
                "SOLUSDT",
                "promoted",
                "kama",
                build_version="phase1_snapshot_builder_v2",
                source_hash="shared-hash",
            )
            _save_artifacts(
                artifacts_dir,
                "run-sol-b",
                "SOLUSDT",
                "blocked",
                "ema",
                build_version="phase1_snapshot_builder_v2",
                source_hash="shared-hash",
            )
            for run_id in ("run-sol-a", "run-sol-b"):
                runcard_path = artifacts_dir / f"{run_id}.runcard.json"
                payload = json.loads(runcard_path.read_text(encoding="utf-8"))
                payload["artifacts"]["snapshot_id"] = "shared-snap"
                runcard_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
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
                                "sources": [
                                    {
                                        "title": "CCXT Manual",
                                        "url": "https://github.com/ccxt/ccxt/wiki/Manual",
                                        "source_type": "official_docs",
                                    }
                                ],
                            },
                            {
                                "id": "psr_dsr_references",
                                "title": "PSR and DSR references",
                                "status": "indexed_not_yet_reviewed",
                                "intended_usage": "reference_only",
                                "sources": [
                                    {
                                        "title": "DSR",
                                        "url": "https://example.com/dsr",
                                        "source_type": "paper",
                                    }
                                ],
                            },
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            env = dict(os.environ, ENGINE_RESOURCE_LEDGER_PATH=str(ledger_path))

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            self.assertIn("snapshot_lineage=provider=csv,mode=bundle_csv,usage=2,first=run-sol-a", query_completed.stdout)
            self.assertIn("resource_links=count=2,resources=2,blocked=0,groups=non_repo_source", query_completed.stdout)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_surfaces_agent_decision_summary(self) -> None:
        root = Path("test-output-memory-agent-decisions")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol",
                "SOLUSDT",
                "promoted",
                "kama",
                karpathy_entries=[
                    {
                        "iteration": 1,
                        "decision": "keep",
                        "reason": "improved_objective",
                        "validation_status": "passed",
                        "metric_name": "selection_oos_sharpe",
                        "metric_value": 0.84,
                        "candidate_run_ids": ["run-sol-1"],
                        "kept_run_ids": ["run-sol-1"],
                    }
                ],
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--decision",
                    "promoted",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            self.assertIn("decision_count=1", query_completed.stdout)
            self.assertIn("latest_decision=keep", query_completed.stdout)
            self.assertIn("decision_family=karpathy", query_completed.stdout)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_query_memory_surfaces_meta_policy_summary(self) -> None:
        root = Path("test-output-memory-meta-policies")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol",
                "SOLUSDT",
                "promoted",
                "kama",
                meta_policies=[
                    {
                        "policy_id": "meta-bandit-v1",
                        "policy_family": "bandit",
                        "status": "trained",
                        "action_map": {"balanced": 0, "conservative": 1},
                        "training_stats": {
                            "episodes": 24,
                            "best_reward": 1.7,
                            "selected_action": "conservative",
                            "training_example_count": 6,
                        },
                        "offline_evaluation": {
                            "method": "logged_bandit_mean_reward_v1",
                            "best_observed_action": "conservative",
                        },
                        "eval_validation_run_id": "run-sol",
                        "eval_stress_summary": {"scenario_count": 3, "failed_scenarios": 0},
                        "artifact_path": "outputs/policies/meta-bandit-v1.json",
                    }
                ],
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            self.assertIn(
                "meta_policies=count=1,family=bandit,status=trained,latest=meta-bandit-v1,selected=conservative,train_examples=6,offline_eval=logged_bandit_mean_reward_v1",
                query_completed.stdout,
            )
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_can_summarize_memory_with_quality_policy(self) -> None:
        root = Path("test-memory-summary-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(
                artifacts_dir,
                "run-sol",
                "SOLUSDT",
                "promoted",
                "kama",
                quality_status="clean",
                build_version="phase1_snapshot_builder_v1",
                source_hash="abc123",
            )
            _save_artifacts(
                artifacts_dir,
                "run-sol-dirty",
                "SOLUSDT",
                "promoted",
                "flat9",
                quality_status="dirty",
                build_version="phase1_snapshot_builder_v2",
                source_hash="def456",
            )

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            clean_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--memory-quality-policy",
                    "clean-only",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(clean_completed.returncode, 0, msg=clean_completed.stderr)
            self.assertIn("Memory quality policy: clean-only", clean_completed.stdout)
            self.assertIn("Prior runs: 1", clean_completed.stdout)
            self.assertIn("Excluded dirty runs: 1", clean_completed.stdout)
            self.assertIn("Promising layers: kama(1)", clean_completed.stdout)
            self.assertIn("Recovered duplicate runs: 1", clean_completed.stdout)
            self.assertIn("Top duplicate matches: prior-same-study(1)", clean_completed.stdout)
            self.assertIn("Scenario profiles: outage-shock(1)", clean_completed.stdout)
            self.assertIn(
                "Top runtime profile: search_summary_limit=3, slippage_bps=5.0",
                clean_completed.stdout,
            )
            self.assertNotIn("flat9(1)", clean_completed.stdout)

            all_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--memory-quality-policy",
                    "all",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(all_completed.returncode, 0, msg=all_completed.stderr)
            self.assertIn("Memory quality policy: all", all_completed.stdout)
            self.assertIn("Prior runs: 2", all_completed.stdout)
            self.assertIn("Excluded dirty runs: 0", all_completed.stdout)
            self.assertIn("Promising layers:", all_completed.stdout)
            self.assertIn("kama(1)", all_completed.stdout)
            self.assertIn("flat9(1)", all_completed.stdout)
            self.assertIn("Recovered duplicate runs: 1", all_completed.stdout)
            self.assertIn("Top duplicate matches: prior-same-study(1)", all_completed.stdout)
            self.assertIn("Scenario profiles: outage-shock(2)", all_completed.stdout)
            self.assertIn("Top runtime profile:", all_completed.stdout)
            self.assertIn("Top snapshot builds: phase1_snapshot_builder_v1(1), phase1_snapshot_builder_v2(1)", all_completed.stdout)
            self.assertIn("Snapshot source hashes: 2 distinct", all_completed.stdout)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_cli_summarize_memory_reports_fragile_scenario_profile_avoidance_in_json(self) -> None:
        root = Path("test-memory-summary-avoidance-cli")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _save_artifacts(artifacts_dir, "run-promoted", "SOLUSDT", "promoted", "kama", quality_status="clean")
            _save_artifacts(artifacts_dir, "run-blocked-a", "SOLUSDT", "blocked", "kama", quality_status="clean")
            _save_artifacts(artifacts_dir, "run-blocked-b", "SOLUSDT", "blocked", "hull", quality_status="clean")

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifacts_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            summary_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--memory-quality-policy",
                    "clean-only",
                    "--format",
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(summary_completed.returncode, 0, msg=summary_completed.stderr)
            payload = json.loads(summary_completed.stdout)
            self.assertEqual(
                payload["scenario_profile_avoidance"]["outage-shock"]["profile"]["latency_delta_bars"],
                3,
            )
            self.assertEqual(
                payload["scenario_profile_avoidance"]["outage-shock"]["count"],
                2,
            )

            text_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-memory",
                    "--db",
                    str(db_path),
                    "--symbol",
                    "SOLUSDT",
                    "--memory-quality-policy",
                    "clean-only",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(text_completed.returncode, 0, msg=text_completed.stderr)
            self.assertIn("Top scenario profile: outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock", text_completed.stdout)
            self.assertIn("Fragile scenario profiles: outage-shock(2)", text_completed.stdout)
            self.assertIn(
                "Top fragile profile: outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock",
                text_completed.stdout,
            )
        finally:
            if root.exists():
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
