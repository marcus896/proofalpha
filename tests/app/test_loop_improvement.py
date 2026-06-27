import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.app.loop_improvement import build_loop_improvement_gate


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _supporting_artifacts(root: Path) -> tuple[Path, Path, Path, Path]:
    ledger_path = _write_json(
        root / "ledger.json",
        {
            "artifact_type": "loop_evidence_ledger",
            "promoted_run_count": 1,
            "failed_gate_counts": {},
            "readiness_blocker_counts": {},
            "runs": [
                {
                    "run_id": "study-promoted",
                    "promoted_run_ids": ["study-promoted"],
                    "failed_gates": [],
                    "failure_taxonomy": [],
                }
            ],
        },
    )
    dashboard_path = _write_json(
        root / "paper-dashboard.json",
        {
            "artifact_type": "paper_session_dashboard",
            "status": "completed",
            "orders": {
                "order_count": 24,
                "rejected_count": 0,
                "risk_blocked_count": 0,
                "max_abs_slip_bps": 8.0,
            },
            "pnl": {"telemetry_quality_score": 0.91},
            "risk": {"risk_block_count": 0},
        },
    )
    postrun_path = _write_json(
        root / "postrun-summary.json",
        {
            "artifact_type": "paper_post_run_summary",
            "status": "actionable",
            "weak_artifacts": [],
            "calibration_readiness": {
                "ready_for_model_update": True,
                "guard_reasons": [],
                "sample_count": 24,
                "telemetry_quality_score": 0.91,
            },
        },
    )
    calibration_path = _write_json(
        root / "calibration-feedback.json",
        {
            "artifact_type": "paper_calibration_feedback",
            "status": "ready",
            "sample_count": 24,
            "guard_reasons": [],
            "model_update_allowed": True,
            "telemetry_quality": {"score": 0.91},
            "capacity_questions": {
                "mean_edge_erosion_bps": 4.0,
                "max_participation_rate_seen": 0.001,
            },
        },
    )
    return ledger_path, dashboard_path, postrun_path, calibration_path


def _data_sufficiency_artifact(root: Path, *, improvement_ready: bool) -> Path:
    return _write_json(
        root / "data-sufficiency.json",
        {
            "artifact_type": "data_sufficiency_report",
            "profile": "strict_v3",
            "run_ready": True,
            "research_ready": improvement_ready,
            "improvement_ready": improvement_ready,
            "can_claim_strategy_improvement": False,
            "blockers": [] if improvement_ready else ["insufficient_history_for_v3_improvement"],
            "missing_data_requirements": [] if improvement_ready else ["strict_v3_history"],
            "feature_availability": {
                "liquidation_notional": "observed" if improvement_ready else "unavailable",
                "liquidation_dependent_features_allowed": improvement_ready,
            },
        },
    )


