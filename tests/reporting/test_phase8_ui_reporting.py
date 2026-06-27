"""Tests for Phase 8: agent_loop_metadata and research_program_version
across dashboard, summary, compare, and memory pipeline."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
import tempfile

from engine.config.models import PromotionDecision, RunCard
from engine.memory.query import query_run_memory
from engine.memory.store import ingest_artifact_directory, initialize_memory_db
from engine.reporting.compare import compare_dashboard_payloads, format_compare_payload
from engine.reporting.dashboard import build_dashboard_payload
from engine.reporting.listing import render_runcard_listing
from engine.reporting.runcards import save_runcard
from engine.reporting.summary import build_autoresearch_summary, build_batch_summary, build_dashboard_summary


# ─── Shared minimal RunCard fixture ─────────────────────────────────────────

def _minimal_runcard() -> RunCard:
    return RunCard(
        run_id="run-phase8",
        strategy_hash="hash-phase8",
        phase="phase-5",
        split_id="snap:60-20-20",
        seed=7,
        decision=PromotionDecision(decision="promoted", reasons=[]),
        metrics={
            "selection_oos_sharpe": 0.55,
            "selection_oos_net_pnl": 100.0,
            "selection_oos_drawdown": -0.10,
            "scenario_pass_rate": 1.0,
            "accepted_layers": 1.0,
        },
        artifacts={
            "snapshot_id": "snap-01",
            "final_status": "promoted",
            "symbol": "BTCUSDT",
            "venue": "binance",
            "snapshot_quality_status": "clean",
            "snapshot_quality_flag_count": "0",
            "snapshot_quality_flags_json": "[]",
            "runtime_settings_json": "{}",
            "scenario_profiles_json": "{}",
            "stress_liquidity_metrics_json": "{}",
            "regime_scenario_pass_matrix_json": "{}",
            "selected_parameters_json": "{}",
            "parameter_search_json": "{}",
        },
    )


# ─── Dashboard tests ─────────────────────────────────────────────────────────

class TestDashboardAgentLoopMetadata(unittest.TestCase):
    def test_agent_loop_metadata_included_when_provided(self) -> None:
        meta = {"loop_id": "loop-01", "iteration": 3, "stop_reason": "budget"}
        payload = build_dashboard_payload(_minimal_runcard(), agent_loop_metadata=meta)
        self.assertEqual(payload["agent_loop_metadata"], meta)

    def test_agent_loop_metadata_omitted_when_absent(self) -> None:
        payload = build_dashboard_payload(_minimal_runcard())
        self.assertNotIn("agent_loop_metadata", payload)

    def test_agent_loop_metadata_is_a_copy(self) -> None:
        """Mutation of the input dict should not affect the payload."""
        meta: dict[str, object] = {"loop_id": "loop-01", "iteration": 1, "stop_reason": None}
        payload = build_dashboard_payload(_minimal_runcard(), agent_loop_metadata=meta)
        meta["loop_id"] = "mutated"
        self.assertEqual(payload["agent_loop_metadata"]["loop_id"], "loop-01")


class TestDashboardResearchProgramVersion(unittest.TestCase):
    def test_research_program_version_included_when_provided(self) -> None:
        payload = build_dashboard_payload(_minimal_runcard(), research_program_version="v1.2.0")
        self.assertEqual(payload["research_program_version"], "v1.2.0")

    def test_research_program_version_omitted_when_absent(self) -> None:
        payload = build_dashboard_payload(_minimal_runcard())
        self.assertNotIn("research_program_version", payload)


# ─── Summary tests ───────────────────────────────────────────────────────────

class TestSummaryAgentLoopMetadata(unittest.TestCase):
    def test_summary_includes_agent_loop_when_present(self) -> None:
        payload = {
            "run_id": "r1",
            "decision": "promoted",
            "agent_loop_metadata": {
                "loop_id": "loop-01",
                "iteration": 2,
                "stop_reason": "budget",
                "requested_loop_mode": "auto",
                "effective_loop_mode": "bounded",
                "loop_mode_selection_reason": "auto_selected_bounded_standard_study_loop",
                "failure_taxonomy_counts": {"holdout_failure": 2, "stress_failure": 1},
                "next_hypotheses": ["raise_holdout_robustness", "harden_stress_scenarios"],
                "upstream_adaptation_summary": {
                    "linked_resource_count": 2,
                    "blocked_resource_count": 1,
                    "provenance_gap_count": 0,
                    "linked_resources": [
                        {
                            "resource_id": "finrl_crypto",
                            "intended_usage": "adapter_only",
                            "status": "cloned_pinned",
                        },
                        {
                            "resource_id": "openbb",
                            "intended_usage": "reference_only",
                            "status": "blocked_license_review",
                        },
                    ],
                },
            },
        }
        summary = build_dashboard_summary(payload)
        self.assertIn("Agent loop", summary)
        self.assertIn("loop-01", summary)
        self.assertIn("iteration=2", summary)
        self.assertIn("stop=budget", summary)
        self.assertIn("Loop mode: requested=auto | effective=bounded | reason=auto_selected_bounded_standard_study_loop", summary)
        self.assertIn("Loop pressure:", summary)
        self.assertIn("holdout_failure=2", summary)
        self.assertIn("Next actions:", summary)
        self.assertIn("raise_holdout_robustness", summary)
        self.assertIn("Upstream adaptation: linked=2 | blocked=1 | provenance_gaps=0", summary)
        self.assertIn("finrl_crypto(adapter_only, cloned_pinned)", summary)
        self.assertIn("openbb(reference_only, blocked_license_review)", summary)

    def test_summary_omits_agent_loop_when_absent(self) -> None:
        payload = {"run_id": "r1", "decision": "promoted"}
        summary = build_dashboard_summary(payload)
        self.assertNotIn("Agent loop", summary)
        self.assertNotIn("agent_loop", summary)

    def test_summary_includes_program_version_when_present(self) -> None:
        payload = {"run_id": "r1", "decision": "promoted", "research_program_version": "v2.0"}
        summary = build_dashboard_summary(payload)
        self.assertIn("Program:", summary)
        self.assertIn("v2.0", summary)

    def test_summary_omits_program_version_when_absent(self) -> None:
        payload = {"run_id": "r1", "decision": "promoted"}
        summary = build_dashboard_summary(payload)
        self.assertNotIn("Program:", summary)

    def test_summary_includes_validation_bundle_headline_fields(self) -> None:
        payload = {
            "run_id": "r1",
            "decision": "promoted",
            "validation_protocol": {
                "status": "failed",
                "deflated_sharpe_ratio": 0.91,
                "probabilistic_sharpe_ratio": 0.88,
                "pbo_score": 0.27,
                "spa_pvalue": 0.12,
                "validation_gate_results": {
                    "deflated_sharpe_ratio": False,
                    "pbo": False,
                    "spa": False,
                    "final_holdout_excellence": True,
                },
            },
        }
        summary = build_dashboard_summary(payload)
        self.assertIn("Validation: failed", summary)
        self.assertIn("Deflated Sharpe Ratio: 0.91", summary)
        self.assertIn("Probabilistic Sharpe Ratio: 0.88", summary)
        self.assertIn("PBO: 0.27", summary)
        self.assertIn("SPA p-value: 0.12", summary)
        self.assertIn("Failed gates: deflated_sharpe_ratio, pbo, spa", summary)

    def test_summary_includes_execution_pressure_when_present(self) -> None:
        payload = {
            "run_id": "r1",
            "decision": "promoted",
            "selection_oos_execution_pressure": {
                "fill_event_count": 2,
                "partial_fill_event_count": 1,
                "average_fill_ratio": 0.72,
                "min_fill_ratio": 0.44,
            },
        }

        summary = build_dashboard_summary(payload)
        self.assertIn("Execution pressure:", summary)
        self.assertIn("partial_fill_event_count=1", summary)
        self.assertIn("average_fill_ratio=0.72", summary)

    def test_summary_includes_phase_candidate_execution_pressure_when_present(self) -> None:
        payload = {
            "run_id": "r2",
            "decision": "promoted",
            "phases": [
                {
                    "phase_name": "phase-2",
                    "layer_name": "kama",
                    "decision": "accept",
                    "accepted": True,
                    "oos_sharpe": 0.31,
                    "selected_parameters": {"aggressiveness": 2},
                    "permutation_count": 4,
                    "search_summary": [
                        {
                            "decision": "accept",
                            "oos_sharpe": 0.31,
                            "parameters": {"aggressiveness": 2},
                            "execution_pressure_summary": {
                                "partial_fill_event_count": 1,
                                "average_fill_ratio": 0.72,
                            },
                        }
                    ],
                }
            ],
        }

        summary = build_dashboard_summary(payload)
        self.assertIn("execution_pressure=average_fill_ratio=0.72, partial_fill_event_count=1", summary)


class TestAutoresearchSummaryLoopFields(unittest.TestCase):
    def test_autoresearch_summary_includes_loop_pressure_and_next_actions_from_memory_summary(self) -> None:
        payload = {
            "run_id": "auto-loop",
            "status": "promoted",
            "memory_summary": {
                "prior_runs": 5,
                "promoted_runs": 3,
                "blocked_runs": 2,
                "excluded_dirty_runs": 1,
                "recovered_duplicate_runs": 2,
                "top_duplicate_matches": [{"run_id": "prior-a", "count": 2}],
                "loop_failure_taxonomy_counts": [
                    {"taxonomy_label": "holdout_failure", "count": 3},
                    {"taxonomy_label": "stress_failure", "count": 1},
                ],
                "next_actions": [
                    {"action": "raise_holdout_robustness", "count": 2},
                    {"action": "harden_stress_scenarios", "count": 1},
                ],
            },
            "hypotheses": [],
        }

        text = build_autoresearch_summary(payload)
        self.assertIn("Loop pressure: holdout_failure(3), stress_failure(1)", text)
        self.assertIn("Top next actions: raise_holdout_robustness(2), harden_stress_scenarios(1)", text)


class TestBatchSummaryLoopFields(unittest.TestCase):
    def test_batch_summary_includes_base_and_variant_loop_pressure_and_next_actions(self) -> None:
        payload = {
            "run_id": "batch-loop",
            "status": "promoted",
            "base_run": {
                "run_id": "batch-loop",
                "status": "promoted",
                "metrics": {"selection_oos_sharpe": 0.4, "selection_oos_drawdown": -0.12},
                "agent_loop_metadata": {
                    "failure_taxonomy_counts": {"holdout_failure": 2},
                    "next_hypotheses": ["raise_holdout_robustness"],
                },
            },
            "preferred_variant": {
                "variant": "balanced",
                "status": "promoted",
                "selection_oos_sharpe": 0.8,
                "agent_loop_metadata": {
                    "failure_taxonomy_counts": {"stress_failure": 2},
                    "next_hypotheses": ["harden_stress_scenarios"],
                },
            },
            "variant_results": [
                {
                    "variant": "balanced",
                    "status": "promoted",
                    "selection_oos_sharpe": 0.8,
                    "scenario_pass_rate": 1.0,
                    "agent_loop_metadata": {
                        "failure_taxonomy_counts": {"stress_failure": 2},
                        "next_hypotheses": ["harden_stress_scenarios"],
                    },
                    "duplicate_baseline_history": {},
                    "compare_to_base": {},
                }
            ],
        }

        text = build_batch_summary(payload)
        self.assertIn("Base loop pressure: holdout_failure=2", text)
        self.assertIn("Base next actions: raise_holdout_robustness", text)
        self.assertIn("Preferred loop pressure: stress_failure=2", text)
        self.assertIn("Preferred next actions: harden_stress_scenarios", text)
        self.assertIn("  Loop pressure: stress_failure=2", text)
        self.assertIn("  Next actions: harden_stress_scenarios", text)


# ─── Compare tests ───────────────────────────────────────────────────────────

class TestCompareAgentLoopChanges(unittest.TestCase):
    def _base(self, run_id: str) -> dict[str, object]:
        return {"run_id": run_id, "decision": "promoted", "metrics": {}, "phases": []}

    def test_compare_includes_agent_loop_changes_when_different(self) -> None:
        left = {**self._base("l"), "agent_loop_metadata": {"loop_id": "A", "iteration": 1}}
        right = {**self._base("r"), "agent_loop_metadata": {"loop_id": "B", "iteration": 2}}
        result = compare_dashboard_payloads(left, right)
        self.assertIn("agent_loop_changes", result)
        self.assertIn("loop_id", result["agent_loop_changes"])

    def test_compare_omits_agent_loop_when_both_absent(self) -> None:
        left = self._base("l")
        right = self._base("r")
        result = compare_dashboard_payloads(left, right)
        self.assertNotIn("agent_loop_changes", result)

    def test_compare_includes_version_change_when_different(self) -> None:
        left = {**self._base("l"), "research_program_version": "v1"}
        right = {**self._base("r"), "research_program_version": "v2"}
        result = compare_dashboard_payloads(left, right)
        self.assertIn("research_program_version_change", result)
        self.assertEqual(result["research_program_version_change"]["left"], "v1")
        self.assertEqual(result["research_program_version_change"]["right"], "v2")

    def test_compare_omits_version_when_identical(self) -> None:
        left = {**self._base("l"), "research_program_version": "v1"}
        right = {**self._base("r"), "research_program_version": "v1"}
        result = compare_dashboard_payloads(left, right)
        self.assertNotIn("research_program_version_change", result)

    def test_format_compare_renders_agent_loop_changes(self) -> None:
        left = {**self._base("l"), "agent_loop_metadata": {"loop_id": "A", "iteration": 1}}
        right = {**self._base("r"), "agent_loop_metadata": {"loop_id": "B", "iteration": 2}}
        result = compare_dashboard_payloads(left, right)
        text = format_compare_payload(result)
        self.assertIn("Agent loop changes:", text)
        self.assertIn("loop_id:", text)

    def test_format_compare_renders_agent_loop_pressure_and_next_actions(self) -> None:
        left = {
            **self._base("l"),
            "agent_loop_metadata": {
                "loop_id": "A",
                "failure_taxonomy_counts": {"holdout_failure": 2},
                "next_hypotheses": ["raise_holdout_robustness"],
            },
        }
        right = {
            **self._base("r"),
            "agent_loop_metadata": {
                "loop_id": "A",
                "failure_taxonomy_counts": {"stress_failure": 3},
                "next_hypotheses": ["harden_stress_scenarios"],
            },
        }
        result = compare_dashboard_payloads(left, right)
        text = format_compare_payload(result)
        self.assertIn("failure_taxonomy_counts:", text)
        self.assertIn("holdout_failure", text)
        self.assertIn("stress_failure", text)
        self.assertIn("next_hypotheses:", text)
        self.assertIn("raise_holdout_robustness", text)
        self.assertIn("harden_stress_scenarios", text)

    def test_format_compare_renders_version_change(self) -> None:
        left = {**self._base("l"), "research_program_version": "v1"}
        right = {**self._base("r"), "research_program_version": "v2"}
        result = compare_dashboard_payloads(left, right)
        text = format_compare_payload(result)
        self.assertIn("Program version:", text)
        self.assertIn("v1", text)
        self.assertIn("v2", text)

    def test_compare_includes_snapshot_provenance_changes_when_different(self) -> None:
        left = {
            **self._base("l"),
            "snapshot_quality": {"status": "clean", "report": {"quality_score": 1.0, "passed": True}},
            "snapshot_provenance": {"build_version": "phase1_snapshot_builder_v1", "source_hash": "abc123"},
        }
        right = {
            **self._base("r"),
            "snapshot_quality": {"status": "dirty", "report": {"quality_score": 0.75, "passed": False}},
            "snapshot_provenance": {"build_version": "phase1_snapshot_builder_v2", "source_hash": "def456"},
        }
        result = compare_dashboard_payloads(left, right)
        self.assertIn("snapshot_quality_change", result)
        self.assertIn("snapshot_provenance_change", result)
        self.assertEqual(
            result["snapshot_provenance_change"]["changed_fields"]["build_version"],
            {"left": "phase1_snapshot_builder_v1", "right": "phase1_snapshot_builder_v2"},
        )

    def test_format_compare_renders_snapshot_provenance_changes(self) -> None:
        left = {
            **self._base("l"),
            "snapshot_quality": {"status": "clean", "report": {"quality_score": 1.0, "passed": True}},
            "snapshot_provenance": {"build_version": "phase1_snapshot_builder_v1", "source_hash": "abc123"},
        }
        right = {
            **self._base("r"),
            "snapshot_quality": {"status": "dirty", "report": {"quality_score": 0.75, "passed": False}},
            "snapshot_provenance": {"build_version": "phase1_snapshot_builder_v2", "source_hash": "def456"},
        }
        result = compare_dashboard_payloads(left, right)
        text = format_compare_payload(result)
        self.assertIn("Snapshot quality:", text)
        self.assertIn("Snapshot provenance changes:", text)
        self.assertIn("build_version:", text)

    def test_compare_includes_validation_bundle_changes_when_different(self) -> None:
        left = {
            **self._base("l"),
            "validation_protocol": {
                "status": "failed",
                "deflated_sharpe_ratio": 0.91,
                "probabilistic_sharpe_ratio": 0.88,
                "pbo_score": 0.27,
                "spa_pvalue": 0.12,
                "validation_gate_results": {
                    "deflated_sharpe_ratio": False,
                    "pbo": False,
                    "spa": False,
                    "final_holdout_excellence": True,
                },
            },
        }
        right = {
            **self._base("r"),
            "validation_protocol": {
                "status": "passed",
                "deflated_sharpe_ratio": 0.95,
                "probabilistic_sharpe_ratio": 0.93,
                "pbo_score": 0.08,
                "spa_pvalue": 0.02,
                "validation_gate_results": {
                    "deflated_sharpe_ratio": True,
                    "pbo": True,
                    "spa": True,
                    "final_holdout_excellence": True,
                },
            },
        }
        result = compare_dashboard_payloads(left, right)
        self.assertIn("validation_bundle_change", result)
        self.assertEqual(result["validation_bundle_left"]["status"], "failed")
        self.assertEqual(result["validation_bundle_left"]["pbo_score"], 0.27)
        self.assertEqual(result["validation_bundle_left"]["spa_pvalue"], 0.12)
        self.assertEqual(result["validation_bundle_left"]["failed_gates"], ["deflated_sharpe_ratio", "pbo", "spa"])
        self.assertEqual(result["validation_bundle_right"]["status"], "passed")
        self.assertEqual(result["validation_bundle_right"]["pbo_score"], 0.08)
        self.assertEqual(result["validation_bundle_right"]["spa_pvalue"], 0.02)
        self.assertEqual(result["validation_bundle_right"]["failed_gates"], [])
        self.assertEqual(
            result["validation_bundle_change"]["changed_fields"]["pbo_score"],
            {"left": 0.27, "right": 0.08},
        )
        self.assertEqual(
            result["validation_bundle_change"]["changed_fields"]["failed_gates"],
            {"left": ["deflated_sharpe_ratio", "pbo", "spa"], "right": []},
        )

    def test_format_compare_renders_validation_bundle_changes(self) -> None:
        left = {
            **self._base("l"),
            "validation_protocol": {
                "status": "failed",
                "deflated_sharpe_ratio": 0.91,
                "probabilistic_sharpe_ratio": 0.88,
                "pbo_score": 0.27,
                "spa_pvalue": 0.12,
                "validation_gate_results": {
                    "deflated_sharpe_ratio": False,
                    "pbo": False,
                    "spa": False,
                    "final_holdout_excellence": True,
                },
            },
        }
        right = {
            **self._base("r"),
            "validation_protocol": {
                "status": "passed",
                "deflated_sharpe_ratio": 0.95,
                "probabilistic_sharpe_ratio": 0.93,
                "pbo_score": 0.08,
                "spa_pvalue": 0.02,
                "validation_gate_results": {
                    "deflated_sharpe_ratio": True,
                    "pbo": True,
                    "spa": True,
                    "final_holdout_excellence": True,
                },
            },
        }
        result = compare_dashboard_payloads(left, right)
        text = format_compare_payload(result)
        self.assertIn("Validation bundle changes:", text)
        self.assertIn("pbo_score:", text)
        self.assertIn("spa_pvalue:", text)
        self.assertIn("failed_gates:", text)
        self.assertIn("deflated_sharpe_ratio, pbo, spa", text)


# ─── Memory store+query tests ────────────────────────────────────────────────

def _make_runcard_with_loop(run_id: str, loop_meta: dict | None = None, version: str = "") -> RunCard:
    rc = _minimal_runcard()
    artifacts = dict(rc.artifacts)
    artifacts["agent_loop_metadata_json"] = json.dumps(loop_meta or {})
    artifacts["research_program_version"] = version
    return RunCard(
        run_id=run_id,
        strategy_hash=rc.strategy_hash,
        phase=rc.phase,
        split_id=rc.split_id,
        seed=rc.seed,
        decision=rc.decision,
        metrics=rc.metrics,
        artifacts=artifacts,
    )


class TestMemoryAgentLoopFields(unittest.TestCase):
    def setUp(self) -> None:
        self._root = Path.cwd() / f"tmp_phase8_memory_{next(tempfile._get_candidate_names())}"
        self._root.mkdir(parents=True, exist_ok=False)
        self._tmp = str(self._root)
        self._db = self._root / "mem.sqlite"
        initialize_memory_db(self._db)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _ingest(self, run_id: str, loop_meta: dict | None = None, version: str = "") -> None:
        rc = _make_runcard_with_loop(run_id, loop_meta, version)
        save_runcard(self._root / f"{run_id}.runcard.json", rc)
        (self._root / f"{run_id}.dashboard.json").write_text(
            json.dumps({"run_id": run_id}), encoding="utf-8"
        )
        ingest_artifact_directory(self._db, self._root)

    def test_agent_loop_metadata_stored_and_retrieved(self) -> None:
        loop_meta = {"loop_id": "lp-1", "iteration": 3, "stop_reason": "budget"}
        self._ingest("run-loop", loop_meta=loop_meta)
        rows = query_run_memory(self._db, run_id="run-loop")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent_loop_metadata"], loop_meta)

    def test_agent_loop_metadata_empty_for_legacy_runs(self) -> None:
        self._ingest("run-legacy")
        rows = query_run_memory(self._db, run_id="run-legacy")
        self.assertEqual(len(rows), 1)
        # Empty dict from stored "{}" or None is acceptable — not an error
        meta = rows[0]["agent_loop_metadata"]
        self.assertIn(meta, ({}, None))

    def test_research_program_version_stored_and_retrieved(self) -> None:
        self._ingest("run-ver", version="v3.1.0")
        rows = query_run_memory(self._db, run_id="run-ver")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["research_program_version"], "v3.1.0")

    def test_research_program_version_none_for_legacy_runs(self) -> None:
        self._ingest("run-no-ver")
        rows = query_run_memory(self._db, run_id="run-no-ver")
        self.assertEqual(len(rows), 1)
        ver = rows[0]["research_program_version"]
        # Empty string stored as "" resolves to None in query
        self.assertIn(ver, (None, ""))


class TestListingAgentLoopFields(unittest.TestCase):
    def test_render_runcard_listing_includes_loop_pressure_and_next_action(self) -> None:
        card = _minimal_runcard()
        artifacts = dict(card.artifacts)
        artifacts["snapshot_build_version"] = "phase1_snapshot_builder_v1"
        artifacts["agent_loop_metadata_json"] = json.dumps(
            {
                "loop_id": "loop-01",
                "failure_taxonomy_counts": {"holdout_failure": 2},
                "next_hypotheses": ["raise_holdout_robustness"],
            },
            sort_keys=True,
        )
        card = RunCard(
            run_id=card.run_id,
            strategy_hash=card.strategy_hash,
            phase=card.phase,
            split_id=card.split_id,
            seed=card.seed,
            decision=card.decision,
            metrics=card.metrics,
            artifacts=artifacts,
        )

        text = render_runcard_listing([card], sort_by="selection_oos_sharpe", fmt="text")
        self.assertIn("loop=holdout_failure=2", text)
        self.assertIn("next=raise_holdout_robustness", text)


if __name__ == "__main__":
    unittest.main()
