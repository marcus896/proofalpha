import csv
import json
import subprocess
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.app.config import load_study_config
from engine.config.models import PromotionDecision, RunCard
from engine.memory.store import ingest_artifact_directory, initialize_memory_db
from engine.reporting.runcards import save_runcard

class StudyConfigTests(unittest.TestCase):
    def test_load_study_config_builds_snapshot_layers_and_evaluations(self) -> None:
        config_path = Path("test-study-config.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "cli-run",
                    "seed": 9,
                    "snapshot": {
                        "snapshot_id": "cli-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": ["flat9"],
                    "custom_filters": [],
                    "exit_layers": [],
                    "evaluations": {
                        "mom_squeeze": {
                            "decision": "accept",
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 120.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                        },
                        "kama": {
                            "decision": "accept",
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 130.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.31, "sortino": 0.41, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 140.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.31, "sortino": 0.41, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 130.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                        },
                        "flat9": {
                            "decision": "accept",
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 140.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.35, "sortino": 0.45, "max_drawdown": -0.08, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 150.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.35, "sortino": 0.45, "max_drawdown": -0.08, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 135.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                        },
                    },
                    "scenarios": [
                        {"name": "attention-burst", "severity": 0.6, "description": "Attention shock"},
                        {"name": "outage-shock", "severity": 0.9, "description": "Outage shock"},
                    ],
                    "scenario_results": {
                        "attention-burst": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 90.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.40, "sortino": 0.50, "max_drawdown": -0.18, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "outage-shock": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 40.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.10, "sortino": 0.20, "max_drawdown": -0.30, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                    },
                    "holdout_decision": {"decision": "accept", "reasons": []},
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        self.assertEqual(study.run_id, "cli-run")
        self.assertEqual(study.snapshot.symbol, "SOLUSDT")
        self.assertEqual(study.directional_layers[0].name, "kama")
        self.assertEqual(study.known_good_filters[0].name, "flat9")
        self.assertEqual(study.evaluations["kama"].oos_result.sharpe, 0.31)
        self.assertEqual(study.scenario_results["outage-shock"].max_drawdown, -0.30)

    def test_load_study_config_supports_builtin_runtime_mode_without_fixtures(self) -> None:
        config_path = Path("test-study-config-builtin.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "builtin-run",
                    "seed": 5,
                    "runtime": {"mode": "builtin", "fail_on_quality_flags": True, "regime_model": "hsmm", "regime_n_states": 5},
                    "snapshot": {
                        "snapshot_id": "builtin-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": ["flat9"],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                    "holdout_decision": {"decision": "accept", "reasons": []},
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        self.assertEqual(study.run_id, "builtin-run")
        self.assertEqual(study.runtime_mode, "builtin")
        self.assertTrue(study.runtime_settings.fail_on_quality_flags)
        self.assertEqual(study.runtime_settings.regime_model, "hsmm")
        self.assertEqual(study.runtime_settings.regime_n_states, 5)
        self.assertEqual(study.evaluations, {})
        self.assertEqual(study.scenario_results, {})

    def test_load_study_config_parses_scenario_specific_knobs(self) -> None:
        config_path = Path("test-scenario-knobs-config.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "scenario-knobs",
                    "seed": 2,
                    "runtime": {"mode": "builtin"},
                    "snapshot": {
                        "snapshot_id": "scenario-knobs-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(12)
                        ],
                        "funding_rates": [0.0] * 12,
                        "open_interest": [100.0] * 12,
                        "liquidation_notional": [0.0] * 12,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [
                        {
                            "name": "liquidity-withdrawal",
                            "severity": 0.8,
                            "description": "stress",
                            "funding_multiplier": 2.0,
                            "liquidity_penalty_bps": 50.0,
                            "latency_delta_bars": 2,
                            "drawdown_multiplier": 1.25,
                            "mark_premium_bps": 80.0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        scenario = study.scenarios[0]
        self.assertEqual(scenario.funding_multiplier, 2.0)
        self.assertEqual(scenario.liquidity_penalty_bps, 50.0)
        self.assertEqual(scenario.latency_delta_bars, 2)
        self.assertEqual(scenario.drawdown_multiplier, 1.25)
        self.assertEqual(scenario.mark_premium_bps, 80.0)


class CliIntegrationTests(unittest.TestCase):
    def test_cli_project_status_renders_text_summary(self) -> None:
        status_dir = Path("test-output-project-status-show")
        status_dir.mkdir(exist_ok=True)
        status_json = status_dir / "PLAN_STATUS.json"
        status_json.write_text(
            json.dumps(
                {
                    "plan_version": "Crypto Stress Research Engine v3 Implementation Plan",
                    "canonical_plan_file": "PLAN.md",
                    "planning_memory_mode": "repo_tracked",
                    "autoresearch_memory_separation": True,
                    "current_execution_state": "not_started",
                    "startup_files": [
                        "PLAN.md",
                        "PLAN_STATUS.json",
                        "AGENTS.md",
                    ],
                    "highest_priority_next_step": {
                        "id": "phase_1_honest_validation_core",
                        "title": "Phase 1: Honest Validation Core",
                        "status": "planned",
                    },
                    "phases": [
                        {
                            "id": "phase_1_honest_validation_core",
                            "title": "Phase 1: Honest Validation Core",
                            "status": "planned",
                            "notes": ["first implementation target"],
                        }
                    ],
                    "deferred_work": [],
                    "resume_order": ["phase_1_honest_validation_core"],
                }
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "project-status",
                    "--status-json",
                    str(status_json),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Implementation plan status", completed.stdout)
            self.assertIn("Canonical plan file: PLAN.md", completed.stdout)
            self.assertIn(f"Status JSON file: {status_json}", completed.stdout)
            self.assertIn(f"Progress ledger: {status_json}", completed.stdout)
            self.assertIn("PLAN_STATUS.json", completed.stdout)
            self.assertIn("Current execution state: not_started", completed.stdout)
            self.assertIn("Highest-priority next step: Phase 1: Honest Validation Core", completed.stdout)
        finally:
            for path in status_dir.glob("*"):
                path.unlink()
            status_dir.rmdir()

    def test_cli_project_status_update_writes_json_only(self) -> None:
        status_dir = Path("test-output-project-status-update")
        status_dir.mkdir(exist_ok=True)
        status_json = status_dir / "PLAN_STATUS.json"
        status_json.write_text(
            json.dumps(
                {
                    "plan_version": "Crypto Stress Research Engine v3 Implementation Plan",
                    "canonical_plan_file": "PLAN.md",
                    "planning_memory_mode": "repo_tracked",
                    "autoresearch_memory_separation": True,
                    "current_execution_state": "not_started",
                    "highest_priority_next_step": {
                        "id": "phase_1_honest_validation_core",
                        "title": "Phase 1: Honest Validation Core",
                        "status": "planned",
                    },
                    "phases": [
                        {
                            "id": "phase_1_honest_validation_core",
                            "title": "Phase 1: Honest Validation Core",
                            "status": "planned",
                            "notes": ["first implementation target"],
                        },
                        {
                            "id": "phase_2_bootstrap_and_regime_upgrade",
                            "title": "Phase 2: Bootstrap and Regime Upgrade",
                            "status": "planned",
                            "notes": ["depends on validation-core rollout shape"],
                        },
                    ],
                    "deferred_work": [],
                    "resume_order": [
                        "phase_1_honest_validation_core",
                        "phase_2_bootstrap_and_regime_upgrade",
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "project-status",
                    "update",
                    "--status-json",
                    str(status_json),
                    "--phase",
                    "phase_1_honest_validation_core",
                    "--status",
                    "in_progress",
                    "--note",
                    "Implementing PSR/DSR validators",
                    "--set-next",
                    "phase_2_bootstrap_and_regime_upgrade",
                    "--execution-state",
                    "active",
                    "--format",
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["current_execution_state"], "active")
            self.assertEqual(payload["highest_priority_next_step"]["id"], "phase_2_bootstrap_and_regime_upgrade")

            saved = json.loads(status_json.read_text(encoding="utf-8"))
            phase = next(item for item in saved["phases"] if item["id"] == "phase_1_honest_validation_core")
            self.assertEqual(phase["status"], "in_progress")
            self.assertIn("Implementing PSR/DSR validators", phase["notes"])
            self.assertEqual(list(status_dir.glob("*.md")), [])
        finally:
            for path in status_dir.glob("*"):
                path.unlink()
            status_dir.rmdir()

    def test_cli_project_status_update_rejects_unknown_phase(self) -> None:
        status_dir = Path("test-output-project-status-invalid")
        status_dir.mkdir(exist_ok=True)
        status_json = status_dir / "PLAN_STATUS.json"
        status_json.write_text(
            json.dumps(
                {
                    "plan_version": "Crypto Stress Research Engine v3 Implementation Plan",
                    "canonical_plan_file": "PLAN.md",
                    "planning_memory_mode": "repo_tracked",
                    "autoresearch_memory_separation": True,
                    "current_execution_state": "not_started",
                    "highest_priority_next_step": {
                        "id": "phase_1_honest_validation_core",
                        "title": "Phase 1: Honest Validation Core",
                        "status": "planned",
                    },
                    "phases": [
                        {
                            "id": "phase_1_honest_validation_core",
                            "title": "Phase 1: Honest Validation Core",
                            "status": "planned",
                            "notes": ["first implementation target"],
                        }
                    ],
                    "deferred_work": [],
                    "resume_order": ["phase_1_honest_validation_core"],
                }
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "project-status",
                    "update",
                    "--status-json",
                    str(status_json),
                    "--phase",
                    "phase_missing",
                    "--status",
                    "done",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("unknown phase id", completed.stderr)
        finally:
            for path in status_dir.glob("*"):
                path.unlink()
            status_dir.rmdir()

    def test_cli_list_runs_sorts_limits_and_formats_text(self) -> None:
        output_dir = Path("test-output-cli-list-runs")
        output_dir.mkdir(exist_ok=True)
        try:
            for run_id, sharpe, pnl in [
                ("run-low", 0.31, 120.0),
                ("run-high", 0.52, 170.0),
                ("run-mid", 0.41, 145.0),
            ]:
                save_runcard(
                    output_dir / f"{run_id}.runcard.json",
                    RunCard(
                        run_id=run_id,
                        strategy_hash=f"{run_id}-hash",
                        phase="phase-5",
                        split_id="snap:60-20-20",
                        seed=7,
                        decision=PromotionDecision(decision="promoted", reasons=[]),
                        metrics={
                            "selection_oos_sharpe": sharpe,
                            "selection_oos_net_pnl": pnl,
                            "selection_oos_drawdown": -0.12,
                            "scenario_pass_rate": 1.0,
                            "accepted_layers": 2.0,
                        },
                        artifacts={
                            "snapshot_id": f"{run_id}-snap",
                            "final_status": "promoted",
                            "symbol": "SOLUSDT",
                            "venue": "binance",
                            "selected_parameters_json": "{}",
                            "parameter_search_json": "{}",
                        },
                    ),
                )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "list-runs",
                    "--dir",
                    str(output_dir),
                    "--sort-by",
                    "selection_oos_sharpe",
                    "--limit",
                    "2",
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Runs ranked by selection_oos_sharpe", completed.stdout)
            self.assertIn("1. run-high", completed.stdout)
            self.assertIn("2. run-mid", completed.stdout)
            self.assertNotIn("run-low", completed.stdout)
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_list_runs_filters_by_decision_and_symbol(self) -> None:
        output_dir = Path("test-output-cli-list-runs-filtered")
        output_dir.mkdir(exist_ok=True)
        try:
            for run_id, decision, symbol, sharpe in [
                ("run-sol-promoted", "promoted", "SOLUSDT", 0.48),
                ("run-btc-promoted", "promoted", "BTCUSDT", 0.61),
                ("run-sol-blocked", "blocked", "SOLUSDT", 0.72),
            ]:
                save_runcard(
                    output_dir / f"{run_id}.runcard.json",
                    RunCard(
                        run_id=run_id,
                        strategy_hash=f"{run_id}-hash",
                        phase="phase-5",
                        split_id="snap:60-20-20",
                        seed=9,
                        decision=PromotionDecision(decision=decision, reasons=[]),
                        metrics={
                            "selection_oos_sharpe": sharpe,
                            "selection_oos_net_pnl": 140.0,
                            "selection_oos_drawdown": -0.12,
                            "scenario_pass_rate": 1.0,
                            "accepted_layers": 2.0,
                        },
                        artifacts={
                            "snapshot_id": f"{run_id}-snap",
                            "final_status": decision,
                            "symbol": symbol,
                            "venue": "binance",
                            "selected_parameters_json": "{}",
                            "parameter_search_json": "{}",
                        },
                    ),
                )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "list-runs",
                    "--dir",
                    str(output_dir),
                    "--decision",
                    "promoted",
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

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("run-sol-promoted", completed.stdout)
            self.assertNotIn("run-btc-promoted", completed.stdout)
            self.assertNotIn("run-sol-blocked", completed.stdout)
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_list_runs_filters_by_snapshot_quality_status(self) -> None:
        output_dir = Path("test-output-cli-list-runs-quality")
        output_dir.mkdir(exist_ok=True)
        try:
            for run_id, quality_status in [
                ("run-clean", "clean"),
                ("run-dirty", "dirty"),
            ]:
                save_runcard(
                    output_dir / f"{run_id}.runcard.json",
                    RunCard(
                        run_id=run_id,
                        strategy_hash=f"{run_id}-hash",
                        phase="phase-5",
                        split_id="snap:60-20-20",
                        seed=5,
                        decision=PromotionDecision(decision="promoted", reasons=[]),
                        metrics={
                            "selection_oos_sharpe": 0.4,
                            "selection_oos_net_pnl": 140.0,
                            "selection_oos_drawdown": -0.12,
                            "scenario_pass_rate": 1.0,
                            "accepted_layers": 2.0,
                        },
                        artifacts={
                            "snapshot_id": f"{run_id}-snap",
                            "final_status": "promoted",
                            "symbol": "SOLUSDT",
                            "venue": "binance",
                            "snapshot_quality_status": quality_status,
                            "snapshot_quality_flag_count": "0" if quality_status == "clean" else "2",
                            "snapshot_quality_flags_json": "[]" if quality_status == "clean" else '["missing_funding_rate_count=4"]',
                            "snapshot_build_version": "phase1_snapshot_builder_v1" if quality_status == "dirty" else "",
                            "selected_parameters_json": "{}",
                            "parameter_search_json": "{}",
                        },
                    ),
                )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "list-runs",
                    "--dir",
                    str(output_dir),
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

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("run-dirty", completed.stdout)
            self.assertNotIn("run-clean", completed.stdout)
            self.assertIn("quality=dirty", completed.stdout)
            self.assertIn("build=phase1_snapshot_builder_v1", completed.stdout)
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_cli_list_runs_skips_malformed_runcards(self) -> None:
        output_dir = Path("test-output-cli-list-runs-malformed")
        output_dir.mkdir(exist_ok=True)
        try:
            save_runcard(
                output_dir / "run-good.runcard.json",
                RunCard(
                    run_id="run-good",
                    strategy_hash="run-good-hash",
                    phase="phase-5",
                    split_id="snap:60-20-20",
                    seed=5,
                    decision=PromotionDecision(decision="promoted", reasons=[]),
                    metrics={
                        "selection_oos_sharpe": 0.4,
                        "selection_oos_net_pnl": 140.0,
                        "selection_oos_drawdown": -0.12,
                        "scenario_pass_rate": 1.0,
                        "accepted_layers": 2.0,
                    },
                    artifacts={
                        "snapshot_id": "run-good-snap",
                        "final_status": "promoted",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "selected_parameters_json": "{}",
                        "parameter_search_json": "{}",
                    },
                ),
            )
            (output_dir / "run-bad.runcard.json").write_text("{not json", encoding="utf-8")

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "list-runs",
                    "--dir",
                    str(output_dir),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("run-good", completed.stdout)
            self.assertIn("skipped malformed runcards: 1", completed.stdout)

            json_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "list-runs",
                    "--dir",
                    str(output_dir),
                    "--format",
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(json_completed.returncode, 0, msg=json_completed.stderr)
            self.assertIsInstance(json.loads(json_completed.stdout), list)
            self.assertIn("Skipped malformed runcards: 1", json_completed.stderr)
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_executes_study_from_json_config(self) -> None:
        config_path = Path("test-study-cli.json")
        output_dir = Path("test-output-cli")
        output_dir.mkdir(exist_ok=True)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "cli-run-2",
                    "seed": 11,
                    "snapshot": {
                        "snapshot_id": "cli-snap-2",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "evaluations": {
                        "mom_squeeze": {
                            "decision": "accept",
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 120.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                        },
                        "kama": {
                            "decision": "accept",
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 130.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.31, "sortino": 0.41, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 140.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.31, "sortino": 0.41, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 130.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                            "selected_parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0},
                            "permutation_count": 4,
                            "search_summary": [
                                {"parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0}, "decision": "accept", "oos_sharpe": 0.31, "bootstrap_worst_drawdown": -0.10, "oos_net_pnl": 140.0},
                                {"parameters": {"aggressiveness": 1, "mean_threshold_offset": 0.08}, "decision": "wash", "oos_sharpe": 0.28, "bootstrap_worst_drawdown": -0.12, "oos_net_pnl": 120.0},
                            ],
                        },
                    },
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                    "scenario_results": {
                        "attention-burst": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 90.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.40, "sortino": 0.50, "max_drawdown": -0.18, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []}
                    },
                    "holdout_decision": {"decision": "accept", "reasons": []},
                }
            ),
            encoding="utf-8",
        )

        try:
            completed = subprocess.run(
                ["python", "-m", "engine.app.cli", "--config", str(config_path), "--output-dir", str(output_dir)],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("cli-run-2", completed.stdout)
            self.assertTrue((output_dir / "cli-run-2.runcard.json").exists())
            self.assertTrue((output_dir / "cli-run-2.dashboard.json").exists())
        finally:
            if config_path.exists():
                config_path.unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_summarize_run_prints_optimizer_trace(self) -> None:
        config_path = Path("test-study-cli-summary.json")
        output_dir = Path("test-output-cli-summary")
        output_dir.mkdir(exist_ok=True)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "cli-run-summary",
                    "seed": 15,
                    "snapshot": {
                        "snapshot_id": "cli-snap-summary",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "evaluations": {
                        "mom_squeeze": {
                            "decision": "accept",
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 120.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                        },
                        "kama": {
                            "decision": "accept",
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 130.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.31, "sortino": 0.41, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 140.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.31, "sortino": 0.41, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 130.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                            "selected_parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0},
                            "permutation_count": 4,
                            "search_summary": [
                                {"parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0}, "decision": "accept", "oos_sharpe": 0.31, "bootstrap_worst_drawdown": -0.10, "oos_net_pnl": 140.0},
                                {"parameters": {"aggressiveness": 1, "mean_threshold_offset": 0.08}, "decision": "wash", "oos_sharpe": 0.28, "bootstrap_worst_drawdown": -0.12, "oos_net_pnl": 120.0},
                            ],
                        },
                    },
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                    "scenario_results": {
                        "attention-burst": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 90.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.40, "sortino": 0.50, "max_drawdown": -0.18, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []}
                    },
                    "holdout_decision": {"decision": "accept", "reasons": []},
                }
            ),
            encoding="utf-8",
        )

        try:
            run_completed = subprocess.run(
                ["python", "-m", "engine.app.cli", "--config", str(config_path), "--output-dir", str(output_dir)],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run_completed.returncode, 0, msg=run_completed.stderr)

            summary_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-run",
                    "--dashboard",
                    str(output_dir / "cli-run-summary.dashboard.json"),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(summary_completed.returncode, 0, msg=summary_completed.stderr)
            self.assertIn("Run cli-run-summary", summary_completed.stdout)
            self.assertIn("Backbone: mom_squeeze", summary_completed.stdout)
            self.assertIn("kama", summary_completed.stdout)
            self.assertIn("permutations=4", summary_completed.stdout)
            self.assertIn("aggressiveness=2", summary_completed.stdout)
            self.assertIn("Scenario profiles:", summary_completed.stdout)
            self.assertIn("attention-burst", summary_completed.stdout)
        finally:
            if config_path.exists():
                config_path.unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_summarize_run_supports_phase_filter_and_top_limit(self) -> None:
        config_path = Path("test-study-cli-summary-filtered.json")
        output_dir = Path("test-output-cli-summary-filtered")
        output_dir.mkdir(exist_ok=True)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "cli-run-summary-filtered",
                    "seed": 16,
                    "snapshot": {
                        "snapshot_id": "cli-snap-summary-filtered",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": ["flat9"],
                    "custom_filters": [],
                    "exit_layers": [],
                    "evaluations": {
                        "mom_squeeze": {
                            "decision": "accept",
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 120.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                        },
                        "kama": {
                            "decision": "accept",
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 130.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.31, "sortino": 0.41, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 140.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.31, "sortino": 0.41, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 130.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                            "selected_parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0},
                            "permutation_count": 4,
                            "search_summary": [
                                {"parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0}, "decision": "accept", "oos_sharpe": 0.31, "bootstrap_worst_drawdown": -0.10, "oos_net_pnl": 140.0},
                                {"parameters": {"aggressiveness": 1, "mean_threshold_offset": 0.08}, "decision": "wash", "oos_sharpe": 0.28, "bootstrap_worst_drawdown": -0.12, "oos_net_pnl": 120.0},
                            ],
                        },
                        "flat9": {
                            "decision": "reject",
                            "reasons": ["oos_sharpe_floor"],
                            "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 110.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.21, "sortino": 0.31, "max_drawdown": -0.11, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 115.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.18, "sortino": 0.28, "max_drawdown": -0.12, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                            "bootstrap": {"sample_count": 32, "median_net_profit": 110.0, "median_max_drawdown": -0.09, "worst_case_net_profit": -12.0, "worst_case_drawdown": -0.13, "pass_rate": 0.7},
                        },
                    },
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                    "scenario_results": {
                        "attention-burst": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 90.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.40, "sortino": 0.50, "max_drawdown": -0.18, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []}
                    },
                    "holdout_decision": {"decision": "accept", "reasons": []},
                }
            ),
            encoding="utf-8",
        )

        try:
            run_completed = subprocess.run(
                ["python", "-m", "engine.app.cli", "--config", str(config_path), "--output-dir", str(output_dir)],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run_completed.returncode, 0, msg=run_completed.stderr)

            summary_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-run",
                    "--dashboard",
                    str(output_dir / "cli-run-summary-filtered.dashboard.json"),
                    "--phase-filter",
                    "all",
                    "--top",
                    "1",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(summary_completed.returncode, 0, msg=summary_completed.stderr)
            self.assertIn("flat9", summary_completed.stdout)
            self.assertIn("decision=reject", summary_completed.stdout)
            self.assertIn("aggressiveness=2", summary_completed.stdout)
            self.assertNotIn("mean_threshold_offset=0.08", summary_completed.stdout)
        finally:
            if config_path.exists():
                config_path.unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_compare_runs_returns_machine_readable_diff(self) -> None:
        left_config_path = Path("test-study-cli-compare-left.json")
        right_config_path = Path("test-study-cli-compare-right.json")
        output_dir = Path("test-output-cli-compare")
        output_dir.mkdir(exist_ok=True)
        start = datetime(2024, 1, 1, tzinfo=UTC)

        def _payload(
            run_id: str,
            kama_sharpe: float,
            kama_net_pnl: float,
            flat9_decision: str,
            *,
            liquidity_penalty_bps: float | None = None,
            latency_delta_bars: int | None = None,
            search_summary_limit: int = 3,
            max_parameter_permutations: int = 64,
        ) -> dict:
            scenario = {"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}
            if liquidity_penalty_bps is not None:
                scenario["liquidity_penalty_bps"] = liquidity_penalty_bps
            if latency_delta_bars is not None:
                scenario["latency_delta_bars"] = latency_delta_bars
            payload = {
                "run_id": run_id,
                "seed": 21,
                "runtime": {
                    "mode": "builtin",
                    "search_summary_limit": search_summary_limit,
                    "max_parameter_permutations": max_parameter_permutations,
                },
                "snapshot": {
                    "snapshot_id": f"{run_id}-snap",
                    "symbol": "SOLUSDT",
                    "venue": "binance",
                    "timeframe": "1h",
                    "candles": [
                        {
                            "timestamp": (start + timedelta(hours=hour)).isoformat(),
                            "open": 100 + hour,
                            "high": 101 + hour,
                            "low": 99 + hour,
                            "close": 100 + hour,
                            "volume": 1000.0,
                        }
                        for hour in range(120)
                    ],
                    "funding_rates": [0.0] * 120,
                    "open_interest": [100.0] * 120,
                    "liquidation_notional": [0.0] * 120,
                    "maker_fee_bps": 2.0,
                    "taker_fee_bps": 5.0,
                    "quality_flags": [],
                },
                "incumbent": {"backbone": "mom_squeeze"},
                "directional_layers": ["kama"],
                "known_good_filters": ["flat9"],
                "custom_filters": [],
                "exit_layers": [],
                "evaluations": {
                    "mom_squeeze": {
                        "decision": "accept",
                        "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "bootstrap": {"sample_count": 32, "median_net_profit": 120.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                    },
                    "kama": {
                        "decision": "accept",
                        "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 130.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": kama_sharpe - 0.02, "sortino": kama_sharpe + 0.08, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": kama_net_pnl, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": kama_sharpe, "sortino": kama_sharpe + 0.10, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "bootstrap": {"sample_count": 32, "median_net_profit": kama_net_pnl - 10.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                        "selected_parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0 if kama_sharpe > 0.31 else 0.08},
                        "permutation_count": 4,
                        "search_summary": [
                            {"parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0 if kama_sharpe > 0.31 else 0.08}, "decision": "accept", "oos_sharpe": kama_sharpe, "bootstrap_worst_drawdown": -0.10, "oos_net_pnl": kama_net_pnl},
                        ],
                    },
                    "flat9": {
                        "decision": flat9_decision,
                        "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 110.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.21, "sortino": 0.31, "max_drawdown": -0.11, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 115.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.18, "sortino": 0.28, "max_drawdown": -0.12, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "bootstrap": {"sample_count": 32, "median_net_profit": 110.0, "median_max_drawdown": -0.09, "worst_case_net_profit": -12.0, "worst_case_drawdown": -0.13, "pass_rate": 0.7},
                    },
                },
                "scenarios": [scenario],
                "scenario_results": {
                    "attention-burst": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 90.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.40, "sortino": 0.50, "max_drawdown": -0.18, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []}
                },
                "holdout_decision": {"decision": "accept", "reasons": []},
            }
            return payload

        left_config_path.write_text(json.dumps(_payload("compare-left", 0.31, 140.0, "reject")), encoding="utf-8")
        right_config_path.write_text(
            json.dumps(
                _payload(
                    "compare-right",
                    0.36,
                    155.0,
                    "accept",
                    liquidity_penalty_bps=45.0,
                    latency_delta_bars=2,
                    search_summary_limit=5,
                    max_parameter_permutations=128,
                )
            ),
            encoding="utf-8",
        )

        try:
            for config_path in (left_config_path, right_config_path):
                run_completed = subprocess.run(
                    ["python", "-m", "engine.app.cli", "--config", str(config_path), "--output-dir", str(output_dir)],
                    cwd=Path(__file__).resolve().parents[2],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(run_completed.returncode, 0, msg=run_completed.stderr)

            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--left",
                    str(output_dir / "compare-left.dashboard.json"),
                    "--right",
                    str(output_dir / "compare-right.dashboard.json"),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            payload = json.loads(compare_completed.stdout)
            self.assertEqual(payload["left_run_id"], "compare-left")
            self.assertEqual(payload["right_run_id"], "compare-right")
            self.assertEqual(payload["decision_change"]["left"], payload["decision_change"]["right"])
            self.assertEqual(
                payload["scenario_profile_changes"]["changed"]["attention-burst"]["changed_fields"]["liquidity_penalty_bps"],
                {"left": 12.0, "right": 45.0},
            )
            self.assertEqual(
                payload["scenario_profile_changes"]["changed"]["attention-burst"]["changed_fields"]["latency_delta_bars"],
                {"left": 0, "right": 2},
            )
            self.assertEqual(
                payload["runtime_settings_changes"]["changed_fields"]["search_summary_limit"],
                {"left": 3, "right": 5},
            )
            self.assertEqual(
                payload["runtime_settings_changes"]["changed_fields"]["max_parameter_permutations"],
                {"left": 64, "right": 128},
            )
        finally:
            for config_path in (left_config_path, right_config_path):
                if config_path.exists():
                    config_path.unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_compare_runs_supports_runcards_and_output_file(self) -> None:
        left_config_path = Path("test-study-cli-compare-runcard-left.json")
        right_config_path = Path("test-study-cli-compare-runcard-right.json")
        output_dir = Path("test-output-cli-compare-runcard")
        compare_output_path = output_dir / "runcard-compare.json"
        output_dir.mkdir(exist_ok=True)
        start = datetime(2024, 1, 1, tzinfo=UTC)

        def _payload(run_id: str, kama_sharpe: float, scenario_pass_rate: float) -> dict:
            return {
                "run_id": run_id,
                "seed": 22,
                "snapshot": {
                    "snapshot_id": f"{run_id}-snap",
                    "symbol": "SOLUSDT",
                    "venue": "binance",
                    "timeframe": "1h",
                    "candles": [
                        {
                            "timestamp": (start + timedelta(hours=hour)).isoformat(),
                            "open": 100 + hour,
                            "high": 101 + hour,
                            "low": 99 + hour,
                            "close": 100 + hour,
                            "volume": 1000.0,
                        }
                        for hour in range(120)
                    ],
                    "funding_rates": [0.0] * 120,
                    "open_interest": [100.0] * 120,
                    "liquidation_notional": [0.0] * 120,
                    "maker_fee_bps": 2.0,
                    "taker_fee_bps": 5.0,
                    "quality_flags": [],
                },
                "incumbent": {"backbone": "mom_squeeze"},
                "directional_layers": ["kama"],
                "known_good_filters": [],
                "custom_filters": [],
                "exit_layers": [],
                "evaluations": {
                    "mom_squeeze": {
                        "decision": "accept",
                        "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "bootstrap": {"sample_count": 32, "median_net_profit": 120.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                    },
                    "kama": {
                        "decision": "accept",
                        "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 130.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": kama_sharpe - 0.02, "sortino": kama_sharpe + 0.08, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 140.0 + (kama_sharpe * 10), "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": kama_sharpe, "sortino": kama_sharpe + 0.10, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "bootstrap": {"sample_count": 32, "median_net_profit": 130.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": scenario_pass_rate},
                        "selected_parameters": {"aggressiveness": 2},
                        "permutation_count": 4,
                        "search_summary": [
                            {"parameters": {"aggressiveness": 2}, "decision": "accept", "oos_sharpe": kama_sharpe, "bootstrap_worst_drawdown": -0.10, "oos_net_pnl": 140.0 + (kama_sharpe * 10)},
                        ],
                    },
                },
                "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                "scenario_results": {
                    "attention-burst": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 90.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.40, "sortino": 0.50, "max_drawdown": -0.18 if scenario_pass_rate > 0.7 else -0.30, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []}
                },
                "holdout_decision": {"decision": "accept", "reasons": []},
            }

        left_config_path.write_text(json.dumps(_payload("compare-runcard-left", 0.31, 0.6)), encoding="utf-8")
        right_config_path.write_text(json.dumps(_payload("compare-runcard-right", 0.35, 1.0)), encoding="utf-8")

        try:
            for config_path in (left_config_path, right_config_path):
                run_completed = subprocess.run(
                    ["python", "-m", "engine.app.cli", "--config", str(config_path), "--output-dir", str(output_dir)],
                    cwd=Path(__file__).resolve().parents[2],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(run_completed.returncode, 0, msg=run_completed.stderr)

            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--kind",
                    "runcard",
                    "--left",
                    str(output_dir / "compare-runcard-left.runcard.json"),
                    "--right",
                    str(output_dir / "compare-runcard-right.runcard.json"),
                    "--output",
                    str(compare_output_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            stdout_payload = json.loads(compare_completed.stdout)
            file_payload = json.loads(compare_output_path.read_text(encoding="utf-8"))
            self.assertEqual(stdout_payload, file_payload)
            self.assertEqual(file_payload["left_run_id"], "compare-runcard-left")
            self.assertAlmostEqual(file_payload["metric_deltas"]["selection_oos_sharpe"], 0.04)
            self.assertAlmostEqual(file_payload["metric_deltas"]["scenario_pass_rate"], 1.0)
            self.assertEqual(file_payload["artifact_changes"]["snapshot_id"]["left"], "compare-runcard-left-snap")
            self.assertIn("kama", file_payload["parameter_layers"])
        finally:
            for config_path in (left_config_path, right_config_path):
                if config_path.exists():
                    config_path.unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_compare_runs_supports_text_format(self) -> None:
        left_config_path = Path("test-study-cli-compare-text-left.json").resolve()
        right_config_path = Path("test-study-cli-compare-text-right.json").resolve()
        output_dir = Path("test-output-cli-compare-text").resolve()
        output_dir.mkdir(exist_ok=True)
        start = datetime(2024, 1, 1, tzinfo=UTC)

        def _payload(
            run_id: str,
            kama_sharpe: float,
            flat9_decision: str,
            *,
            liquidity_penalty_bps: float | None = None,
            latency_delta_bars: int | None = None,
            search_summary_limit: int = 3,
            max_parameter_permutations: int = 64,
        ) -> dict:
            scenario = {"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}
            if liquidity_penalty_bps is not None:
                scenario["liquidity_penalty_bps"] = liquidity_penalty_bps
            if latency_delta_bars is not None:
                scenario["latency_delta_bars"] = latency_delta_bars
            return {
                "run_id": run_id,
                "seed": 31,
                "runtime": {
                    "mode": "builtin",
                    "search_summary_limit": search_summary_limit,
                    "max_parameter_permutations": max_parameter_permutations,
                },
                "snapshot": {
                    "snapshot_id": f"{run_id}-snap",
                    "symbol": "SOLUSDT",
                    "venue": "binance",
                    "timeframe": "1h",
                    "candles": [
                        {
                            "timestamp": (start + timedelta(hours=hour)).isoformat(),
                            "open": 100 + hour,
                            "high": 101 + hour,
                            "low": 99 + hour,
                            "close": 100 + hour,
                            "volume": 1000.0,
                        }
                        for hour in range(120)
                    ],
                    "funding_rates": [0.0] * 120,
                    "open_interest": [100.0] * 120,
                    "liquidation_notional": [0.0] * 120,
                    "maker_fee_bps": 2.0,
                    "taker_fee_bps": 5.0,
                    "quality_flags": [],
                },
                "incumbent": {"backbone": "mom_squeeze"},
                "directional_layers": ["kama"],
                "known_good_filters": ["flat9"],
                "custom_filters": [],
                "exit_layers": [],
                "evaluations": {
                    "mom_squeeze": {
                        "decision": "accept",
                        "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 100.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.20, "sortino": 0.30, "max_drawdown": -0.10, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "bootstrap": {"sample_count": 32, "median_net_profit": 120.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                    },
                    "kama": {
                        "decision": "accept",
                        "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 130.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": kama_sharpe - 0.02, "sortino": kama_sharpe + 0.08, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 140.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": kama_sharpe, "sortino": kama_sharpe + 0.10, "max_drawdown": -0.09, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "bootstrap": {"sample_count": 32, "median_net_profit": 130.0, "median_max_drawdown": -0.08, "worst_case_net_profit": -10.0, "worst_case_drawdown": -0.10, "pass_rate": 0.8},
                        "selected_parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0 if kama_sharpe > 0.31 else 0.08},
                        "permutation_count": 4,
                        "search_summary": [
                            {"parameters": {"aggressiveness": 2, "mean_threshold_offset": 0.0 if kama_sharpe > 0.31 else 0.08}, "decision": "accept", "oos_sharpe": kama_sharpe, "bootstrap_worst_drawdown": -0.10, "oos_net_pnl": 140.0},
                        ],
                    },
                    "flat9": {
                        "decision": flat9_decision,
                        "train": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 110.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.21, "sortino": 0.31, "max_drawdown": -0.11, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "oos": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 115.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.18, "sortino": 0.28, "max_drawdown": -0.12, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []},
                        "bootstrap": {"sample_count": 32, "median_net_profit": 110.0, "median_max_drawdown": -0.09, "worst_case_net_profit": -12.0, "worst_case_drawdown": -0.13, "pass_rate": 0.7},
                    },
                },
                "scenarios": [scenario],
                "scenario_results": {
                    "attention-burst": {"trade_count": 170, "win_rate": 0.46, "gross_pnl": 120.0, "net_pnl": 90.0, "fee_spend": 5.0, "funding_spend": 1.0, "sharpe": 0.40, "sortino": 0.50, "max_drawdown": -0.18, "equity_curve": [0.0, 10.0, -5.0, 20.0], "liquidation_events": []}
                },
                "holdout_decision": {"decision": "accept", "reasons": []},
            }

        left_config_path.write_text(json.dumps(_payload("compare-text-left", 0.31, "reject")), encoding="utf-8")
        right_config_path.write_text(
            json.dumps(
                _payload(
                    "compare-text-right",
                    0.36,
                    "accept",
                    liquidity_penalty_bps=45.0,
                    latency_delta_bars=2,
                    search_summary_limit=5,
                    max_parameter_permutations=128,
                )
            ),
            encoding="utf-8",
        )

        try:
            for config_path in (left_config_path, right_config_path):
                run_completed = subprocess.run(
                    ["python", "-m", "engine.app.cli", "--config", str(config_path), "--output-dir", str(output_dir)],
                    cwd=Path(__file__).resolve().parents[2],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(run_completed.returncode, 0, msg=run_completed.stderr)

            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--left",
                    str((output_dir / "compare-text-left.dashboard.json").resolve()),
                    "--right",
                    str((output_dir / "compare-text-right.dashboard.json").resolve()),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            self.assertIn("Compare compare-text-left -> compare-text-right", compare_completed.stdout)
            self.assertIn("Scenario profile changes:", compare_completed.stdout)
            self.assertIn("attention-burst:", compare_completed.stdout)
            self.assertIn("liquidity_penalty_bps=12.0", compare_completed.stdout)
            self.assertIn("liquidity_penalty_bps=45.0", compare_completed.stdout)
            self.assertIn("latency_delta_bars=2", compare_completed.stdout)
            self.assertIn("Runtime setting changes:", compare_completed.stdout)
            self.assertIn("search_summary_limit: 3 -> 5", compare_completed.stdout)
            self.assertIn(
                "max_parameter_permutations: 64 -> 128",
                compare_completed.stdout,
            )
        finally:
            for config_path in (left_config_path, right_config_path):
                if config_path.exists():
                    config_path.unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_cli_compare_runs_text_surfaces_validation_bundle_drift(self) -> None:
        left_dashboard_path = Path("test-compare-validation-left.dashboard.json").resolve()
        right_dashboard_path = Path("test-compare-validation-right.dashboard.json").resolve()
        left_dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "compare-validation-left",
                    "decision": "blocked",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "compare-validation-right",
                    "decision": "promoted",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--left",
                    str(left_dashboard_path),
                    "--right",
                    str(right_dashboard_path),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            self.assertIn("Validation bundle changes:", compare_completed.stdout)
            self.assertIn("status: failed -> passed", compare_completed.stdout)
            self.assertIn("pbo_score: 0.27 -> 0.08", compare_completed.stdout)
            self.assertIn("spa_pvalue: 0.12 -> 0.02", compare_completed.stdout)
            self.assertIn(
                "failed_gates: deflated_sharpe_ratio, pbo, spa -> none",
                compare_completed.stdout,
            )
        finally:
            for path in (left_dashboard_path, right_dashboard_path):
                if path.exists():
                    path.unlink()

    def test_cli_compare_runs_json_surfaces_validation_bundle_drift(self) -> None:
        left_dashboard_path = Path("test-compare-validation-json-left.dashboard.json").resolve()
        right_dashboard_path = Path("test-compare-validation-json-right.dashboard.json").resolve()
        left_dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "compare-validation-json-left",
                    "decision": "blocked",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "compare-validation-json-right",
                    "decision": "promoted",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--left",
                    str(left_dashboard_path),
                    "--right",
                    str(right_dashboard_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            payload = json.loads(compare_completed.stdout)
            self.assertIn("validation_bundle_change", payload)
            self.assertEqual(payload["validation_bundle_left"]["status"], "failed")
            self.assertEqual(payload["validation_bundle_left"]["pbo_score"], 0.27)
            self.assertEqual(payload["validation_bundle_left"]["spa_pvalue"], 0.12)
            self.assertEqual(payload["validation_bundle_left"]["failed_gates"], ["deflated_sharpe_ratio", "pbo", "spa"])
            self.assertEqual(payload["validation_bundle_right"]["status"], "passed")
            self.assertEqual(payload["validation_bundle_right"]["pbo_score"], 0.08)
            self.assertEqual(payload["validation_bundle_right"]["spa_pvalue"], 0.02)
            self.assertEqual(payload["validation_bundle_right"]["failed_gates"], [])
            self.assertEqual(
                payload["validation_bundle_change"]["changed_fields"]["status"],
                {"left": "failed", "right": "passed"},
            )
            self.assertEqual(
                payload["validation_bundle_change"]["changed_fields"]["pbo_score"],
                {"left": 0.27, "right": 0.08},
            )
            self.assertEqual(
                payload["validation_bundle_change"]["changed_fields"]["spa_pvalue"],
                {"left": 0.12, "right": 0.02},
            )
            self.assertEqual(
                payload["validation_bundle_change"]["changed_fields"]["failed_gates"],
                {"left": ["deflated_sharpe_ratio", "pbo", "spa"], "right": []},
            )
        finally:
            for path in (left_dashboard_path, right_dashboard_path):
                if path.exists():
                    path.unlink()

    def test_cli_compare_runs_json_output_file_preserves_validation_bundle_drift(self) -> None:
        left_dashboard_path = Path("test-compare-validation-json-file-left.dashboard.json").resolve()
        right_dashboard_path = Path("test-compare-validation-json-file-right.dashboard.json").resolve()
        compare_output_path = Path("test-compare-validation-json-file.compare.json").resolve()
        left_dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "compare-validation-json-file-left",
                    "decision": "blocked",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "compare-validation-json-file-right",
                    "decision": "promoted",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--left",
                    str(left_dashboard_path),
                    "--right",
                    str(right_dashboard_path),
                    "--output",
                    str(compare_output_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            stdout_payload = json.loads(compare_completed.stdout)
            file_payload = json.loads(compare_output_path.read_text(encoding="utf-8"))
            self.assertEqual(stdout_payload, file_payload)
            self.assertEqual(file_payload["validation_bundle_left"]["status"], "failed")
            self.assertEqual(file_payload["validation_bundle_left"]["pbo_score"], 0.27)
            self.assertEqual(file_payload["validation_bundle_left"]["failed_gates"], ["deflated_sharpe_ratio", "pbo", "spa"])
            self.assertEqual(file_payload["validation_bundle_right"]["status"], "passed")
            self.assertEqual(file_payload["validation_bundle_right"]["pbo_score"], 0.08)
            self.assertEqual(file_payload["validation_bundle_right"]["failed_gates"], [])
            self.assertEqual(
                file_payload["validation_bundle_change"]["changed_fields"]["pbo_score"],
                {"left": 0.27, "right": 0.08},
            )
            self.assertEqual(
                file_payload["validation_bundle_change"]["changed_fields"]["failed_gates"],
                {"left": ["deflated_sharpe_ratio", "pbo", "spa"], "right": []},
            )
        finally:
            for path in (left_dashboard_path, right_dashboard_path, compare_output_path):
                if path.exists():
                    path.unlink()

    def test_cli_compare_runs_text_output_file_preserves_validation_bundle_drift(self) -> None:
        left_dashboard_path = Path("test-compare-validation-text-file-left.dashboard.json").resolve()
        right_dashboard_path = Path("test-compare-validation-text-file-right.dashboard.json").resolve()
        compare_output_path = Path("test-compare-validation-text-file.compare.txt").resolve()
        left_dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "compare-validation-text-file-left",
                    "decision": "blocked",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "compare-validation-text-file-right",
                    "decision": "promoted",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--left",
                    str(left_dashboard_path),
                    "--right",
                    str(right_dashboard_path),
                    "--format",
                    "text",
                    "--output",
                    str(compare_output_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            file_text = compare_output_path.read_text(encoding="utf-8")
            self.assertEqual(compare_completed.stdout.strip(), file_text.strip())
            self.assertIn("Validation bundle changes:", file_text)
            self.assertIn("pbo_score: 0.27 -> 0.08", file_text)
            self.assertIn("failed_gates: deflated_sharpe_ratio, pbo, spa -> none", file_text)
        finally:
            for path in (left_dashboard_path, right_dashboard_path, compare_output_path):
                if path.exists():
                    path.unlink()


    def test_cli_compare_runs_supports_autoresearch_kind_with_duplicate_baseline_diff(self) -> None:
        left_report_path = Path("test-compare-autoresearch-left.autoresearch.json")
        right_report_path = Path("test-compare-autoresearch-right.autoresearch.json")
        left_report_path.write_text(
            json.dumps(
                {
                    "run_id": "autoresearch-left",
                    "status": "promoted",
                    "research_lineage": {
                        "selected_variant": "balanced",
                        "selection_variant_result": {
                            "variant": "balanced",
                            "duplicate_baseline_history": {
                                "sample_count": 1,
                                "promoted_count": 1,
                                "success_rate": 0.5,
                                "average_sharpe": 0.31,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 1,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 30.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 1,
                                        "profile": {
                                            "latency_delta_bars": 2,
                                            "liquidity_penalty_bps": 55.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 1,
                                    "profile": {
                                        "search_summary_limit": 2,
                                        "slippage_bps": 4.0,
                                    },
                                },
                            },
                        },
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_report_path.write_text(
            json.dumps(
                {
                    "run_id": "autoresearch-right",
                    "status": "promoted",
                    "research_lineage": {
                        "selected_variant": "conservative",
                        "selection_variant_result": {
                            "variant": "conservative",
                            "duplicate_baseline_history": {
                                "sample_count": 3,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.25,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 2,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 45.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 2,
                                        "profile": {
                                            "latency_delta_bars": 3,
                                            "liquidity_penalty_bps": 65.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 2,
                                    "profile": {
                                        "search_summary_limit": 3,
                                        "slippage_bps": 5.0,
                                    },
                                },
                            },
                        },
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--kind",
                    "autoresearch",
                    "--left",
                    str(left_report_path),
                    "--right",
                    str(right_report_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            payload = json.loads(compare_completed.stdout)
            self.assertEqual(payload["left_run_id"], "autoresearch-left")
            self.assertEqual(payload["right_run_id"], "autoresearch-right")
            self.assertEqual(payload["selected_variant_change"], {"left": "balanced", "right": "conservative"})
            self.assertEqual(
                payload["duplicate_baseline_history_changes"]["net_rationale"],
                {
                    "direction": "improved",
                    "strength": "high",
                    "label": "improved (high)",
                    "score": 7.42,
                },
            )
            self.assertEqual(
                payload["duplicate_baseline_history_changes"]["changed_fields"]["success_rate"],
                {"left": 0.5, "right": 1.0},
            )
            self.assertEqual(
                payload["duplicate_baseline_history_changes"]["scenario_profile_hints"]["changed"]["attention-burst"]["profile_changed_fields"]["liquidity_penalty_bps"],
                {"left": 30.0, "right": 45.0},
            )
            self.assertEqual(
                payload["duplicate_baseline_history_changes"]["scenario_profile_avoidance"]["changed"]["outage-shock"]["profile_changed_fields"]["latency_delta_bars"],
                {"left": 2, "right": 3},
            )
            self.assertEqual(
                payload["duplicate_baseline_history_changes"]["top_runtime_profile_change"],
                {
                    "left": "search_summary_limit=2, slippage_bps=4.0",
                    "right": "search_summary_limit=3, slippage_bps=5.0",
                },
            )
            self.assertEqual(
                payload["duplicate_baseline_history_changes"]["runtime_profile_hints"]["changed_fields"],
                {
                    "search_summary_limit": {"left": 2, "right": 3},
                    "slippage_bps": {"left": 4.0, "right": 5.0},
                },
            )
        finally:
            if left_report_path.exists():
                left_report_path.unlink()
            if right_report_path.exists():
                right_report_path.unlink()

    def test_cli_compare_runs_supports_autoresearch_text_rationale_summary(self) -> None:
        left_report_path = Path("test-compare-autoresearch-text-left.autoresearch.json")
        right_report_path = Path("test-compare-autoresearch-text-right.autoresearch.json")
        left_report_path.write_text(
            json.dumps(
                {
                    "run_id": "autoresearch-text-left",
                    "status": "promoted",
                    "research_lineage": {
                        "selected_variant": "balanced",
                        "selection_variant_result": {
                            "variant": "balanced",
                            "duplicate_baseline_history": {
                                "sample_count": 1,
                                "promoted_count": 1,
                                "success_rate": 0.5,
                                "average_sharpe": 0.31,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 1,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 30.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 1,
                                        "profile": {
                                            "latency_delta_bars": 2,
                                            "liquidity_penalty_bps": 55.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 2,
                                    "profile": {
                                        "search_summary_limit": 3,
                                        "slippage_bps": 5.0,
                                    },
                                },
                            },
                        },
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_report_path.write_text(
            json.dumps(
                {
                    "run_id": "autoresearch-text-right",
                    "status": "promoted",
                    "research_lineage": {
                        "selected_variant": "conservative",
                        "selection_variant_result": {
                            "variant": "conservative",
                            "duplicate_baseline_history": {
                                "sample_count": 3,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.25,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 2,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 45.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 2,
                                        "profile": {
                                            "latency_delta_bars": 3,
                                            "liquidity_penalty_bps": 65.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 2,
                                    "profile": {
                                        "search_summary_limit": 3,
                                        "slippage_bps": 5.0,
                                    },
                                },
                            },
                        },
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--kind",
                    "autoresearch",
                    "--left",
                    str(left_report_path),
                    "--right",
                    str(right_report_path),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            self.assertIn("Selected variant: balanced -> conservative", compare_completed.stdout)
            self.assertIn("Net rationale: improved (high)", compare_completed.stdout)
            self.assertIn("Net rationale score: 7.42", compare_completed.stdout)
            self.assertIn("Likely selection drivers:", compare_completed.stdout)
            self.assertIn("[high] success_rate improved: 0.5 -> 1.0", compare_completed.stdout)
            self.assertIn("[low] average_sharpe worsened: 0.31 -> 0.25", compare_completed.stdout)
            self.assertLess(
                compare_completed.stdout.index("[high] promoted_count improved: 1 -> 2"),
                compare_completed.stdout.index("[low] average_sharpe worsened: 0.31 -> 0.25"),
            )
            self.assertIn("Top scenario profile:", compare_completed.stdout)
            self.assertIn("Top fragile profile:", compare_completed.stdout)
            self.assertIn(
                "Top runtime profile: search_summary_limit=3, slippage_bps=5.0 -> search_summary_limit=3, slippage_bps=5.0",
                compare_completed.stdout,
            )
            self.assertIn("Runtime profile hints:", compare_completed.stdout)
        finally:
            if left_report_path.exists():
                left_report_path.unlink()
            if right_report_path.exists():
                right_report_path.unlink()

    def test_cli_compare_runs_supports_autoresearch_text_mixed_verdict(self) -> None:
        left_report_path = Path("test-compare-autoresearch-mixed-left.autoresearch.json")
        right_report_path = Path("test-compare-autoresearch-mixed-right.autoresearch.json")
        left_report_path.write_text(
            json.dumps(
                {
                    "run_id": "autoresearch-mixed-left",
                    "status": "promoted",
                    "research_lineage": {
                        "selected_variant": "balanced",
                        "selection_variant_result": {
                            "variant": "balanced",
                            "duplicate_baseline_history": {
                                "success_rate": 0.50,
                                "average_sharpe": 0.31,
                            },
                        },
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_report_path.write_text(
            json.dumps(
                {
                    "run_id": "autoresearch-mixed-right",
                    "status": "promoted",
                    "research_lineage": {
                        "selected_variant": "conservative",
                        "selection_variant_result": {
                            "variant": "conservative",
                            "duplicate_baseline_history": {
                                "success_rate": 0.51,
                                "average_sharpe": 0.3007,
                            },
                        },
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--kind",
                    "autoresearch",
                    "--left",
                    str(left_report_path),
                    "--right",
                    str(right_report_path),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            self.assertIn("Net rationale: mixed (low)", compare_completed.stdout)
            self.assertIn("[low] success_rate improved: 0.5 -> 0.51", compare_completed.stdout)
            self.assertIn("[low] average_sharpe worsened: 0.31 -> 0.3007", compare_completed.stdout)
        finally:
            if left_report_path.exists():
                left_report_path.unlink()
            if right_report_path.exists():
                right_report_path.unlink()

    def test_cli_compare_runs_supports_autoresearch_text_worsened_verdict(self) -> None:
        left_report_path = Path("test-compare-autoresearch-worsened-left.autoresearch.json")
        right_report_path = Path("test-compare-autoresearch-worsened-right.autoresearch.json")
        left_report_path.write_text(
            json.dumps(
                {
                    "run_id": "autoresearch-worsened-left",
                    "status": "promoted",
                    "research_lineage": {
                        "selected_variant": "balanced",
                        "selection_variant_result": {
                            "variant": "balanced",
                            "duplicate_baseline_history": {
                                "success_rate": 0.80,
                                "average_sharpe": 0.50,
                            },
                        },
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_report_path.write_text(
            json.dumps(
                {
                    "run_id": "autoresearch-worsened-right",
                    "status": "promoted",
                    "research_lineage": {
                        "selected_variant": "exploratory",
                        "selection_variant_result": {
                            "variant": "exploratory",
                            "duplicate_baseline_history": {
                                "success_rate": 0.50,
                                "average_sharpe": 0.20,
                            },
                        },
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--kind",
                    "autoresearch",
                    "--left",
                    str(left_report_path),
                    "--right",
                    str(right_report_path),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            self.assertIn("Net rationale: worsened (high)", compare_completed.stdout)
            self.assertIn("[medium] success_rate worsened: 0.8 -> 0.5", compare_completed.stdout)
            self.assertIn("[medium] average_sharpe worsened: 0.5 -> 0.2", compare_completed.stdout)
        finally:
            if left_report_path.exists():
                left_report_path.unlink()
            if right_report_path.exists():
                right_report_path.unlink()

    def test_cli_compare_runs_supports_batch_json(self) -> None:
        left_batch_path = Path("test-compare-batch-left.variant-batch.json")
        right_batch_path = Path("test-compare-batch-right.variant-batch.json")
        left_batch_path.write_text(
            json.dumps(
                {
                    "base_run": {"run_id": "batch-left"},
                    "preferred_variant": {
                        "variant": "balanced",
                        "duplicate_baseline_score": 11.53,
                        "duplicate_baseline_history": {
                            "sample_count": 2,
                            "promoted_count": 2,
                            "success_rate": 1.0,
                            "average_sharpe": 0.51,
                            "runtime_profile_hints": {
                                "count": 2,
                                "profile": {
                                    "search_summary_limit": 3,
                                    "slippage_bps": 5.0,
                                },
                            },
                        },
                    },
                    "variant_results": [
                        {
                            "variant": "balanced",
                            "status": "promoted",
                            "duplicate_baseline_score": 11.53,
                            "duplicate_baseline_delta_vs_preferred": 0.0,
                            "duplicate_baseline_history": {
                                "sample_count": 2,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.51,
                                "runtime_profile_hints": {
                                    "count": 2,
                                    "profile": {
                                        "search_summary_limit": 3,
                                        "slippage_bps": 5.0,
                                    },
                                },
                            },
                        },
                        {
                            "variant": "conservative",
                            "status": "blocked",
                            "duplicate_baseline_score": 1.36,
                            "duplicate_baseline_delta_vs_preferred": -10.17,
                            "duplicate_baseline_history": {
                                "sample_count": 1,
                                "promoted_count": 0,
                                "success_rate": 0.25,
                                "average_sharpe": 0.12,
                            },
                        },
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_batch_path.write_text(
            json.dumps(
                {
                    "base_run": {"run_id": "batch-right"},
                    "preferred_variant": {
                        "variant": "conservative",
                        "duplicate_baseline_score": 13.8,
                        "duplicate_baseline_history": {
                            "sample_count": 3,
                            "promoted_count": 2,
                            "success_rate": 1.0,
                            "average_sharpe": 0.60,
                            "runtime_profile_hints": {
                                "count": 3,
                                "profile": {
                                    "search_summary_limit": 5,
                                    "slippage_bps": 7.0,
                                },
                            },
                        },
                    },
                    "variant_results": [
                        {
                            "variant": "conservative",
                            "status": "promoted",
                            "duplicate_baseline_score": 13.8,
                            "duplicate_baseline_delta_vs_preferred": 0.0,
                            "duplicate_baseline_history": {
                                "sample_count": 3,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.60,
                                "runtime_profile_hints": {
                                    "count": 3,
                                    "profile": {
                                        "search_summary_limit": 5,
                                        "slippage_bps": 7.0,
                                    },
                                },
                            },
                        },
                        {
                            "variant": "balanced",
                            "status": "promoted",
                            "duplicate_baseline_score": 4.0,
                            "duplicate_baseline_delta_vs_preferred": -9.8,
                            "duplicate_baseline_history": {
                                "sample_count": 2,
                                "promoted_count": 1,
                                "success_rate": 0.50,
                                "average_sharpe": 0.20,
                                "runtime_profile_hints": {
                                    "count": 3,
                                    "profile": {
                                        "search_summary_limit": 5,
                                        "slippage_bps": 7.0,
                                    },
                                },
                            },
                        },
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--kind",
                    "batch",
                    "--left",
                    str(left_batch_path),
                    "--right",
                    str(right_batch_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            payload = json.loads(compare_completed.stdout)
            self.assertEqual(payload["left_run_id"], "batch-left")
            self.assertEqual(payload["right_run_id"], "batch-right")
            self.assertEqual(payload["preferred_variant_change"], {"left": "balanced", "right": "conservative"})
            self.assertEqual(
                payload["variant_score_changes"]["balanced"],
                {
                    "left_score": 11.53,
                    "right_score": 4.0,
                    "score_delta": -7.53,
                    "left_delta_vs_preferred": 0.0,
                    "right_delta_vs_preferred": -9.8,
                    "delta_vs_preferred_change": -9.8,
                },
            )
            self.assertEqual(
                payload["variant_score_changes"]["conservative"],
                {
                    "left_score": 1.36,
                    "right_score": 13.8,
                    "score_delta": 12.44,
                    "left_delta_vs_preferred": -10.17,
                    "right_delta_vs_preferred": 0.0,
                    "delta_vs_preferred_change": 10.17,
                },
            )
            self.assertEqual(
                payload["variant_history_changes"]["balanced"]["changed_fields"]["average_sharpe"],
                {"left": 0.51, "right": 0.2},
            )
            self.assertEqual(
                payload["variant_history_changes"]["balanced"]["net_rationale"],
                {
                    "direction": "worsened",
                    "strength": "high",
                    "label": "worsened (high)",
                    "score": -4.82,
                },
            )
            self.assertEqual(
                payload["variant_history_changes"]["conservative"]["changed_fields"]["promoted_count"],
                {"left": 0, "right": 2},
            )
            self.assertEqual(
                payload["preferred_duplicate_baseline_history_changes"]["top_runtime_profile_change"],
                {
                    "left": "search_summary_limit=3, slippage_bps=5.0",
                    "right": "search_summary_limit=5, slippage_bps=7.0",
                },
            )
            self.assertEqual(
                payload["preferred_duplicate_baseline_history_changes"]["runtime_profile_hints"]["changed_fields"],
                {
                    "search_summary_limit": {"left": 3, "right": 5},
                    "slippage_bps": {"left": 5.0, "right": 7.0},
                },
            )
            self.assertEqual(
                payload["variant_history_changes"]["balanced"]["runtime_profile_hints"]["changed_fields"],
                {
                    "search_summary_limit": {"left": 3, "right": 5},
                    "slippage_bps": {"left": 5.0, "right": 7.0},
                },
            )
        finally:
            if left_batch_path.exists():
                left_batch_path.unlink()
            if right_batch_path.exists():
                right_batch_path.unlink()

    def test_cli_summarize_run_prints_runtime_settings(self) -> None:
        dashboard_path = Path("test-summarize-run-runtime.dashboard.json")
        dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-visible-run",
                    "decision": "promoted",
                    "strategy": {"backbone": "mom_squeeze", "layers": ["kama"], "risk_guards": []},
                    "metrics": {"selection_oos_sharpe": 0.91, "selection_oos_net_pnl": 145.0},
                    "holdout": {"decision": "accept", "reasons": []},
                    "runtime_settings": {
                        "position_side": "short",
                        "liquidation_mark_price_weight": 0.35,
                        "liquidation_mark_premium_bps": 12.0,
                    },
                    "snapshot_quality": {
                        "status": "dirty",
                        "flag_count": 1,
                        "flags": ["missing_funding_rate_count=4"],
                        "report": {"quality_score": 0.75, "passed": False},
                    },
                    "snapshot_provenance": {
                        "build_version": "phase1_snapshot_builder_v1",
                        "source_hash": "abc123",
                    },
                    "scenario_profiles": {},
                    "phases": [],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            summary_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-run",
                    "--dashboard",
                    str(dashboard_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(summary_completed.returncode, 0, msg=summary_completed.stderr)
            self.assertIn("Runtime settings:", summary_completed.stdout)
            self.assertIn("position_side=short", summary_completed.stdout)
            self.assertIn("liquidation_mark_price_weight=0.35", summary_completed.stdout)
            self.assertIn("Snapshot quality: dirty", summary_completed.stdout)
            self.assertIn("quality_score=0.75", summary_completed.stdout)
            self.assertIn("Snapshot build: phase1_snapshot_builder_v1", summary_completed.stdout)
            self.assertIn("Snapshot source hash: abc123", summary_completed.stdout)
        finally:
            if dashboard_path.exists():
                dashboard_path.unlink()

    def test_cli_compare_runs_supports_batch_text_rationale_summary(self) -> None:
        left_batch_path = Path("test-compare-batch-text-left.variant-batch.json")
        right_batch_path = Path("test-compare-batch-text-right.variant-batch.json")
        left_batch_path.write_text(
            json.dumps(
                {
                    "base_run": {"run_id": "batch-text-left"},
                    "preferred_variant": {
                        "variant": "balanced",
                        "duplicate_baseline_history": {
                            "sample_count": 2,
                            "promoted_count": 1,
                            "success_rate": 0.5,
                            "average_sharpe": 0.31,
                            "scenario_profile_hints": {
                                "attention-burst": {
                                    "count": 1,
                                    "profile": {
                                        "funding_multiplier": 1.5,
                                        "liquidity_penalty_bps": 30.0,
                                        "name": "attention-burst",
                                    },
                                }
                            },
                            "scenario_profile_avoidance": {
                                "outage-shock": {
                                    "count": 1,
                                    "profile": {
                                        "latency_delta_bars": 2,
                                        "liquidity_penalty_bps": 55.0,
                                        "name": "outage-shock",
                                    },
                                }
                            },
                            "runtime_profile_hints": {
                                "count": 2,
                                "profile": {
                                    "search_summary_limit": 3,
                                    "slippage_bps": 5.0,
                                },
                            },
                        },
                    },
                    "variant_results": [
                        {
                            "variant": "balanced",
                            "status": "promoted",
                            "duplicate_baseline_score": 7.43,
                            "duplicate_baseline_delta_vs_preferred": 0.0,
                            "duplicate_baseline_history": {
                                "sample_count": 2,
                                "promoted_count": 1,
                                "success_rate": 0.5,
                                "average_sharpe": 0.31,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 1,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 30.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 1,
                                        "profile": {
                                            "latency_delta_bars": 2,
                                            "liquidity_penalty_bps": 55.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 2,
                                    "profile": {
                                        "search_summary_limit": 3,
                                        "slippage_bps": 5.0,
                                    },
                                },
                            },
                        }
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_batch_path.write_text(
            json.dumps(
                {
                    "base_run": {"run_id": "batch-text-right"},
                    "preferred_variant": {
                        "variant": "conservative",
                        "duplicate_baseline_history": {
                            "sample_count": 3,
                            "promoted_count": 2,
                            "success_rate": 1.0,
                            "average_sharpe": 0.25,
                            "scenario_profile_hints": {
                                "attention-burst": {
                                    "count": 2,
                                    "profile": {
                                        "funding_multiplier": 1.5,
                                        "liquidity_penalty_bps": 45.0,
                                        "name": "attention-burst",
                                    },
                                }
                            },
                            "scenario_profile_avoidance": {
                                "outage-shock": {
                                    "count": 2,
                                    "profile": {
                                        "latency_delta_bars": 3,
                                        "liquidity_penalty_bps": 65.0,
                                        "name": "outage-shock",
                                    },
                                }
                            },
                            "runtime_profile_hints": {
                                "count": 3,
                                "profile": {
                                    "search_summary_limit": 5,
                                    "slippage_bps": 7.0,
                                },
                            },
                        },
                    },
                    "variant_results": [
                        {
                            "variant": "conservative",
                            "status": "promoted",
                            "duplicate_baseline_score": 8.39,
                            "duplicate_baseline_delta_vs_preferred": 0.0,
                            "duplicate_baseline_history": {
                                "sample_count": 3,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.25,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 2,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 45.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 2,
                                        "profile": {
                                            "latency_delta_bars": 3,
                                            "liquidity_penalty_bps": 65.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 3,
                                    "profile": {
                                        "search_summary_limit": 5,
                                        "slippage_bps": 7.0,
                                    },
                                },
                            },
                        }
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--kind",
                    "batch",
                    "--left",
                    str(left_batch_path),
                    "--right",
                    str(right_batch_path),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)
            self.assertIn("Preferred variant: balanced -> conservative", compare_completed.stdout)
            self.assertIn("Preferred net rationale: improved (high)", compare_completed.stdout)
            self.assertIn("Preferred net rationale score: 5.92", compare_completed.stdout)
            self.assertIn("Likely preferred drivers:", compare_completed.stdout)
            self.assertIn("[high] success_rate improved: 0.5 -> 1.0", compare_completed.stdout)
            self.assertIn("[low] average_sharpe worsened: 0.31 -> 0.25", compare_completed.stdout)
            self.assertIn(
                "Preferred top scenario profile: attention-burst | funding_multiplier=1.5, liquidity_penalty_bps=30.0, name=attention-burst -> attention-burst | funding_multiplier=1.5, liquidity_penalty_bps=45.0, name=attention-burst",
                compare_completed.stdout,
            )
            self.assertIn(
                "Preferred top fragile profile: outage-shock | latency_delta_bars=2, liquidity_penalty_bps=55.0, name=outage-shock -> outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock",
                compare_completed.stdout,
            )
            self.assertIn(
                "Preferred top runtime profile: search_summary_limit=3, slippage_bps=5.0 -> search_summary_limit=5, slippage_bps=7.0",
                compare_completed.stdout,
            )
            self.assertIn("Scenario profile hints:", compare_completed.stdout)
            self.assertIn("Scenario profile avoidance:", compare_completed.stdout)
            self.assertIn("Runtime profile hints:", compare_completed.stdout)
            self.assertIn("- search_summary_limit: 3 -> 5", compare_completed.stdout)
            self.assertIn("- slippage_bps: 5.0 -> 7.0", compare_completed.stdout)
        finally:
            if left_batch_path.exists():
                left_batch_path.unlink()
            if right_batch_path.exists():
                right_batch_path.unlink()

    def test_cli_summarize_batch_prints_preferred_variant_and_deltas(self) -> None:
        output_dir = Path("test-output-cli-summarize-batch")
        db_path = Path("test-output-cli-summarize-batch.sqlite")
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)
        for candidate in (db_path, db_path.with_name(f"{db_path.name}-wal"), db_path.with_name(f"{db_path.name}-shm")):
            candidate.unlink(missing_ok=True)
        output_dir.mkdir(exist_ok=True)
        try:
            batch_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "batch-autoresearch",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(batch_completed.returncode, 0, msg=batch_completed.stderr)
            batch_payload = json.loads(batch_completed.stdout)

            summary_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-batch",
                    "--batch-report",
                    str(batch_payload["batch_report_path"]),
                    "--top",
                    "2",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(summary_completed.returncode, 0, msg=summary_completed.stderr)
            self.assertIn("Batch run", summary_completed.stdout)
            self.assertIn("Preferred variant:", summary_completed.stdout)
            self.assertIn("Base run:", summary_completed.stdout)
            self.assertIn("Delta vs base:", summary_completed.stdout)
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_summarize_batch_prints_accepted_duplicate_path_when_present(self) -> None:
        report_path = Path("test-output-cli-summarize-batch-duplicate.json")
        report_path.write_text(
            json.dumps(
                {
                    "run_id": "batch-duplicate",
                    "status": "skipped",
                    "accepted_duplicate_config_path": "outputs\\batch-duplicate.accepted-duplicate.json",
                    "base_run": {
                        "run_id": "batch-duplicate",
                        "status": "skipped",
                        "metrics": {},
                    },
                    "preferred_variant": None,
                    "variant_results": [],
                }
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-batch",
                    "--batch-report",
                    str(report_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Accepted duplicate config: outputs\\batch-duplicate.accepted-duplicate.json", completed.stdout)
        finally:
            if report_path.exists():
                report_path.unlink()

    def test_cli_summarize_batch_prints_duplicate_baseline_history_when_present(self) -> None:
        report_path = Path("test-output-cli-summarize-batch-history.json")
        report_path.write_text(
            json.dumps(
                {
                    "run_id": "batch-history",
                    "status": "promoted",
                    "duplicate_baseline_run_id": "seed-baseline-a",
                    "duplicate_baseline_history": {
                        "balanced": {
                            "sample_count": 1,
                            "promoted_count": 0,
                            "success_rate": 0.0,
                            "average_sharpe": 0.18,
                            "duplicate_baseline_run_id": "seed-baseline-a",
                        },
                        "conservative": {
                            "sample_count": 2,
                            "promoted_count": 2,
                            "success_rate": 1.0,
                            "average_sharpe": 0.51,
                            "duplicate_baseline_run_id": "seed-baseline-a",
                            "scenario_profile_avoidance_count": 2,
                            "scenario_profile_hints": {
                                "attention-burst": {
                                    "count": 2,
                                    "profile": {
                                        "funding_multiplier": 1.5,
                                        "liquidity_penalty_bps": 30.0,
                                        "name": "attention-burst",
                                    },
                                }
                            },
                            "scenario_profile_avoidance": {
                                "outage-shock": {
                                    "count": 2,
                                    "profile": {
                                        "latency_delta_bars": 3,
                                        "liquidity_penalty_bps": 65.0,
                                        "name": "outage-shock",
                                    },
                                }
                            },
                            "runtime_profile_hints": {
                                "count": 2,
                                "profile": {
                                    "search_summary_limit": 3,
                                    "slippage_bps": 5.0,
                                },
                            },
                        },
                    },
                    "base_run": {
                        "run_id": "batch-history",
                        "status": "promoted",
                        "metrics": {"selection_oos_sharpe": 0.31, "selection_oos_drawdown": -0.09},
                    },
                    "preferred_variant": {
                        "variant": "conservative",
                        "status": "promoted",
                        "selection_oos_sharpe": 0.35,
                        "duplicate_baseline_history": {
                            "sample_count": 2,
                            "promoted_count": 2,
                            "success_rate": 1.0,
                            "average_sharpe": 0.51,
                            "duplicate_baseline_run_id": "seed-baseline-a",
                            "scenario_profile_avoidance_count": 2,
                            "scenario_profile_hints": {
                                "attention-burst": {
                                    "count": 2,
                                    "profile": {
                                        "funding_multiplier": 1.5,
                                        "liquidity_penalty_bps": 30.0,
                                        "name": "attention-burst",
                                    },
                                }
                            },
                            "scenario_profile_avoidance": {
                                "outage-shock": {
                                    "count": 2,
                                    "profile": {
                                        "latency_delta_bars": 3,
                                        "liquidity_penalty_bps": 65.0,
                                        "name": "outage-shock",
                                    },
                                }
                            },
                            "runtime_profile_hints": {
                                "count": 2,
                                "profile": {
                                    "search_summary_limit": 3,
                                    "slippage_bps": 5.0,
                                },
                            },
                        },
                    },
                    "variant_results": [
                        {
                            "variant": "balanced",
                            "status": "blocked",
                            "selection_oos_sharpe": 0.18,
                            "scenario_pass_rate": 0.5,
                            "duplicate_baseline_history": {
                                "sample_count": 1,
                                "promoted_count": 0,
                                "success_rate": 0.0,
                                "average_sharpe": 0.18,
                                "duplicate_baseline_run_id": "seed-baseline-a",
                            },
                            "compare_to_base": {"metric_deltas": {"selection_oos_sharpe": -0.13}},
                        },
                        {
                            "variant": "conservative",
                            "status": "promoted",
                            "selection_oos_sharpe": 0.35,
                            "scenario_pass_rate": 1.0,
                            "duplicate_baseline_history": {
                                "sample_count": 2,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.51,
                                "duplicate_baseline_run_id": "seed-baseline-a",
                                "scenario_profile_avoidance_count": 2,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 2,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 30.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 2,
                                        "profile": {
                                            "latency_delta_bars": 3,
                                            "liquidity_penalty_bps": 65.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 2,
                                    "profile": {
                                        "search_summary_limit": 3,
                                        "slippage_bps": 5.0,
                                    },
                                },
                            },
                            "compare_to_base": {"metric_deltas": {"selection_oos_sharpe": 0.04}},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-batch",
                    "--batch-report",
                    str(report_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Duplicate baseline: seed-baseline-a", completed.stdout)
            self.assertIn("Preferred history: samples=2 | promoted=2 | success_rate=1.0 | average_sharpe=0.51", completed.stdout)
            self.assertIn("Preferred duplicate baseline score: 11.53", completed.stdout)
            self.assertIn("avoided_profiles=2", completed.stdout)
            self.assertIn(
                "Preferred top scenario profile: attention-burst | funding_multiplier=1.5, liquidity_penalty_bps=30.0, name=attention-burst",
                completed.stdout,
            )
            self.assertIn(
                "Preferred top fragile profile: outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock",
                completed.stdout,
            )
            self.assertIn(
                "Preferred top runtime profile: search_summary_limit=3, slippage_bps=5.0",
                completed.stdout,
            )
            self.assertIn("History vs baseline: samples=2 | promoted=2 | success_rate=1.0 | average_sharpe=0.51", completed.stdout)
            self.assertIn(
                "History scenario profile: attention-burst | funding_multiplier=1.5, liquidity_penalty_bps=30.0, name=attention-burst",
                completed.stdout,
            )
            self.assertIn(
                "History fragile profile: outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock",
                completed.stdout,
            )
            self.assertIn(
                "History runtime profile: search_summary_limit=3, slippage_bps=5.0",
                completed.stdout,
            )
            self.assertIn("History score: 11.53", completed.stdout)
            self.assertIn("History delta vs preferred: -9.99", completed.stdout)
            self.assertIn("History delta vs preferred: +0.00", completed.stdout)
        finally:
            if report_path.exists():
                report_path.unlink()

    def test_cli_summarize_autoresearch_prints_duplicate_match_and_hypotheses(self) -> None:
        report_path = Path("test-output-cli-summarize-autoresearch.json")
        report_path.write_text(
            json.dumps(
                {
                    "run_id": "auto-duplicate",
                    "status": "skipped",
                    "skip_reason": "duplicate_study_signature",
                    "accepted_duplicate_config_path": "outputs\\auto-duplicate.accepted-duplicate.json",
                    "duplicate_match": {
                        "match_type": "study_signature",
                        "run_id": "prior-same-study",
                        "decision": "promoted",
                        "study_signature": "abc123",
                        "selection_oos_sharpe": 0.51,
                        "snapshot_quality_status": "clean",
                    },
                    "memory_summary": {
                        "prior_runs": 4,
                        "promoted_runs": 2,
                        "blocked_runs": 2,
                        "excluded_dirty_runs": 1,
                        "memory_quality_policy": "clean-only",
                        "recovered_duplicate_runs": 1,
                        "top_duplicate_matches": [{"run_id": "prior-same-study", "count": 1}],
                        "scenario_profile_hints": {
                            "attention-burst": {
                                "count": 2,
                                "profile": {
                                    "funding_multiplier": 1.5,
                                    "liquidity_penalty_bps": 30.0,
                                    "name": "attention-burst",
                                },
                            }
                        },
                        "scenario_profile_avoidance": {
                            "outage-shock": {
                                "count": 2,
                                "profile": {
                                    "name": "outage-shock",
                                    "latency_delta_bars": 3,
                                    "liquidity_penalty_bps": 65.0,
                                },
                            }
                        },
                        "runtime_profile_hints": {
                            "count": 2,
                            "profile": {
                                "search_summary_limit": 3,
                                "slippage_bps": 5.0,
                            },
                        },
                    },
                    "hypotheses": [
                        {"type": "promising_layer", "layer_name": "kama", "count": 2},
                        {"type": "fragile_layer", "layer_name": "flat9", "count": 1},
                        {"type": "duplicate_recovery_baseline", "run_id": "prior-same-study", "count": 1},
                        {"type": "fragile_scenario_profile", "scenario_name": "outage-shock", "count": 2},
                    ],
                    "research_lineage": {
                        "selected_variant": "balanced",
                        "selection_variant_result": {
                            "variant": "balanced",
                            "duplicate_baseline_history": {
                                "sample_count": 2,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.51,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 2,
                                        "profile": {
                                            "funding_multiplier": 1.7,
                                            "liquidity_penalty_bps": 35.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 2,
                                        "profile": {
                                            "name": "outage-shock",
                                            "latency_delta_bars": 4,
                                            "liquidity_penalty_bps": 70.0,
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 2,
                                    "profile": {
                                        "search_summary_limit": 4,
                                        "slippage_bps": 6.0,
                                    },
                                },
                            },
                        },
                    },
                    "runcard_path": None,
                    "dashboard_path": None,
                }
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-autoresearch",
                    "--autoresearch-report",
                    str(report_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Autoresearch auto-duplicate", completed.stdout)
            self.assertIn("Status: skipped", completed.stdout)
            self.assertIn("Skip reason: duplicate_study_signature", completed.stdout)
            self.assertIn("Accepted duplicate config: outputs\\auto-duplicate.accepted-duplicate.json", completed.stdout)
            self.assertIn("Duplicate match: study_signature -> prior-same-study", completed.stdout)
            self.assertIn("Memory: prior_runs=4 | promoted=2 | blocked=2 | excluded_dirty=1", completed.stdout)
            self.assertIn("Recovered duplicates: 1 | top_matches=prior-same-study(1)", completed.stdout)
            self.assertIn(
                "Top scenario profile: attention-burst | funding_multiplier=1.5, liquidity_penalty_bps=30.0, name=attention-burst",
                completed.stdout,
            )
            self.assertIn(
                "Top fragile profile: outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock",
                completed.stdout,
            )
            self.assertIn(
                "Top runtime profile: search_summary_limit=3, slippage_bps=5.0",
                completed.stdout,
            )
            self.assertIn(
                "Selected runtime profile: search_summary_limit=4, slippage_bps=6.0",
                completed.stdout,
            )
            self.assertIn(
                "Selected scenario profile: attention-burst | funding_multiplier=1.7, liquidity_penalty_bps=35.0, name=attention-burst",
                completed.stdout,
            )
            self.assertIn(
                "Selected fragile profile: outage-shock | latency_delta_bars=4, liquidity_penalty_bps=70.0, name=outage-shock",
                completed.stdout,
            )
            self.assertIn("Hypotheses:", completed.stdout)
            self.assertIn("- promising_layer kama (count=2)", completed.stdout)
            self.assertIn("- fragile_layer flat9 (count=1)", completed.stdout)
            self.assertIn("- duplicate_recovery_baseline prior-same-study (count=1)", completed.stdout)
            self.assertIn("- fragile_scenario_profile outage-shock (count=2)", completed.stdout)
        finally:
            if report_path.exists():
                report_path.unlink()

    def test_cli_compare_duplicate_match_prints_requested_vs_matched_run(self) -> None:
        config_path = Path("test-compare-duplicate-study.json")
        report_path = Path("test-output-cli-compare-duplicate.autoresearch.json")
        artifact_dir = Path("test-memory-compare-duplicate")
        db_path = Path("test-output-cli-compare-duplicate.sqlite")
        artifact_dir.mkdir(exist_ok=True)
        payload = {
            "run_id": "auto-new-run-id",
            "seed": 41,
            "snapshot": {
                "snapshot_id": "auto-new-run-id-snap",
                "symbol": "SOLUSDT",
                "venue": "binance",
                "timeframe": "1h",
                "candles": [],
                "funding_rates": [],
                "open_interest": [],
                "liquidation_notional": [],
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 5.0,
                "quality_flags": [],
            },
            "incumbent": {"backbone": "mom_squeeze"},
            "directional_layers": ["kama"],
            "known_good_filters": ["flat9"],
            "custom_filters": [],
            "exit_layers": [],
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        report_path.write_text(
            json.dumps(
                {
                    "run_id": "auto-new-run-id",
                    "status": "skipped",
                    "skip_reason": "duplicate_study_signature",
                    "duplicate_match": {
                        "match_type": "study_signature",
                        "run_id": "prior-same-study",
                        "decision": "promoted",
                        "study_signature": "abc123",
                        "selection_oos_sharpe": 0.51,
                        "snapshot_quality_status": "clean",
                    },
                    "memory_summary": {},
                    "hypotheses": [],
                    "research_lineage": {},
                    "runcard_path": None,
                    "dashboard_path": None,
                }
            ),
            encoding="utf-8",
        )
        save_runcard(
            artifact_dir / "prior-same-study.runcard.json",
            RunCard(
                run_id="prior-same-study",
                strategy_hash="prior-same-study-hash",
                phase="phase-5",
                split_id="snap:60-20-20",
                seed=19,
                decision=PromotionDecision(decision="promoted", reasons=[]),
                metrics={
                    "selection_oos_sharpe": 0.51,
                    "selection_oos_net_pnl": 175.0,
                    "selection_oos_drawdown": -0.11,
                    "scenario_pass_rate": 1.0,
                    "accepted_layers": 1.0,
                },
                artifacts={
                    "snapshot_id": "prior-same-study-snap",
                    "final_status": "promoted",
                    "symbol": "SOLUSDT",
                    "venue": "binance",
                    "snapshot_quality_status": "clean",
                    "snapshot_quality_flag_count": "0",
                    "snapshot_quality_flags_json": "[]",
                    "study_signature": "abc123",
                    "selected_parameters_json": json.dumps({"kama": {"aggressiveness": 2}}, sort_keys=True),
                    "parameter_search_json": "{}",
                },
            ),
        )
        (artifact_dir / "prior-same-study.dashboard.json").write_text(
            json.dumps(
                {
                    "run_id": "prior-same-study",
                    "strategy": {"backbone": "mom_squeeze", "layers": ["kama"], "risk_guards": []},
                    "phases": [
                        {
                            "phase_name": "phase-2",
                            "layer_name": "kama",
                            "decision": "accept",
                            "accepted": True,
                            "selected_parameters": {"aggressiveness": 2},
                        },
                        {
                            "phase_name": "phase-3",
                            "layer_name": "flat9",
                            "decision": "reject",
                            "accepted": False,
                            "selected_parameters": {},
                        },
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifact_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-duplicate-match",
                    "--autoresearch-report",
                    str(report_path),
                    "--config",
                    str(config_path),
                    "--db",
                    str(db_path),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Duplicate compare for auto-new-run-id", completed.stdout)
            self.assertIn("Match: study_signature -> prior-same-study", completed.stdout)
            self.assertIn("Requested directional: kama", completed.stdout)
            self.assertIn("Requested known-good: flat9", completed.stdout)
            self.assertIn("Matched accepted: kama", completed.stdout)
            self.assertIn("Matched rejected: flat9", completed.stdout)
            self.assertIn("Matched metrics: sharpe=0.51 | pnl=175.0 | drawdown=-0.11", completed.stdout)
        finally:
            for path in (config_path, report_path, db_path):
                if path.exists():
                    path.unlink()
            if artifact_dir.exists():
                for path in artifact_dir.glob("*"):
                    path.unlink()
                artifact_dir.rmdir()

    def test_cli_accept_duplicate_match_writes_followup_config_with_incumbent_layers(self) -> None:
        config_path = Path("test-accept-duplicate-study.json")
        output_config_path = Path("test-accepted-duplicate-study.json")
        report_path = Path("test-output-cli-accept-duplicate.autoresearch.json")
        artifact_dir = Path("test-memory-accept-duplicate")
        db_path = Path("test-output-cli-accept-duplicate.sqlite")
        artifact_dir.mkdir(exist_ok=True)
        payload = {
            "run_id": "auto-new-run-id",
            "seed": 41,
            "snapshot": {
                "snapshot_id": "auto-new-run-id-snap",
                "symbol": "SOLUSDT",
                "venue": "binance",
                "timeframe": "1h",
                "candles": [],
                "funding_rates": [],
                "open_interest": [],
                "liquidation_notional": [],
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 5.0,
                "quality_flags": [],
            },
            "incumbent": {"backbone": "mom_squeeze"},
            "directional_layers": ["kama"],
            "known_good_filters": ["flat9"],
            "custom_filters": [],
            "exit_layers": ["time_stop"],
            "layer_parameters": {"mom_squeeze": {"entry_stride": 4}},
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        report_path.write_text(
            json.dumps(
                {
                    "run_id": "auto-new-run-id",
                    "status": "skipped",
                    "skip_reason": "duplicate_study_signature",
                    "duplicate_match": {
                        "match_type": "study_signature",
                        "run_id": "prior-same-study",
                        "decision": "promoted",
                        "study_signature": "abc123",
                        "selection_oos_sharpe": 0.51,
                        "snapshot_quality_status": "clean",
                    },
                    "memory_summary": {},
                    "hypotheses": [],
                    "research_lineage": {},
                    "runcard_path": None,
                    "dashboard_path": None,
                }
            ),
            encoding="utf-8",
        )
        save_runcard(
            artifact_dir / "prior-same-study.runcard.json",
            RunCard(
                run_id="prior-same-study",
                strategy_hash="prior-same-study-hash",
                phase="phase-5",
                split_id="snap:60-20-20",
                seed=19,
                decision=PromotionDecision(decision="promoted", reasons=[]),
                metrics={
                    "selection_oos_sharpe": 0.51,
                    "selection_oos_net_pnl": 175.0,
                    "selection_oos_drawdown": -0.11,
                    "scenario_pass_rate": 1.0,
                    "accepted_layers": 1.0,
                },
                artifacts={
                    "snapshot_id": "prior-same-study-snap",
                    "final_status": "promoted",
                    "symbol": "SOLUSDT",
                    "venue": "binance",
                    "snapshot_quality_status": "clean",
                    "snapshot_quality_flag_count": "0",
                    "snapshot_quality_flags_json": "[]",
                    "study_signature": "abc123",
                    "selected_parameters_json": json.dumps({"kama": {"aggressiveness": 2}}, sort_keys=True),
                    "parameter_search_json": "{}",
                },
            ),
        )
        (artifact_dir / "prior-same-study.dashboard.json").write_text(
            json.dumps(
                {
                    "run_id": "prior-same-study",
                    "strategy": {"backbone": "mom_squeeze", "layers": ["kama"], "risk_guards": []},
                    "phases": [
                        {
                            "phase_name": "phase-2",
                            "layer_name": "kama",
                            "decision": "accept",
                            "accepted": True,
                            "selected_parameters": {"aggressiveness": 2},
                        },
                        {
                            "phase_name": "phase-3",
                            "layer_name": "flat9",
                            "decision": "reject",
                            "accepted": False,
                            "selected_parameters": {},
                        },
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            ingest_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "ingest-memory",
                    "--dir",
                    str(artifact_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ingest_completed.returncode, 0, msg=ingest_completed.stderr)

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "accept-duplicate-match",
                    "--autoresearch-report",
                    str(report_path),
                    "--config",
                    str(config_path),
                    "--db",
                    str(db_path),
                    "--output-config",
                    str(output_config_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload_out = json.loads(completed.stdout)
            self.assertEqual(payload_out["matched_run_id"], "prior-same-study")
            self.assertEqual(Path(payload_out["output_config_path"]), output_config_path)
            output_payload = json.loads(output_config_path.read_text(encoding="utf-8"))
            self.assertEqual(output_payload["run_id"], "auto-new-run-id-accepted-duplicate")
            self.assertEqual(output_payload["incumbent"]["layers"], ["kama"])
            self.assertEqual(output_payload["directional_layers"], [])
            self.assertEqual(output_payload["known_good_filters"], [])
            self.assertEqual(output_payload["exit_layers"], ["time_stop"])
            self.assertEqual(output_payload["layer_parameters"]["kama"]["aggressiveness"], 2)
            self.assertEqual(output_payload["research_lineage"]["accepted_duplicate_match_run_id"], "prior-same-study")
            accepted_study = load_study_config(output_config_path)
            self.assertEqual([layer.name for layer in accepted_study.incumbent.layers], ["kama"])
        finally:
            for path in (config_path, output_config_path, report_path, db_path):
                if path.exists():
                    path.unlink()
            if artifact_dir.exists():
                for path in artifact_dir.glob("*"):
                    path.unlink()
                artifact_dir.rmdir()

    def test_cli_select_batch_variant_writes_selected_followup_config(self) -> None:
        output_dir = Path("test-output-cli-select-batch")
        db_path = Path("test-output-cli-select-batch.sqlite")
        selected_config_path = output_dir / "selected-followup.json"
        output_dir.mkdir(exist_ok=True)
        try:
            batch_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "batch-autoresearch",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(batch_completed.returncode, 0, msg=batch_completed.stderr)
            batch_payload = json.loads(batch_completed.stdout)

            select_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "select-batch-variant",
                    "--batch-report",
                    str(batch_payload["batch_report_path"]),
                    "--variant",
                    "preferred",
                    "--output-config",
                    str(selected_config_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(select_completed.returncode, 0, msg=select_completed.stderr)
            payload = json.loads(select_completed.stdout)
            self.assertEqual(payload["selected_variant"], "balanced")
            self.assertTrue(selected_config_path.exists())
            selected_payload = json.loads(selected_config_path.read_text(encoding="utf-8"))
            self.assertEqual(selected_payload["research_variant"]["name"], "balanced")
            self.assertEqual(Path(payload["output_config_path"]), selected_config_path)
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_select_batch_variant_returns_profile_rationale_when_history_present(self) -> None:
        report_path = Path("test-output-cli-select-batch-history.json")
        source_config_path = Path("test-output-cli-select-batch-history.balanced.json")
        output_config_path = Path("test-output-cli-select-batch-history.selected.json")
        source_config_path.write_text(
            json.dumps({"run_id": "batch-history-next", "research_variant": {"name": "balanced"}}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        report_path.write_text(
            json.dumps(
                {
                    "run_id": "batch-history",
                    "status": "promoted",
                    "next_study_variant_paths": {
                        "balanced": str(source_config_path),
                    },
                    "preferred_variant": {
                        "variant": "balanced",
                        "status": "promoted",
                        "selection_oos_sharpe": 0.35,
                        "duplicate_baseline_history": {
                            "sample_count": 2,
                            "promoted_count": 2,
                            "success_rate": 1.0,
                            "average_sharpe": 0.51,
                            "scenario_profile_hints": {
                                "attention-burst": {
                                    "count": 2,
                                    "profile": {
                                        "funding_multiplier": 1.5,
                                        "liquidity_penalty_bps": 30.0,
                                        "name": "attention-burst",
                                    },
                                }
                            },
                            "scenario_profile_avoidance": {
                                "outage-shock": {
                                    "count": 2,
                                    "profile": {
                                        "latency_delta_bars": 3,
                                        "liquidity_penalty_bps": 65.0,
                                        "name": "outage-shock",
                                    },
                                }
                            },
                        },
                    },
                    "variant_results": [
                        {
                            "variant": "balanced",
                            "status": "promoted",
                            "selection_oos_sharpe": 0.35,
                            "duplicate_baseline_history": {
                                "sample_count": 2,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.51,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 2,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 30.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 2,
                                        "profile": {
                                            "latency_delta_bars": 3,
                                            "liquidity_penalty_bps": 65.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 2,
                                    "profile": {
                                        "search_summary_limit": 3,
                                        "slippage_bps": 5.0,
                                    },
                                },
                            },
                        }
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "select-batch-variant",
                    "--batch-report",
                    str(report_path),
                    "--variant",
                    "preferred",
                    "--output-config",
                    str(output_config_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["selected_variant"], "balanced")
            self.assertAlmostEqual(payload["selected_duplicate_baseline_score"], 11.53)
            self.assertAlmostEqual(payload["selected_duplicate_baseline_delta_vs_preferred"], 0.0)
            self.assertEqual(
                payload["selected_top_scenario_profile"],
                "attention-burst | funding_multiplier=1.5, liquidity_penalty_bps=30.0, name=attention-burst",
            )
            self.assertEqual(
                payload["selected_top_fragile_profile"],
                "outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock",
            )
            self.assertEqual(
                payload["selected_top_runtime_profile"],
                "search_summary_limit=3, slippage_bps=5.0",
            )
        finally:
            for path in (report_path, source_config_path, output_config_path):
                if path.exists():
                    path.unlink()

    def test_cli_continue_batch_runs_selected_variant_as_new_autoresearch_cycle(self) -> None:
        output_dir = Path("test-output-cli-continue-batch")
        db_path = Path("test-output-cli-continue-batch.sqlite")
        continue_output_dir = output_dir / "continued"
        output_dir.mkdir(exist_ok=True)
        try:
            batch_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "batch-autoresearch",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(batch_completed.returncode, 0, msg=batch_completed.stderr)
            batch_payload = json.loads(batch_completed.stdout)

            continue_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "continue-batch",
                    "--batch-report",
                    str(batch_payload["batch_report_path"]),
                    "--variant",
                    "preferred",
                    "--output-dir",
                    str(continue_output_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(continue_completed.returncode, 0, msg=continue_completed.stderr)
            payload = json.loads(continue_completed.stdout)
            self.assertEqual(payload["selected_variant"], "balanced")
            self.assertEqual(payload["run_id"], "example-study-next-continued")
            self.assertIn("autoresearch_report_path", payload)
            self.assertTrue((continue_output_dir / "example-study-next-continued.autoresearch.json").exists())
            self.assertTrue((continue_output_dir / "example-study-next-continued.runcard.json").exists())
            self.assertTrue((continue_output_dir / "example-study-next-continued.continued-study.json").exists())
            continued_study_payload = json.loads(
                (continue_output_dir / "example-study-next-continued.continued-study.json").read_text(encoding="utf-8")
            )
            self.assertEqual(continued_study_payload["research_lineage"]["selected_variant"], "balanced")
            self.assertEqual(continued_study_payload["research_lineage"]["selection_source"], "batch_report")
            self.assertEqual(continued_study_payload["research_lineage"]["selection_preference_mode"], "preferred")
            self.assertIn("selection_variant_result", continued_study_payload["research_lineage"])
            continued_report_payload = json.loads(
                (continue_output_dir / "example-study-next-continued.autoresearch.json").read_text(encoding="utf-8")
            )
            self.assertEqual(continued_report_payload["research_lineage"]["selected_variant"], "balanced")
            self.assertEqual(continued_report_payload["research_lineage"]["selection_source"], "batch_report")
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if continue_output_dir.exists():
                import shutil
            shutil.rmtree(continue_output_dir, ignore_errors=True)

            for path in output_dir.glob("*"):
                if path.is_file():
                    path.unlink()

    def test_cli_continue_batch_returns_profile_rationale_when_selection_history_present(self) -> None:
        output_dir = Path("test-output-cli-continue-batch-history")
        db_path = Path("test-output-cli-continue-batch-history.sqlite")
        continue_output_dir = output_dir / "continued"
        batch_report_path = output_dir / "batch-history.variant-batch.json"
        output_dir.mkdir(exist_ok=True)
        try:
            batch_report_path.write_text(
                json.dumps(
                    {
                        "run_id": "batch-history",
                        "next_study_variant_paths": {
                            "balanced": str(Path("examples\\minimal_builtin_study.json")),
                        },
                        "preferred_variant": {
                            "variant": "balanced",
                            "status": "promoted",
                            "selection_oos_sharpe": 0.35,
                            "duplicate_baseline_history": {
                                "sample_count": 2,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.51,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 2,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 30.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 2,
                                        "profile": {
                                            "latency_delta_bars": 3,
                                            "liquidity_penalty_bps": 65.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                            },
                        },
                        "variant_results": [
                            {
                                "variant": "balanced",
                                "status": "promoted",
                                "selection_oos_sharpe": 0.35,
                                "duplicate_baseline_history": {
                                    "sample_count": 2,
                                    "promoted_count": 2,
                                    "success_rate": 1.0,
                                    "average_sharpe": 0.51,
                                    "scenario_profile_hints": {
                                        "attention-burst": {
                                            "count": 2,
                                            "profile": {
                                                "funding_multiplier": 1.5,
                                                "liquidity_penalty_bps": 30.0,
                                                "name": "attention-burst",
                                            },
                                        }
                                    },
                                    "scenario_profile_avoidance": {
                                        "outage-shock": {
                                            "count": 2,
                                            "profile": {
                                                "latency_delta_bars": 3,
                                                "liquidity_penalty_bps": 65.0,
                                                "name": "outage-shock",
                                            },
                                        }
                                    },
                                    "runtime_profile_hints": {
                                        "count": 2,
                                        "profile": {
                                            "search_summary_limit": 3,
                                            "slippage_bps": 5.0,
                                        },
                                    },
                                },
                            }
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "continue-batch",
                    "--batch-report",
                    str(batch_report_path),
                    "--variant",
                    "preferred",
                    "--output-dir",
                    str(continue_output_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["selected_variant"], "balanced")
            self.assertAlmostEqual(payload["selected_duplicate_baseline_score"], 11.53)
            self.assertAlmostEqual(payload["selected_duplicate_baseline_delta_vs_preferred"], 0.0)
            self.assertEqual(
                payload["selected_top_scenario_profile"],
                "attention-burst | funding_multiplier=1.5, liquidity_penalty_bps=30.0, name=attention-burst",
            )
            self.assertEqual(
                payload["selected_top_fragile_profile"],
                "outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock",
            )
            self.assertEqual(
                payload["selected_top_runtime_profile"],
                "search_summary_limit=3, slippage_bps=5.0",
            )
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if continue_output_dir.exists():
                import shutil
            shutil.rmtree(continue_output_dir, ignore_errors=True)

            if batch_report_path.exists():
                batch_report_path.unlink()
            if output_dir.exists():
                import shutil
                shutil.rmtree(output_dir, ignore_errors=True)

    def test_cli_trace_lineage_reads_continued_autoresearch_report(self) -> None:
        output_dir = Path("test-output-cli-trace-lineage")
        db_path = Path("test-output-cli-trace-lineage.sqlite")
        continue_output_dir = output_dir / "continued"
        output_dir.mkdir(exist_ok=True)
        try:
            batch_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "batch-autoresearch",
                    "--config",
                    "examples\\minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(batch_completed.returncode, 0, msg=batch_completed.stderr)
            batch_payload = json.loads(batch_completed.stdout)

            continue_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "continue-batch",
                    "--batch-report",
                    str(batch_payload["batch_report_path"]),
                    "--variant",
                    "preferred",
                    "--output-dir",
                    str(continue_output_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(continue_completed.returncode, 0, msg=continue_completed.stderr)
            continue_payload = json.loads(continue_completed.stdout)

            trace_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "trace-lineage",
                    "--autoresearch-report",
                    str(continue_payload["autoresearch_report_path"]),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(trace_completed.returncode, 0, msg=trace_completed.stderr)
            self.assertIn("Run: example-study-next-continued", trace_completed.stdout)
            self.assertIn("Selected variant: balanced", trace_completed.stdout)
            self.assertIn("Selection source: batch_report", trace_completed.stdout)
            self.assertIn("Selection mode: preferred", trace_completed.stdout)
            self.assertIn("Parent batch run: example-study", trace_completed.stdout)
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if continue_output_dir.exists():
                import shutil
            shutil.rmtree(continue_output_dir, ignore_errors=True)

            for path in output_dir.glob("*"):
                if path.is_file():
                    path.unlink()

    def test_cli_trace_lineage_prints_profile_rationale_when_present(self) -> None:
        report_path = Path("test-output-cli-trace-lineage-rationale.json")
        report_path.write_text(
            json.dumps(
                {
                    "run_id": "example-study-next-continued",
                    "status": "promoted",
                    "research_lineage": {
                        "selected_variant": "balanced",
                        "selection_source": "batch_report",
                        "selection_preference_mode": "preferred",
                        "parent_batch_run_id": "example-study",
                        "parent_batch_report_path": "outputs\\example-study.variant-batch.json",
                        "source_config_path": "outputs\\example-study-next.json",
                        "selection_variant_result": {
                            "variant": "balanced",
                            "duplicate_baseline_history": {
                                "sample_count": 2,
                                "promoted_count": 2,
                                "success_rate": 1.0,
                                "average_sharpe": 0.51,
                                "scenario_profile_hints": {
                                    "attention-burst": {
                                        "count": 2,
                                        "profile": {
                                            "funding_multiplier": 1.5,
                                            "liquidity_penalty_bps": 30.0,
                                            "name": "attention-burst",
                                        },
                                    }
                                },
                                "scenario_profile_avoidance": {
                                    "outage-shock": {
                                        "count": 2,
                                        "profile": {
                                            "latency_delta_bars": 3,
                                            "liquidity_penalty_bps": 65.0,
                                            "name": "outage-shock",
                                        },
                                    }
                                },
                                "runtime_profile_hints": {
                                    "count": 2,
                                    "profile": {
                                        "search_summary_limit": 3,
                                        "slippage_bps": 5.0,
                                    },
                                },
                            },
                        },
                    },
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "trace-lineage",
                    "--autoresearch-report",
                    str(report_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Duplicate baseline score: 11.53", completed.stdout)
            self.assertIn(
                "Top scenario profile: attention-burst | funding_multiplier=1.5, liquidity_penalty_bps=30.0, name=attention-burst",
                completed.stdout,
            )
            self.assertIn(
                "Top fragile profile: outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock",
                completed.stdout,
            )
            self.assertIn(
                "Top runtime profile: search_summary_limit=3, slippage_bps=5.0",
                completed.stdout,
            )
        finally:
            if report_path.exists():
                report_path.unlink()

    def test_cli_continue_accepted_duplicate_runs_new_autoresearch_cycle(self) -> None:
        output_dir = Path("test-output-cli-continue-accepted-duplicate")
        db_path = Path("test-output-cli-continue-accepted-duplicate.sqlite")
        continue_output_dir = output_dir / "continued"
        history_dir = output_dir / "history"
        output_dir.mkdir(exist_ok=True)
        history_dir.mkdir(exist_ok=True)
        try:
            for run_id, decision, scenario_profile in [
                (
                    "history-promoted",
                    "promoted",
                    {
                        "attention-burst": {
                            "funding_multiplier": 1.5,
                            "liquidity_penalty_bps": 30.0,
                            "name": "attention-burst",
                        }
                    },
                ),
                (
                    "history-blocked-a",
                    "blocked",
                    {
                        "outage-shock": {
                            "latency_delta_bars": 3,
                            "liquidity_penalty_bps": 65.0,
                            "name": "outage-shock",
                        }
                    },
                ),
                (
                    "history-blocked-b",
                    "blocked",
                    {
                        "outage-shock": {
                            "latency_delta_bars": 3,
                            "liquidity_penalty_bps": 65.0,
                            "name": "outage-shock",
                        }
                    },
                ),
            ]:
                save_runcard(
                    history_dir / f"{run_id}.runcard.json",
                    RunCard(
                        run_id=run_id,
                        strategy_hash=f"{run_id}-hash",
                        phase="phase-5",
                        split_id="snap:60-20-20",
                        seed=7,
                        decision=PromotionDecision(decision=decision, reasons=[]),
                        metrics={
                            "selection_oos_sharpe": 0.42 if decision == "promoted" else 0.11,
                            "selection_oos_net_pnl": 145.0 if decision == "promoted" else 35.0,
                            "selection_oos_drawdown": -0.12 if decision == "promoted" else -0.28,
                            "scenario_pass_rate": 0.8 if decision == "promoted" else 0.2,
                            "accepted_layers": 1.0,
                        },
                        artifacts={
                            "snapshot_id": f"{run_id}-snap",
                            "final_status": decision,
                            "symbol": "SOLUSDT",
                            "venue": "binance",
                            "snapshot_quality_status": "clean",
                            "snapshot_quality_flag_count": "0",
                            "snapshot_quality_flags_json": "[]",
                            "scenario_profiles_json": json.dumps(scenario_profile, sort_keys=True),
                            "runtime_settings_json": json.dumps(
                                {"search_summary_limit": 3, "slippage_bps": 5.0},
                                sort_keys=True,
                            ),
                            "selected_parameters_json": json.dumps({"kama": {"aggressiveness": 2}}, sort_keys=True),
                            "parameter_search_json": "{}",
                        },
                    ),
                )
                (history_dir / f"{run_id}.dashboard.json").write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "strategy": {"backbone": "mom_squeeze", "layers": ["kama"], "risk_guards": []},
                            "phases": [
                                {
                                    "phase_name": "phase-2",
                                    "layer_name": "kama",
                                    "decision": "accept" if decision == "promoted" else "reject",
                                    "accepted": decision == "promoted",
                                    "selected_parameters": {"aggressiveness": 2},
                                }
                            ],
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                (history_dir / f"{run_id}.autoresearch.json").write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "status": decision,
                            "research_lineage": {
                                "selected_variant": "balanced",
                                "accepted_duplicate_match_run_id": "prior-same-study",
                            },
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, history_dir)

            accepted_config_path = output_dir / "example-study.accepted-duplicate.json"
            accepted_payload = json.loads(Path("examples\\minimal_builtin_study.json").read_text(encoding="utf-8"))
            accepted_payload["run_id"] = "example-study-accepted-duplicate"
            accepted_payload["research_lineage"] = {
                "accepted_duplicate_match_run_id": "prior-same-study",
                "accepted_duplicate_match_type": "duplicate_match",
                "accepted_duplicate_source_report": str(output_dir / "example-study.autoresearch.json"),
            }
            accepted_payload["incumbent"]["layers"] = ["kama"]
            accepted_payload["directional_layers"] = []
            accepted_payload["layer_parameters"] = {"kama": {"aggressiveness": 2}}
            accepted_config_path.write_text(json.dumps(accepted_payload, indent=2, sort_keys=True), encoding="utf-8")

            autoresearch_report_path = output_dir / "example-study.autoresearch.json"
            autoresearch_report_path.write_text(
                json.dumps(
                    {
                        "run_id": "example-study",
                        "status": "skipped",
                        "skip_reason": "duplicate_study_signature",
                        "accepted_duplicate_config_path": str(accepted_config_path),
                        "duplicate_match": {
                            "match_type": "study_signature",
                            "run_id": "prior-same-study",
                        },
                        "memory_summary": {},
                        "hypotheses": [],
                        "research_lineage": {},
                        "runcard_path": None,
                        "dashboard_path": None,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "continue-accepted-duplicate",
                    "--autoresearch-report",
                    str(autoresearch_report_path),
                    "--output-dir",
                    str(continue_output_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["run_id"], "example-study-accepted-duplicate-continued")
            self.assertIn(payload["status"], ("promoted", "blocked", "wash"))
            self.assertAlmostEqual(payload["selected_duplicate_baseline_score"], 6.97, places=2)
            self.assertEqual(
                payload["selected_top_scenario_profile"],
                "attention-burst | funding_multiplier=1.5, liquidity_penalty_bps=30.0, name=attention-burst",
            )
            self.assertEqual(
                payload["selected_top_fragile_profile"],
                "outage-shock | latency_delta_bars=3, liquidity_penalty_bps=65.0, name=outage-shock",
            )
            self.assertEqual(
                payload["selected_top_runtime_profile"],
                "search_summary_limit=3, slippage_bps=5.0",
            )
            self.assertTrue((continue_output_dir / "example-study-accepted-duplicate-continued.continued-study.json").exists())
            self.assertTrue((continue_output_dir / "example-study-accepted-duplicate-continued.autoresearch.json").exists())
            self.assertTrue((continue_output_dir / "example-study-accepted-duplicate-continued.runcard.json").exists())
            continued_study_payload = json.loads(
                (continue_output_dir / "example-study-accepted-duplicate-continued.continued-study.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                continued_study_payload["research_lineage"]["accepted_duplicate_source_config_path"],
                str(accepted_config_path),
            )
            self.assertEqual(
                continued_study_payload["research_lineage"]["accepted_duplicate_source_report_path"],
                str(autoresearch_report_path),
            )
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if continue_output_dir.exists():
                import shutil
            shutil.rmtree(continue_output_dir, ignore_errors=True)

            if history_dir.exists():
                for path in history_dir.glob("*"):
                    path.unlink()
                history_dir.rmdir()
            for path in output_dir.glob("*"):
                if path.is_file():
                    path.unlink()

    def test_cli_inspect_study_reports_snapshot_quality_flags(self) -> None:
        candles_path = Path("test-cli-inspect-candles.csv")
        funding_path = Path("test-cli-inspect-funding.csv")
        config_path = Path("test-cli-inspect-study.json")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            for hour in range(120):
                writer.writerow(
                    {
                        "timestamp": f"2024-01-{1 + (hour // 24):02d}T{hour % 24:02d}:00:00+00:00",
                        "open": str(100 + hour),
                        "high": str(101 + hour),
                        "low": str(99 + hour),
                        "close": str(100 + hour),
                        "volume": "1000",
                    }
                )

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "funding_rate"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "funding_rate": "0.0001"})

        try:
            init_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "init-example-bundle",
                    "--candles-csv",
                    str(candles_path),
                    "--funding-csv",
                    str(funding_path),
                    "--config-out",
                    str(config_path),
                    "--snapshot-id",
                    "inspect-snap",
                    "--symbol",
                    "SOLUSDT",
                    "--venue",
                    "binance",
                    "--timeframe",
                    "1h",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_completed.returncode, 0, msg=init_completed.stderr)

            inspect_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "inspect-study",
                    "--config",
                    str(config_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(inspect_completed.returncode, 0, msg=inspect_completed.stderr)
            self.assertIn("Study: example-study", inspect_completed.stdout)
            self.assertIn("Snapshot: inspect-snap", inspect_completed.stdout)
            self.assertIn("Funding coverage:", inspect_completed.stdout)
            self.assertIn("Quality report: failed", inspect_completed.stdout)
            self.assertIn("Build version: phase1_snapshot_builder_v1", inspect_completed.stdout)
            self.assertIn("Source hash:", inspect_completed.stdout)
            self.assertIn("Candle span:", inspect_completed.stdout)
            self.assertIn("missing_funding_rate_count=", inspect_completed.stdout)
        finally:
            for path in (candles_path, funding_path, config_path):
                if path.exists():
                    path.unlink()

    def test_cli_run_strict_quality_blocks_dirty_snapshot(self) -> None:
        config_path = Path("test-cli-strict-quality-run.json")
        output_dir = Path("test-output-cli-strict-quality-run")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        output_dir.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "strict-quality-run",
                    "seed": 3,
                    "runtime": {"mode": "builtin"},
                    "snapshot": {
                        "snapshot_id": "strict-quality-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": ["missing_funding_rate_count=119"],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [],
                    "holdout_decision": {"decision": "accept", "reasons": []},
                }
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "run",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                    "--strict-quality",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("strict-quality", completed.stderr)
            self.assertIn("missing_funding_rate_count=119", completed.stderr)
            self.assertIn("inspect-study", completed.stderr)
            self.assertFalse((output_dir / "strict-quality-run.runcard.json").exists())
        finally:
            if config_path.exists():
                config_path.unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


    def test_cli_autoresearch_strict_quality_blocks_dirty_snapshot(self) -> None:
        config_path = Path("test-cli-strict-quality-autoresearch.json")
        output_dir = Path("test-output-cli-strict-quality-autoresearch")
        db_path = Path("test-output-cli-strict-quality-autoresearch.sqlite")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        output_dir.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "strict-quality-autoresearch",
                    "seed": 4,
                    "runtime": {"mode": "builtin"},
                    "snapshot": {
                        "snapshot_id": "strict-quality-auto-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": ["missing_open_interest_count=120"],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [],
                    "holdout_decision": {"decision": "accept", "reasons": []},
                }
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "autoresearch",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--strict-quality",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("strict-quality", completed.stderr)
            self.assertIn("missing_open_interest_count=120", completed.stderr)
            self.assertIn("inspect-study", completed.stderr)
            self.assertFalse((output_dir / "strict-quality-autoresearch.autoresearch.json").exists())
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_cli_mcp_call_compare_validation_results_surfaces_validation_bundle_drift(self) -> None:
        output_dir = Path("test-output-cli-mcp-compare-validation").resolve()
        db_path = (output_dir / "memory.sqlite").resolve()
        left_path = (output_dir / "left.dashboard.json").resolve()
        right_path = (output_dir / "right.dashboard.json").resolve()
        output_dir.mkdir(exist_ok=True)
        left_path.write_text(
            json.dumps(
                {
                    "run_id": "left-run",
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_path.write_text(
            json.dumps(
                {
                    "run_id": "right-run",
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "mcp-call",
                    "--profile",
                    "read_only",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--tool",
                    "compare_validation_results",
                    "--params",
                    json.dumps({"path_a": str(left_path), "path_b": str(right_path)}, sort_keys=True),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["run_id_a"], "left-run")
            self.assertEqual(payload["run_id_b"], "right-run")
            self.assertEqual(payload["pbo_a"], 0.27)
            self.assertEqual(payload["pbo_b"], 0.08)
            self.assertEqual(payload["spa_a"], 0.12)
            self.assertEqual(payload["spa_b"], 0.02)
            self.assertEqual(payload["failed_gates_a"], ["deflated_sharpe_ratio", "pbo", "spa"])
            self.assertEqual(payload["failed_gates_b"], [])
            self.assertEqual(payload["validation_bundle_change"]["changed_fields"]["status"], {"left": "failed", "right": "passed"})
            self.assertEqual(payload["validation_bundle_change"]["changed_fields"]["pbo_score"], {"left": 0.27, "right": 0.08})
            self.assertEqual(payload["validation_bundle_change"]["changed_fields"]["spa_pvalue"], {"left": 0.12, "right": 0.02})
            self.assertEqual(payload["validation_bundle_change"]["changed_fields"]["failed_gates"], {"left": ["deflated_sharpe_ratio", "pbo", "spa"], "right": []})
            self.assertEqual(payload["validation_bundle_a"]["status"], "failed")
            self.assertEqual(payload["validation_bundle_a"]["pbo_score"], 0.27)
            self.assertEqual(payload["validation_bundle_a"]["spa_pvalue"], 0.12)
            self.assertEqual(payload["validation_bundle_a"]["failed_gates"], ["deflated_sharpe_ratio", "pbo", "spa"])
            self.assertEqual(payload["validation_bundle_b"]["status"], "passed")
            self.assertEqual(payload["validation_bundle_b"]["pbo_score"], 0.08)
            self.assertEqual(payload["validation_bundle_b"]["spa_pvalue"], 0.02)
            self.assertEqual(payload["validation_bundle_b"]["failed_gates"], [])
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_cli_mcp_call_get_validation_protocol_surfaces_phase2_fields(self) -> None:
        output_dir = Path("test-output-cli-mcp-get-validation").resolve()
        db_path = (output_dir / "memory.sqlite").resolve()
        dashboard_path = (output_dir / "protocol.dashboard.json").resolve()
        output_dir.mkdir(exist_ok=True)
        dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "protocol-run",
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "mcp-call",
                    "--profile",
                    "read_only",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--tool",
                    "get_validation_protocol",
                    "--params",
                    json.dumps({"path": str(dashboard_path)}, sort_keys=True),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["deflated_sharpe_ratio"], 0.91)
            self.assertEqual(payload["probabilistic_sharpe_ratio"], 0.88)
            self.assertEqual(payload["pbo_score"], 0.27)
            self.assertEqual(payload["spa_pvalue"], 0.12)
            self.assertFalse(payload["validation_gate_results"]["pbo"])
            self.assertFalse(payload["validation_gate_results"]["spa"])
            self.assertEqual(payload["validation_bundle"]["status"], "failed")
            self.assertEqual(payload["validation_bundle"]["pbo_score"], 0.27)
            self.assertEqual(payload["validation_bundle"]["spa_pvalue"], 0.12)
            self.assertEqual(payload["validation_bundle"]["failed_gates"], ["deflated_sharpe_ratio", "pbo", "spa"])
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_cli_mcp_list_tools_surfaces_compare_validation_results_contract(self) -> None:
        completed = subprocess.run(
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
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        tools = {tool["name"]: tool for tool in payload["tools"]}
        self.assertIn("compare_validation_results", tools)
        self.assertIn("PBO", tools["compare_validation_results"]["description"])
        self.assertIn("SPA", tools["compare_validation_results"]["description"])
        self.assertIn("failed gates", tools["compare_validation_results"]["description"])

    def test_cli_mcp_list_tools_surfaces_get_validation_protocol_contract(self) -> None:
        completed = subprocess.run(
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
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        tools = {tool["name"]: tool for tool in payload["tools"]}
        self.assertIn("get_validation_protocol", tools)
        self.assertIn("PBO", tools["get_validation_protocol"]["description"])
        self.assertIn("SPA", tools["get_validation_protocol"]["description"])
        self.assertIn("failed gates", tools["get_validation_protocol"]["description"])

    def test_cli_summarize_run_matches_mcp_validation_protocol_phase2_fields(self) -> None:
        output_dir = Path("test-output-cli-summary-mcp-parity").resolve()
        db_path = (output_dir / "memory.sqlite").resolve()
        dashboard_path = (output_dir / "parity.dashboard.json").resolve()
        output_dir.mkdir(exist_ok=True)
        dashboard_path.write_text(
            json.dumps(
                {
                    "run_id": "parity-run",
                    "decision": "blocked",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            summary_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-run",
                    "--dashboard",
                    str(dashboard_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(summary_completed.returncode, 0, msg=summary_completed.stderr)

            mcp_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "mcp-call",
                    "--profile",
                    "read_only",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--tool",
                    "get_validation_protocol",
                    "--params",
                    json.dumps({"path": str(dashboard_path)}, sort_keys=True),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(mcp_completed.returncode, 0, msg=mcp_completed.stderr)

            mcp_payload = json.loads(mcp_completed.stdout)
            self.assertIn(f"Validation: {mcp_payload['status']}", summary_completed.stdout)
            self.assertIn(f"PBO: {mcp_payload['pbo_score']}", summary_completed.stdout)
            self.assertIn(f"SPA p-value: {mcp_payload['spa_pvalue']}", summary_completed.stdout)
            self.assertIn("Failed gates: deflated_sharpe_ratio, pbo, spa", summary_completed.stdout)
            self.assertFalse(mcp_payload["validation_gate_results"]["pbo"])
            self.assertFalse(mcp_payload["validation_gate_results"]["spa"])
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_cli_compare_run_text_matches_mcp_validation_compare_phase2_fields(self) -> None:
        output_dir = Path("test-output-cli-compare-mcp-parity").resolve()
        db_path = (output_dir / "memory.sqlite").resolve()
        left_path = (output_dir / "left.dashboard.json").resolve()
        right_path = (output_dir / "right.dashboard.json").resolve()
        output_dir.mkdir(exist_ok=True)
        left_path.write_text(
            json.dumps(
                {
                    "run_id": "left-run",
                    "decision": "blocked",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_path.write_text(
            json.dumps(
                {
                    "run_id": "right-run",
                    "decision": "promoted",
                    "metrics": {},
                    "phases": [],
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
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            compare_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--left",
                    str(left_path),
                    "--right",
                    str(right_path),
                    "--format",
                    "text",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(compare_completed.returncode, 0, msg=compare_completed.stderr)

            mcp_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "mcp-call",
                    "--profile",
                    "read_only",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--tool",
                    "compare_validation_results",
                    "--params",
                    json.dumps({"path_a": str(left_path), "path_b": str(right_path)}, sort_keys=True),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(mcp_completed.returncode, 0, msg=mcp_completed.stderr)

            mcp_payload = json.loads(mcp_completed.stdout)
            self.assertIn(f"pbo_score: {mcp_payload['pbo_a']} -> {mcp_payload['pbo_b']}", compare_completed.stdout)
            self.assertIn(f"spa_pvalue: {mcp_payload['spa_a']} -> {mcp_payload['spa_b']}", compare_completed.stdout)
            self.assertIn(
                "failed_gates: "
                + f"{', '.join(mcp_payload['failed_gates_a']) if mcp_payload['failed_gates_a'] else 'none'}"
                + " -> "
                + f"{', '.join(mcp_payload['failed_gates_b']) if mcp_payload['failed_gates_b'] else 'none'}",
                compare_completed.stdout,
            )
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)



if __name__ == "__main__":
    unittest.main()
