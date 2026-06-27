import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _write_clean_real_study(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
    payload["run_id"] = "guarded-cycle-real"
    snapshot = payload["snapshot"]
    snapshot["snapshot_id"] = "guarded-cycle-real-snapshot"
    snapshot["quality_flags"] = []
    snapshot["provenance"] = {
        "provider": "binance_perps",
        "fetch_manifest": str(root / "fetch_manifest.json"),
        "source_hash": "sha256:guarded-cycle",
        "field_confidence": {
            "liquidation_notional": "observed_public_forceorder_with_zero_buckets",
        },
    }
    path = root / "study.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _write_short_real_study(root: Path, *, candle_count: int = 2) -> Path:
    path = _write_clean_real_study(root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    snapshot = payload["snapshot"]
    for key, value in list(snapshot.items()):
        if isinstance(value, list) and len(value) == 120:
            snapshot[key] = value[:candle_count]
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _write_hydratable_study(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
    payload["run_id"] = "guarded-cycle-hydrate"
    snapshot = payload["snapshot"]
    for key, value in list(snapshot.items()):
        if isinstance(value, list) and len(value) == 120:
            snapshot[key] = value[:2]
    snapshot["snapshot_id"] = "guarded-cycle-hydrate-snapshot"
    snapshot["symbol"] = "BTCUSDT"
    snapshot["venue"] = "binance"
    snapshot["timeframe"] = "1Hour"
    snapshot["quality_flags"] = ["missing_liquidation_notional_count=2"]
    snapshot["liquidation_notional"] = [0.0, 0.0]
    candles = snapshot["candles"]

    candles_path = root / "candles.csv"
    funding_path = root / "funding_rates.csv"
    open_interest_path = root / "open_interest.csv"
    sidecar_path = root / "liquidation_notional.csv"
    candles_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        + "\n".join(
            f"{candle['timestamp']},{candle['open']},{candle['high']},{candle['low']},{candle['close']},{candle['volume']}"
            for candle in candles
        )
        + "\n",
        encoding="utf-8",
    )
    funding_path.write_text(
        "timestamp,funding_rate\n" + "\n".join(f"{candle['timestamp']},0.0" for candle in candles) + "\n",
        encoding="utf-8",
    )
    open_interest_path.write_text(
        "timestamp,open_interest\n" + "\n".join(f"{candle['timestamp']},100.0" for candle in candles) + "\n",
        encoding="utf-8",
    )
    sidecar_path.write_text(
        "timestamp,liquidation_notional\n"
        f"{candles[0]['timestamp']},12.5\n"
        f"{candles[1]['timestamp']},-1.0\n",
        encoding="utf-8",
    )
    snapshot["provenance"] = {
        "provider": "binance_perps",
        "fetch_manifest": str(root / "fetch_manifest.json"),
        "source_hash": "sha256:guarded-cycle-before-hydrate",
        "source_paths": {
            "candles": str(candles_path),
            "funding_rate": str(funding_path),
            "open_interest": str(open_interest_path),
        },
    }
    study_path = root / "study.json"
    study_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return study_path, sidecar_path


class GuardedLoopCycleTests(unittest.TestCase):
    def test_cli_guarded_loop_cycle_blocks_bad_sidecar_without_hydrating(self) -> None:
        root = Path("test-guarded-loop-cycle-bad-sidecar")
        output_dir = root / "out"
        hydrated_path = output_dir / "hydrated-study.json"
        try:
            study_path, sidecar_path = _write_hydratable_study(root)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "guarded-loop-cycle",
                        "--config",
                        str(study_path),
                        "--liquidations",
                        str(sidecar_path),
                        "--hydrated-config",
                        str(hydrated_path),
                        "--output-dir",
                        str(output_dir),
                        "--db",
                        str(root / "memory.sqlite"),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "blocked_sidecar_not_ready")
            self.assertFalse(printed["strategy_improvement_supported"])
            self.assertFalse(hydrated_path.exists())
            self.assertTrue(Path(printed["cycle_report_path"]).exists())
        finally:
            _clean_tree(root)

    def test_cli_guarded_loop_cycle_runs_clean_ready_study_and_writes_evidence(self) -> None:
        root = Path("test-guarded-loop-cycle-clean")
        output_dir = root / "out"
        try:
            study_path = _write_clean_real_study(root)
            fake_report_path = output_dir / "guarded-cycle-real.agent-loop.json"
            fake_report = {
                "run_id": "guarded-cycle-real",
                "status": "completed",
                "mode_runtime": "bounded",
                "loop_mode_requested": "auto",
                "loop_mode": "bounded",
                "loop_mode_selection_reason": "test",
                "stop_reason": "run_budget_exhausted",
                "iteration_count": 1,
                "completed_run_ids": ["guarded-cycle-real"],
                "promoted_run_ids": [],
                "report_path": str(fake_report_path),
                "best_result_summary": {
                    "failed_gates": ["validation_min_trades"],
                    "failure_taxonomy": ["sample_too_small"],
                },
            }

            def _fake_run(*, initial_payload: dict[str, object], output_dir: Path, db_path: Path) -> dict[str, object]:
                output_dir.mkdir(parents=True, exist_ok=True)
                fake_report_path.write_text(json.dumps(fake_report, sort_keys=True), encoding="utf-8")
                return fake_report

            with mock.patch("engine.app.guarded_loop.AgentLoopController") as controller_cls:
                controller_cls.return_value.run.side_effect = _fake_run
                with mock.patch("builtins.print") as print_mock:
                    exit_code = main(
                        [
                            "guarded-loop-cycle",
                            "--config",
                            str(study_path),
                            "--output-dir",
                            str(output_dir),
                            "--db",
                            str(root / "memory.sqlite"),
                            "--iterations",
                            "1",
                            "--run-budget",
                            "1",
                        ]
                    )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "completed")
            self.assertFalse(printed["strategy_improvement_supported"])
            self.assertEqual(printed["strategy_improvement_evidence_status"], "not_evaluated_missing_paper_artifacts")
            self.assertTrue(Path(printed["readiness_report_path"]).exists())
            self.assertTrue(Path(printed["evidence_ledger_path"]).exists())
            self.assertTrue(Path(printed["cycle_report_path"]).exists())
            ledger = json.loads(Path(printed["evidence_ledger_path"]).read_text(encoding="utf-8"))
            self.assertEqual(ledger["run_count"], 1)
            self.assertEqual(ledger["readiness_report_count"], 1)
        finally:
            _clean_tree(root)

    def test_cli_guarded_loop_cycle_reports_observed_bucket_shortfall(self) -> None:
        root = Path("test-guarded-loop-cycle-bucket-shortfall")
        output_dir = root / "out"
        try:
            study_path = _write_short_real_study(root, candle_count=2)

            with mock.patch("engine.app.guarded_loop.AgentLoopController") as controller_cls:
                with mock.patch("builtins.print") as print_mock:
                    exit_code = main(
                        [
                            "guarded-loop-cycle",
                            "--config",
                            str(study_path),
                            "--output-dir",
                            str(output_dir),
                            "--db",
                            str(root / "memory.sqlite"),
                        ]
                    )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "blocked_loop_readiness")
            self.assertEqual(printed["next_actions"][0]["id"], "collect_minimum_observed_buckets")
            self.assertIn("candle_count=2", printed["next_actions"][0]["evidence"])
            self.assertIn("minimum_candle_count=5", printed["next_actions"][0]["evidence"])
            self.assertIn("missing_candle_count=3", printed["next_actions"][0]["evidence"])
            controller_cls.assert_not_called()
        finally:
            _clean_tree(root)

    def test_cli_guarded_loop_cycle_routes_agent_loop_crash_to_next_action(self) -> None:
        root = Path("test-guarded-loop-cycle-crash-action")
        output_dir = root / "out"
        try:
            study_path = _write_clean_real_study(root)
            fake_report_path = output_dir / "guarded-cycle-real.agent-loop.json"
            fake_report = {
                "run_id": "guarded-cycle-real",
                "status": "stopped",
                "stop_reason": "max_iterations_reached",
                "iteration_count": 1,
                "completed_run_ids": ["guarded-cycle-real"],
                "promoted_run_ids": [],
                "report_path": str(fake_report_path),
                "events": [
                    {
                        "event": "iteration_crashed",
                        "details": {"error": "signal_tf_not_allowed"},
                    }
                ],
            }

            def _fake_run(*, initial_payload: dict[str, object], output_dir: Path, db_path: Path) -> dict[str, object]:
                output_dir.mkdir(parents=True, exist_ok=True)
                fake_report_path.write_text(json.dumps(fake_report, sort_keys=True), encoding="utf-8")
                return fake_report

            with mock.patch("engine.app.guarded_loop.AgentLoopController") as controller_cls:
                controller_cls.return_value.run.side_effect = _fake_run
                with mock.patch("builtins.print") as print_mock:
                    exit_code = main(
                        [
                            "guarded-loop-cycle",
                            "--config",
                            str(study_path),
                            "--output-dir",
                            str(output_dir),
                            "--db",
                            str(root / "memory.sqlite"),
                            "--iterations",
                            "1",
                            "--run-budget",
                            "1",
                        ]
                    )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "stopped")
            self.assertEqual(printed["next_actions"][0]["id"], "repair_strategy_timeframe_contract")
            self.assertIn("signal_tf_not_allowed", printed["next_actions"][0]["evidence"])
        finally:
            _clean_tree(root)

    def test_cli_guarded_loop_cycle_blocks_partial_paper_feedback_bundle(self) -> None:
        root = Path("test-guarded-loop-cycle-partial-paper")
        output_dir = root / "out"
        paper_dashboard_path = root / "paper-dashboard.json"
        try:
            study_path = _write_clean_real_study(root)
            paper_dashboard_path.write_text(json.dumps({"status": "completed"}, sort_keys=True), encoding="utf-8")

            with mock.patch("engine.app.guarded_loop.AgentLoopController") as controller_cls:
                with mock.patch("builtins.print") as print_mock:
                    exit_code = main(
                        [
                            "guarded-loop-cycle",
                            "--config",
                            str(study_path),
                            "--output-dir",
                            str(output_dir),
                            "--db",
                            str(root / "memory.sqlite"),
                            "--paper-dashboard",
                            str(paper_dashboard_path),
                        ]
                    )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "blocked_paper_feedback_incomplete")
            self.assertEqual(printed["next_actions"][0]["id"], "supply_complete_valid_paper_feedback_bundle")
            self.assertFalse(printed["strategy_improvement_supported"])
            self.assertIn("paper_postrun_summary", printed["stages"]["paper_feedback_preflight"]["missing_inputs"])
            self.assertIn("paper_calibration_feedback", printed["stages"]["paper_feedback_preflight"]["missing_inputs"])
            controller_cls.assert_not_called()
        finally:
            _clean_tree(root)

    def test_cli_guarded_loop_cycle_blocks_invalid_paper_feedback_bundle(self) -> None:
        root = Path("test-guarded-loop-cycle-invalid-paper")
        output_dir = root / "out"
        paper_dashboard_path = root / "paper-dashboard.json"
        postrun_path = root / "postrun.json"
        calibration_path = root / "calibration.json"
        try:
            study_path = _write_clean_real_study(root)
            paper_dashboard_path.write_text(json.dumps({"status": "completed"}, sort_keys=True), encoding="utf-8")
            postrun_path.write_text("{not-json", encoding="utf-8")
            calibration_path.write_text(json.dumps({"status": "sample_guarded"}, sort_keys=True), encoding="utf-8")

            with mock.patch("engine.app.guarded_loop.AgentLoopController") as controller_cls:
                with mock.patch("builtins.print") as print_mock:
                    exit_code = main(
                        [
                            "guarded-loop-cycle",
                            "--config",
                            str(study_path),
                            "--output-dir",
                            str(output_dir),
                            "--db",
                            str(root / "memory.sqlite"),
                            "--paper-dashboard",
                            str(paper_dashboard_path),
                            "--paper-postrun-summary",
                            str(postrun_path),
                            "--paper-calibration-feedback",
                            str(calibration_path),
                        ]
                    )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "blocked_paper_feedback_incomplete")
            preflight = printed["stages"]["paper_feedback_preflight"]
            self.assertEqual(preflight["missing_inputs"], [])
            self.assertEqual(preflight["invalid_files"][0]["path"], str(postrun_path))
            self.assertIn("JSONDecodeError", preflight["invalid_files"][0]["error"])
            controller_cls.assert_not_called()
        finally:
            _clean_tree(root)


