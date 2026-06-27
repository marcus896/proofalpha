import json
import os
import sqlite3
import subprocess
import shutil
import unittest
from pathlib import Path

from engine.agent.controller import (
    AgentLoopController,
    AgentLoopSettings,
    _build_bounded_meta_policy,
    _build_failure_taxonomy,
    _build_meta_policy_training_examples,
    _build_upstream_adaptation_summary,
    _default_materializer,
    _default_refinement_planner,
    _merge_advisory_summaries,
)
from engine.agent.regression import run_agent_loop_regression
from engine.agent.scratchpad import LoopIterationResult
from engine.memory.store import initialize_memory_db


def _force_remove_tree(path: Path) -> None:
    def _onexc(func, target, excinfo) -> None:
        os.chmod(target, 0o700)
        func(target)

    shutil.rmtree(path, onexc=_onexc)


class AgentLoopControllerTests(unittest.TestCase):
    def test_merge_advisory_summaries_accepts_two_source_paths(self) -> None:
        merged = _merge_advisory_summaries(
            {
                "source_path": "trace.json",
                "failure_taxonomy_hints": ["holdout_failure"],
                "planner_notes": ["repair holdout"],
                "next_hypotheses": ["h1"],
            },
            {
                "source_path": "gate.json",
                "failure_taxonomy_hints": ["scenario_failure"],
                "planner_notes": ["narrow search"],
                "next_hypotheses": ["h2"],
            },
        )

        self.assertEqual(merged["source_paths"], ["trace.json", "gate.json"])
        self.assertEqual(merged["failure_taxonomy_hints"], ["holdout_failure", "scenario_failure"])

    def test_upstream_summary_does_not_block_reviewed_reference_only_sources_without_license(self) -> None:
        db_path = Path("test-output-agent-controller-reference-provenance.sqlite")
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO resource_index (
                        resource_id, resource_group, title, url, license, status,
                        intended_usage, local_destination, pinned_ref, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "reviewed_docs",
                        "non_repo_source",
                        "Reviewed docs",
                        "https://example.test/docs",
                        None,
                        "reviewed_reference_checked",
                        "reference_only",
                        None,
                        None,
                        json.dumps({"sources": [{"url": "https://example.test/docs"}]}),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO run_resource_links (
                        run_id, resource_id, link_role, evidence_source, rationale, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("run-a", "reviewed_docs", "validation", "validation_protocol", "reviewed source", "{}"),
                )
                connection.commit()
            finally:
                connection.close()

            summary = _build_upstream_adaptation_summary(db_path=db_path, run_ids=["run-a"])

            self.assertEqual(summary["linked_resource_count"], 1)
            self.assertEqual(summary["provenance_gap_count"], 0)
            self.assertIsNone(summary["recommended_stop_reason"])
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_upstream_summary_still_blocks_unpinned_adapter_only_sources(self) -> None:
        db_path = Path("test-output-agent-controller-adapter-provenance.sqlite")
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO resource_index (
                        resource_id, resource_group, title, url, license, status,
                        intended_usage, local_destination, pinned_ref, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "adapter_repo",
                        "required_repo",
                        "Adapter repo",
                        "https://example.test/repo",
                        "MIT",
                        "reviewed_reference_checked",
                        "adapter_only",
                        "references/upstream/adapter",
                        None,
                        json.dumps({"repo": "example/adapter"}),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO run_resource_links (
                        run_id, resource_id, link_role, evidence_source, rationale, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("run-a", "adapter_repo", "adapter", "validation_protocol", "unpinned adapter", "{}"),
                )
                connection.commit()
            finally:
                connection.close()

            summary = _build_upstream_adaptation_summary(db_path=db_path, run_ids=["run-a"])

            self.assertEqual(summary["provenance_gap_count"], 1)
            self.assertEqual(summary["recommended_stop_reason"], "upstream_provenance_gap")
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_default_materializer_rejects_payload_that_bypasses_bounded_strategy_interface(self) -> None:
        output_dir = Path("test-output-agent-controller-bounded-dsl")
        try:
            context = {
                "iteration": 1,
                "output_dir": output_dir,
                "payload": {
                    "run_id": "phase5-bounded-dsl",
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": ["flat9"],
                    "custom_filters": [],
                    "exit_layers": [],
                    "snapshot": {
                        "symbol": "BTCUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                    },
                    "python_code": "def trade(): return 'BUY'",
                },
                "settings": {
                    "loop_mode": "bounded",
                    "karpathy_target_kind": "json_config",
                },
                "root_run_id": "phase5-bounded-dsl",
            }

            with self.assertRaisesRegex(ValueError, "free_form_code_not_allowed"):
                _default_materializer(context, {"mode": "single"})
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_writes_phase5_artifacts_and_model_governance_records(self) -> None:
        output_dir = Path("test-output-agent-controller-phase5-artifacts")
        try:
            def _refinement(_ctx, _result, _memory_summary):
                return {
                    "continue": False,
                    "stop_reason": "done",
                    "next_payload": {
                        "run_id": "phase5-governed-next",
                        "incumbent": {"backbone": "mom_squeeze"},
                        "directional_layers": ["kama"],
                        "known_good_filters": ["flat9"],
                        "custom_filters": [],
                        "exit_layers": ["time_stop"],
                        "snapshot": {
                            "symbol": "BTCUSDT",
                            "venue": "binance",
                            "timeframe": "1h",
                        },
                    },
                }

            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=1, run_budget=1),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-phase5-artifacts"],
                    "promoted_run_ids": [],
                    "status": "evaluated",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                    "memory_summary": {},
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=_refinement,
            )

            report = controller.run(
                initial_payload={
                    "run_id": "phase5-artifacts",
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": ["flat9"],
                    "custom_filters": [],
                    "exit_layers": [],
                    "snapshot": {
                        "symbol": "BTCUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                    },
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertIn("phase5_frontier_artifact_path", report)
            self.assertIn("phase5_evolution_summary_artifact_path", report)
            self.assertIn("phase5_regression_result", report)
            self.assertIn("model_governance_artifact_path", report)
            self.assertIn("model_governance_records", report)
            self.assertTrue(Path(report["phase5_frontier_artifact_path"]).exists())
            self.assertTrue(Path(report["phase5_evolution_summary_artifact_path"]).exists())
            self.assertTrue(Path(report["model_governance_artifact_path"]).exists())
            self.assertTrue(report["phase5_regression_result"]["acceptable_against_incumbent"])
            self.assertGreaterEqual(len(report["model_governance_records"]), 1)

            frontier = json.loads(Path(report["phase5_frontier_artifact_path"]).read_text(encoding="utf-8"))
            self.assertEqual(frontier["frontier"][0]["variant_id"], "baseline")

            governance = json.loads(Path(report["model_governance_artifact_path"]).read_text(encoding="utf-8"))
            self.assertEqual(governance["records"][0]["approval_state"], "approved")
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_reuses_cached_phase5_regression_artifacts_for_same_policy_settings(self) -> None:
        output_dir = Path("test-output-agent-controller-phase5-cache")
        try:
            def _run_once(run_id: str) -> dict[str, object]:
                controller = AgentLoopController(
                    settings=AgentLoopSettings(max_iterations=1, run_budget=1, memory_quality_policy="clean-only"),
                    planner=lambda ctx: {"mode": "single"},
                    materializer=lambda ctx, plan: {"config_paths": [output_dir / f"{run_id}.json"]},
                    validator=lambda ctx, materialized: {
                        "run_ids": [f"{run_id}-child"],
                        "promoted_run_ids": [],
                        "status": "evaluated",
                        "objective_score": 1.0,
                        "failed_gates": [],
                        "regime_failure_labels": [],
                        "scenario_failure_names": [],
                        "memory_summary": {},
                    },
                    memory_updater=lambda ctx, result: {},
                    refinement_planner=lambda ctx, result, memory_summary: {
                        "continue": False,
                        "stop_reason": "done",
                        "next_payload": dict(ctx["payload"]),
                    },
                )
                return controller.run(
                    initial_payload={
                        "run_id": run_id,
                        "incumbent": {"backbone": "mom_squeeze"},
                        "directional_layers": ["kama"],
                        "known_good_filters": ["flat9"],
                        "custom_filters": [],
                        "exit_layers": [],
                        "snapshot": {
                            "symbol": "BTCUSDT",
                            "venue": "binance",
                            "timeframe": "1h",
                        },
                    },
                    output_dir=output_dir,
                    db_path=output_dir / "memory.sqlite",
                )

            from unittest.mock import patch

            with patch("engine.agent.controller.run_agent_loop_regression", wraps=run_agent_loop_regression) as mocked:
                first = _run_once("phase5-cache-a")
                second = _run_once("phase5-cache-b")

            self.assertEqual(mocked.call_count, 2)
            self.assertEqual(first["phase5_regression_cache"]["status"], "miss")
            self.assertEqual(second["phase5_regression_cache"]["status"], "hit")
            self.assertNotEqual(first["phase5_frontier_artifact_path"], second["phase5_frontier_artifact_path"])
            self.assertTrue(Path(second["phase5_frontier_artifact_path"]).exists())
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_rebuilds_phase5_regression_cache_when_cached_payload_schema_is_invalid(self) -> None:
        output_dir = Path("test-output-agent-controller-phase5-cache-invalid")
        try:
            def _run_once(run_id: str) -> dict[str, object]:
                controller = AgentLoopController(
                    settings=AgentLoopSettings(max_iterations=1, run_budget=1, memory_quality_policy="clean-only"),
                    planner=lambda ctx: {"mode": "single"},
                    materializer=lambda ctx, plan: {"config_paths": [output_dir / f"{run_id}.json"]},
                    validator=lambda ctx, materialized: {
                        "run_ids": [f"{run_id}-child"],
                        "promoted_run_ids": [],
                        "status": "evaluated",
                        "objective_score": 1.0,
                        "failed_gates": [],
                        "regime_failure_labels": [],
                        "scenario_failure_names": [],
                        "memory_summary": {},
                    },
                    memory_updater=lambda ctx, result: {},
                    refinement_planner=lambda ctx, result, memory_summary: {
                        "continue": False,
                        "stop_reason": "done",
                        "next_payload": dict(ctx["payload"]),
                    },
                )
                return controller.run(
                    initial_payload={
                        "run_id": run_id,
                        "incumbent": {"backbone": "mom_squeeze"},
                        "directional_layers": ["kama"],
                        "known_good_filters": ["flat9"],
                        "custom_filters": [],
                        "exit_layers": [],
                        "snapshot": {
                            "symbol": "BTCUSDT",
                            "venue": "binance",
                            "timeframe": "1h",
                        },
                    },
                    output_dir=output_dir,
                    db_path=output_dir / "memory.sqlite",
                )

            from unittest.mock import patch

            first = _run_once("phase5-cache-invalid-a")
            cache_path = Path(first["phase5_regression_cache"]["cache_path"])
            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cache_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "agent_loop_phase5_regression_cache",
                        "cache_schema_version": 1,
                        "cache_key": cache_payload["cache_key"],
                    }
                ),
                encoding="utf-8",
            )

            with patch("engine.agent.controller.run_agent_loop_regression", wraps=run_agent_loop_regression) as mocked:
                second = _run_once("phase5-cache-invalid-b")

            self.assertEqual(mocked.call_count, 2)
            self.assertEqual(second["phase5_regression_cache"]["status"], "miss")
            self.assertTrue(Path(second["phase5_frontier_artifact_path"]).exists())
            self.assertIn("frontier", json.loads(Path(second["phase5_frontier_artifact_path"]).read_text(encoding="utf-8")))
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_build_bounded_meta_policy_stops_on_upstream_governance_risk(self) -> None:
        policy = _build_bounded_meta_policy(
            run_id="meta-stop",
            execution_status="blocked",
            objective_score=None,
            failed_gates=[],
            regime_failure_labels=[],
            scenario_failure_names=[],
            failure_taxonomy=["resource_license_risk"],
            next_study_paths={
                "balanced": "balanced.json",
                "conservative": "conservative.json",
                "exploratory": "exploratory.json",
            },
        )

        self.assertEqual(policy["status"], "validated")
        self.assertEqual(policy["policy_family"], "bandit")
        self.assertEqual(policy["payload"]["selected_action"], "stop")
        self.assertIsNone(policy["payload"]["selected_variant_path"])

    def test_build_bounded_meta_policy_can_select_exploratory_on_clean_promoted_run(self) -> None:
        policy = _build_bounded_meta_policy(
            run_id="meta-explore",
            execution_status="promoted",
            objective_score=2.1,
            failed_gates=[],
            regime_failure_labels=[],
            scenario_failure_names=[],
            failure_taxonomy=[],
            next_study_paths={
                "balanced": "balanced.json",
                "conservative": "conservative.json",
                "exploratory": "exploratory.json",
            },
        )

        self.assertEqual(policy["payload"]["selected_action"], "exploratory")
        self.assertEqual(policy["payload"]["selected_variant_path"], "exploratory.json")

    def test_build_bounded_meta_policy_uses_prior_variant_rewards(self) -> None:
        training_examples = _build_meta_policy_training_examples(
            [
                {
                    "run_id": "prior-balanced",
                    "selected_variant": "balanced",
                    "decision": "promoted",
                    "selection_oos_sharpe": 0.4,
                    "failed_validation_gates": [],
                },
                {
                    "run_id": "prior-conservative",
                    "selected_variant": "conservative",
                    "decision": "promoted",
                    "selection_oos_sharpe": 3.5,
                    "failed_validation_gates": [],
                },
                {
                    "run_id": "prior-exploratory",
                    "selected_variant": "exploratory",
                    "decision": "blocked",
                    "selection_oos_sharpe": 0.1,
                    "failed_validation_gates": ["pbo"],
                },
                {
                    "run_id": "current",
                    "selected_variant": "conservative",
                    "decision": "promoted",
                    "selection_oos_sharpe": 9.9,
                },
            ],
            exclude_run_id="current",
        )
        policy = _build_bounded_meta_policy(
            run_id="meta-trained",
            execution_status="blocked",
            objective_score=0.1,
            failed_gates=[],
            regime_failure_labels=[],
            scenario_failure_names=[],
            failure_taxonomy=[],
            next_study_paths={
                "balanced": "balanced.json",
                "conservative": "conservative.json",
                "exploratory": "exploratory.json",
            },
            training_examples=training_examples,
        )

        self.assertEqual(policy["payload"]["selected_action"], "conservative")
        self.assertEqual(policy["status"], "trained")
        self.assertEqual(policy["training_stats"]["training_example_count"], 3)
        self.assertGreater(policy["training_stats"]["mean_reward_by_action"]["conservative"], 4.0)
        self.assertEqual(policy["offline_evaluation"]["method"], "logged_bandit_mean_reward_v1")
        self.assertEqual(policy["offline_evaluation"]["best_observed_action"], "conservative")
        self.assertEqual(policy["offline_evaluation"]["selected_action_support"], 1)
        self.assertFalse(policy["offline_evaluation"]["direct_trading_action_bypass"])
        self.assertTrue(policy["payload"]["safety_contract"]["validation_stress_gates_required"])

    def test_build_failure_taxonomy_maps_current_loop_signals_to_controlled_labels(self) -> None:
        taxonomy = _build_failure_taxonomy(
            failed_gates=[
                "minimum_backtest_length",
                "in_sample_permutation",
                "pbo",
                "final_holdout_drawdown",
            ],
            regime_failure_labels=["crash"],
            scenario_failure_names=["liquidation-cascade", "venue-outage"],
            quality_flags=["missing_funding_rate"],
            has_venue_profile=False,
        )

        self.assertEqual(
            taxonomy,
            [
                "data_quality_failure",
                "venue_profile_gap",
                "liquidation_realism_failure",
                "insufficient_backtest_length",
                "multiple_testing_failure",
                "overfit_high_pbo",
                "holdout_failure",
                "stress_failure",
                "regime_brittleness",
            ],
        )

    def test_controller_auto_mode_selects_bounded_for_standard_study_loop(self) -> None:
        output_dir = Path("test-output-agent-controller-auto-bounded")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=1, run_budget=1),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-auto-bounded"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-auto-bounded"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["loop_mode_requested"], "auto")
            self.assertEqual(report["loop_mode"], "bounded")
            self.assertEqual(report["loop_mode_selection_reason"], "auto_selected_bounded_standard_study_loop")
            self.assertEqual(report["mode_runtime"]["requested_loop_mode"], "auto")
            self.assertEqual(report["mode_runtime"]["effective_loop_mode"], "bounded")
            self.assertEqual(report["settings"]["loop_mode"], "auto")
            self.assertEqual(report["settings"]["effective_loop_mode"], "bounded")
            self.assertEqual(report["scratchpad"]["loop_mode"], "bounded")
            self.assertEqual(report["events"][0]["event"], "mode_selected")
            self.assertEqual(report["events"][0]["details"]["effective_loop_mode"], "bounded")
            self.assertIsNone(report["karpathy_summary"])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_auto_mode_selects_karpathy_for_python_source_target(self) -> None:
        output_dir = Path("test-output-agent-controller-auto-karpathy")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    karpathy_target_kind="python_source",
                    max_iterations=1,
                    run_budget=1,
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-auto-karpathy"],
                    "promoted_run_ids": [],
                    "status": "evaluated",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-auto-karpathy"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["loop_mode_requested"], "auto")
            self.assertEqual(report["loop_mode"], "karpathy")
            self.assertEqual(report["loop_mode_selection_reason"], "auto_selected_karpathy_python_source_target")
            self.assertEqual(report["mode_runtime"]["requested_loop_mode"], "auto")
            self.assertEqual(report["mode_runtime"]["effective_loop_mode"], "karpathy")
            self.assertEqual(report["settings"]["loop_mode"], "auto")
            self.assertEqual(report["settings"]["effective_loop_mode"], "karpathy")
            self.assertEqual(report["scratchpad"]["loop_mode"], "karpathy")
            self.assertEqual(report["events"][0]["event"], "mode_selected")
            self.assertEqual(report["events"][0]["details"]["effective_loop_mode"], "karpathy")
            self.assertIsInstance(report["karpathy_summary"], dict)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_stops_on_blocked_upstream_resource_links_and_reports_adaptation_summary(self) -> None:
        output_dir = Path("test-output-agent-controller-upstream-risk")
        db_path = output_dir / "memory.sqlite"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO research_runs (
                        run_id, strategy_hash, phase, split_id, seed, decision, symbol, venue, snapshot_id,
                        final_status, selection_oos_sharpe, selection_oos_net_pnl, selection_oos_drawdown,
                        scenario_pass_rate, accepted_layers, snapshot_quality_status, snapshot_quality_flag_count,
                        snapshot_quality_flags_json, snapshot_quality_report_json, snapshot_provenance_json,
                        snapshot_build_version, snapshot_source_hash, runtime_settings_json, selected_parameters_json,
                        parameter_search_json, agent_loop_metadata_json, research_program_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "run-license-risk",
                        "hash-risk",
                        "phase-5",
                        "snap:60-20-20",
                        7,
                        "blocked",
                        "BTCUSDT",
                        "binance",
                        "snap-risk",
                        "blocked",
                        0.1,
                        1.0,
                        -0.1,
                        0.0,
                        0,
                        "clean",
                        0,
                        "[]",
                        "{}",
                        "{}",
                        "v1",
                        "hash-risk",
                        "{}",
                        "{}",
                        "{}",
                        "{}",
                        "phase5-v1",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO resource_index (
                        resource_id, resource_group, title, url, license, status, intended_usage,
                        local_destination, pinned_ref, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "openbb",
                        "conditional_repo",
                        "OpenBB",
                        "https://github.com/OpenBB-finance/OpenBB",
                        "AGPL-3.0",
                        "blocked_license_review",
                        "reference_only",
                        None,
                        None,
                        "{}",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO run_resource_links (
                        run_id, resource_id, link_role, evidence_source, rationale, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "run-license-risk",
                        "openbb",
                        "validation_reference",
                        "validation_bundle",
                        "blocked repo linked into current run evidence",
                        "{}",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=2, run_budget=2),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-license-risk"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 0.2,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                    "memory_summary": {},
                },
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-upstream-risk"},
                output_dir=output_dir,
                db_path=db_path,
            )

            self.assertEqual(report["stop_reason"], "resource_license_risk")
            self.assertEqual(report["scratchpad"]["failure_taxonomy_counts"]["resource_license_risk"], 1)
            self.assertEqual(report["scratchpad"]["next_hypotheses"], ["review_upstream_license_boundary"])
            upstream = report["upstream_adaptation_summary"]
            self.assertEqual(upstream["linked_resource_count"], 1)
            self.assertEqual(upstream["blocked_resource_count"], 1)
            self.assertEqual(upstream["linked_resources"][0]["resource_id"], "openbb")
            self.assertEqual(upstream["linked_resources"][0]["status"], "blocked_license_review")
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["stop_reason"], "resource_license_risk")
            self.assertEqual(persisted["upstream_adaptation_summary"]["linked_resources"][0]["resource_id"], "openbb")
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_does_not_double_count_post_validation_crashes(self) -> None:
        output_dir = Path("test-output-agent-controller-post-validation-crash")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=3, run_budget=3, max_stagnation_rounds=1),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-a"],
                    "promoted_run_ids": ["run-a"],
                    "status": "promoted",
                    "objective_score": 2.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: (_ for _ in ()).throw(RuntimeError("memory updater exploded")),
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-post-validation-crash"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["stop_reason"], "pipeline_crash")
            self.assertEqual(report["iteration_count"], 1)
            self.assertEqual(report["completed_run_ids"], ["run-a"])
            self.assertEqual([event["event"] for event in report["events"]][-2:], ["iteration_crashed", "loop_stopped"])
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["iteration_count"], 1)
            self.assertEqual(len(persisted["iteration_results"]), 1)
            self.assertEqual(persisted["iteration_results"][0]["status"], "promoted")
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_logs_loop_and_iteration_boundaries(self) -> None:
        output_dir = Path("test-output-agent-controller-logging")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=2, run_budget=2, max_stagnation_rounds=1),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            with self.assertLogs("engine.agent.controller", level="INFO") as captured_logs:
                report = controller.run(
                    initial_payload={"run_id": "phase5-logging"},
                    output_dir=output_dir,
                    db_path=output_dir / "memory.sqlite",
                )

            self.assertEqual(report["iteration_count"], 1)
            self.assertTrue(
                any(
                    "loop start" in message.lower()
                    and "phase5-logging" in message
                    and "max_iterations=2" in message
                    and "run_budget=2" in message
                    for message in captured_logs.output
                ),
                captured_logs.output,
            )
            self.assertTrue(
                any(
                    "iteration 1 started" in message.lower()
                    and "root_run_id=phase5-logging" in message
                    and "run_id=phase5-logging" in message
                    for message in captured_logs.output
                ),
                captured_logs.output,
            )
            self.assertTrue(
                any(
                    "validation completed" in message.lower()
                    and "status=blocked" in message
                    and "run_ids=['run-1']" in message
                    for message in captured_logs.output
                ),
                captured_logs.output,
            )
            self.assertTrue(
                any(
                    "iteration 1 ended" in message.lower()
                    and "run_ids=['run-1']" in message
                    and "status=blocked" in message
                    for message in captured_logs.output
                ),
                captured_logs.output,
            )
            self.assertTrue(
                any(
                    "loop stopped" in message.lower()
                    and "stop_reason=done" in message
                    and "completed_iterations=1" in message
                    for message in captured_logs.output
                ),
                captured_logs.output,
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_records_iteration_crash_and_persists_report(self) -> None:
        output_dir = Path("test-output-agent-controller-crash")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=2, run_budget=2, max_stagnation_rounds=1),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: (_ for _ in ()).throw(ValueError("validator exploded")),
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False},
            )

            with self.assertLogs("engine.agent.controller", level="INFO") as captured_logs:
                report = controller.run(
                    initial_payload={"run_id": "phase5-crash"},
                    output_dir=output_dir,
                    db_path=output_dir / "memory.sqlite",
                )

            self.assertEqual(report["status"], "stopped")
            self.assertEqual(report["stop_reason"], "pipeline_crash")
            self.assertEqual(report["iteration_count"], 1)
            self.assertIn("iteration_crashed", [event["event"] for event in report["events"]])
            self.assertTrue(
                any(
                    "validator exploded" in message.lower() and "iteration 1 failed" in message.lower()
                    for message in captured_logs.output
                ),
                captured_logs.output,
            )
            self.assertTrue(
                any(
                    "loop stopped" in message.lower()
                    and "stop_reason=pipeline_crash" in message
                    and "completed_iterations=1" in message
                    for message in captured_logs.output
                ),
                captured_logs.output,
            )
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["stop_reason"], "pipeline_crash")
            self.assertEqual(persisted["iteration_count"], 1)
            self.assertEqual([event["event"] for event in persisted["events"]][-2:], ["iteration_crashed", "loop_stopped"])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_emits_required_events_and_stops_on_plateau(self) -> None:
        output_dir = Path("test-output-agent-controller")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=3, run_budget=3, max_stagnation_rounds=1),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-a"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": ["deflated_sharpe_ratio"],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {"validation_failures": [{"gate_name": "deflated_sharpe_ratio", "count": 1}]},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": True, "next_hypotheses": ["retry"]},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["status"], "stopped")
            self.assertEqual(report["stop_reason"], "no_improvement_plateau")
            self.assertEqual(report["iteration_count"], 2)
            self.assertEqual(report["completed_run_ids"], ["run-a", "run-a"])
            self.assertEqual(
                [event["event"] for event in report["events"][:5]],
                ["mode_selected", "planning_started", "study_proposed", "study_materialized", "validation_started"],
            )
            self.assertIn("timestamp", report["events"][0])
            self.assertEqual(report["events"][0]["role"], "Controller")
            self.assertEqual(report["events"][1]["role"], "ResearchPlanner")
            self.assertIn("summary", report["events"][0])
            self.assertEqual(report["events"][-1]["event"], "loop_stopped")
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["iteration_count"], 2)
            self.assertEqual(persisted["iteration_results"][-1]["status"], "blocked")
            self.assertIn("best_result_summary", persisted)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_report_persists_failure_taxonomy_counts(self) -> None:
        output_dir = Path("test-output-agent-controller-failure-taxonomy")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=1, run_budget=1),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-taxonomy"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 0.5,
                    "failed_gates": ["pbo", "final_holdout_excellence"],
                    "regime_failure_labels": ["bear"],
                    "scenario_failure_names": ["venue-outage"],
                    "failure_taxonomy": ["overfit_high_pbo", "holdout_failure", "stress_failure", "regime_brittleness"],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-failure-taxonomy"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(
                report["scratchpad"]["failure_taxonomy_counts"],
                {
                    "overfit_high_pbo": 1,
                    "holdout_failure": 1,
                    "stress_failure": 1,
                    "regime_brittleness": 1,
                },
            )
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["iteration_results"][0]["failure_taxonomy"],
                ["overfit_high_pbo", "holdout_failure", "stress_failure", "regime_brittleness"],
            )
            self.assertEqual(
                persisted["scratchpad"]["failure_taxonomy_counts"],
                report["scratchpad"]["failure_taxonomy_counts"],
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_default_refinement_planner_prefers_taxonomy_actions_in_next_hypotheses(self) -> None:
        refinement = _default_refinement_planner(
            {"validation_result": {"next_payload": {"run_id": "next-run"}, "next_payload_path": "next.json"}},
            LoopIterationResult(
                iteration=1,
                run_ids=["run-a"],
                promoted_run_ids=[],
                validation_status="blocked",
                failed_gates=["pbo"],
                failure_taxonomy=["overfit_high_pbo", "stress_failure"],
            ),
            {},
        )

        self.assertEqual(
            refinement["next_hypotheses"],
            ["reduce_overfit_risk", "harden_stress_scenarios", "pbo"],
        )

    def test_controller_wires_trace_advisory_notes_into_hypotheses_without_trading_authority(self) -> None:
        output_dir = Path("test-output-agent-controller-trace-advisory")
        notes_path = output_dir / "trace-advisory-notes.json"
        next_payload_path = output_dir / "next-study.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            notes_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "agent_loop_trace_advisory_notes",
                        "controlled_failure_taxonomy_hints": [
                            {"label": "holdout_failure", "note": "Holdout keeps failing."},
                            {"label": "emit_buy_sell_size", "note": "BUY 10 BTC"},
                        ],
                        "planner_notes": ["Prioritize holdout repair before wider search."],
                        "executor_action": "place_order",
                    }
                ),
                encoding="utf-8",
            )
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    max_iterations=1,
                    run_budget=1,
                    trace_advisory_notes_path=str(notes_path),
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-advisory"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 0.5,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                    "next_payload": {"run_id": "next-run", "research_hypotheses": {}},
                    "next_payload_path": str(next_payload_path),
                },
                memory_updater=lambda ctx, result: {},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-trace-advisory"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(
                report["scratchpad"]["next_hypotheses"],
                [
                    "raise_holdout_robustness",
                    "trace_advisory_note:Prioritize holdout repair before wider search.",
                ],
            )
            self.assertEqual(report["trace_advisory_summary"]["failure_taxonomy_hints"], ["holdout_failure"])
            self.assertEqual(
                report["trace_advisory_summary"]["planner_notes"],
                ["Prioritize holdout repair before wider search."],
            )
            encoded = json.dumps(report, sort_keys=True)
            self.assertNotIn("BUY", encoded)
            self.assertNotIn("place_order", encoded)
            self.assertNotIn("emit_buy_sell_size", encoded)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_stops_after_repeated_stress_failures_even_when_scenarios_change(self) -> None:
        output_dir = Path("test-output-agent-controller-taxonomy-stress")
        scenario_names = iter(["venue-outage", "liquidation-cascade"])
        scores = iter([1.0, 1.1])
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    max_iterations=4,
                    run_budget=4,
                    max_stagnation_rounds=5,
                    max_repeated_scenario_failures=2,
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": next(scores),
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [next(scenario_names)],
                    "failure_taxonomy": ["stress_failure"],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": True, "next_hypotheses": ["retry"]},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-taxonomy-stress"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["stop_reason"], "repeated_stress_failures")
            self.assertEqual(report["iteration_count"], 2)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_scratchpad_event_log_includes_post_validation_loop_events(self) -> None:
        output_dir = Path("test-output-agent-controller-event-log")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=1, run_budget=1),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-event-log"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {"memory_mode": "updated"},
                refinement_planner=lambda ctx, result, memory_summary: {
                    "continue": False,
                    "stop_reason": "done",
                    "next_hypotheses": ["check-log"],
                },
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-event-log"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            event_names = [event["event"] for event in report["events"]]
            self.assertEqual(
                [event["event"] for event in report["scratchpad"]["event_log"]],
                event_names,
            )
            self.assertEqual(
                [event["event"] for event in report["scratchpad"]["event_log"][-3:]],
                ["memory_updated", "batch_refined", "loop_stopped"],
            )
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                [event["event"] for event in persisted["scratchpad"]["event_log"]],
                event_names,
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_stops_at_run_budget_cap(self) -> None:
        output_dir = Path("test-output-agent-controller-budget")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=4, run_budget=1, max_stagnation_rounds=5),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-a"],
                    "promoted_run_ids": ["run-a"],
                    "status": "promoted",
                    "objective_score": 2.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": True, "next_hypotheses": ["continue"]},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-budget"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["stop_reason"], "run_budget_exhausted")
            self.assertEqual(report["iteration_count"], 1)
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["scratchpad"]["remaining_budget"], 0)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_stops_after_repeated_regime_failures(self) -> None:
        output_dir = Path("test-output-agent-controller-regime")
        scores = iter([1.0, 1.1])
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    max_iterations=4,
                    run_budget=4,
                    max_stagnation_rounds=5,
                    max_repeated_regime_failures=2,
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": next(scores),
                    "failed_gates": [],
                    "regime_failure_labels": ["crash"],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": True, "next_hypotheses": ["retry"]},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-regime"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["stop_reason"], "repeated_regime_failures")
            self.assertEqual(report["iteration_count"], 2)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_stops_after_repeated_scenario_failures(self) -> None:
        output_dir = Path("test-output-agent-controller-scenario")
        scores = iter([1.0, 1.1])
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    max_iterations=4,
                    run_budget=4,
                    max_stagnation_rounds=5,
                    max_repeated_scenario_failures=2,
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": next(scores),
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": ["venue_outage"],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": True, "next_hypotheses": ["retry"]},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-scenario"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["stop_reason"], "repeated_scenario_failures")
            self.assertEqual(report["iteration_count"], 2)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_consumes_queued_follow_up_payloads(self) -> None:
        output_dir = Path("test-output-agent-controller-queue")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(max_iterations=4, run_budget=4, max_stagnation_rounds=5),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / f"{ctx['payload']['run_id']}.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [str(ctx["payload"]["run_id"])],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": float(ctx["iteration"]),
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: (
                    {
                        "continue": True,
                        "queued_payloads": [{"run_id": "queued-study"}],
                        "next_hypotheses": ["queue-next"],
                    }
                    if ctx["iteration"] == 1
                    else {"continue": False, "next_hypotheses": ["stop"]}
                ),
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-queue"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["iteration_count"], 2)
            self.assertEqual(report["completed_run_ids"], ["phase5-queue", "queued-study"])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_honors_explicit_stop_request_before_execution(self) -> None:
        output_dir = Path("test-output-agent-controller-stop")
        try:
            controller = AgentLoopController(settings=AgentLoopSettings(max_iterations=4, run_budget=4))
            report = controller.run(
                initial_payload={"run_id": "phase5-stop"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
                stop_requested=True,
            )

            self.assertEqual(report["stop_reason"], "user_stop_requested")
            self.assertEqual(report["iteration_count"], 0)
            self.assertEqual([event["event"] for event in report["events"]], ["mode_selected", "loop_stopped"])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_mode_ignores_plateau_until_explicit_stop(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=4,
                    run_budget=4,
                    max_stagnation_rounds=1,
                    max_duplicate_baseline_plateau_rounds=1,
                    max_repeated_regime_failures=1,
                    max_repeated_scenario_failures=1,
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / f"{ctx['iteration']}.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": ["deflated_sharpe_ratio"],
                    "regime_failure_labels": ["crash"],
                    "scenario_failure_names": ["venue_outage"],
                    "duplicate_baseline_score": 5.0,
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: (
                    {"continue": True, "next_hypotheses": ["keep-going"]}
                    if ctx["iteration"] < 3
                    else {"continue": False, "stop_reason": "karpathy_manual_stop"}
                ),
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["stop_reason"], "karpathy_manual_stop")
            self.assertEqual(report["iteration_count"], 3)
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["settings"]["loop_mode"], "karpathy")
            self.assertEqual(persisted["scratchpad"]["loop_mode"], "karpathy")
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_mode_reports_keep_discard_summary(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-summary")
        scores = iter([1.0, 1.2, 1.1])
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(loop_mode="karpathy", max_iterations=4, run_budget=4),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / f"{ctx['iteration']}.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": next(scores),
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: (
                    {"continue": True}
                    if ctx["iteration"] < 3
                    else {"continue": False, "stop_reason": "karpathy_manual_stop"}
                ),
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-summary"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["karpathy_summary"],
                {
                    "objective": "maximize_validation_score",
                    "decision": "discard",
                    "reason": "objective_not_improved",
                    "validation_status": "blocked",
                    "metric_name": "maximize_validation_score",
                    "metric_value": 1.1,
                    "metric_direction": None,
                    "candidate_run_ids": ["run-3"],
                    "candidate_score": 1.1,
                    "incumbent_run_ids": ["run-2"],
                    "incumbent_score": 1.2,
                    "kept_run_ids": ["run-2"],
                    "kept_score": 1.2,
                },
            )
            results_tsv_path = Path(persisted["karpathy_results_tsv_path"])
            self.assertTrue(results_tsv_path.exists())
            self.assertEqual(
                results_tsv_path.read_text(encoding="utf-8").splitlines(),
                [
                    "iteration\trun_id\tmetric_name\tmetric_value\tvalidation_status\tdecision\tdescription",
                    "1\trun-1\tmaximize_validation_score\t1.0\tblocked\tkeep\tfirst_scored_run",
                    "2\trun-2\tmaximize_validation_score\t1.2\tblocked\tkeep\tobjective_improved",
                    "3\trun-3\tmaximize_validation_score\t1.1\tblocked\tdiscard\tobjective_not_improved",
                ],
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_mode_carries_forward_kept_lineage(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-lineage")
        seen_payload_run_ids: list[str] = []
        scores = iter([1.0, 1.2, 1.1, 1.15])
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(loop_mode="karpathy", max_iterations=4, run_budget=4),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: (
                    seen_payload_run_ids.append(str(ctx["payload"]["run_id"])) or {"config_paths": [output_dir / f"{ctx['iteration']}.json"]}
                ),
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": next(scores),
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: (
                    {
                        "continue": True,
                        "next_payload": {
                            "run_id": f"proposal-from-{result.run_ids[0]}",
                            "seed_from": result.run_ids[0],
                        },
                    }
                    if ctx["iteration"] < 4
                    else {"continue": False, "stop_reason": "karpathy_manual_stop"}
                ),
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-lineage"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["stop_reason"], "max_iterations_reached")
            self.assertEqual(
                seen_payload_run_ids,
                [
                    "phase5-karpathy-lineage",
                    "proposal-from-run-1",
                    "proposal-from-run-2",
                    "proposal-from-run-2",
                ],
            )
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            artifact_path = Path(persisted["karpathy_incumbent_artifact_path"])
            self.assertTrue(artifact_path.exists())
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["karpathy_summary"]["kept_run_ids"], ["run-2"])
            self.assertEqual(artifact["next_payload"]["run_id"], "proposal-from-run-2")
            ledger_path = Path(persisted["karpathy_ledger_artifact_path"])
            self.assertTrue(ledger_path.exists())
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(len(ledger["entries"]), 4)
            self.assertEqual(ledger["entries"][1]["incumbent_changed"], True)
            self.assertEqual(ledger["entries"][2]["incumbent_changed"], False)
            self.assertEqual(ledger["entries"][2]["selected_next_payload_run_id"], "proposal-from-run-2")
            self.assertEqual(ledger["entries"][2]["validation_status"], "blocked")
            self.assertEqual(len(persisted["karpathy_decisions"]), 4)
            self.assertEqual(
                persisted["karpathy_decisions"][2],
                {
                    "iteration": 3,
                    "objective": "maximize_validation_score",
                    "metric_name": "maximize_validation_score",
                    "metric_value": 1.1,
                    "metric_direction": None,
                    "candidate_run_ids": ["run-3"],
                    "candidate_score": 1.1,
                    "decision": "discard",
                    "reason": "objective_not_improved",
                    "validation_status": "blocked",
                    "incumbent_run_ids": ["run-2"],
                    "incumbent_score": 1.2,
                    "kept_run_ids": ["run-2"],
                    "kept_score": 1.2,
                    "proposed_next_payload_run_id": "proposal-from-run-3",
                    "selected_next_payload_run_id": "proposal-from-run-2",
                },
            )
            self.assertEqual(artifact["karpathy_decisions"][2]["selected_next_payload_run_id"], "proposal-from-run-2")
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_mode_reuses_one_working_config_path(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-working")
        seen_config_paths: list[str] = []
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(loop_mode="karpathy", max_iterations=3, run_budget=3),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: (
                    seen_config_paths.append(str(materialized["config_paths"][0]))
                    or {
                        "run_ids": [f"run-{ctx['iteration']}"],
                        "promoted_run_ids": [],
                        "status": "blocked",
                        "objective_score": float(ctx["iteration"]),
                        "failed_gates": [],
                        "regime_failure_labels": [],
                        "scenario_failure_names": [],
                    }
                ),
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: (
                    {"continue": True, "next_payload": {"run_id": f"proposal-{ctx['iteration']}"}}
                    if ctx["iteration"] < 3
                    else {"continue": False, "stop_reason": "karpathy_manual_stop"}
                ),
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-working"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                seen_config_paths,
                [
                    str(output_dir / "phase5-karpathy-working.karpathy-working.json"),
                    str(output_dir / "phase5-karpathy-working.karpathy-working.json"),
                    str(output_dir / "phase5-karpathy-working.karpathy-working.json"),
                ],
            )
            self.assertEqual(
                persisted["karpathy_working_config_path"],
                str(output_dir / "phase5-karpathy-working.karpathy-working.json"),
            )
            self.assertTrue(Path(persisted["karpathy_working_config_path"]).exists())
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_mode_uses_working_file_as_next_iteration_source_of_truth(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-working-authority")
        seen_payload_run_ids: list[str] = []
        try:
            def refinement_planner(
                ctx: dict[str, object],
                result: LoopIterationResult,
                memory_summary: dict[str, object],
            ) -> dict[str, object]:
                working_path = output_dir / "phase5-karpathy-working-authority.karpathy-working.json"
                if ctx["iteration"] == 1:
                    working_path.write_text(
                        json.dumps({"run_id": "disk-authoritative", "source": "working-file"}, indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
                    return {"continue": True}
                return {"continue": False, "stop_reason": "karpathy_manual_stop"}

            controller = AgentLoopController(
                settings=AgentLoopSettings(loop_mode="karpathy", max_iterations=2, run_budget=2),
                planner=lambda ctx: (
                    seen_payload_run_ids.append(str(ctx["payload"]["run_id"]))
                    or {"mode": "single"}
                ),
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": float(ctx["iteration"]),
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=refinement_planner,
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-working-authority"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                seen_payload_run_ids,
                [
                    "phase5-karpathy-working-authority",
                    "disk-authoritative",
                ],
            )
            self.assertEqual(
                json.loads(Path(persisted["karpathy_working_config_path"]).read_text(encoding="utf-8")),
                {"run_id": "disk-authoritative", "source": "working-file"},
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_mode_supports_first_class_target_path(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-target-path")
        target_path = output_dir / "custom-target.json"
        seen_config_paths: list[str] = []
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: (
                    seen_config_paths.append(str(materialized["config_paths"][0]))
                    or {
                        "run_ids": ["run-1"],
                        "promoted_run_ids": [],
                        "status": "blocked",
                        "objective_score": 1.0,
                        "failed_gates": [],
                        "regime_failure_labels": [],
                        "scenario_failure_names": [],
                    }
                ),
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-target-path"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(seen_config_paths, [str(target_path)])
            self.assertEqual(report["karpathy_target_path"], str(target_path))
            self.assertEqual(report["karpathy_target_kind"], "json_config")
            self.assertEqual(persisted["karpathy_target_path"], str(target_path))
            self.assertEqual(persisted["karpathy_target_kind"], "json_config")
            self.assertEqual(report["karpathy_working_config_path"], str(target_path))
            self.assertTrue(target_path.exists())
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_mode_supports_python_source_target(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-target")
        target_path = output_dir / "custom-target.py"
        seen_payload_run_ids: list[str] = []
        seen_config_paths: list[str] = []
        try:
            def refinement_planner(
                ctx: dict[str, object],
                result: LoopIterationResult,
                memory_summary: dict[str, object],
            ) -> dict[str, object]:
                if ctx["iteration"] == 1:
                    target_path.write_text(
                        "from __future__ import annotations\n\n"
                        "def mutate_payload(payload: dict[str, object], context: dict[str, object]) -> None:\n"
                        '    payload["carry"] = payload.get("carry", "missing")\n'
                        '    payload["iteration_seen"] = context["iteration"]\n'
                        '    payload["run_id"] = "python-target-authoritative"\n'
                        '    payload["source"] = "python-file"\n',
                        encoding="utf-8",
                    )
                    return {"continue": True}
                return {"continue": False, "stop_reason": "done"}

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=2,
                    run_budget=2,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: (
                    seen_payload_run_ids.append(str(ctx["payload"]["run_id"]))
                    or {"mode": "single"}
                ),
                validator=lambda ctx, materialized: (
                    seen_config_paths.append(str(materialized["config_paths"][0]))
                    or {
                        "run_ids": [f"run-{ctx['iteration']}"],
                        "promoted_run_ids": [],
                        "status": "blocked",
                        "objective_score": float(ctx["iteration"]),
                        "failed_gates": [],
                        "regime_failure_labels": [],
                        "scenario_failure_names": [],
                    }
                ),
                memory_updater=lambda ctx, result: {},
                refinement_planner=refinement_planner,
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-python-target", "carry": "from-base"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                seen_payload_run_ids,
                [
                    "phase5-karpathy-python-target",
                    "python-target-authoritative",
                ],
            )
            self.assertEqual(report["karpathy_target_path"], str(target_path))
            self.assertEqual(report["karpathy_target_kind"], "python_source")
            self.assertEqual(persisted["karpathy_target_kind"], "python_source")
            self.assertEqual(
                seen_config_paths,
                [
                    str(output_dir / "phase5-karpathy-python-target.karpathy-materialized.json"),
                    str(output_dir / "phase5-karpathy-python-target.karpathy-materialized.json"),
                ],
            )
            self.assertIn("def mutate_payload(payload: dict[str, object], context:", target_path.read_text(encoding="utf-8"))
            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-target.karpathy-materialized.json").read_text(encoding="utf-8")
            )
            self.assertEqual(materialized_payload["carry"], "from-base")
            self.assertEqual(materialized_payload["iteration_seen"], 2)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_can_import_sibling_helper_module(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-imports")
        target_path = output_dir / "custom-target.py"
        helper_path = output_dir / "target_helpers.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            helper_path.write_text(
                "from __future__ import annotations\n\n"
                "def apply_helper(payload: dict[str, object], context: dict[str, object]) -> None:\n"
                '    payload["run_id"] = "python-import-authoritative"\n'
                '    payload["helper_used"] = True\n'
                '    payload["iteration_seen"] = context["iteration"]\n',
                encoding="utf-8",
            )
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "from target_helpers import apply_helper\n\n"
                "def mutate_payload(payload: dict[str, object], context: dict[str, object]) -> None:\n"
                "    apply_helper(payload, context)\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-python-imports"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-imports.karpathy-materialized.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["karpathy_target_kind"], "python_source")
            self.assertEqual(materialized_payload["run_id"], "python-import-authoritative")
            self.assertEqual(materialized_payload["helper_used"], True)
            self.assertEqual(materialized_payload["iteration_seen"], 1)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_patch_builder_module(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-patch-builder")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "def build_payload_patch(\n"
                "    base_payload: dict[str, object],\n"
                "    context: dict[str, object],\n"
                ") -> dict[str, object]:\n"
                "    return {\n"
                '        "run_id": "python-patch-authoritative",\n'
                '        "metadata": {\n'
                '            "strategy_mode": "patch-builder",\n'
                '            "iteration_seen": context["iteration"],\n'
                '        },\n'
                '        "risk": {\n'
                '            "max_positions": 3,\n'
                '        },\n'
                "    }\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-patch-builder",
                    "metadata": {"source": "base"},
                    "risk": {"max_drawdown": 0.2},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-patch-builder.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "python-patch-authoritative")
            self.assertEqual(materialized_payload["metadata"]["source"], "base")
            self.assertEqual(materialized_payload["metadata"]["strategy_mode"], "patch-builder")
            self.assertEqual(materialized_payload["metadata"]["iteration_seen"], 1)
            self.assertEqual(materialized_payload["risk"]["max_drawdown"], 0.2)
            self.assertEqual(materialized_payload["risk"]["max_positions"], 3)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_study_patch_module(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-study-patch")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "def build_study_patch(\n"
                "    base_study: dict[str, object],\n"
                "    context: dict[str, object],\n"
                ") -> dict[str, object]:\n"
                "    return {\n"
                '        "run_id": "python-study-authoritative",\n'
                '        "directional_layers": ["ema_cross", "kama"],\n'
                '        "runtime": {\n'
                '            "mode": "builtin",\n'
                '            "tag": f"iter-{context[\'iteration\']}",\n'
                '        },\n'
                "    }\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-study-patch",
                    "known_good_filters": ["flat9"],
                    "runtime": {"seed_mode": "fixed"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-study-patch.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "python-study-authoritative")
            self.assertEqual(materialized_payload["directional_layers"], ["ema_cross", "kama"])
            self.assertEqual(materialized_payload["known_good_filters"], ["flat9"])
            self.assertEqual(materialized_payload["runtime"]["seed_mode"], "fixed")
            self.assertEqual(materialized_payload["runtime"]["tag"], "iter-1")
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_domain_strategy_hooks(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-domain-hooks")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "def build_layer_stack(\n"
                "    base_study: dict[str, object],\n"
                "    context: dict[str, object],\n"
                ") -> dict[str, object]:\n"
                "    return {\n"
                '        "directional_layers": ["ema_cross", "kama"],\n'
                '        "known_good_filters": list(base_study.get("known_good_filters", [])) + ["atr_guard"],\n'
                "    }\n\n"
                "def build_runtime_settings(\n"
                "    base_study: dict[str, object],\n"
                "    context: dict[str, object],\n"
                ") -> dict[str, object]:\n"
                "    return {\n"
                '        "mode": "builtin",\n'
                '        "tag": f"iter-{context[\'iteration\']}",\n'
                "    }\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-domain-hooks",
                    "known_good_filters": ["flat9"],
                    "runtime": {"seed_mode": "fixed"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-domain-hooks.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["directional_layers"], ["ema_cross", "kama"])
            self.assertEqual(materialized_payload["known_good_filters"], ["flat9", "atr_guard"])
            self.assertEqual(materialized_payload["runtime"]["seed_mode"], "fixed")
            self.assertEqual(materialized_payload["runtime"]["tag"], "iter-1")
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_finalize_study_hook(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-finalize-study")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "def build_layer_stack(\n"
                "    base_study: dict[str, object],\n"
                "    context: dict[str, object],\n"
                ") -> dict[str, object]:\n"
                '    return {"directional_layers": ["ema_cross"]}\n\n'
                "def finalize_study(\n"
                "    study: dict[str, object],\n"
                "    context: dict[str, object],\n"
                ") -> None:\n"
                '    study["run_id"] = f"{study[\'run_id\']}-final"\n'
                '    study["known_good_filters"] = list(study.get("known_good_filters", [])) + ["confirm_filter"]\n'
                '    study["runtime"]["finalized_iteration"] = context["iteration"]\n',
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-finalize-study",
                    "known_good_filters": ["flat9"],
                    "runtime": {"mode": "builtin"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-finalize-study.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "phase5-karpathy-python-finalize-study-final")
            self.assertEqual(materialized_payload["directional_layers"], ["ema_cross"])
            self.assertEqual(materialized_payload["known_good_filters"], ["flat9", "confirm_filter"])
            self.assertEqual(materialized_payload["runtime"]["finalized_iteration"], 1)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_study_module_factory(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-study-module")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "class StudyModule:\n"
                "    def __init__(self, base_study: dict[str, object], context: dict[str, object]) -> None:\n"
                "        self.base_study = dict(base_study)\n"
                "        self.context = dict(context)\n\n"
                "    def build_layer_stack(self) -> dict[str, object]:\n"
                "        return {\n"
                '            "directional_layers": ["ema_cross", "kama"],\n'
                '            "known_good_filters": list(self.base_study.get("known_good_filters", [])) + ["module_filter"],\n'
                "        }\n\n"
                "    def finalize_study(self, study: dict[str, object]) -> None:\n"
                '        study["run_id"] = f"{study[\'run_id\']}-module"\n'
                '        study["runtime"]["module_iteration"] = self.context["iteration"]\n\n'
                "def build_study_module(base_study: dict[str, object], context: dict[str, object]) -> StudyModule:\n"
                "    return StudyModule(base_study, context)\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-study-module",
                    "known_good_filters": ["flat9"],
                    "runtime": {"mode": "builtin"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-study-module.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "phase5-karpathy-python-study-module-module")
            self.assertEqual(materialized_payload["directional_layers"], ["ema_cross", "kama"])
            self.assertEqual(materialized_payload["known_good_filters"], ["flat9", "module_filter"])
            self.assertEqual(materialized_payload["runtime"]["module_iteration"], 1)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_study_module_build_method(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-study-module-build")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "class StudyModule:\n"
                "    def __init__(self, base_study: dict[str, object], context: dict[str, object]) -> None:\n"
                "        self.base_study = dict(base_study)\n"
                "        self.context = dict(context)\n\n"
                "    def build_study(self) -> dict[str, object]:\n"
                "        study = dict(self.base_study)\n"
                '        study["run_id"] = f"{study[\'run_id\']}-built"\n'
                '        study["directional_layers"] = ["hma"]\n'
                '        study["runtime"] = dict(study.get("runtime", {}))\n'
                '        study["runtime"]["built_iteration"] = self.context["iteration"]\n'
                "        return study\n\n"
                "def build_study_module(base_study: dict[str, object], context: dict[str, object]) -> StudyModule:\n"
                "    return StudyModule(base_study, context)\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-study-module-build",
                    "runtime": {"mode": "builtin"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-study-module-build.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "phase5-karpathy-python-study-module-build-built")
            self.assertEqual(materialized_payload["directional_layers"], ["hma"])
            self.assertEqual(materialized_payload["runtime"]["built_iteration"], 1)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_stateful_study_module_class(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-study-module-class")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "class StudyModule:\n"
                "    def __init__(self, base_study: dict[str, object], context: dict[str, object]) -> None:\n"
                "        self.base_study = dict(base_study)\n"
                "        self.context = dict(context)\n\n"
                "    def build_study(self) -> dict[str, object]:\n"
                "        study = dict(self.base_study)\n"
                '        study["run_id"] = f"{study[\'run_id\']}-class"\n'
                '        study["directional_layers"] = ["supertrend"]\n'
                '        study["runtime"] = dict(study.get("runtime", {}))\n'
                '        study["runtime"]["class_iteration"] = self.context["iteration"]\n'
                "        return study\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-study-module-class",
                    "runtime": {"mode": "builtin"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-study-module-class.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "phase5-karpathy-python-study-module-class-class")
            self.assertEqual(materialized_payload["directional_layers"], ["supertrend"])
            self.assertEqual(materialized_payload["runtime"]["class_iteration"], 1)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_strategy_section_hooks(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-strategy-sections")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "class StudyModule:\n"
                "    def __init__(self, base_study: dict[str, object], context: dict[str, object]) -> None:\n"
                "        self.base_study = dict(base_study)\n"
                "        self.context = dict(context)\n\n"
                "    def build_directional_layers(self) -> list[str]:\n"
                '        return ["ema_cross", f"iter-{self.context[\'iteration\']}"]\n\n'
                "    def build_known_good_filters(self) -> list[str]:\n"
                '        return list(self.base_study.get("known_good_filters", [])) + ["vol_guard"]\n\n'
                "    def build_exit_layers(self) -> list[str]:\n"
                '        return ["atr_exit"]\n\n'
                "    def build_custom_filters(self) -> list[str]:\n"
                '        return ["hour_window"]\n',
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-strategy-sections",
                    "directional_layers": ["legacy_layer"],
                    "known_good_filters": ["flat9"],
                    "exit_layers": ["legacy_exit"],
                    "custom_filters": [],
                    "runtime": {"mode": "builtin"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-strategy-sections.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["directional_layers"], ["ema_cross", "iter-1"])
            self.assertEqual(materialized_payload["known_good_filters"], ["flat9", "vol_guard"])
            self.assertEqual(materialized_payload["exit_layers"], ["atr_exit"])
            self.assertEqual(materialized_payload["custom_filters"], ["hour_window"])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_strategy_plan_dataclass(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-strategy-plan")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "from dataclasses import dataclass, field\n\n"
                "@dataclass\n"
                "class StrategyPlan:\n"
                "    directional_layers: list[str] = field(default_factory=list)\n"
                "    known_good_filters: list[str] = field(default_factory=list)\n"
                "    runtime_settings: dict[str, object] = field(default_factory=dict)\n"
                "    scenarios: list[dict[str, object]] = field(default_factory=list)\n"
                "    incumbent: dict[str, object] = field(default_factory=dict)\n"
                "    holdout_decision: dict[str, object] = field(default_factory=dict)\n\n"
                "class StudyModule:\n"
                "    def __init__(self, base_study: dict[str, object], context: dict[str, object]) -> None:\n"
                "        self.base_study = dict(base_study)\n"
                "        self.context = dict(context)\n\n"
                "    def build_strategy_plan(self) -> StrategyPlan:\n"
                "        return StrategyPlan(\n"
                '            directional_layers=["ema_cross", "plan"],\n'
                '            known_good_filters=list(self.base_study.get("known_good_filters", [])) + ["plan_filter"],\n'
                '            runtime_settings={"plan_iteration": self.context["iteration"]},\n'
                '            scenarios=[{"name": "plan-shock", "severity": 0.7}],\n'
                '            incumbent={"backbone": "kama_hma"},\n'
                '            holdout_decision={"decision": "review", "reasons": ["plan"]},\n'
                "        )\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-strategy-plan",
                    "known_good_filters": ["flat9"],
                    "runtime": {"mode": "builtin"},
                    "incumbent": {"backbone": "mom_squeeze"},
                    "holdout_decision": {"decision": "accept", "reasons": []},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-strategy-plan.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["directional_layers"], ["ema_cross", "plan"])
            self.assertEqual(materialized_payload["known_good_filters"], ["flat9", "plan_filter"])
            self.assertEqual(materialized_payload["runtime"]["mode"], "builtin")
            self.assertEqual(materialized_payload["runtime"]["plan_iteration"], 1)
            self.assertEqual(materialized_payload["scenarios"], [{"name": "plan-shock", "severity": 0.7}])
            self.assertEqual(materialized_payload["incumbent"], {"backbone": "kama_hma"})
            self.assertEqual(materialized_payload["holdout_decision"], {"decision": "review", "reasons": ["plan"]})
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_strategy_plan_behavior_object(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-strategy-plan-behavior")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "class StrategyPlan:\n"
                "    def __init__(self, base_study: dict[str, object], context: dict[str, object]) -> None:\n"
                "        self.base_study = dict(base_study)\n"
                "        self.context = dict(context)\n\n"
                "    def to_study_patch(self) -> dict[str, object]:\n"
                "        return {\n"
                '            "directional_layers": ["behavior_layer"],\n'
                '            "known_good_filters": list(self.base_study.get("known_good_filters", [])) + ["behavior_filter"],\n'
                '            "runtime": {"behavior_iteration": self.context["iteration"]},\n'
                '            "incumbent": {"backbone": "keltner_fade"},\n'
                "        }\n\n"
                "class StudyModule:\n"
                "    def __init__(self, base_study: dict[str, object], context: dict[str, object]) -> None:\n"
                "        self.base_study = dict(base_study)\n"
                "        self.context = dict(context)\n\n"
                "    def build_strategy_plan(self) -> StrategyPlan:\n"
                "        return StrategyPlan(self.base_study, self.context)\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-strategy-plan-behavior",
                    "known_good_filters": ["flat9"],
                    "runtime": {"mode": "builtin"},
                    "incumbent": {"backbone": "mom_squeeze"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (
                    output_dir / "phase5-karpathy-python-strategy-plan-behavior.karpathy-materialized.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(materialized_payload["directional_layers"], ["behavior_layer"])
            self.assertEqual(materialized_payload["known_good_filters"], ["flat9", "behavior_filter"])
            self.assertEqual(materialized_payload["runtime"]["mode"], "builtin")
            self.assertEqual(materialized_payload["runtime"]["behavior_iteration"], 1)
            self.assertEqual(materialized_payload["incumbent"], {"backbone": "keltner_fade"})
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_python_source_target_supports_executable_main_program(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-main-program-v2")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "import argparse\n"
                "import json\n"
                "from pathlib import Path\n\n"
                "def main(argv: list[str] | None = None) -> int:\n"
                "    parser = argparse.ArgumentParser()\n"
                "    parser.add_argument('--emit-study', action='store_true')\n"
                "    parser.add_argument('--base-study')\n"
                "    parser.add_argument('--context')\n"
                "    parser.add_argument('--output')\n"
                "    args = parser.parse_args(argv)\n"
                "    if not args.emit_study:\n"
                "        return 1\n"
                "    base_study = json.loads(Path(args.base_study).read_text(encoding='utf-8'))\n"
                "    context = json.loads(Path(args.context).read_text(encoding='utf-8'))\n"
                "    study = dict(base_study)\n"
                "    study['run_id'] = f\"{study['run_id']}-main\"\n"
                "    study['directional_layers'] = ['main_program']\n"
                "    study['runtime'] = dict(study.get('runtime', {}))\n"
                "    study['runtime']['main_iteration'] = context['iteration']\n"
                "    Path(args.output).write_text(json.dumps(study, indent=2, sort_keys=True), encoding='utf-8')\n"
                "    return 0\n\n"
                "if __name__ == '__main__':\n"
                "    raise SystemExit(main())\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-main-program",
                    "runtime": {"mode": "builtin"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-main-program.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "phase5-karpathy-python-main-program-main")
            self.assertEqual(materialized_payload["directional_layers"], ["main_program"])
            self.assertEqual(materialized_payload["runtime"]["main_iteration"], 1)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_controller_karpathy_python_source_target_supports_executable_main_direct_eval(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-main-direct-eval")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "import argparse\n"
                "import json\n"
                "from pathlib import Path\n\n"
                "def build_study(base_study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    study = dict(base_study)\n"
                "    study['run_id'] = f\"{study['run_id']}-study\"\n"
                "    study['directional_layers'] = ['direct_eval_program']\n"
                "    study['runtime'] = dict(study.get('runtime', {}))\n"
                "    study['runtime']['study_iteration'] = context['iteration']\n"
                "    return study\n\n"
                "def evaluate_study(study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    next_payload = dict(study)\n"
                "    next_payload['run_id'] = f\"{study['run_id']}-next\"\n"
                "    return {\n"
                "        'run_ids': [f\"{study['run_id']}-eval\"],\n"
                "        'promoted_run_ids': [],\n"
                "        'status': 'evaluated',\n"
                "        'objective_score': 9.5,\n"
                "        'failed_gates': [],\n"
                "        'regime_failure_labels': [],\n"
                "        'scenario_failure_names': [],\n"
                "        'memory_summary': {'mode': 'direct_eval'},\n"
                "        'next_payload': next_payload,\n"
                "    }\n\n"
                "def main(argv: list[str] | None = None) -> int:\n"
                "    parser = argparse.ArgumentParser()\n"
                "    parser.add_argument('--emit-study', action='store_true')\n"
                "    parser.add_argument('--emit-eval', action='store_true')\n"
                "    parser.add_argument('--base-study')\n"
                "    parser.add_argument('--context')\n"
                "    parser.add_argument('--output')\n"
                "    args = parser.parse_args(argv)\n"
                "    base_study = json.loads(Path(args.base_study).read_text(encoding='utf-8')) if args.base_study else {}\n"
                "    context = json.loads(Path(args.context).read_text(encoding='utf-8')) if args.context else {}\n"
                "    study = build_study(base_study, context)\n"
                "    if args.emit_study:\n"
                "        Path(args.output).write_text(json.dumps(study, indent=2, sort_keys=True), encoding='utf-8')\n"
                "        return 0\n"
                "    if args.emit_eval:\n"
                "        result = evaluate_study(base_study, context)\n"
                "        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf-8')\n"
                "        return 0\n"
                "    return 1\n\n"
                "if __name__ == '__main__':\n"
                "    raise SystemExit(main())\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-main-direct-eval",
                    "runtime": {"mode": "builtin"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["iteration_count"], 1)
            self.assertEqual(report["completed_run_ids"], ["phase5-karpathy-python-main-direct-eval-study-eval"])
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["iteration_results"][0]["status"], "evaluated")
            self.assertEqual(persisted["iteration_results"][0]["objective_score"], 9.5)
            self.assertEqual(persisted["scratchpad"]["latest_memory_summary"], {"mode": "direct_eval"})
            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-main-direct-eval.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "phase5-karpathy-python-main-direct-eval-study")
            self.assertEqual(materialized_payload["directional_layers"], ["direct_eval_program"])
            self.assertEqual(materialized_payload["runtime"]["study_iteration"], 1)
            self.assertIn("def evaluate_study(", target_path.read_text(encoding="utf-8"))
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_controller_karpathy_python_source_target_supports_import_hook_direct_eval(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-hook-direct-eval")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "def build_study(base_study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    study = dict(base_study)\n"
                "    study['run_id'] = f\"{study['run_id']}-hook-study\"\n"
                "    study['known_good_filters'] = list(study.get('known_good_filters', [])) + ['hook_filter']\n"
                "    study['runtime'] = dict(study.get('runtime', {}))\n"
                "    study['runtime']['hook_iteration'] = context['iteration']\n"
                "    return study\n\n"
                "def evaluate_study(study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    next_payload = dict(study)\n"
                "    next_payload['run_id'] = f\"{study['run_id']}-next\"\n"
                "    return {\n"
                "        'run_ids': [f\"{study['run_id']}-eval\"],\n"
                "        'promoted_run_ids': [f\"{study['run_id']}-eval\"],\n"
                "        'status': 'promoted',\n"
                "        'objective_score': 12.25,\n"
                "        'failed_gates': [],\n"
                "        'regime_failure_labels': [],\n"
                "        'scenario_failure_names': [],\n"
                "        'memory_summary': {'mode': 'hook_direct_eval'},\n"
                "        'next_payload': next_payload,\n"
                "    }\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-hook-direct-eval",
                    "known_good_filters": ["base_filter"],
                    "runtime": {"mode": "builtin"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["iteration_count"], 1)
            self.assertEqual(report["completed_run_ids"], ["phase5-karpathy-python-hook-direct-eval-hook-study-eval"])
            self.assertEqual(report["promoted_run_ids"], ["phase5-karpathy-python-hook-direct-eval-hook-study-eval"])
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["iteration_results"][0]["status"], "promoted")
            self.assertEqual(persisted["iteration_results"][0]["objective_score"], 12.25)
            self.assertEqual(persisted["scratchpad"]["latest_memory_summary"], {"mode": "hook_direct_eval"})
            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-hook-direct-eval.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "phase5-karpathy-python-hook-direct-eval-hook-study")
            self.assertEqual(materialized_payload["known_good_filters"], ["base_filter", "hook_filter"])
            self.assertEqual(materialized_payload["runtime"]["hook_iteration"], 1)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_controller_karpathy_python_source_target_supports_generic_experiment_result(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-generic-experiment")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "def build_study(base_study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    study = dict(base_study)\n"
                "    study['run_id'] = f\"{study['run_id']}-generic-study\"\n"
                "    return study\n\n"
                "def build_experiment_result(study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    return {\n"
                "        'run_id': f\"{study['run_id']}-experiment\",\n"
                "        'metric_name': 'val_bpb',\n"
                "        'metric_value': 0.03125,\n"
                "        'metric_direction': 'minimize',\n"
                "        'status': 'evaluated',\n"
                "        'memory_summary': {'mode': 'generic_experiment'},\n"
                "        'next_payload': {'run_id': f\"{study['run_id']}-next\"},\n"
                "    }\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-python-generic-experiment"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["iteration_count"], 1)
            self.assertEqual(
                report["completed_run_ids"],
                ["phase5-karpathy-python-generic-experiment-generic-study-experiment"],
            )
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["iteration_results"][0]["objective_score"], -0.03125)
            self.assertEqual(persisted["iteration_results"][0]["metric_name"], "val_bpb")
            self.assertEqual(persisted["iteration_results"][0]["metric_value"], 0.03125)
            self.assertEqual(persisted["iteration_results"][0]["metric_direction"], "minimize")
            self.assertEqual(
                persisted["iteration_results"][0]["karpathy_program_result"]["run_id"],
                "phase5-karpathy-python-generic-experiment-generic-study-experiment",
            )
            self.assertEqual(
                persisted["iteration_results"][0]["karpathy_program_result_mode"],
                "hook:build_experiment_result",
            )
            self.assertEqual(persisted["scratchpad"]["latest_memory_summary"], {"mode": "generic_experiment"})
            self.assertEqual(persisted["karpathy_summary"]["metric_name"], "val_bpb")
            self.assertEqual(persisted["karpathy_summary"]["metric_value"], 0.03125)
            self.assertEqual(
                persisted["karpathy_latest_program_result"]["run_id"],
                "phase5-karpathy-python-generic-experiment-generic-study-experiment",
            )
            self.assertEqual(
                persisted["karpathy_latest_program_result_mode"],
                "hook:build_experiment_result",
            )
            self.assertEqual(
                Path(persisted["karpathy_results_tsv_path"]).read_text(encoding="utf-8").splitlines(),
                [
                    "iteration\trun_id\tmetric_name\tmetric_value\tvalidation_status\tdecision\tdescription",
                    "1\tphase5-karpathy-python-generic-experiment-generic-study-experiment\tval_bpb\t0.03125\tevaluated\tkeep\tfirst_scored_run",
                ],
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_controller_karpathy_python_source_target_supports_main_emit_experiment(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-main-experiment")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "import argparse\n"
                "import json\n"
                "from pathlib import Path\n\n"
                "def build_study(base_study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    study = dict(base_study)\n"
                "    study['run_id'] = f\"{study['run_id']}-main-experiment-study\"\n"
                "    return study\n\n"
                "def run_experiment(study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    return {\n"
                "        'run_id': f\"{study['run_id']}-main-experiment\",\n"
                "        'metric_name': 'profit_factor',\n"
                "        'metric_value': 1.8,\n"
                "        'metric_direction': 'maximize',\n"
                "        'status': 'evaluated',\n"
                "    }\n\n"
                "def main(argv: list[str] | None = None) -> int:\n"
                "    parser = argparse.ArgumentParser()\n"
                "    parser.add_argument('--emit-study', action='store_true')\n"
                "    parser.add_argument('--emit-experiment', action='store_true')\n"
                "    parser.add_argument('--base-study')\n"
                "    parser.add_argument('--context')\n"
                "    parser.add_argument('--output')\n"
                "    args = parser.parse_args(argv)\n"
                "    base_study = json.loads(Path(args.base_study).read_text(encoding='utf-8')) if args.base_study else {}\n"
                "    context = json.loads(Path(args.context).read_text(encoding='utf-8')) if args.context else {}\n"
                "    study = build_study(base_study, context)\n"
                "    if args.emit_study:\n"
                "        Path(args.output).write_text(json.dumps(study, indent=2, sort_keys=True), encoding='utf-8')\n"
                "        return 0\n"
                "    if args.emit_experiment:\n"
                "        Path(args.output).write_text(json.dumps(run_experiment(study, context), indent=2, sort_keys=True), encoding='utf-8')\n"
                "        return 0\n"
                "    return 1\n\n"
                "if __name__ == '__main__':\n"
                "    raise SystemExit(main())\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-python-main-experiment"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["completed_run_ids"], ["phase5-karpathy-python-main-experiment-main-experiment-study-main-experiment"])
            self.assertEqual(persisted["iteration_results"][0]["objective_score"], 1.8)
            self.assertEqual(persisted["iteration_results"][0]["metric_name"], "profit_factor")
            self.assertEqual(persisted["iteration_results"][0]["metric_direction"], "maximize")
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_controller_karpathy_python_source_target_supports_research_program_bundle(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-program-bundle")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "def run_research_program(base_study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    study = dict(base_study)\n"
                "    study['run_id'] = f\"{study['run_id']}-program-study\"\n"
                "    study['directional_layers'] = ['program_bundle']\n"
                "    study['runtime'] = dict(study.get('runtime', {}))\n"
                "    study['runtime']['program_iteration'] = context['iteration']\n"
                "    return {\n"
                "        'study': study,\n"
                "        'evaluation': {\n"
                "            'run_ids': [f\"{study['run_id']}-eval\"],\n"
                "            'promoted_run_ids': [],\n"
                "            'status': 'evaluated',\n"
                "            'objective_score': 7.75,\n"
                "            'failed_gates': [],\n"
                "            'regime_failure_labels': [],\n"
                "            'scenario_failure_names': [],\n"
                "            'memory_summary': {'mode': 'program_bundle'},\n"
                "            'next_payload': {'run_id': f\"{study['run_id']}-next\"},\n"
                "        },\n"
                "    }\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={
                    "run_id": "phase5-karpathy-python-program-bundle",
                    "runtime": {"mode": "builtin"},
                },
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["iteration_count"], 1)
            self.assertEqual(report["completed_run_ids"], ["phase5-karpathy-python-program-bundle-program-study-eval"])
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["iteration_results"][0]["status"], "evaluated")
            self.assertEqual(persisted["iteration_results"][0]["objective_score"], 7.75)
            self.assertEqual(persisted["scratchpad"]["latest_memory_summary"], {"mode": "program_bundle"})
            materialized_payload = json.loads(
                (output_dir / "phase5-karpathy-python-program-bundle.karpathy-materialized.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(materialized_payload["run_id"], "phase5-karpathy-python-program-bundle-program-study")
            self.assertEqual(materialized_payload["directional_layers"], ["program_bundle"])
            self.assertEqual(materialized_payload["runtime"]["program_iteration"], 1)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_controller_karpathy_python_source_target_supports_research_program_experiment_without_study(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-program-experiment-only")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "def run_research_program(base_study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    return {\n"
                "        'experiment': {\n"
                "            'run_id': f\"{base_study['run_id']}-program-experiment\",\n"
                "            'metric_name': 'net_pnl',\n"
                "            'metric_value': 42.0,\n"
                "            'metric_direction': 'maximize',\n"
                "            'status': 'evaluated',\n"
                "            'memory_summary': {'mode': 'program_experiment_only'},\n"
                "            'next_payload': {'run_id': f\"{base_study['run_id']}-next\"},\n"
                "        },\n"
                "    }\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-python-program-experiment-only"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                report["completed_run_ids"],
                ["phase5-karpathy-python-program-experiment-only-program-experiment"],
            )
            self.assertEqual(report["karpathy_program_first"], True)
            self.assertEqual(report["karpathy_primary_artifact_kind"], "python_source_target")
            self.assertEqual(report["karpathy_primary_artifact_path"], str(target_path))
            self.assertEqual(persisted["iteration_results"][0]["objective_score"], 42.0)
            self.assertEqual(persisted["iteration_results"][0]["metric_name"], "net_pnl")
            self.assertEqual(persisted["scratchpad"]["latest_memory_summary"], {"mode": "program_experiment_only"})
            self.assertFalse(
                (output_dir / "phase5-karpathy-python-program-experiment-only.karpathy-materialized.json").exists()
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_controller_karpathy_python_source_target_supports_pure_experiment_hook_without_study(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-pure-experiment-hook")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "def build_experiment_result(study: dict[str, object], context: dict[str, object]) -> dict[str, object]:\n"
                "    return {\n"
                "        'run_id': f\"{study['run_id']}-pure-experiment\",\n"
                "        'metric_name': 'calmar_ratio',\n"
                "        'metric_value': 2.5,\n"
                "        'metric_direction': 'maximize',\n"
                "        'status': 'evaluated',\n"
                "        'memory_summary': {'mode': 'pure_experiment_hook'},\n"
                "    }\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-python-pure-experiment-hook"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                report["completed_run_ids"],
                ["phase5-karpathy-python-pure-experiment-hook-pure-experiment"],
            )
            self.assertEqual(report["karpathy_program_first"], True)
            self.assertEqual(report["karpathy_primary_artifact_kind"], "python_source_target")
            self.assertEqual(report["karpathy_primary_artifact_path"], str(target_path))
            self.assertEqual(persisted["iteration_results"][0]["objective_score"], 2.5)
            self.assertEqual(persisted["iteration_results"][0]["metric_name"], "calmar_ratio")
            self.assertEqual(persisted["scratchpad"]["latest_memory_summary"], {"mode": "pure_experiment_hook"})
            self.assertFalse(
                (output_dir / "phase5-karpathy-python-pure-experiment-hook.karpathy-materialized.json").exists()
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_controller_karpathy_python_source_target_supports_pure_main_experiment_without_study(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-python-pure-main-experiment")
        target_path = output_dir / "custom-target.py"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "from __future__ import annotations\n\n"
                "import argparse\n"
                "import json\n"
                "from pathlib import Path\n\n"
                "def main(argv: list[str] | None = None) -> int:\n"
                "    parser = argparse.ArgumentParser()\n"
                "    parser.add_argument('--emit-experiment', action='store_true')\n"
                "    parser.add_argument('--base-study')\n"
                "    parser.add_argument('--context')\n"
                "    parser.add_argument('--output')\n"
                "    args = parser.parse_args(argv)\n"
                "    base_study = json.loads(Path(args.base_study).read_text(encoding='utf-8')) if args.base_study else {}\n"
                "    if not args.emit_experiment:\n"
                "        return 1\n"
                "    Path(args.output).write_text(\n"
                "        json.dumps(\n"
                "            {\n"
                "                'run_id': f\"{base_study['run_id']}-pure-main-experiment\",\n"
                "                'metric_name': 'omega_ratio',\n"
                "                'metric_value': 1.4,\n"
                "                'metric_direction': 'maximize',\n"
                "                'status': 'evaluated',\n"
                "                'memory_summary': {'mode': 'pure_main_experiment'},\n"
                "            },\n"
                "            indent=2,\n"
                "            sort_keys=True,\n"
                "        ),\n"
                "        encoding='utf-8',\n"
                "    )\n"
                "    return 0\n\n"
                "if __name__ == '__main__':\n"
                "    raise SystemExit(main())\n",
                encoding="utf-8",
            )

            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-python-pure-main-experiment"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                report["completed_run_ids"],
                ["phase5-karpathy-python-pure-main-experiment-pure-main-experiment"],
            )
            self.assertEqual(report["karpathy_program_first"], True)
            self.assertEqual(report["karpathy_primary_artifact_kind"], "python_source_target")
            self.assertEqual(report["karpathy_primary_artifact_path"], str(target_path))
            self.assertEqual(persisted["iteration_results"][0]["objective_score"], 1.4)
            self.assertEqual(persisted["iteration_results"][0]["metric_name"], "omega_ratio")
            self.assertEqual(
                persisted["karpathy_latest_program_result"]["run_id"],
                "phase5-karpathy-python-pure-main-experiment-pure-main-experiment",
            )
            self.assertEqual(
                persisted["karpathy_latest_program_result_mode"],
                "main:--emit-experiment",
            )
            self.assertEqual(report["karpathy_program_runtime"]["materialization_mode"], "program_first")
            self.assertEqual(report["karpathy_program_runtime"]["source_of_truth"], "python_source_target")
            self.assertEqual(
                report["karpathy_program_runtime"]["contract_inventory"]["evaluation_emit_flag"],
                "--emit-experiment",
            )
            self.assertEqual(report["karpathy_program_runtime"]["repo_snapshot"]["effective_mode"], "artifact-native")
            self.assertTrue(Path(report["karpathy_program_runtime_artifact_path"]).exists())
            runtime_artifact = json.loads(
                Path(report["karpathy_program_runtime_artifact_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(runtime_artifact["karpathy_program_runtime"]["target_path"], str(target_path))
            self.assertEqual(runtime_artifact["karpathy_program_runtime"]["materialization_mode"], "program_first")
            self.assertEqual(
                persisted["karpathy_program_runtime"]["contract_inventory"]["evaluation_emit_flag"],
                "--emit-experiment",
            )
            self.assertEqual(persisted["scratchpad"]["latest_memory_summary"], {"mode": "pure_main_experiment"})
            self.assertFalse(
                (output_dir / "phase5-karpathy-python-pure-main-experiment.karpathy-materialized.json").exists()
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_controller_karpathy_git_native_request_records_artifact_fallback(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-git-fallback")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    karpathy_execution_mode="git-native",
                    max_iterations=1,
                    run_budget=1,
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
                karpathy_git_probe=lambda workspace_root: {
                    "git_available": False,
                    "workspace_root": str(workspace_root),
                    "branch": None,
                    "head_commit": None,
                    "blocking_reason": "not_a_git_repository",
                },
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-git-fallback"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["karpathy_execution_mode"], "artifact-native")
            self.assertEqual(report["karpathy_git_state"]["requested_mode"], "git-native")
            self.assertEqual(report["karpathy_git_state"]["effective_mode"], "artifact-native")
            self.assertEqual(report["karpathy_git_state"]["blocking_reason"], "not_a_git_repository")
            artifact_path = Path(report["karpathy_git_state_artifact_path"])
            self.assertTrue(artifact_path.exists())
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["settings"]["karpathy_execution_mode"], "git-native")
            self.assertEqual(persisted["karpathy_execution_mode"], "artifact-native")
            self.assertEqual(
                persisted["karpathy_git_state"],
                {
                    "requested_mode": "git-native",
                    "effective_mode": "artifact-native",
                    "git_available": False,
                    "workspace_root": str(output_dir),
                    "branch": None,
                    "head_commit": None,
                    "blocking_reason": "not_a_git_repository",
                },
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_git_native_builds_action_plan_when_git_available(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-git-plan")
        scores = iter([1.0, 1.2, 1.1])
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    karpathy_execution_mode="git-native",
                    karpathy_git_execute_actions=False,
                    max_iterations=3,
                    run_budget=3,
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / f"{ctx['iteration']}.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": next(scores),
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: (
                    {
                        "continue": True,
                        "next_payload": {
                            "run_id": f"proposal-from-{result.run_ids[0]}",
                            "seed_from": result.run_ids[0],
                        },
                    }
                    if ctx["iteration"] < 3
                    else {"continue": False, "stop_reason": "done"}
                ),
                karpathy_git_probe=lambda workspace_root: {
                    "git_available": True,
                    "workspace_root": str(workspace_root),
                    "branch": "main",
                    "head_commit": "abc123",
                    "blocking_reason": None,
                },
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-git-plan"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["karpathy_execution_mode"], "git-native")
            self.assertEqual(report["karpathy_git_action_plan"]["status"], "planned")
            self.assertEqual(report["karpathy_git_action_plan"]["branch_name"], "autoresearch/phase5-karpathy-git-plan")
            self.assertEqual(report["karpathy_git_action_plan"]["base_branch"], "main")
            self.assertEqual(report["karpathy_git_action_plan"]["base_commit"], "abc123")
            self.assertEqual(
                [item["step"] for item in report["karpathy_git_action_plan"]["actions"]],
                [
                    "checkout_branch",
                    "commit_candidate",
                    "commit_candidate",
                    "reset_to_incumbent",
                ],
            )
            self.assertEqual(
                report["karpathy_git_action_plan"]["actions"][2]["target_run_ids"],
                ["run-2"],
            )
            artifact_path = Path(report["karpathy_git_action_plan_artifact_path"])
            self.assertTrue(artifact_path.exists())
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["karpathy_git_action_plan"]["status"], "planned")
            self.assertEqual(
                persisted["karpathy_git_action_plan"]["actions"][1]["commit_message"],
                "autoresearch(phase5-karpathy-git-plan): keep iteration 1",
            )
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_git_native_can_execute_local_git_actions(self) -> None:
        repo_root = Path("test-output-agent-controller-karpathy-git-exec-repo")
        try:
            if repo_root.exists():
                _force_remove_tree(repo_root)
            repo_root.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Codex Test"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "codex-test@example.com"], cwd=repo_root, check=True, capture_output=True, text=True)
            (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "seed"], cwd=repo_root, check=True, capture_output=True, text=True)

            output_dir = repo_root / "out"
            scores = iter([1.0, 1.2, 1.1])
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=3,
                    run_budget=3,
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / f"{ctx['iteration']}.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [f"run-{ctx['iteration']}"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": next(scores),
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: (
                    {
                        "continue": True,
                        "next_payload": {
                            "run_id": f"proposal-from-{result.run_ids[0]}",
                            "seed_from": result.run_ids[0],
                        },
                    }
                    if ctx["iteration"] < 3
                    else {"continue": False, "stop_reason": "done"}
                ),
                workspace_root=repo_root,
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-git-exec"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["karpathy_git_state"]["requested_mode"], "auto")
            self.assertEqual(report["karpathy_execution_mode"], "git-native")
            self.assertEqual(report["karpathy_git_execution"]["status"], "executed")
            self.assertEqual(report["karpathy_git_execution"]["executed_steps"], 4)
            self.assertTrue(Path(report["karpathy_git_execution_artifact_path"]).exists())

            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(branch.stdout.strip(), "autoresearch/phase5-karpathy-git-exec")

            log_output = subprocess.run(
                ["git", "log", "--pretty=%s", "-3"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("autoresearch(phase5-karpathy-git-exec): keep iteration 2", log_output.stdout)
            self.assertIn("autoresearch(phase5-karpathy-git-exec): keep iteration 1", log_output.stdout)

            status_output = subprocess.run(
                ["git", "status", "--short"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(status_output.stdout.strip(), "")
        finally:
            if repo_root.exists():
                _force_remove_tree(repo_root)

    def test_controller_karpathy_git_native_manages_python_source_target_file(self) -> None:
        repo_root = Path("test-output-agent-controller-karpathy-git-python-target-repo")
        try:
            if repo_root.exists():
                _force_remove_tree(repo_root)
            repo_root.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Codex Test"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "codex-test@example.com"], cwd=repo_root, check=True, capture_output=True, text=True)
            (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "seed"], cwd=repo_root, check=True, capture_output=True, text=True)

            output_dir = repo_root / "out"
            target_path = repo_root / "custom-target.py"
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    max_iterations=1,
                    run_budget=1,
                    karpathy_target_path=str(target_path),
                    karpathy_target_kind="python_source",
                ),
                planner=lambda ctx: {"mode": "single"},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-python-target"],
                    "promoted_run_ids": [],
                    "status": "evaluated",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
                workspace_root=repo_root,
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-git-python-target"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["karpathy_git_execution"]["status"], "executed")
            self.assertIn("custom-target.py", report["karpathy_git_execution"]["managed_paths"])
            show_output = subprocess.run(
                ["git", "show", "--name-only", "--pretty=", "HEAD"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("custom-target.py", show_output.stdout.splitlines())
        finally:
            if repo_root.exists():
                _force_remove_tree(repo_root)

    def test_controller_karpathy_git_native_can_disable_default_local_git_execution(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-git-disabled")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(
                    loop_mode="karpathy",
                    karpathy_execution_mode="git-native",
                    karpathy_git_execute_actions=False,
                    max_iterations=1,
                    run_budget=1,
                ),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / "study.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": ["run-1"],
                    "promoted_run_ids": [],
                    "status": "blocked",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
                karpathy_git_probe=lambda workspace_root: {
                    "git_available": True,
                    "workspace_root": str(workspace_root),
                    "branch": "main",
                    "head_commit": "abc123",
                    "blocking_reason": None,
                },
            )

            report = controller.run(
                initial_payload={"run_id": "phase5-karpathy-git-disabled"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            self.assertEqual(report["karpathy_execution_mode"], "git-native")
            self.assertEqual(report["karpathy_git_execution"]["status"], "not_requested")
            self.assertEqual(report["karpathy_git_execution"]["executed_steps"], 0)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_controller_karpathy_results_tsv_is_namespaced_per_root_run(self) -> None:
        output_dir = Path("test-output-agent-controller-karpathy-results-tsv")
        try:
            controller = AgentLoopController(
                settings=AgentLoopSettings(loop_mode="karpathy", max_iterations=1, run_budget=1),
                planner=lambda ctx: {"mode": "single"},
                materializer=lambda ctx, plan: {"config_paths": [output_dir / f"{ctx['payload']['run_id']}.json"]},
                validator=lambda ctx, materialized: {
                    "run_ids": [f"{ctx['payload']['run_id']}-result"],
                    "promoted_run_ids": [],
                    "status": "evaluated",
                    "objective_score": 1.0,
                    "failed_gates": [],
                    "regime_failure_labels": [],
                    "scenario_failure_names": [],
                },
                memory_updater=lambda ctx, result: {},
                refinement_planner=lambda ctx, result, memory_summary: {"continue": False, "stop_reason": "done"},
            )

            first = controller.run(
                initial_payload={"run_id": "phase5-results-a"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )
            second = controller.run(
                initial_payload={"run_id": "phase5-results-b"},
                output_dir=output_dir,
                db_path=output_dir / "memory.sqlite",
            )

            first_path = Path(first["karpathy_results_tsv_path"])
            second_path = Path(second["karpathy_results_tsv_path"])
            self.assertNotEqual(first_path, second_path)
            self.assertEqual(first_path.name, "phase5-results-a.results.tsv")
            self.assertEqual(second_path.name, "phase5-results-b.results.tsv")
            self.assertIn("phase5-results-a-result", first_path.read_text(encoding="utf-8"))
            self.assertIn("phase5-results-b-result", second_path.read_text(encoding="utf-8"))
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)
