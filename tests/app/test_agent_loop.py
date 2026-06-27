import json
import shutil
import subprocess
import unittest
from pathlib import Path

from engine.memory.query import query_run_memory
from engine.reporting.summary import build_dashboard_summary


WORKDIR = Path(__file__).resolve().parents[2]


class AgentLoopCliTests(unittest.TestCase):
    def test_cli_agent_loop_require_readiness_blocks_example_study(self) -> None:
        output_dir = Path("test-output-agent-loop-readiness-block")
        db_path = Path("test-output-agent-loop-readiness-block.sqlite")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--require-loop-readiness",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("loop-readiness preflight blocked", completed.stderr)
            self.assertIn("example_or_fixture_study", completed.stderr)
            self.assertFalse(output_dir.exists())
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()

    def test_cli_agent_loop_readiness_block_can_write_preflight_report(self) -> None:
        output_dir = Path("test-output-agent-loop-readiness-block-report")
        report_path = Path("test-output-agent-loop-readiness-block-report.json")
        db_path = Path("test-output-agent-loop-readiness-block-report.sqlite")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--require-loop-readiness",
                    "--readiness-report-output",
                    str(report_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["eligible"])
            self.assertIn("example_or_fixture_study", report["blockers"])
            self.assertFalse(output_dir.exists())
        finally:
            if report_path.exists():
                report_path.unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()

    def test_cli_agent_loop_readiness_block_can_write_evidence_ledger(self) -> None:
        output_dir = Path("test-output-agent-loop-readiness-block-ledger")
        readiness_path = Path("test-output-agent-loop-readiness-block-ledger-readiness.json")
        ledger_path = Path("test-output-agent-loop-readiness-block-ledger.json")
        db_path = Path("test-output-agent-loop-readiness-block-ledger.sqlite")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--require-loop-readiness",
                    "--readiness-report-output",
                    str(readiness_path),
                    "--evidence-ledger-output",
                    str(ledger_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(completed.returncode, 0)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(ledger["run_count"], 0)
            self.assertEqual(ledger["readiness_report_count"], 1)
            self.assertEqual(ledger["readiness_blocker_counts"]["example_or_fixture_study"], 1)
            self.assertFalse(output_dir.exists())
        finally:
            for path in [readiness_path, ledger_path]:
                if path.exists():
                    path.unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()

    def test_cli_agent_loop_persists_queryable_meta_policy_artifact(self) -> None:
        output_dir = Path("test-output-agent-loop-meta-policy")
        db_path = Path("test-output-agent-loop-meta-policy.sqlite")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-meta-policies",
                    "--db",
                    str(db_path),
                    "--run-id",
                    "example-study",
                    "--format",
                    "json",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            rows = json.loads(query_completed.stdout)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["run_id"], "example-study")
            self.assertEqual(rows[0]["policy_family"], "bandit")
            self.assertEqual(rows[0]["status"], "validated")
            self.assertIn("balanced", rows[0]["action_map"])
            self.assertIn("stop", rows[0]["action_map"])
            self.assertTrue(Path(rows[0]["artifact_path"]).exists())
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_agent_loop_auto_mode_selects_karpathy_for_python_source_target(self) -> None:
        output_dir = Path("test-output-agent-loop-auto-karpathy")
        db_path = Path("test-output-agent-loop-auto-karpathy.sqlite")
        target_path = output_dir / "custom-target.py"
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--karpathy-target-path",
                    str(target_path),
                    "--karpathy-target-kind",
                    "python_source",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["loop_mode_requested"], "auto")
            self.assertEqual(payload["loop_mode"], "karpathy")
            self.assertEqual(payload["loop_mode_selection_reason"], "auto_selected_karpathy_python_source_target")
            self.assertEqual(payload["mode_runtime"]["requested_loop_mode"], "auto")
            self.assertEqual(payload["mode_runtime"]["effective_loop_mode"], "karpathy")
            report = json.loads(Path(payload["agent_loop_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["settings"]["loop_mode"], "auto")
            self.assertEqual(report["settings"]["effective_loop_mode"], "karpathy")
            self.assertEqual(report["scratchpad"]["loop_mode"], "karpathy")
            self.assertEqual(report["events"][0]["event"], "mode_selected")
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_agent_loop_writes_report_and_returns_stop_reason(self) -> None:
        output_dir = Path("test-output-agent-loop")
        db_path = Path("test-output-agent-loop.sqlite")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "stopped")
            self.assertEqual(payload["loop_mode_requested"], "auto")
            self.assertEqual(payload["loop_mode"], "bounded")
            self.assertEqual(payload["loop_mode_selection_reason"], "auto_selected_bounded_standard_study_loop")
            self.assertEqual(payload["mode_runtime"]["requested_loop_mode"], "auto")
            self.assertEqual(payload["mode_runtime"]["effective_loop_mode"], "bounded")
            self.assertEqual(payload["stop_reason"], "max_iterations_reached")
            self.assertEqual(payload["iteration_count"], 1)
            self.assertEqual(payload["completed_run_ids"], ["example-study"])
            self.assertTrue(Path(payload["agent_loop_report_path"]).exists())
            report = json.loads(Path(payload["agent_loop_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["run_id"], "example-study")
            self.assertEqual(report["settings"]["loop_mode"], "auto")
            self.assertEqual(report["settings"]["effective_loop_mode"], "bounded")
            self.assertTrue(report["events"])
            self.assertEqual(report["events"][0]["event"], "mode_selected")
            self.assertEqual(report["events"][-1]["event"], "loop_stopped")
            self.assertIn("timestamp", report["events"][0])
            self.assertIn("role", report["events"][0])
            next_payload = json.loads((output_dir / "example-study.next-study.json").read_text(encoding="utf-8"))
            self.assertIn("agent_loop_metadata", next_payload)
            self.assertEqual(next_payload["agent_loop_metadata"]["loop_id"], "example-study")
            self.assertEqual(next_payload["agent_loop_metadata"]["parent_loop_run_id"], "example-study")
            self.assertEqual(next_payload["agent_loop_metadata"]["completed_run_ids"], ["example-study"])
            self.assertEqual(next_payload["agent_loop_metadata"]["requested_loop_mode"], "auto")
            self.assertEqual(next_payload["agent_loop_metadata"]["effective_loop_mode"], "bounded")
            self.assertEqual(next_payload["agent_loop_metadata"]["stop_reason"], "max_iterations_reached")
            self.assertEqual(
                next_payload["agent_loop_metadata"]["loop_mode_selection_reason"],
                "auto_selected_bounded_standard_study_loop",
            )
            memory_rows = query_run_memory(db_path, run_id="example-study", limit=1)
            self.assertEqual(len(memory_rows), 1)
            self.assertEqual(memory_rows[0]["agent_loop_metadata"]["loop_id"], "example-study")
            self.assertEqual(memory_rows[0]["agent_loop_metadata"]["iteration"], 1)
            self.assertEqual(memory_rows[0]["agent_loop_metadata"]["requested_loop_mode"], "auto")
            self.assertEqual(memory_rows[0]["agent_loop_metadata"]["effective_loop_mode"], "bounded")
            self.assertEqual(memory_rows[0]["agent_loop_metadata"]["stop_reason"], "max_iterations_reached")
            self.assertEqual(
                memory_rows[0]["agent_loop_metadata"]["loop_mode_selection_reason"],
                "auto_selected_bounded_standard_study_loop",
            )
            dashboard_payload = json.loads((output_dir / "example-study.dashboard.json").read_text(encoding="utf-8"))
            self.assertEqual(dashboard_payload["agent_loop_metadata"]["stop_reason"], "max_iterations_reached")
            self.assertIn("failure_taxonomy_counts", dashboard_payload["agent_loop_metadata"])
            self.assertIn("next_hypotheses", dashboard_payload["agent_loop_metadata"])
            self.assertIn("stop=max_iterations_reached", build_dashboard_summary(dashboard_payload))
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_agent_loop_can_write_evidence_ledger(self) -> None:
        output_dir = Path("test-output-agent-loop-evidence-ledger")
        db_path = Path("test-output-agent-loop-evidence-ledger.sqlite")
        ledger_path = output_dir / "loop-evidence-ledger.json"
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--evidence-ledger-output",
                    str(ledger_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout.splitlines()[0])
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["agent_loop_evidence_ledger_path"], str(ledger_path))
            self.assertEqual(ledger["artifact_type"], "loop_evidence_ledger")
            self.assertEqual(ledger["run_count"], 1)
            self.assertEqual(ledger["runs"][0]["run_id"], "example-study")
            self.assertTrue(ledger["runs"][0]["next_candidate_exists"])
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_trace_audit_export_and_ingest_write_controlled_advisory_notes(self) -> None:
        output_dir = Path("test-output-trace-audit-cli")
        report_path = output_dir / "loop.report.json"
        trace_path = output_dir / "trace-audit.json"
        advisory_path = output_dir / "halo-advisory.json"
        notes_path = output_dir / "trace-advisory-notes.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "run_id": "loop-btc",
                        "status": "stopped",
                        "stop_reason": "repeated_holdout_failures",
                        "iteration_count": 1,
                        "events": [
                            {
                                "event": "loop_stopped",
                                "iteration": 1,
                                "run_id": "loop-btc",
                                "order": {"side": "BUY"},
                            }
                        ],
                        "scratchpad": {"failure_taxonomy_counts": {"holdout_failure": 2}},
                    }
                ),
                encoding="utf-8",
            )
            advisory_path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "failure_taxonomy": "holdout_failure",
                                "note": "Keep follow-up search narrow until holdout recovers.",
                                "proposed_code_edit": "raise score",
                            },
                            {
                                "failure_taxonomy": "emit_buy_sell_size",
                                "note": "BUY 10 BTC",
                            },
                        ],
                        "planner_notes": ["Prioritize holdout repair before new variants."],
                        "executor_action": "place_order",
                    }
                ),
                encoding="utf-8",
            )

            export_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "trace-audit-export",
                    "--agent-loop-report",
                    str(report_path),
                    "--output",
                    str(trace_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(export_completed.returncode, 0, msg=export_completed.stderr)
            export_payload = json.loads(export_completed.stdout)
            self.assertEqual(export_payload["artifact_type"], "agent_loop_trace_audit_export")
            self.assertEqual(export_payload["output"], str(trace_path))
            self.assertTrue(trace_path.exists())

            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "trace-audit-ingest",
                    "--advisory-report",
                    str(advisory_path),
                    "--trace-export",
                    str(trace_path),
                    "--output",
                    str(notes_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)
            notes_payload = json.loads(notes_path.read_text(encoding="utf-8"))
            self.assertEqual(notes_payload["artifact_type"], "agent_loop_trace_advisory_notes")
            self.assertEqual(notes_payload["source_loop"]["run_id"], "loop-btc")
            self.assertEqual(notes_payload["controlled_failure_taxonomy_hints"][0]["label"], "holdout_failure")
            self.assertEqual(notes_payload["planner_notes"], ["Prioritize holdout repair before new variants."])
            encoded_notes = json.dumps(notes_payload, sort_keys=True)
            self.assertNotIn("BUY", encoded_notes)
            self.assertNotIn("place_order", encoded_notes)
            self.assertNotIn("emit_buy_sell_size", encoded_notes)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_agent_loop_trace_advisory_notes_reach_followup_hypotheses(self) -> None:
        output_dir = Path("test-output-agent-loop-trace-advisory")
        db_path = Path("test-output-agent-loop-trace-advisory.sqlite")
        notes_path = output_dir / "trace-advisory-notes.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            notes_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "agent_loop_trace_advisory_notes",
                        "controlled_failure_taxonomy_hints": [
                            {"label": "holdout_failure", "note": "Holdout keeps failing."}
                        ],
                        "planner_notes": ["Prioritize holdout repair before wider search."],
                        "executor_action": "place_order",
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--trace-advisory-notes",
                    str(notes_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["trace_advisory_summary"]["failure_taxonomy_hints"], ["holdout_failure"])
            report = json.loads(Path(payload["agent_loop_report_path"]).read_text(encoding="utf-8"))
            self.assertIn("raise_holdout_robustness", report["scratchpad"]["next_hypotheses"])
            self.assertIn(
                "trace_advisory_note:Prioritize holdout repair before wider search.",
                report["scratchpad"]["next_hypotheses"],
            )
            next_payload = json.loads((output_dir / "example-study.next-study.json").read_text(encoding="utf-8"))
            self.assertEqual(
                next_payload["research_hypotheses"]["trace_advisory"]["planner_notes"],
                ["Prioritize holdout repair before wider search."],
            )
            encoded = json.dumps(next_payload, sort_keys=True)
            self.assertNotIn("place_order", encoded)
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_agent_loop_improvement_gate_next_actions_reach_followup_hypotheses(self) -> None:
        output_dir = Path("test-output-agent-loop-improvement-gate")
        db_path = Path("test-output-agent-loop-improvement-gate.sqlite")
        gate_path = output_dir / "loop-improvement-gate.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            gate_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "loop_improvement_gate",
                        "status": "not_supported",
                        "strategy_improvement_supported": False,
                        "next_actions": [
                            {
                                "id": "build_clean_real_study",
                                "action": "Acquire observed liquidation coverage.",
                                "evidence": ["liquidation_notional_not_fully_observed"],
                            },
                            {
                                "id": "paper_risk_block:depth_too_thin",
                                "action": "Investigate paper depth blocks.",
                                "evidence": ["depth_too_thin"],
                            },
                        ],
                        "executor_action": "place_order",
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--improvement-gate",
                    str(gate_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertIn(
                "improvement_gate_action:build_clean_real_study",
                payload["trace_advisory_summary"]["next_hypotheses"],
            )
            report = json.loads(Path(payload["agent_loop_report_path"]).read_text(encoding="utf-8"))
            self.assertIn(
                "improvement_gate_action:build_clean_real_study",
                report["scratchpad"]["next_hypotheses"],
            )
            self.assertIn(
                "improvement_gate_action:paper_risk_block:depth_too_thin",
                report["scratchpad"]["next_hypotheses"],
            )
            next_payload = json.loads((output_dir / "example-study.next-study.json").read_text(encoding="utf-8"))
            self.assertIn(
                "improvement_gate_action:build_clean_real_study",
                next_payload["research_hypotheses"]["next_hypotheses"],
            )
            encoded = json.dumps(next_payload, sort_keys=True)
            self.assertNotIn("place_order", encoded)
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_research_debate_report_is_report_only(self) -> None:
        output_dir = Path("test-output-research-debate-cli")
        candidate_path = output_dir / "candidate.json"
        notes_path = output_dir / "trace-advisory-notes.json"
        debate_path = output_dir / "debate.json"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            candidate_path.write_text(
                json.dumps(
                    {
                        "run_id": "candidate-a",
                        "symbol": "BTCUSDT",
                        "validation_bundle": {"failed_gates": ["final_holdout_excellence"]},
                        "failure_taxonomy": ["holdout_failure"],
                        "trade_action": "BUY",
                    }
                ),
                encoding="utf-8",
            )
            notes_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "agent_loop_trace_advisory_notes",
                        "controlled_failure_taxonomy_hints": [
                            {"label": "stress_failure", "note": "Stress weakness remains."}
                        ],
                        "planner_notes": ["Review stress scenario assumptions."],
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "research-debate-report",
                    "--candidate-report",
                    str(candidate_path),
                    "--trace-advisory-notes",
                    str(notes_path),
                    "--output",
                    str(debate_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(debate_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["artifact_type"], "agent_research_debate_report")
            self.assertFalse(payload["executable_artifact_created"])
            self.assertFalse(payload["provenance"]["tradingagents_direct_use"])
            self.assertEqual(payload["controlled_outputs"]["failure_taxonomy_hints"], ["holdout_failure", "stress_failure"])
            encoded = json.dumps(payload, sort_keys=True)
            self.assertNotIn("BUY", encoded)
            self.assertNotIn("trade_action", encoded)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_agent_loop_accepts_karpathy_mode(self) -> None:
        output_dir = Path("test-output-agent-loop-karpathy")
        db_path = Path("test-output-agent-loop-karpathy.sqlite")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--loop-mode",
                    "karpathy",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["loop_mode"], "karpathy")
            self.assertIn("karpathy_summary", payload)
            self.assertIn("karpathy_incumbent_artifact_path", payload)
            self.assertIn("karpathy_decisions", payload)
            self.assertIn("karpathy_working_config_path", payload)
            self.assertIn("karpathy_target_path", payload)
            self.assertIn("karpathy_target_kind", payload)
            self.assertIn("karpathy_ledger_artifact_path", payload)
            self.assertIn("karpathy_results_tsv_path", payload)
            report = json.loads(Path(payload["agent_loop_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["settings"]["loop_mode"], "karpathy")
            self.assertEqual(report["settings"]["karpathy_execution_mode"], "auto")
            self.assertEqual(payload["karpathy_execution_mode"], "artifact-native")
            self.assertEqual(report["scratchpad"]["loop_mode"], "karpathy")
            self.assertEqual(report["karpathy_summary"]["objective"], "maximize_validation_score")
            self.assertIn(report["karpathy_summary"]["decision"], {"keep", "discard"})
            self.assertTrue(report["karpathy_decisions"])
            self.assertTrue(Path(payload["karpathy_incumbent_artifact_path"]).exists())
            self.assertTrue(Path(payload["karpathy_working_config_path"]).exists())
            self.assertEqual(payload["karpathy_target_path"], payload["karpathy_working_config_path"])
            self.assertEqual(payload["karpathy_target_kind"], "json_config")
            self.assertTrue(Path(payload["karpathy_ledger_artifact_path"]).exists())
            self.assertTrue(Path(payload["karpathy_results_tsv_path"]).exists())
            self.assertEqual(
                Path(payload["karpathy_working_config_path"]).name,
                "example-study.karpathy-working.json",
            )
            self.assertFalse(list(output_dir.glob("*.agent-loop.iteration-*.json")))
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_agent_loop_accepts_custom_karpathy_target_path(self) -> None:
        output_dir = Path("test-output-agent-loop-karpathy-custom-target")
        db_path = Path("test-output-agent-loop-karpathy-custom-target.sqlite")
        target_path = output_dir / "custom-target.json"
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--loop-mode",
                    "karpathy",
                    "--karpathy-target-path",
                    str(target_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["karpathy_target_path"], str(target_path))
            self.assertEqual(payload["karpathy_target_kind"], "json_config")
            self.assertEqual(payload["karpathy_working_config_path"], str(target_path))
            report = json.loads(Path(payload["agent_loop_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["settings"]["karpathy_target_path"], str(target_path))
            self.assertEqual(report["karpathy_target_path"], str(target_path))
            self.assertEqual(report["karpathy_target_kind"], "json_config")
            self.assertTrue(target_path.exists())
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_agent_loop_accepts_python_source_target_kind(self) -> None:
        output_dir = Path("test-output-agent-loop-karpathy-python-target")
        db_path = Path("test-output-agent-loop-karpathy-python-target.sqlite")
        target_path = output_dir / "custom-target.py"
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--loop-mode",
                    "karpathy",
                    "--karpathy-target-path",
                    str(target_path),
                    "--karpathy-target-kind",
                    "python_source",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["karpathy_target_path"], str(target_path))
            self.assertEqual(payload["karpathy_target_kind"], "python_source")
            self.assertEqual(payload["karpathy_working_config_path"], str(target_path))
            self.assertIn("karpathy_latest_program_result", payload)
            self.assertIn("karpathy_latest_program_result_mode", payload)
            self.assertIn("karpathy_program_runtime", payload)
            self.assertIn("karpathy_program_runtime_artifact_path", payload)
            self.assertEqual(payload["karpathy_latest_program_result_mode"], "hook:run_experiment")
            self.assertEqual(payload["karpathy_latest_program_result"]["metric_name"], "objective_score")
            self.assertEqual(payload["karpathy_latest_program_result"]["metric_direction"], "maximize")
            self.assertEqual(payload["karpathy_program_runtime"]["source_of_truth"], "materialized_study")
            self.assertEqual(payload["karpathy_program_runtime"]["contract_inventory"]["supports_emit_study"], True)
            self.assertTrue(Path(payload["karpathy_program_runtime_artifact_path"]).exists())
            source = target_path.read_text(encoding="utf-8")
            self.assertIn("def main(", source)
            self.assertIn("--emit-study", source)
            self.assertIn("--emit-eval", source)
            self.assertIn("--emit-experiment", source)
            self.assertIn("if __name__ == '__main__':", source)
            self.assertIn("def evaluate_study(", source)
            self.assertIn("def run_research_program(", source)
            self.assertIn("def run_experiment(", source)
            self.assertIn("def build_experiment_result(", source)
            self.assertIn("def build_validation_result(", source)
            self.assertIn("def _default_experiment_result(", source)
            self.assertIn("def _experiment_to_validation_result(", source)
            self.assertIn("def _deep_merge_dict(", source)
            self.assertIn("class StrategyPlan:", source)
            self.assertIn("def to_study_patch(", source)
            self.assertIn("def build_strategy_plan(", source)
            self.assertIn("def build_layer_stack(", source)
            self.assertIn("def build_directional_layers(", source)
            self.assertIn("def build_known_good_filters(", source)
            self.assertIn("def build_exit_layers(", source)
            self.assertIn("def build_custom_filters(", source)
            self.assertIn("def build_runtime_settings(", source)
            self.assertIn("def build_scenarios(", source)
            self.assertIn("def finalize_study(", source)
            self.assertIn("class StudyModule:", source)
            self.assertIn("def build_study_module(", source)
            self.assertIn("study_module = build_study_module({}, {})", source)
            self.assertIn("def build_study_patch(", source)
            self.assertIn("def mutate_study(", source)
            self.assertIn("def build_study(", source)
            self.assertIn("def build_payload_patch(", source)
            self.assertIn("def mutate_payload(payload: dict[str, object], context:", source)
            self.assertIn("def build_payload(", source)
            self.assertIn("context: dict[str, object] | None = None", source)
            self.assertIn("evaluation = build_validation_result(study, context)", source)
            self.assertLess(source.index("def run_experiment("), source.index("def evaluate_study("))
            report = json.loads(Path(payload["agent_loop_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["settings"]["karpathy_target_kind"], "python_source")
            self.assertEqual(report["karpathy_target_kind"], "python_source")
            self.assertEqual(report["karpathy_program_runtime"]["source_of_truth"], "materialized_study")
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_agent_loop_reports_git_native_fallback_for_karpathy_mode(self) -> None:
        output_dir = Path("test-output-agent-loop-karpathy-git")
        db_path = Path("test-output-agent-loop-karpathy-git.sqlite")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "agent-loop",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--iterations",
                    "1",
                    "--run-budget",
                    "1",
                    "--loop-mode",
                    "karpathy",
                    "--karpathy-execution",
                    "git-native",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["loop_mode"], "karpathy")
            self.assertEqual(payload["karpathy_execution_mode"], "artifact-native")
            self.assertEqual(payload["karpathy_git_state"]["requested_mode"], "git-native")
            self.assertEqual(payload["karpathy_git_state"]["effective_mode"], "artifact-native")
            self.assertEqual(payload["karpathy_git_state"]["git_available"], False)
            self.assertEqual(payload["karpathy_git_state"]["blocking_reason"], "not_a_git_repository")
            self.assertTrue(Path(payload["karpathy_git_state_artifact_path"]).exists())
            self.assertEqual(payload["karpathy_git_action_plan"]["status"], "blocked")
            self.assertEqual(payload["karpathy_git_action_plan"]["actions"], [])
            self.assertTrue(Path(payload["karpathy_git_action_plan_artifact_path"]).exists())
            self.assertEqual(payload["karpathy_git_execution"]["status"], "blocked")
            self.assertEqual(payload["karpathy_git_execution"]["blocking_reason"], "not_a_git_repository")
            self.assertTrue(Path(payload["karpathy_git_execution_artifact_path"]).exists())
            report = json.loads(Path(payload["agent_loop_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["settings"]["karpathy_execution_mode"], "git-native")
            self.assertEqual(report["settings"]["karpathy_git_execute_actions"], None)
            self.assertEqual(report["karpathy_execution_mode"], "artifact-native")
            self.assertEqual(report["karpathy_git_action_plan"]["blocking_reason"], "not_a_git_repository")
            self.assertEqual(report["karpathy_git_execution"]["status"], "blocked")
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)