class GuardedLoopRepeatTests(unittest.TestCase):
    def test_cli_guarded_loop_repeat_blocks_unhydratable_initial_config_without_traceback(self) -> None:
        root = Path("test-guarded-loop-repeat-unhydratable-sidecar")
        output_dir = root / "out"
        sidecar_path = root / "liquidation_notional.csv"
        hydrated_path = output_dir / "hydrated-study.json"
        try:
            root.mkdir(parents=True, exist_ok=True)
            sidecar_path.write_text(
                "timestamp,liquidation_notional\n"
                "2024-01-01T00:00:00+00:00,-1.0\n",
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "guarded-loop-repeat",
                        "--config",
                        "examples/minimal_builtin_study.json",
                        "--liquidations",
                        str(sidecar_path),
                        "--hydrated-config",
                        str(hydrated_path),
                        "--output-dir",
                        str(output_dir),
                        "--db",
                        str(root / "memory.sqlite"),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "blocked_sidecar_not_ready")
            self.assertEqual(printed["cycle_count"], 1)
            self.assertFalse(hydrated_path.exists())
            self.assertIn("source_paths.candles", printed["cycles"][0]["sidecar_error"])
        finally:
            _clean_tree(root)

    def test_cli_guarded_loop_repeat_blocks_bad_initial_sidecar_without_hydrating(self) -> None:
        root = Path("test-guarded-loop-repeat-bad-sidecar")
        output_dir = root / "out"
        hydrated_path = output_dir / "hydrated-study.json"
        try:
            study_path, sidecar_path = _write_hydratable_study(root)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "guarded-loop-repeat",
                        "--config",
                        str(study_path),
                        "--liquidations",
                        str(sidecar_path),
                        "--hydrated-config",
                        str(hydrated_path),
                        "--output-dir",
                        str(output_dir),
                        "--db",
                        str(root / "memory.sqlite"),
                        "--max-cycles",
                        "2",
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "blocked_sidecar_not_ready")
            self.assertEqual(printed["cycle_count"], 1)
            self.assertFalse(printed["strategy_improvement_supported"])
            self.assertFalse(hydrated_path.exists())
            self.assertEqual(printed["cycles"][0]["status"], "blocked_sidecar_not_ready")
            self.assertEqual(printed["cycles"][0]["learning_summary"]["run_count"], 0)
            self.assertTrue(Path(printed["repeat_report_path"]).exists())
        finally:
            _clean_tree(root)

    def test_cli_guarded_loop_repeat_blocks_when_scan_has_no_eligible_study(self) -> None:
        root = Path("test-guarded-loop-repeat-no-eligible")
        output_dir = root / "out"
        try:
            _write_hydratable_study(root / "dirty")

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "guarded-loop-repeat",
                        "--study-dir",
                        str(root),
                        "--output-dir",
                        str(output_dir),
                        "--db",
                        str(root / "memory.sqlite"),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "blocked_no_eligible_study")
            self.assertEqual(printed["next_actions"][0]["id"], "collect_minimum_observed_buckets")
            self.assertEqual(printed["cycle_count"], 0)
            self.assertTrue(Path(printed["readiness_scan_path"]).exists())
            self.assertTrue(Path(printed["repeat_report_path"]).exists())
        finally:
            _clean_tree(root)

    def test_cli_guarded_loop_repeat_runs_one_eligible_cycle_and_records_history(self) -> None:
        root = Path("test-guarded-loop-repeat-clean")
        output_dir = root / "out"
        try:
            study_path = _write_clean_real_study(root / "study")

            def _fake_cycle(settings: object) -> dict[str, object]:
                cycle_dir = output_dir / "cycle-001"
                cycle_dir.mkdir(parents=True, exist_ok=True)
                ledger_path = cycle_dir / "loop-evidence-ledger.json"
                cycle_path = cycle_dir / "guarded-loop-cycle.json"
                ledger = {
                    "artifact_type": "loop_evidence_ledger",
                    "run_count": 1,
                    "readiness_report_count": 1,
                    "promoted_run_count": 0,
                    "failed_gate_counts": {},
                    "failure_taxonomy_counts": {},
                    "readiness_blocker_counts": {},
                    "runs": [
                        {
                            "run_id": "guarded-cycle-real",
                            "stop_reason": "run_budget_exhausted",
                            "failed_gates": ["validation_min_trades"],
                            "failure_taxonomy": ["sample_too_small"],
                            "memory_effect": {
                                "prior_runs": 2,
                                "promoted_runs": 1,
                                "blocked_runs": 1,
                            },
                            "next_candidate_path": str(cycle_dir / "missing-next-study.json"),
                            "next_candidate_exists": False,
                        }
                    ],
                }
                ledger_path.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
                payload = {
                    "artifact_type": "guarded_loop_cycle_report",
                    "status": "completed",
                    "config_path": str(study_path),
                    "active_config_path": str(study_path),
                    "cycle_report_path": str(cycle_path),
                    "evidence_ledger_path": str(ledger_path),
                    "strategy_improvement_supported": False,
                    "strategy_improvement_evidence_status": "not_evaluated_missing_paper_artifacts",
                }
                cycle_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
                return payload

            with mock.patch("engine.app.guarded_loop.run_guarded_loop_cycle", side_effect=_fake_cycle):
                with mock.patch("builtins.print") as print_mock:
                    exit_code = main(
                        [
                            "guarded-loop-repeat",
                            "--study-dir",
                            str(root),
                            "--output-dir",
                            str(output_dir),
                            "--db",
                            str(root / "memory.sqlite"),
                            "--max-cycles",
                            "2",
                        ]
                    )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "completed_no_next_candidate")
            self.assertEqual(printed["cycle_count"], 1)
            self.assertFalse(printed["strategy_improvement_supported"])
            self.assertEqual(printed["aggregate_learning_summary"]["run_count"], 1)
            self.assertEqual(printed["aggregate_learning_summary"]["promoted_run_count"], 0)
            self.assertEqual(printed["aggregate_learning_summary"]["stop_reasons"], ["run_budget_exhausted"])
            self.assertEqual(printed["aggregate_learning_summary"]["failed_gate_counts"], {"validation_min_trades": 1})
            self.assertEqual(printed["aggregate_learning_summary"]["failure_taxonomy_counts"], {"sample_too_small": 1})
            self.assertEqual(printed["aggregate_learning_summary"]["next_candidate_count"], 1)
            self.assertEqual(
                printed["aggregate_learning_summary"]["next_candidate_paths"],
                [str(output_dir / "cycle-001" / "missing-next-study.json")],
            )
            self.assertEqual(printed["cycles"][0]["config_path"], str(study_path))
            self.assertEqual(printed["cycles"][0]["learning_summary"]["stop_reasons"], ["run_budget_exhausted"])
            self.assertEqual(printed["cycles"][0]["learning_summary"]["failed_gate_counts"], {"validation_min_trades": 1})
            self.assertEqual(printed["cycles"][0]["learning_summary"]["memory_effects"][0]["prior_runs"], 2)
            self.assertEqual(
                printed["cycles"][0]["learning_summary"]["next_candidates"][0]["path"],
                str(output_dir / "cycle-001" / "missing-next-study.json"),
            )
            self.assertTrue(Path(printed["repeat_report_path"]).exists())
        finally:
            _clean_tree(root)
