import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.app.loop_evidence import build_loop_evidence_ledger


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _write_agent_loop_report(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "study-a.agent-loop.json"
    payload = {
        "run_id": "study-a",
        "status": "stopped",
        "stop_reason": "meta_policy_stop",
        "iteration_count": 1,
        "completed_run_ids": ["study-a"],
        "promoted_run_ids": [],
        "best_result_summary": {
            "objective_score": 42.5,
            "failed_gates": ["capacity_5x", "scenario_pass_matrix"],
            "failure_taxonomy": ["stress_failure"],
            "scenario_failure_names": ["outage-shock"],
        },
        "scratchpad": {
            "latest_memory_summary": {
                "prior_runs": 3,
                "blocked_runs": 2,
                "memory_quality_policy": "clean-only",
                "meta_policy": {"status": "trained"},
            }
        },
    }
    report_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    (root / "study-a.next-study.json").write_text("{}", encoding="utf-8")
    return report_path


def _write_readiness_scan(root: Path) -> Path:
    scan_path = root / "scan.json"
    payload = {
        "artifact_type": "loop_readiness_scan",
        "study_count": 2,
        "eligible_count": 0,
        "blocked_count": 2,
        "blocked_by_reason": {
            "liquidation_notional_not_fully_observed": 1,
            "example_or_fixture_study": 1,
        },
    }
    scan_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return scan_path


def _write_readiness_report(root: Path) -> Path:
    report_path = root / "readiness.json"
    payload = {
        "artifact_type": "loop_readiness_report",
        "eligible": False,
        "run_id": "example-study",
        "config_path": "examples/minimal_builtin_study.json",
        "blockers": ["example_or_fixture_study", "missing_real_source_provenance"],
    }
    report_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return report_path


def _write_paper_dashboard(root: Path) -> Path:
    dashboard_path = root / "paper-dashboard.json"
    payload = {
        "artifact_type": "paper_session_dashboard",
        "status": "completed",
        "orders": {
            "order_count": 6,
            "rejected_count": 1,
            "risk_blocked_count": 1,
            "max_abs_slip_bps": 42.0,
        },
        "pnl": {"telemetry_quality_score": 0.82},
        "risk": {"blocks_by_reason": {"depth_too_thin": 1}},
    }
    dashboard_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return dashboard_path


def _write_paper_postrun_summary(root: Path) -> Path:
    postrun_path = root / "postrun-summary.json"
    payload = {
        "artifact_type": "paper_post_run_summary",
        "status": "actionable",
        "session": {"order_count": 6, "risk_block_count": 2, "status": "completed"},
        "calibration_readiness": {
            "ready_for_model_update": False,
            "guard_reasons": ["insufficient_bucket_sample:BTCUSDT|chop"],
            "sample_count": 5,
        },
        "suggested_next_experiments": ["investigate_depth_too_thin_blocks", "collect_more_paper_samples"],
        "weak_artifacts": [{"artifact_id": "fixture-weak-art", "score": 14.0}],
        "top_failure_reasons": [{"reason_code": "depth_too_thin", "count": 1}],
    }
    postrun_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return postrun_path


def _write_paper_calibration_feedback(root: Path) -> Path:
    calibration_path = root / "calibration-feedback.json"
    payload = {
        "artifact_type": "paper_calibration_feedback",
        "status": "sample_guarded",
        "sample_count": 5,
        "model_update_allowed": False,
        "guard_reasons": ["insufficient_bucket_sample:BTCUSDT|chop"],
        "telemetry_quality": {"score": 0.423333},
    }
    calibration_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return calibration_path


class LoopEvidenceTests(unittest.TestCase):
    def test_build_loop_evidence_ledger_extracts_run_and_readiness_evidence(self) -> None:
        root = Path("test-loop-evidence-ledger")
        try:
            report_path = _write_agent_loop_report(root)
            scan_path = _write_readiness_scan(root)
            readiness_report_path = _write_readiness_report(root)
            paper_dashboard_path = _write_paper_dashboard(root)
            postrun_path = _write_paper_postrun_summary(root)
            calibration_path = _write_paper_calibration_feedback(root)

            ledger = build_loop_evidence_ledger(
                agent_loop_report_paths=[report_path],
                readiness_scan_paths=[scan_path],
                readiness_report_paths=[readiness_report_path],
                paper_dashboard_paths=[paper_dashboard_path],
                paper_postrun_summary_paths=[postrun_path],
                paper_calibration_feedback_paths=[calibration_path],
            )

            self.assertEqual(ledger["artifact_type"], "loop_evidence_ledger")
            self.assertEqual(ledger["run_count"], 1)
            self.assertEqual(ledger["readiness_scan_count"], 1)
            self.assertEqual(ledger["readiness_report_count"], 1)
            self.assertEqual(ledger["paper_feedback"]["dashboard_count"], 1)
            self.assertEqual(ledger["paper_feedback"]["postrun_summary_count"], 1)
            self.assertEqual(ledger["paper_feedback"]["calibration_feedback_count"], 1)
            self.assertEqual(ledger["paper_feedback"]["order_count"], 6)
            self.assertEqual(ledger["paper_feedback"]["risk_blocked_count"], 1)
            self.assertEqual(ledger["paper_feedback"]["rejected_count"], 1)
            self.assertEqual(ledger["paper_feedback"]["max_abs_slip_bps"], 42.0)
            self.assertFalse(ledger["paper_feedback"]["model_update_allowed"])
            self.assertIn("fixture-weak-art", ledger["paper_feedback"]["weak_artifact_ids"])
            self.assertIn("paper_experiment:investigate_depth_too_thin_blocks", ledger["paper_next_hypotheses"])
            self.assertIn("paper_guard:insufficient_bucket_sample:BTCUSDT|chop", ledger["paper_next_hypotheses"])
            self.assertEqual(ledger["promoted_run_count"], 0)
            self.assertEqual(ledger["failed_gate_counts"]["capacity_5x"], 1)
            self.assertEqual(ledger["readiness_blocker_counts"]["liquidation_notional_not_fully_observed"], 1)
            self.assertEqual(ledger["readiness_blocker_counts"]["example_or_fixture_study"], 1)
            run = ledger["runs"][0]
            self.assertEqual(run["run_id"], "study-a")
            self.assertEqual(run["stop_reason"], "meta_policy_stop")
            self.assertEqual(run["memory_effect"]["blocked_runs"], 2)
            self.assertEqual(run["memory_effect"]["meta_policy"]["status"], "trained")
            self.assertIn("failed_gate:capacity_5x", run["next_hypotheses"])
            self.assertEqual(run["next_candidate_path"], str(root / "study-a.next-study.json"))
            self.assertTrue(run["next_candidate_exists"])
        finally:
            _clean_tree(root)

    def test_cli_loop_evidence_ledger_writes_output(self) -> None:
        root = Path("test-loop-evidence-ledger-cli")
        output_path = root / "ledger.json"
        try:
            report_path = _write_agent_loop_report(root)
            scan_path = _write_readiness_scan(root)
            readiness_report_path = _write_readiness_report(root)
            paper_dashboard_path = _write_paper_dashboard(root)
            postrun_path = _write_paper_postrun_summary(root)
            calibration_path = _write_paper_calibration_feedback(root)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "loop-evidence-ledger",
                        "--agent-loop-report",
                        str(report_path),
                        "--readiness-scan",
                        str(scan_path),
                        "--readiness-report",
                        str(readiness_report_path),
                        "--paper-dashboard",
                        str(paper_dashboard_path),
                        "--paper-postrun-summary",
                        str(postrun_path),
                        "--paper-calibration-feedback",
                        str(calibration_path),
                        "--output",
                        str(output_path),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["run_count"], 1)
            self.assertEqual(printed["readiness_report_count"], 1)
            self.assertEqual(printed["paper_feedback"]["dashboard_count"], 1)
            self.assertEqual(written["readiness_blocker_counts"]["example_or_fixture_study"], 1)
            self.assertIn("paper_guard:insufficient_bucket_sample:BTCUSDT|chop", written["paper_next_hypotheses"])
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