class LoopImprovementTests(unittest.TestCase):
    def test_improvement_gate_passes_only_when_loop_and_paper_evidence_support_it(self) -> None:
        root = Path("test-loop-improvement-pass")
        try:
            ledger_path, dashboard_path, postrun_path, calibration_path = _supporting_artifacts(root)
            data_sufficiency_path = _data_sufficiency_artifact(root, improvement_ready=True)

            gate = build_loop_improvement_gate(
                ledger_path=ledger_path,
                paper_dashboard_path=dashboard_path,
                postrun_summary_path=postrun_path,
                calibration_feedback_path=calibration_path,
                data_sufficiency_path=data_sufficiency_path,
            )

            self.assertEqual(gate["status"], "supported")
            self.assertTrue(gate["strategy_improvement_supported"])
            self.assertEqual(gate["missing_evidence"], [])
            self.assertEqual(gate["next_actions"], [])
            self.assertEqual(gate["inputs"]["data_sufficiency"], str(data_sufficiency_path))
        finally:
            _clean_tree(root)

    def test_improvement_gate_requires_strict_data_sufficiency_even_with_good_loop_and_paper(self) -> None:
        root = Path("test-loop-improvement-strict-data")
        try:
            ledger_path, dashboard_path, postrun_path, calibration_path = _supporting_artifacts(root)
            data_sufficiency_path = _data_sufficiency_artifact(root, improvement_ready=False)

            gate = build_loop_improvement_gate(
                ledger_path=ledger_path,
                paper_dashboard_path=dashboard_path,
                postrun_summary_path=postrun_path,
                calibration_feedback_path=calibration_path,
                data_sufficiency_path=data_sufficiency_path,
            )

            self.assertEqual(gate["status"], "not_supported")
            self.assertFalse(gate["strategy_improvement_supported"])
            self.assertIn("strict_data_not_improvement_ready", gate["missing_evidence"])
            self.assertIn("insufficient_history_for_v3_improvement", gate["missing_evidence"])
            self.assertIn("collect_strict_v3_data", [action["id"] for action in gate["next_actions"]])
        finally:
            _clean_tree(root)

    def test_improvement_gate_rejects_missing_data_sufficiency_artifact(self) -> None:
        root = Path("test-loop-improvement-missing-strict-data")
        try:
            ledger_path, dashboard_path, postrun_path, calibration_path = _supporting_artifacts(root)

            gate = build_loop_improvement_gate(
                ledger_path=ledger_path,
                paper_dashboard_path=dashboard_path,
                postrun_summary_path=postrun_path,
                calibration_feedback_path=calibration_path,
            )

            self.assertEqual(gate["status"], "not_supported")
            self.assertFalse(gate["strategy_improvement_supported"])
            self.assertIn("strict_data_not_improvement_ready", gate["missing_evidence"])
        finally:
            _clean_tree(root)

    def test_improvement_gate_rejects_missing_promotion_and_guarded_paper_feedback(self) -> None:
        root = Path("test-loop-improvement-reject")
        try:
            ledger_path = _write_json(
                root / "ledger.json",
                {
                    "artifact_type": "loop_evidence_ledger",
                    "promoted_run_count": 0,
                    "failed_gate_counts": {"capacity_5x": 1},
                    "failure_taxonomy_counts": {"stress_failure": 1},
                    "readiness_blocker_counts": {"example_or_fixture_study": 1},
                    "paper_next_hypotheses": [
                        "paper_experiment:collect_more_paper_samples",
                        "paper_risk_block:depth_too_thin",
                    ],
                    "runs": [],
                },
            )
            dashboard_path = _write_json(
                root / "paper-dashboard.json",
                {
                    "artifact_type": "paper_session_dashboard",
                    "status": "attention",
                    "orders": {
                        "order_count": 6,
                        "rejected_count": 1,
                        "risk_blocked_count": 1,
                        "max_abs_slip_bps": 42.0,
                    },
                    "pnl": {"telemetry_quality_score": 0.82},
                    "risk": {"risk_block_count": 2},
                },
            )
            postrun_path = _write_json(
                root / "postrun-summary.json",
                {
                    "artifact_type": "paper_post_run_summary",
                    "status": "actionable",
                    "weak_artifacts": [{"artifact_id": "weak"}],
                    "calibration_readiness": {
                        "ready_for_model_update": False,
                        "guard_reasons": ["insufficient_bucket_sample:BTCUSDT|chop"],
                        "sample_count": 5,
                    },
                },
            )
            calibration_path = _write_json(
                root / "calibration-feedback.json",
                {
                    "artifact_type": "paper_calibration_feedback",
                    "status": "sample_guarded",
                    "sample_count": 5,
                    "guard_reasons": ["insufficient_bucket_sample:BTCUSDT|chop"],
                    "model_update_allowed": False,
                    "telemetry_quality": {"score": 0.42},
                },
            )

            gate = build_loop_improvement_gate(
                ledger_path=ledger_path,
                paper_dashboard_path=dashboard_path,
                postrun_summary_path=postrun_path,
                calibration_feedback_path=calibration_path,
                data_sufficiency_path=_data_sufficiency_artifact(root, improvement_ready=True),
            )

            self.assertEqual(gate["status"], "not_supported")
            self.assertFalse(gate["strategy_improvement_supported"])
            self.assertIn("no_promoted_run", gate["missing_evidence"])
            self.assertIn("validation_gates_failed", gate["missing_evidence"])
            self.assertIn("readiness_blockers_present", gate["missing_evidence"])
            self.assertIn("paper_dashboard_attention", gate["missing_evidence"])
            self.assertIn("paper_slippage_too_high", gate["missing_evidence"])
            self.assertIn("paper_calibration_guarded", gate["missing_evidence"])
            action_ids = [action["id"] for action in gate["next_actions"]]
            self.assertIn("build_clean_real_study", action_ids)
            self.assertIn("repair_validation_failures", action_ids)
            self.assertIn("route_failure_taxonomy", action_ids)
            self.assertIn("collect_paper_samples", action_ids)
            self.assertIn("investigate_paper_execution", action_ids)
            self.assertIn("paper_experiment:collect_more_paper_samples", action_ids)
            self.assertIn("paper_risk_block:depth_too_thin", action_ids)
        finally:
            _clean_tree(root)

    def test_cli_loop_improvement_gate_writes_json(self) -> None:
        root = Path("test-loop-improvement-cli")
        output_path = root / "gate.json"
        try:
            ledger_path, dashboard_path, postrun_path, calibration_path = _supporting_artifacts(root)
            data_sufficiency_path = _data_sufficiency_artifact(root, improvement_ready=True)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "loop-improvement-gate",
                        "--ledger",
                        str(ledger_path),
                        "--paper-dashboard",
                        str(dashboard_path),
                        "--postrun-summary",
                        str(postrun_path),
                        "--calibration-feedback",
                        str(calibration_path),
                        "--data-sufficiency",
                        str(data_sufficiency_path),
                        "--output",
                        str(output_path),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertTrue(printed["strategy_improvement_supported"])
            self.assertEqual(written["status"], "supported")
            self.assertEqual(written["inputs"]["data_sufficiency"], str(data_sufficiency_path))
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
