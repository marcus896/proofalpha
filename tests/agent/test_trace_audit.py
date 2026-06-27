from __future__ import annotations

import json
import unittest
from pathlib import Path

from engine.agent.trace_audit import (
    build_controlled_trace_advisory,
    build_trace_audit_export,
    write_trace_advisory_notes,
    write_trace_audit_export,
)


class TraceAuditExportTests(unittest.TestCase):
    def test_build_trace_audit_export_compacts_agent_loop_report_without_trading_authority(self) -> None:
        payload = build_trace_audit_export(
            {
                "run_id": "loop-btc",
                "status": "stopped",
                "stop_reason": "repeated_holdout_failures",
                "iteration_count": 1,
                "completed_run_ids": ["run-1"],
                "promoted_run_ids": [],
                "loop_mode": "bounded",
                "events": [
                    {
                        "event": "study_materialized",
                        "iteration": 1,
                        "run_id": "run-1",
                        "materialized": {"order": {"side": "BUY"}, "large_payload": "drop-me"},
                    }
                ],
                "iteration_results": [
                    {
                        "iteration": 1,
                        "run_ids": ["run-1"],
                        "promoted_run_ids": [],
                        "status": "blocked",
                        "failure_taxonomy": ["holdout_failure"],
                        "meta_policy_selected_action": "conservative",
                    }
                ],
                "scratchpad": {"failure_taxonomy_counts": {"holdout_failure": 2}},
                "karpathy_git_execution": {"executor_action": "commit"},
            },
            source_path="outputs/loop.report.json",
        )

        self.assertEqual(payload["artifact_type"], "agent_loop_trace_audit_export")
        self.assertTrue(payload["research_only"])
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["halo_reference"]["pinned_ref"], "9f3a14197de2e08879f3940f60ee7a828ff22ce6")
        self.assertEqual(payload["source"]["path"], "outputs/loop.report.json")
        self.assertEqual(payload["loop"]["stop_reason"], "repeated_holdout_failures")
        self.assertEqual(payload["events"], [{"event": "study_materialized", "iteration": 1, "run_id": "run-1"}])
        self.assertEqual(payload["iterations"][0]["failure_taxonomy"], ["holdout_failure"])
        encoded = json.dumps(payload, sort_keys=True)
        self.assertNotIn("order", encoded)
        self.assertNotIn("executor_action", encoded)
        self.assertNotIn("emit_buy_sell_size", encoded)
        self.assertTrue(payload["guardrails"]["no_autonomous_code_edits"])
        self.assertTrue(payload["guardrails"]["no_trading_decisions"])

    def test_write_trace_audit_export_round_trips_atomic_json(self) -> None:
        output = Path("outputs") / "test-temp" / "trace-audit-export.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(output.unlink, missing_ok=True)

        written = write_trace_audit_export(output, build_trace_audit_export({"run_id": "loop"}))

        self.assertEqual(written, output)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["loop"]["run_id"], "loop")

    def test_build_controlled_trace_advisory_filters_to_taxonomy_hints_and_planner_notes(self) -> None:
        payload = build_controlled_trace_advisory(
            {
                "findings": [
                    {
                        "failure_taxonomy": "holdout_failure",
                        "note": "Stop promoting configs that keep missing holdout gates.",
                        "proposed_code_edit": "raise objective_score",
                    },
                    {
                        "failure_taxonomy": "emit_buy_sell_size",
                        "note": "BUY 10 BTC",
                        "executor_action": "place_order",
                    },
                ],
                "planner_notes": [
                    "Prefer smaller follow-up search space after repeated holdout failures.",
                    {"unsafe": "ignore"},
                ],
                "trade_action": "BUY",
            },
            trace_export=build_trace_audit_export(
                {
                    "run_id": "loop-btc",
                    "status": "stopped",
                    "stop_reason": "repeated_holdout_failures",
                    "scratchpad": {"failure_taxonomy_counts": {"holdout_failure": 2}},
                }
            ),
        )

        self.assertEqual(payload["artifact_type"], "agent_loop_trace_advisory_notes")
        self.assertTrue(payload["research_only"])
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["source_loop"]["run_id"], "loop-btc")
        self.assertEqual(
            payload["controlled_failure_taxonomy_hints"],
            [
                {
                    "label": "holdout_failure",
                    "note": "Stop promoting configs that keep missing holdout gates.",
                }
            ],
        )
        self.assertEqual(
            payload["planner_notes"],
            ["Prefer smaller follow-up search space after repeated holdout failures."],
        )
        self.assertEqual(
            payload["rejected_fields"],
            ["executor_action", "proposed_code_edit", "trade_action"],
        )
        encoded = json.dumps(payload, sort_keys=True)
        self.assertNotIn("BUY", encoded)
        self.assertNotIn("place_order", encoded)
        self.assertNotIn("emit_buy_sell_size", encoded)
        self.assertTrue(payload["guardrails"]["no_autonomous_code_edits"])
        self.assertTrue(payload["guardrails"]["no_trading_decisions"])

    def test_write_trace_advisory_notes_round_trips_atomic_json(self) -> None:
        output = Path("outputs") / "test-temp" / "trace-advisory-notes.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(output.unlink, missing_ok=True)

        written = write_trace_advisory_notes(
            output,
            build_controlled_trace_advisory({"planner_notes": ["Use narrower stress follow-up."]}),
        )

        self.assertEqual(written, output)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["planner_notes"], ["Use narrower stress follow-up."])


if __name__ == "__main__":
    unittest.main()
