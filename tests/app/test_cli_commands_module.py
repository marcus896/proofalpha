import argparse
import unittest


class CliCommandGroupTests(unittest.TestCase):
    def test_report_command_group_registers_report_and_followup_commands(self) -> None:
        from engine.app.cli_commands.reports import register_report_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_report_commands(subparsers)

        summary_args = parser.parse_args(["summarize-run", "--dashboard", "dashboard.json", "--phase-filter", "all"])
        self.assertEqual(summary_args.command, "summarize-run")
        self.assertEqual(summary_args.phase_filter, "all")

        retry_args = parser.parse_args(["retry-campaign", "--campaign-report", "campaign.json", "--output-report", "retry.json"])
        self.assertEqual(retry_args.command, "retry-campaign")
        self.assertEqual(retry_args.entry_status, "failed")

        compare_args = parser.parse_args(["compare-runs", "--left", "left.json", "--right", "right.json"])
        self.assertEqual(compare_args.command, "compare-runs")
        self.assertEqual(compare_args.kind, "dashboard")
        self.assertEqual(compare_args.format, "json")

        continue_args = parser.parse_args(
            ["continue-batch", "--batch-report", "batch.json", "--output-dir", "out", "--db", "memory.sqlite"]
        )
        self.assertEqual(continue_args.command, "continue-batch")
        self.assertEqual(continue_args.variant, "preferred")
        self.assertEqual(continue_args.memory_quality_policy, "clean-only")

        trace_export_args = parser.parse_args(
            ["trace-audit-export", "--agent-loop-report", "loop.json", "--output", "trace.json"]
        )
        self.assertEqual(trace_export_args.command, "trace-audit-export")
        self.assertEqual(trace_export_args.agent_loop_report, "loop.json")
        self.assertEqual(trace_export_args.output, "trace.json")

        loop_evidence_args = parser.parse_args(
            [
                "loop-evidence-ledger",
                "--agent-loop-report",
                "loop.json",
                "--readiness-scan",
                "scan.json",
                "--readiness-report",
                "readiness.json",
                "--paper-dashboard",
                "dashboard.json",
                "--paper-postrun-summary",
                "postrun.json",
                "--paper-calibration-feedback",
                "calibration.json",
                "--output",
                "ledger.json",
            ]
        )
        self.assertEqual(loop_evidence_args.command, "loop-evidence-ledger")
        self.assertEqual(loop_evidence_args.agent_loop_report, ["loop.json"])
        self.assertEqual(loop_evidence_args.readiness_scan, ["scan.json"])
        self.assertEqual(loop_evidence_args.readiness_report, ["readiness.json"])
        self.assertEqual(loop_evidence_args.paper_dashboard, ["dashboard.json"])
        self.assertEqual(loop_evidence_args.paper_postrun_summary, ["postrun.json"])
        self.assertEqual(loop_evidence_args.paper_calibration_feedback, ["calibration.json"])

        feature_audit_args = parser.parse_args(
            ["feature-causality-audit", "--input", "feature.json", "--output", "audit.json"]
        )
        self.assertEqual(feature_audit_args.command, "feature-causality-audit")
        self.assertEqual(feature_audit_args.input, "feature.json")

        tournament_args = parser.parse_args(
            ["strategy-tournament", "--input", "buckets.json", "--output", "tournament.json"]
        )
        self.assertEqual(tournament_args.command, "strategy-tournament")
        self.assertEqual(tournament_args.minimum_bucket_count, 2)

        robust_eval_args = parser.parse_args(
            ["robust-evaluate", "--input", "evidence.json", "--output", "scorecard.json"]
        )
        self.assertEqual(robust_eval_args.command, "robust-evaluate")

        sealed_holdout_args = parser.parse_args(
            ["sealed-holdout-check", "--input", "holdout.json", "--output", "sealed.json"]
        )
        self.assertEqual(sealed_holdout_args.command, "sealed-holdout-check")

        paper_forward_args = parser.parse_args(
            [
                "paper-forward-score",
                "--candidate-id",
                "candidate",
                "--data-inventory",
                "inventory.json",
                "--paper-dashboard",
                "paper-dashboard.json",
                "--output",
                "paper-forward.json",
            ]
        )
        self.assertEqual(paper_forward_args.command, "paper-forward-score")
        self.assertEqual(paper_forward_args.candidate_id, "candidate")
        self.assertEqual(paper_forward_args.minimum_paper_orders, 10)

        evidence_card_args = parser.parse_args(
            [
                "strategy-evidence-card",
                "--candidate-id",
                "candidate",
                "--data-matrix",
                "matrix.json",
                "--feature-audit",
                "feature.json",
                "--strategy-tournament",
                "tournament.json",
                "--robust-evaluation",
                "robust.json",
                "--sealed-holdout",
                "holdout.json",
                "--paper-forward-score",
                "paper-forward.json",
                "--output",
                "card.json",
            ]
        )
        self.assertEqual(evidence_card_args.command, "strategy-evidence-card")
        self.assertEqual(evidence_card_args.paper_forward_score, "paper-forward.json")
        self.assertFalse(evidence_card_args.promotion_governance_approved)

        improvement_args = parser.parse_args(
            [
                "loop-improvement-gate",
                "--ledger",
                "ledger.json",
                "--paper-dashboard",
                "paper-dashboard.json",
                "--postrun-summary",
                "postrun.json",
                "--calibration-feedback",
                "calibration.json",
                "--data-sufficiency",
                "data-sufficiency.json",
                "--output",
                "gate.json",
            ]
        )
        self.assertEqual(improvement_args.command, "loop-improvement-gate")
        self.assertEqual(improvement_args.ledger, "ledger.json")
        self.assertEqual(improvement_args.data_sufficiency, "data-sufficiency.json")
        self.assertEqual(improvement_args.max_abs_slip_bps, 25.0)

        trace_ingest_args = parser.parse_args(
            [
                "trace-audit-ingest",
                "--advisory-report",
                "advisory.json",
                "--trace-export",
                "trace.json",
                "--output",
                "notes.json",
            ]
        )
        self.assertEqual(trace_ingest_args.command, "trace-audit-ingest")
        self.assertEqual(trace_ingest_args.advisory_report, "advisory.json")
        self.assertEqual(trace_ingest_args.trace_export, "trace.json")
        self.assertEqual(trace_ingest_args.output, "notes.json")

        debate_args = parser.parse_args(
            [
                "research-debate-report",
                "--candidate-report",
                "candidate.json",
                "--trace-advisory-notes",
                "notes.json",
                "--output",
                "debate.json",
            ]
        )
        self.assertEqual(debate_args.command, "research-debate-report")
        self.assertEqual(debate_args.candidate_report, "candidate.json")
        self.assertEqual(debate_args.trace_advisory_notes, "notes.json")
        self.assertEqual(debate_args.output, "debate.json")

    def test_memory_command_group_registers_memory_query_commands(self) -> None:
        from engine.app.cli_commands.memory import register_memory_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_memory_commands(subparsers)

        ingest_args = parser.parse_args(["ingest-memory", "--dir", "outputs", "--db", "memory.sqlite"])
        self.assertEqual(ingest_args.command, "ingest-memory")

        query_args = parser.parse_args(["query-memory", "--db", "memory.sqlite", "--candidate-pressure-only"])
        self.assertEqual(query_args.command, "query-memory")
        self.assertTrue(query_args.candidate_pressure_only)
        self.assertEqual(query_args.sort_by, "sharpe")

        meta_args = parser.parse_args(["query-meta-policies", "--db", "memory.sqlite", "--format", "text"])
        self.assertEqual(meta_args.command, "query-meta-policies")
        self.assertEqual(meta_args.format, "text")

        summarize_args = parser.parse_args(["summarize-memory", "--db", "memory.sqlite"])
        self.assertEqual(summarize_args.command, "summarize-memory")
        self.assertEqual(summarize_args.memory_quality_policy, "clean-only")

    def test_research_command_group_registers_research_loop_commands(self) -> None:
        from engine.app.cli_commands.research import register_research_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_research_commands(subparsers)

        autoresearch_args = parser.parse_args(
            ["autoresearch", "--config", "study.json", "--output-dir", "out", "--db", "memory.sqlite"]
        )
        self.assertEqual(autoresearch_args.command, "autoresearch")
        self.assertEqual(autoresearch_args.memory_limit, 25)

        batch_args = parser.parse_args(
            ["batch-autoresearch", "--config", "study.json", "--output-dir", "out", "--db", "memory.sqlite"]
        )
        self.assertEqual(batch_args.command, "batch-autoresearch")
        self.assertEqual(batch_args.memory_quality_policy, "clean-only")

        loop_args = parser.parse_args(
            [
                "agent-loop",
                "--config",
                "study.json",
                "--output-dir",
                "out",
                "--db",
                "memory.sqlite",
                "--trace-advisory-notes",
                "notes.json",
                "--improvement-gate",
                "gate.json",
                "--evidence-ledger-output",
                "ledger.json",
                "--readiness-report-output",
                "readiness.json",
            ]
        )
        self.assertEqual(loop_args.command, "agent-loop")
        self.assertEqual(loop_args.iterations, 3)
        self.assertEqual(loop_args.loop_mode, "auto")
        self.assertIsNone(loop_args.karpathy_execute_git_actions)
        self.assertEqual(loop_args.trace_advisory_notes, "notes.json")
        self.assertEqual(loop_args.improvement_gate, "gate.json")
        self.assertEqual(loop_args.evidence_ledger_output, "ledger.json")
        self.assertEqual(loop_args.readiness_report_output, "readiness.json")
        self.assertFalse(loop_args.require_loop_readiness)

        ready_loop_args = parser.parse_args(
            [
                "agent-loop",
                "--config",
                "study.json",
                "--output-dir",
                "out",
                "--db",
                "memory.sqlite",
                "--require-loop-readiness",
            ]
        )
        self.assertTrue(ready_loop_args.require_loop_readiness)

        guarded_loop_args = parser.parse_args(
            [
                "guarded-loop-cycle",
                "--config",
                "study.json",
                "--output-dir",
                "out",
                "--db",
                "memory.sqlite",
                "--liquidations",
                "liquidation_notional.csv",
                "--hydrated-config",
                "hydrated-study.json",
            ]
        )
        self.assertEqual(guarded_loop_args.command, "guarded-loop-cycle")
        self.assertEqual(guarded_loop_args.iterations, 3)
        self.assertEqual(guarded_loop_args.memory_quality_policy, "clean-only")
        self.assertEqual(guarded_loop_args.liquidations, "liquidation_notional.csv")

        guarded_repeat_args = parser.parse_args(
            [
                "guarded-loop-repeat",
                "--study-dir",
                "studies",
                "--output-dir",
                "out",
                "--db",
                "memory.sqlite",
                "--max-cycles",
                "2",
            ]
        )
        self.assertEqual(guarded_repeat_args.command, "guarded-loop-repeat")
        self.assertEqual(guarded_repeat_args.max_cycles, 2)
        self.assertEqual(guarded_repeat_args.memory_quality_policy, "clean-only")

        guarded_repeat_hydrate_args = parser.parse_args(
            [
                "guarded-loop-repeat",
                "--config",
                "study.json",
                "--liquidations",
                "liquidation_notional.csv",
                "--hydrated-config",
                "hydrated-study.json",
                "--output-dir",
                "out",
                "--db",
                "memory.sqlite",
            ]
        )
        self.assertEqual(guarded_repeat_hydrate_args.command, "guarded-loop-repeat")
        self.assertEqual(guarded_repeat_hydrate_args.config, "study.json")
        self.assertEqual(guarded_repeat_hydrate_args.liquidations, "liquidation_notional.csv")

        operate_args = parser.parse_args(
            [
                "operate-loop",
                "--config",
                "study.json",
                "--output-dir",
                "operate",
                "--db",
                "memory.sqlite",
                "--profile",
                "strict_v3",
                "--max-cycles",
                "2",
                "--iterations",
                "2",
                "--run-budget",
                "2",
                "--require-improvement-ready",
                "--candidate-queue",
                "queue.json",
                "--strategy-evidence-card",
                "card.json",
            ]
        )
        self.assertEqual(operate_args.command, "operate-loop")
        self.assertEqual(operate_args.profile, "strict_v3")
        self.assertTrue(operate_args.require_improvement_ready)
        self.assertEqual(operate_args.candidate_queue, "queue.json")
        self.assertEqual(operate_args.strategy_evidence_card, "card.json")

        campaign_args = parser.parse_args(
            ["run-campaign", "--manifest", "campaign.json", "--output-report", "report.json"]
        )
        self.assertEqual(campaign_args.command, "run-campaign")

    def test_data_forecast_command_group_registers_local_profile_command(self) -> None:
        from engine.app.cli_commands.data_forecast import register_data_forecast_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_data_forecast_commands(subparsers)

        args = parser.parse_args(["profile-local-harness", "--fixture", "--output", "profile.json"])
        self.assertEqual(args.command, "profile-local-harness")
        self.assertTrue(args.fixture)
        self.assertEqual(args.output, "profile.json")

        matrix_args = parser.parse_args(
            [
                "dataset-matrix",
                "--inventory",
                "inventory.json",
                "--output",
                "matrix.json",
                "--symbol",
                "BTCUSDT",
                "--timeframe",
                "1Hour",
                "--minimum-distinct-years",
                "5",
                "--required-sidecar",
                "liquidation_notional",
            ]
        )
        self.assertEqual(matrix_args.command, "dataset-matrix")
        self.assertEqual(matrix_args.inventory, "inventory.json")
        self.assertEqual(matrix_args.output, "matrix.json")
        self.assertEqual(matrix_args.symbol, ["BTCUSDT"])
        self.assertEqual(matrix_args.timeframe, ["1Hour"])
        self.assertEqual(matrix_args.minimum_distinct_years, 5)
        self.assertEqual(matrix_args.required_sidecar, ["liquidation_notional"])

    def test_execution_command_group_registers_execution_portfolio_and_calibration_commands(self) -> None:
        from engine.app.cli_commands.execution import register_execution_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_execution_commands(subparsers)

        chaos_args = parser.parse_args(
            [
                "no-key-executor-chaos",
                "--db",
                "memory.sqlite",
                "--symbol",
                "BTCUSDT",
                "--side",
                "BUY",
                "--qty",
                "1",
                "--price",
                "100",
                "--client-order-id",
                "order-1",
                "--output",
                "chaos.json",
            ]
        )
        self.assertEqual(chaos_args.command, "no-key-executor-chaos")
        self.assertEqual(chaos_args.scenario, "all")
        self.assertEqual(chaos_args.session_id, "phase2-no-key")

        portfolio_args = parser.parse_args(["portfolio-plan", "--input", "plan.json"])
        self.assertEqual(portfolio_args.command, "portfolio-plan")
        self.assertIsNone(portfolio_args.output)
        self.assertIsNone(portfolio_args.db)

        override_args = parser.parse_args(
            [
                "portfolio-override",
                "--db",
                "memory.sqlite",
                "--action",
                "kill_switch",
                "--operator-id",
                "operator",
            ]
        )
        self.assertEqual(override_args.command, "portfolio-override")
        self.assertEqual(override_args.action, "kill_switch")

        calibration_args = parser.parse_args(
            [
                "calibrate-cost-capacity",
                "--db",
                "memory.sqlite",
                "--output",
                "calibration.json",
                "--baseline-edge-bps",
                "12.5",
            ]
        )
        self.assertEqual(calibration_args.command, "calibrate-cost-capacity")
        self.assertEqual(calibration_args.source_model_version, "cost-v1")
        self.assertEqual(calibration_args.minimum_orders_per_bucket, 200)

        lifecycle_args = parser.parse_args(["lifecycle-status", "--db", "memory.sqlite", "--artifact-id", "artifact"])
        self.assertEqual(lifecycle_args.command, "lifecycle-status")
        self.assertEqual(lifecycle_args.artifact_id, "artifact")

    def test_paper_command_group_registers_artifact_and_paper_commands(self) -> None:
        from engine.app.cli_commands.paper import register_paper_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_paper_commands(subparsers)

        validate_args = parser.parse_args(["validate-artifact", "--artifact", "strategy.json"])
        self.assertEqual(validate_args.command, "validate-artifact")
        self.assertEqual(validate_args.artifact, "strategy.json")

        daemon_args = parser.parse_args(
            [
                "paper-daemon",
                "--db",
                "memory.sqlite",
                "--artifact",
                "strategy-a.json",
                "--artifact",
                "strategy-b.json",
                "--market-fixture",
                "market.json",
                "--dry-run",
            ]
        )
        self.assertEqual(daemon_args.command, "paper-daemon")
        self.assertEqual(daemon_args.artifact, ["strategy-a.json", "strategy-b.json"])
        self.assertTrue(daemon_args.dry_run)
        self.assertEqual(daemon_args.max_order_rate_per_minute, 60)

        ws_args = parser.parse_args(
            [
                "paper-ws-run",
                "--db",
                "memory.sqlite",
                "--artifact",
                "strategy.json",
                "--symbol",
                "BTCUSDT",
                "--max-duration-seconds",
                "1.5",
            ]
        )
        self.assertEqual(ws_args.command, "paper-ws-run")
        self.assertEqual(ws_args.symbol, ["BTCUSDT"])
        self.assertEqual(ws_args.max_duration_seconds, 1.5)
        self.assertEqual(ws_args.reconnect_attempts, 3)

        closeout_args = parser.parse_args(
            [
                "paper-soak-closeout",
                "--db",
                "memory.sqlite",
                "--session-id",
                "session",
                "--export-dir",
                "export",
                "--restore-db",
                "restore.sqlite",
                "--hosted-repo-dir",
                "repo",
                "--hosted-state-dir",
                "state",
                "--hosted-log-dir",
                "logs",
                "--hosted-backup-dir",
                "backups",
                "--hosted-template-root",
                "templates",
                "--minimum-soak-seconds",
                "60",
                "--output",
                "closeout.json",
            ]
        )
        self.assertEqual(closeout_args.command, "paper-soak-closeout")
        self.assertEqual(closeout_args.minimum_soak_seconds, 60)

    def test_data_forecast_command_group_registers_market_data_and_timesfm_commands(self) -> None:
        from engine.app.cli_commands.data_forecast import register_data_forecast_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_data_forecast_commands(subparsers)

        micro_args = parser.parse_args(["fetch-microstructure", "--output-dir", "out"])
        self.assertEqual(micro_args.command, "fetch-microstructure")
        self.assertEqual(micro_args.symbol, "BTCUSDT")
        self.assertEqual(micro_args.depth_limit, 100)
        self.assertEqual(micro_args.agg_trade_limit, 1000)

        hydrate_args = parser.parse_args(
            [
                "hydrate-study-liquidations",
                "--config",
                "study.json",
                "--liquidations",
                "liquidation_notional.csv",
                "--output",
                "hydrated-study.json",
                "--require-ready",
            ]
        )
        self.assertEqual(hydrate_args.command, "hydrate-study-liquidations")
        self.assertEqual(hydrate_args.liquidations, "liquidation_notional.csv")
        self.assertTrue(hydrate_args.require_ready)

        verify_args = parser.parse_args(
            [
                "verify-study-liquidations",
                "--config",
                "study.json",
                "--liquidations",
                "liquidation_notional.csv",
                "--output",
                "sidecar-report.json",
            ]
        )
        self.assertEqual(verify_args.command, "verify-study-liquidations")
        self.assertEqual(verify_args.output, "sidecar-report.json")

        forceorder_args = parser.parse_args(
            [
                "export-forceorder-liquidations",
                "--db",
                "memory.sqlite",
                "--session-id",
                "paper-session",
                "--output",
                "liquidation_notional.csv",
                "--include-observed-zero-buckets",
            ]
        )
        self.assertEqual(forceorder_args.command, "export-forceorder-liquidations")
        self.assertEqual(forceorder_args.timeframe, "1Hour")
        self.assertTrue(forceorder_args.include_observed_zero_buckets)
        minute_forceorder_args = parser.parse_args(
            [
                "export-forceorder-liquidations",
                "--db",
                "memory.sqlite",
                "--session-id",
                "paper-session",
                "--output",
                "liquidation_notional.csv",
                "--timeframe",
                "1Min",
            ]
        )
        self.assertEqual(minute_forceorder_args.timeframe, "1Min")

        smoke_args = parser.parse_args(["timesfm-smoke", "--fixture", "--symbol", "ETHUSDT"])
        self.assertEqual(smoke_args.command, "timesfm-smoke")
        self.assertEqual(smoke_args.symbol, "ETHUSDT")
        self.assertTrue(smoke_args.fixture)

        benchmark_args = parser.parse_args(["timesfm-benchmark", "--output", "profile.json", "--warm-batch"])
        self.assertEqual(benchmark_args.command, "timesfm-benchmark")
        self.assertEqual(benchmark_args.output, "profile.json")
        self.assertTrue(benchmark_args.warm_batch)

        archive_args = parser.parse_args(
            [
                "fetch-binance-archive",
                "--output-dir",
                "snapshots",
                "--start-date",
                "2026-01-01",
                "--end-date",
                "2026-01-02",
            ]
        )
        self.assertEqual(archive_args.command, "fetch-binance-archive")
        self.assertEqual(archive_args.symbol, "BTCUSDT")
        self.assertEqual(archive_args.timeframe, "1Hour")
        self.assertFalse(archive_args.skip_agg_trades)

    def test_core_command_group_registers_example_and_schema_commands(self) -> None:
        from engine.app.cli_commands.core import register_core_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_core_commands(subparsers)

        inspect_args = parser.parse_args(["inspect-study", "--config", "study.json"])
        self.assertEqual(inspect_args.command, "inspect-study")
        self.assertEqual(inspect_args.config, "study.json")

        readiness_scan_args = parser.parse_args(["loop-readiness-scan", "--dir", "outputs", "--output", "scan.json"])
        self.assertEqual(readiness_scan_args.command, "loop-readiness-scan")
        self.assertEqual(readiness_scan_args.dir, "outputs")
        self.assertEqual(readiness_scan_args.output, "scan.json")
        self.assertFalse(readiness_scan_args.require_eligible)

        readiness_scan_required_args = parser.parse_args(
            ["loop-readiness-scan", "--dir", "outputs", "--require-eligible"]
        )
        self.assertTrue(readiness_scan_required_args.require_eligible)

        doctor_args = parser.parse_args(["doctor", "--format", "json"])
        self.assertEqual(doctor_args.command, "doctor")
        self.assertEqual(doctor_args.format, "json")

        init_args = parser.parse_args(
            [
                "init-example",
                "--csv",
                "candles.csv",
                "--config-out",
                "study.json",
                "--snapshot-id",
                "snap",
                "--symbol",
                "BTCUSDT",
                "--venue",
                "binance",
                "--timeframe",
                "1h",
            ]
        )
        self.assertEqual(init_args.command, "init-example")
        self.assertEqual(init_args.run_id, "example-study")
        self.assertEqual(init_args.seed, 7)
        self.assertEqual(init_args.maker_fee_bps, 2.0)
        self.assertEqual(init_args.taker_fee_bps, 5.0)

        schema_args = parser.parse_args(["export-schema", "--output", "schema.json"])
        self.assertEqual(schema_args.command, "export-schema")
        self.assertEqual(schema_args.output, "schema.json")

        refresh_args = parser.parse_args(["refresh-examples"])
        self.assertEqual(refresh_args.command, "refresh-examples")
        self.assertEqual(refresh_args.dir, "examples")

    def test_skill_command_group_registers_skill_commands(self) -> None:
        from engine.app.cli_commands.skills import register_skill_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_skill_commands(subparsers)

        list_args = parser.parse_args(["list-skills", "--format", "json"])
        self.assertEqual(list_args.command, "list-skills")
        self.assertEqual(list_args.format, "json")

        inspect_args = parser.parse_args(["inspect-skill", "--name", "strategy-composer", "--format", "text"])
        self.assertEqual(inspect_args.command, "inspect-skill")
        self.assertEqual(inspect_args.name, "strategy-composer")
        self.assertEqual(inspect_args.format, "text")

    def test_mcp_command_group_registers_mcp_commands(self) -> None:
        from engine.app.cli_commands.mcp import register_mcp_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_mcp_commands(subparsers)

        profiles_args = parser.parse_args(["mcp-list-profiles"])
        self.assertEqual(profiles_args.command, "mcp-list-profiles")

        tools_args = parser.parse_args(["mcp-list-tools", "--profile", "launcher"])
        self.assertEqual(tools_args.command, "mcp-list-tools")
        self.assertEqual(tools_args.profile, "launcher")

        call_args = parser.parse_args(
            [
                "mcp-call",
                "--profile",
                "discovery",
                "--tool",
                "get_validation_protocol",
                "--params",
                "{}",
                "--output-dir",
                "outputs",
            ]
        )
        self.assertEqual(call_args.command, "mcp-call")
        self.assertEqual(call_args.profile, "discovery")
        self.assertEqual(call_args.tool, "get_validation_protocol")
        self.assertEqual(call_args.params, "{}")
        self.assertEqual(call_args.output_dir, "outputs")
        self.assertEqual(call_args.db, "outputs/research-memory.sqlite")

    def test_status_command_group_registers_project_status_commands(self) -> None:
        from engine.app.cli_commands.status import register_project_status_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)

        register_project_status_commands(subparsers)

        args = parser.parse_args(
            [
                "project-status",
                "--status-json",
                "planning/status.json",
                "--format",
                "json",
            ]
        )
        self.assertEqual(args.command, "project-status")
        self.assertIsNone(args.project_status_action)
        self.assertEqual(args.status_json, "planning/status.json")
        self.assertEqual(args.format, "json")

        update_args = parser.parse_args(
            [
                "project-status",
                "--status-json",
                "planning/status.json",
                "update",
                "--phase",
                "optimization_phase_3_agent_loop_cli_simplification",
                "--status",
                "in_progress",
                "--note",
                "split cli commands",
            ]
        )
        self.assertEqual(update_args.project_status_action, "update")
        self.assertEqual(update_args.phase, "optimization_phase_3_agent_loop_cli_simplification")
        self.assertEqual(update_args.status, "in_progress")
        self.assertEqual(update_args.note, "split cli commands")


if __name__ == "__main__":
    unittest.main()
