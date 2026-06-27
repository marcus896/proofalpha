import json
import subprocess
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.app.autoresearch import (
    _load_batch_run_summary,
    build_next_study_variants,
    load_duplicate_baseline_variant_history_for_lineage,
)
from engine.app.config import build_study_signature_from_payload
from engine.config.models import PromotionDecision, RunCard
from engine.memory.insights import build_memory_summary
from engine.memory.store import ingest_artifact_directory, initialize_memory_db
from engine.reporting.runcards import save_runcard


def _fixture_payload(run_id: str) -> dict:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return {
        "run_id": run_id,
        "seed": 41,
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
        "parameter_grids": {
            "kama": {
                "aggressiveness": {"minimum": 1.0, "maximum": 3.0, "step": 1.0},
                "mean_threshold_offset": {"minimum": 0.0, "maximum": 0.16, "step": 0.08},
            },
            "flat9": {
                "strictness": {"minimum": 1.0, "maximum": 3.0, "step": 1.0},
            },
        },
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
                "selected_parameters": {"aggressiveness": 2},
            },
            "flat9": {
                "decision": "reject",
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


def _write_memory_artifacts(
    directory: Path,
    run_id: str,
    decision: str,
    accepted_layers: list[str],
    rejected_layers: list[str],
    selected_parameters: dict[str, dict[str, int | float]] | None = None,
    quality_status: str = "clean",
    study_signature: str | None = None,
    research_lineage: dict[str, object] | None = None,
    scenario_profiles: dict[str, dict[str, object]] | None = None,
    snapshot_build_version: str | None = None,
    snapshot_source_hash: str | None = None,
    regime_summary: dict[str, object] | None = None,
) -> None:
    selected_parameters = selected_parameters or {layer: {"aggressiveness": 2} for layer in accepted_layers}
    scenario_profiles = scenario_profiles if scenario_profiles is not None else {
        "outage-shock": {
            "name": "outage-shock",
            "latency_delta_bars": 3,
            "liquidity_penalty_bps": 65.0,
        }
    }
    save_runcard(
        directory / f"{run_id}.runcard.json",
        RunCard(
            run_id=run_id,
            strategy_hash=f"{run_id}-hash",
            phase="phase-5",
            split_id="snap:60-20-20",
            seed=19,
            decision=PromotionDecision(decision=decision, reasons=[]),
            metrics={
                "selection_oos_sharpe": 0.51 if decision == "promoted" else 0.12,
                "selection_oos_net_pnl": 175.0 if decision == "promoted" else 60.0,
                "selection_oos_drawdown": -0.11 if decision == "promoted" else -0.26,
                "scenario_pass_rate": 1.0 if decision == "promoted" else 0.4,
                "accepted_layers": float(len(accepted_layers)),
            },
            artifacts={
                "snapshot_id": f"{run_id}-snap",
                "final_status": decision,
                "symbol": "SOLUSDT",
                "venue": "binance",
                "snapshot_quality_status": quality_status,
                "snapshot_quality_flag_count": "0" if quality_status == "clean" else "1",
                "snapshot_quality_flags_json": "[]" if quality_status == "clean" else '["missing_open_interest_count=120"]',
                "snapshot_build_version": snapshot_build_version or "",
                "snapshot_source_hash": snapshot_source_hash or "",
                "study_signature": study_signature or f"{run_id}-signature",
                "scenario_profiles_json": json.dumps(scenario_profiles, sort_keys=True),
                "regime_summary_json": json.dumps(regime_summary or {}, sort_keys=True),
                "selected_parameters_json": json.dumps(selected_parameters, sort_keys=True),
                "parameter_search_json": "{}",
            },
        ),
    )
    phases = []
    for layer in accepted_layers:
        phases.append(
            {
                "phase_name": "phase-2",
                "layer_name": layer,
                "decision": "accept",
                "accepted": True,
                "selected_parameters": {"aggressiveness": 2},
            }
        )
    for layer in rejected_layers:
        phases.append(
            {
                "phase_name": "phase-3",
                "layer_name": layer,
                "decision": "reject",
                "accepted": False,
                "selected_parameters": {},
            }
        )
    (directory / f"{run_id}.dashboard.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "strategy": {"backbone": "mom_squeeze", "layers": accepted_layers, "risk_guards": []},
                "phases": phases,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    if isinstance(research_lineage, dict):
        (directory / f"{run_id}.autoresearch.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": decision,
                    "research_lineage": research_lineage,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )


class AutoresearchCliTests(unittest.TestCase):
    def test_memory_summary_builds_regime_conditional_parameter_hints(self) -> None:
        rows = [
            {
                "decision": "promoted",
                "accepted_layers": ["kama"],
                "selected_parameters": {"kama": {"aggressiveness": 2}},
                "regime_summary": {
                    "regime_metadata": {
                        "regime_state_key": "short_squeeze|positive|low|rising_fast",
                    }
                },
            },
            {
                "decision": "promoted",
                "accepted_layers": ["kama"],
                "selected_parameters": {"kama": {"aggressiveness": 2}},
                "regime_summary": {
                    "regime_metadata": {
                        "regime_state_key": "short_squeeze|positive|low|rising_fast",
                    }
                },
            },
        ]

        summary = build_memory_summary(rows)

        hint = summary["regime_parameter_hints"]["short_squeeze|positive|low|rising_fast"]["parameter_hints"]["kama"][
            "aggressiveness"
        ]
        self.assertEqual(hint["minimum"], 2)
        self.assertEqual(hint["maximum"], 2)
        self.assertEqual(hint["confidence"], "high")

    def test_load_batch_run_summary_includes_agent_loop_metadata_from_dashboard(self) -> None:
        root = Path("test-load-batch-run-summary")
        root.mkdir(exist_ok=True)
        runcard_path = root / "batch-run.runcard.json"
        dashboard_path = root / "batch-run.dashboard.json"
        try:
            save_runcard(
                runcard_path,
                RunCard(
                    run_id="batch-run",
                    strategy_hash="batch-hash",
                    phase="phase-5",
                    split_id="snap:60-20-20",
                    seed=17,
                    decision=PromotionDecision(decision="promoted", reasons=[]),
                    metrics={
                        "selection_oos_sharpe": 0.73,
                        "selection_oos_drawdown": -0.14,
                        "scenario_pass_rate": 1.0,
                        "accepted_layers": 2.0,
                    },
                    artifacts={
                        "snapshot_id": "batch-run-snap",
                        "final_status": "promoted",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "snapshot_quality_status": "clean",
                        "snapshot_quality_flag_count": "0",
                        "snapshot_quality_flags_json": "[]",
                    },
                ),
            )
            dashboard_path.write_text(
                json.dumps(
                    {
                        "run_id": "batch-run",
                        "agent_loop_metadata": {
                            "loop_id": "loop-7",
                            "failure_taxonomy_counts": {"stress_failure": 2},
                            "next_hypotheses": ["harden_stress_scenarios"],
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            summary = _load_batch_run_summary(
                run_id="batch-run",
                status="promoted",
                runcard_path=str(runcard_path),
                dashboard_path=str(dashboard_path),
            )

            self.assertEqual(summary["selection_oos_sharpe"], 0.73)
            self.assertEqual(summary["scenario_pass_rate"], 1.0)
            self.assertEqual(
                summary["agent_loop_metadata"],
                {
                    "loop_id": "loop-7",
                    "failure_taxonomy_counts": {"stress_failure": 2},
                    "next_hypotheses": ["harden_stress_scenarios"],
                },
            )
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_load_duplicate_baseline_variant_history_for_lineage_prefers_compatible_snapshot_build(self) -> None:
        root = Path("test-duplicate-baseline-compatibility")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _write_memory_artifacts(
                artifacts_dir,
                "compatible-variant-run",
                "promoted",
                ["kama"],
                [],
                research_lineage={
                    "selected_variant": "balanced",
                    "accepted_duplicate_match_run_id": "baseline-accepted",
                },
                snapshot_build_version="phase1_snapshot_builder_v1",
                snapshot_source_hash="hash-compatible",
            )
            _write_memory_artifacts(
                artifacts_dir,
                "incompatible-variant-run",
                "promoted",
                ["flat9"],
                [],
                research_lineage={
                    "selected_variant": "balanced",
                    "accepted_duplicate_match_run_id": "baseline-accepted",
                },
                snapshot_build_version="phase1_snapshot_builder_v1",
                snapshot_source_hash="hash-incompatible",
            )

            initialize_memory_db(db_path)
            ingest_artifact_directory(db_path, artifacts_dir)

            history = load_duplicate_baseline_variant_history_for_lineage(
                db_path=db_path,
                research_lineage={"accepted_duplicate_match_run_id": "baseline-accepted"},
                memory_quality_policy="clean-only",
                snapshot_provenance={
                    "build_version": "phase1_snapshot_builder_v1",
                    "source_hash": "hash-compatible",
                },
            )

            self.assertEqual(history["balanced"]["sample_count"], 1)
            self.assertEqual(history["balanced"]["promoted_count"], 1)
            self.assertEqual(history["balanced"]["promising_layers"], [{"layer_name": "kama", "count": 1}])
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_ingest_artifact_directory_skips_unchanged_artifact_groups(self) -> None:
        root = Path("test-artifact-ingestion-skip")
        artifacts_dir = root / "artifacts"
        db_path = root / "research-memory.sqlite"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        try:
            _write_memory_artifacts(
                artifacts_dir,
                "skip-run",
                "promoted",
                ["kama"],
                [],
                research_lineage={"selected_variant": "balanced"},
            )

            self.assertEqual(ingest_artifact_directory(db_path, artifacts_dir), 1)
            self.assertEqual(ingest_artifact_directory(db_path, artifacts_dir), 0)

            dashboard_path = artifacts_dir / "skip-run.dashboard.json"
            dashboard_payload = json.loads(dashboard_path.read_text(encoding="utf-8"))
            dashboard_payload["phases"].append(
                {
                    "phase_name": "phase-2",
                    "layer_name": "hull",
                    "decision": "accept",
                    "accepted": True,
                    "selected_parameters": {"aggressiveness": 2},
                }
            )
            dashboard_path.write_text(json.dumps(dashboard_payload, sort_keys=True), encoding="utf-8")

            self.assertEqual(ingest_artifact_directory(db_path, artifacts_dir), 1)
            self.assertEqual(ingest_artifact_directory(db_path, artifacts_dir), 0)
        finally:
            if root.exists():
                for path in sorted(root.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                if root.exists():
                    root.rmdir()

    def test_build_next_study_variants_reorders_layers_using_duplicate_baseline_history(self) -> None:
        payload = _fixture_payload("variant-order")
        payload["directional_layers"] = ["ema", "kama", "hull"]
        memory_summary = {
            "promising_layers": [{"layer_name": "kama", "count": 2}],
            "fragile_layers": [],
            "parameter_hints": {},
            "top_duplicate_matches": [],
        }
        duplicate_baseline_history = {
            "conservative": {
                "sample_count": 2,
                "promoted_count": 2,
                "success_rate": 1.0,
                "average_sharpe": 0.6,
                "duplicate_baseline_run_id": "seed-baseline-a",
                "promising_layers": [
                    {"layer_name": "hull", "count": 2},
                    {"layer_name": "ema", "count": 1},
                ],
            }
        }

        variants = build_next_study_variants(
            payload,
            memory_summary,
            duplicate_baseline_history_by_variant=duplicate_baseline_history,
        )

        self.assertEqual(variants["balanced"]["directional_layers"], ["kama", "ema", "hull"])
        self.assertEqual(variants["conservative"]["directional_layers"], ["hull", "ema", "kama"])

    def test_build_next_study_variants_refines_parameters_using_duplicate_baseline_history(self) -> None:
        payload = _fixture_payload("variant-params")
        memory_summary = {
            "promising_layers": [{"layer_name": "kama", "count": 2}],
            "fragile_layers": [],
            "parameter_hints": {
                "kama": {
                    "aggressiveness": {
                        "minimum": 1.0,
                        "maximum": 3.0,
                        "promoted_count": 2,
                        "blocked_values": [],
                        "confidence": "medium",
                        "narrowed": False,
                    }
                }
            },
            "top_duplicate_matches": [],
        }
        duplicate_baseline_history = {
            "conservative": {
                "sample_count": 2,
                "promoted_count": 2,
                "success_rate": 1.0,
                "average_sharpe": 0.6,
                "duplicate_baseline_run_id": "seed-baseline-a",
                "parameter_hints": {
                    "kama": {
                        "aggressiveness": {
                            "minimum": 2.0,
                            "maximum": 2.0,
                            "promoted_count": 2,
                            "blocked_values": [1.0],
                            "confidence": "high",
                            "narrowed": True,
                        }
                    }
                },
            }
        }

        variants = build_next_study_variants(
            payload,
            memory_summary,
            duplicate_baseline_history_by_variant=duplicate_baseline_history,
        )

        self.assertEqual(variants["balanced"]["parameter_grids"]["kama"]["aggressiveness"]["minimum"], 1.0)
        self.assertEqual(variants["balanced"]["parameter_grids"]["kama"]["aggressiveness"]["maximum"], 3.0)
        self.assertEqual(variants["conservative"]["parameter_grids"]["kama"]["aggressiveness"]["minimum"], 2.0)
        self.assertEqual(variants["conservative"]["parameter_grids"]["kama"]["aggressiveness"]["maximum"], 2.0)
        self.assertEqual(
            variants["conservative"]["parameter_avoidance"]["kama"]["aggressiveness"],
            [1.0],
        )

    def test_build_next_study_variants_prefers_matching_regime_parameter_hints(self) -> None:
        payload = _fixture_payload("variant-regime-params")
        payload["snapshot"]["funding_rates"] = [0.002] * 120
        payload["snapshot"]["open_interest"] = [100.0 + index for index in range(120)]
        memory_summary = {
            "promising_layers": [{"layer_name": "kama", "count": 2}],
            "fragile_layers": [],
            "parameter_hints": {
                "kama": {
                    "aggressiveness": {
                        "minimum": 1.0,
                        "maximum": 3.0,
                        "promoted_count": 2,
                        "blocked_values": [],
                        "confidence": "medium",
                        "narrowed": False,
                    }
                }
            },
            "regime_parameter_hints": {
                "short_squeeze|positive|low|rising_fast": {
                    "state_key": "short_squeeze|positive|low|rising_fast",
                    "parameter_hints": {
                        "kama": {
                            "aggressiveness": {
                                "minimum": 2.0,
                                "maximum": 2.0,
                                "promoted_count": 2,
                                "blocked_values": [],
                                "confidence": "high",
                                "narrowed": True,
                            }
                        }
                    },
                }
            },
            "top_duplicate_matches": [],
        }

        variants = build_next_study_variants(payload, memory_summary)

        self.assertEqual(variants["balanced"]["parameter_grids"]["kama"]["aggressiveness"]["minimum"], 2.0)
        self.assertEqual(variants["balanced"]["parameter_grids"]["kama"]["aggressiveness"]["maximum"], 2.0)
        self.assertTrue(
            variants["balanced"]["research_hypotheses"]["parameter_hints"]["kama"]["aggressiveness"][
                "regime_conditioned"
            ]
        )
        self.assertTrue(variants["balanced"]["research_hypotheses"]["regime_conditioning"]["used_regime_parameter_hints"])

    def test_build_next_study_variants_applies_memory_scenario_profile_hints_without_overwriting_explicit_knobs(self) -> None:
        payload = _fixture_payload("variant-scenarios")
        payload["scenarios"] = [
            {
                "name": "attention-burst",
                "severity": 0.6,
                "description": "Attention shock",
            },
            {
                "name": "outage-shock",
                "severity": 0.9,
                "description": "Venue disruption",
                "latency_delta_bars": 1,
            },
        ]
        memory_summary = {
            "promising_layers": [],
            "fragile_layers": [],
            "parameter_hints": {},
            "top_duplicate_matches": [],
            "scenario_profiles": [{"scenario_name": "outage-shock", "count": 2}],
            "scenario_profile_hints": {
                "outage-shock": {
                    "count": 2,
                    "profile": {
                        "name": "outage-shock",
                        "severity": 0.9,
                        "description": "Venue disruption",
                        "latency_delta_bars": 3,
                        "liquidity_penalty_bps": 65.0,
                        "drawdown_multiplier": 1.5,
                        "mark_premium_bps": 210.0,
                    },
                }
            },
        }

        variants = build_next_study_variants(payload, memory_summary)

        outage = variants["balanced"]["scenarios"][0]
        self.assertEqual(outage["name"], "outage-shock")
        self.assertEqual(outage["latency_delta_bars"], 1)
        self.assertEqual(outage["liquidity_penalty_bps"], 65.0)
        self.assertEqual(outage["drawdown_multiplier"], 1.5)
        self.assertEqual(outage["mark_premium_bps"], 210.0)
        self.assertEqual(
            variants["balanced"]["research_hypotheses"]["scenario_profile_hints"]["outage-shock"]["profile"][
                "liquidity_penalty_bps"
            ],
            65.0,
        )

    def test_build_next_study_variants_can_use_duplicate_baseline_scenario_profile_hints_per_variant(self) -> None:
        payload = _fixture_payload("variant-scenarios-duplicate")
        payload["scenarios"] = [
            {
                "name": "outage-shock",
                "severity": 0.9,
                "description": "Venue disruption",
            },
        ]
        memory_summary = {
            "promising_layers": [],
            "fragile_layers": [],
            "parameter_hints": {},
            "top_duplicate_matches": [],
            "scenario_profiles": [{"scenario_name": "outage-shock", "count": 2}],
            "scenario_profile_hints": {
                "outage-shock": {
                    "count": 2,
                    "profile": {
                        "name": "outage-shock",
                        "severity": 0.9,
                        "description": "Venue disruption",
                        "latency_delta_bars": 2,
                        "liquidity_penalty_bps": 55.0,
                    },
                }
            },
        }
        duplicate_baseline_history = {
            "conservative": {
                "sample_count": 2,
                "promoted_count": 2,
                "success_rate": 1.0,
                "average_sharpe": 0.6,
                "duplicate_baseline_run_id": "seed-baseline-a",
                "scenario_profiles": [{"scenario_name": "outage-shock", "count": 2}],
                "scenario_profile_hints": {
                    "outage-shock": {
                        "count": 2,
                        "profile": {
                            "name": "outage-shock",
                            "severity": 0.9,
                            "description": "Venue disruption",
                            "latency_delta_bars": 4,
                            "liquidity_penalty_bps": 80.0,
                        },
                    }
                },
            }
        }

        variants = build_next_study_variants(
            payload,
            memory_summary,
            duplicate_baseline_history_by_variant=duplicate_baseline_history,
        )

        self.assertEqual(variants["balanced"]["scenarios"][0]["latency_delta_bars"], 2)
        self.assertEqual(variants["balanced"]["scenarios"][0]["liquidity_penalty_bps"], 55.0)
        self.assertEqual(variants["conservative"]["scenarios"][0]["latency_delta_bars"], 4)
        self.assertEqual(variants["conservative"]["scenarios"][0]["liquidity_penalty_bps"], 80.0)

    def test_build_next_study_variants_applies_runtime_profile_hints_without_overwriting_explicit_runtime(self) -> None:
        payload = _fixture_payload("variant-runtime")
        payload["runtime"] = {
            "mode": "builtin",
            "search_summary_limit": 9,
        }
        memory_summary = {
            "promising_layers": [],
            "fragile_layers": [],
            "parameter_hints": {},
            "top_duplicate_matches": [],
            "runtime_profile_hints": {
                "count": 2,
                "profile": {
                    "slippage_bps": 7.0,
                    "search_summary_limit": 3,
                },
            },
        }
        duplicate_baseline_history = {
            "conservative": {
                "sample_count": 2,
                "promoted_count": 2,
                "success_rate": 1.0,
                "average_sharpe": 0.6,
                "duplicate_baseline_run_id": "seed-baseline-a",
                "runtime_profile_hints": {
                    "count": 2,
                    "profile": {
                        "slippage_bps": 11.0,
                        "search_summary_limit": 4,
                    },
                },
            }
        }

        variants = build_next_study_variants(
            payload,
            memory_summary,
            duplicate_baseline_history_by_variant=duplicate_baseline_history,
        )

        self.assertEqual(variants["balanced"]["runtime"]["slippage_bps"], 7.0)
        self.assertEqual(variants["balanced"]["runtime"]["search_summary_limit"], 9)
        self.assertEqual(variants["conservative"]["runtime"]["slippage_bps"], 11.0)
        self.assertEqual(variants["conservative"]["runtime"]["search_summary_limit"], 9)
        self.assertEqual(
            variants["balanced"]["research_hypotheses"]["runtime_profile_hints"]["profile"]["slippage_bps"],
            7.0,
        )
        self.assertEqual(
            variants["conservative"]["research_hypotheses"]["duplicate_baseline_history"]["runtime_profile_hints"]["profile"]["slippage_bps"],
            11.0,
        )

    def test_build_next_study_variants_avoids_exact_fragile_scenario_profile_from_memory(self) -> None:
        payload = _fixture_payload("variant-scenario-avoidance")
        payload["scenarios"] = [
            {
                "name": "outage-shock",
                "severity": 0.9,
                "description": "Venue disruption",
            },
        ]
        blocked_profile = {
            "name": "outage-shock",
            "severity": 0.9,
            "description": "Venue disruption",
            "latency_delta_bars": 3,
            "liquidity_penalty_bps": 65.0,
        }
        memory_summary = {
            "promising_layers": [],
            "fragile_layers": [],
            "parameter_hints": {},
            "top_duplicate_matches": [],
            "scenario_profiles": [{"scenario_name": "outage-shock", "count": 2}],
            "scenario_profile_hints": {
                "outage-shock": {
                    "count": 2,
                    "profile": blocked_profile,
                }
            },
            "scenario_profile_avoidance": {
                "outage-shock": {
                    "count": 2,
                    "profile": blocked_profile,
                }
            },
        }

        variants = build_next_study_variants(payload, memory_summary)

        self.assertNotIn("latency_delta_bars", variants["balanced"]["scenarios"][0])
        self.assertNotIn("liquidity_penalty_bps", variants["balanced"]["scenarios"][0])
        self.assertEqual(
            variants["balanced"]["scenario_profile_avoidance"]["outage-shock"]["profile"]["latency_delta_bars"],
            3,
        )

    def test_build_next_study_variants_can_use_variant_specific_safe_scenario_profile_when_global_profile_is_avoided(
        self,
    ) -> None:
        payload = _fixture_payload("variant-scenario-avoidance-duplicate")
        payload["scenarios"] = [
            {
                "name": "outage-shock",
                "severity": 0.9,
                "description": "Venue disruption",
            },
        ]
        blocked_profile = {
            "name": "outage-shock",
            "severity": 0.9,
            "description": "Venue disruption",
            "latency_delta_bars": 2,
            "liquidity_penalty_bps": 55.0,
        }
        memory_summary = {
            "promising_layers": [],
            "fragile_layers": [],
            "parameter_hints": {},
            "top_duplicate_matches": [],
            "scenario_profiles": [{"scenario_name": "outage-shock", "count": 2}],
            "scenario_profile_hints": {
                "outage-shock": {
                    "count": 2,
                    "profile": blocked_profile,
                }
            },
            "scenario_profile_avoidance": {
                "outage-shock": {
                    "count": 2,
                    "profile": blocked_profile,
                }
            },
        }
        duplicate_baseline_history = {
            "conservative": {
                "sample_count": 2,
                "promoted_count": 2,
                "success_rate": 1.0,
                "average_sharpe": 0.6,
                "duplicate_baseline_run_id": "seed-baseline-a",
                "scenario_profiles": [{"scenario_name": "outage-shock", "count": 2}],
                "scenario_profile_hints": {
                    "outage-shock": {
                        "count": 2,
                        "profile": {
                            "name": "outage-shock",
                            "severity": 0.9,
                            "description": "Venue disruption",
                            "latency_delta_bars": 4,
                            "liquidity_penalty_bps": 80.0,
                        },
                    }
                },
                "scenario_profile_avoidance": {
                    "outage-shock": {
                        "count": 2,
                        "profile": blocked_profile,
                    }
                },
            }
        }

        variants = build_next_study_variants(
            payload,
            memory_summary,
            duplicate_baseline_history_by_variant=duplicate_baseline_history,
        )

        self.assertNotIn("latency_delta_bars", variants["balanced"]["scenarios"][0])
        self.assertEqual(variants["conservative"]["scenarios"][0]["latency_delta_bars"], 4)
        self.assertEqual(variants["conservative"]["scenarios"][0]["liquidity_penalty_bps"], 80.0)

    def test_build_next_study_variants_prunes_layers_using_duplicate_baseline_fragility(self) -> None:
        payload = _fixture_payload("variant-fragile")
        payload["directional_layers"] = ["ema", "kama", "hull"]
        memory_summary = {
            "promising_layers": [{"layer_name": "kama", "count": 2}],
            "fragile_layers": [],
            "parameter_hints": {},
            "top_duplicate_matches": [],
        }
        duplicate_baseline_history = {
            "conservative": {
                "sample_count": 2,
                "promoted_count": 2,
                "success_rate": 1.0,
                "average_sharpe": 0.6,
                "duplicate_baseline_run_id": "seed-baseline-a",
                "fragile_layers": [
                    {"layer_name": "ema", "count": 2},
                ],
            }
        }

        variants = build_next_study_variants(
            payload,
            memory_summary,
            duplicate_baseline_history_by_variant=duplicate_baseline_history,
        )

        self.assertEqual(variants["balanced"]["directional_layers"], ["kama", "ema", "hull"])
        self.assertEqual(variants["conservative"]["directional_layers"], ["kama", "hull"])

    def test_build_next_study_variants_trim_blocked_parameter_edges_from_duplicate_baseline_history(self) -> None:
        payload = _fixture_payload("variant-edge-trim")
        memory_summary = {
            "promising_layers": [{"layer_name": "kama", "count": 2}],
            "fragile_layers": [],
            "parameter_hints": {
                "kama": {
                    "aggressiveness": {
                        "minimum": 1.0,
                        "maximum": 3.0,
                        "promoted_count": 2,
                        "blocked_values": [],
                        "confidence": "low",
                        "narrowed": False,
                    }
                }
            },
            "top_duplicate_matches": [],
        }
        duplicate_baseline_history = {
            "conservative": {
                "sample_count": 3,
                "promoted_count": 2,
                "success_rate": 0.66,
                "average_sharpe": 0.4,
                "duplicate_baseline_run_id": "seed-baseline-a",
                "parameter_hints": {
                    "kama": {
                        "aggressiveness": {
                            "minimum": 2.0,
                            "maximum": 3.0,
                            "promoted_count": 3,
                            "blocked_values": [1.0],
                            "confidence": "medium",
                            "narrowed": False,
                        }
                    }
                },
            }
        }

        variants = build_next_study_variants(
            payload,
            memory_summary,
            duplicate_baseline_history_by_variant=duplicate_baseline_history,
        )

        self.assertEqual(variants["balanced"]["parameter_grids"]["kama"]["aggressiveness"]["minimum"], 1.0)
        self.assertEqual(variants["balanced"]["parameter_grids"]["kama"]["aggressiveness"]["maximum"], 3.0)
        self.assertEqual(variants["conservative"]["parameter_grids"]["kama"]["aggressiveness"]["minimum"], 2.0)
        self.assertEqual(variants["conservative"]["parameter_grids"]["kama"]["aggressiveness"]["maximum"], 3.0)

    def test_build_next_study_variants_exclude_blocked_interior_parameter_values_from_duplicate_baseline_history(self) -> None:
        payload = _fixture_payload("variant-interior-exclude")
        payload["parameter_grids"]["kama"]["aggressiveness"] = {"minimum": 1.0, "maximum": 5.0, "step": 1.0}
        memory_summary = {
            "promising_layers": [{"layer_name": "kama", "count": 2}],
            "fragile_layers": [],
            "parameter_hints": {
                "kama": {
                    "aggressiveness": {
                        "minimum": 1.0,
                        "maximum": 5.0,
                        "promoted_count": 2,
                        "blocked_values": [],
                        "confidence": "low",
                        "narrowed": False,
                    }
                }
            },
            "top_duplicate_matches": [],
        }
        duplicate_baseline_history = {
            "conservative": {
                "sample_count": 4,
                "promoted_count": 3,
                "success_rate": 0.75,
                "average_sharpe": 0.5,
                "duplicate_baseline_run_id": "seed-baseline-a",
                "parameter_hints": {
                    "kama": {
                        "aggressiveness": {
                            "minimum": 1.0,
                            "maximum": 5.0,
                            "promoted_count": 4,
                            "blocked_values": [3.0],
                            "confidence": "high",
                            "narrowed": False,
                        }
                    }
                },
            }
        }

        variants = build_next_study_variants(
            payload,
            memory_summary,
            duplicate_baseline_history_by_variant=duplicate_baseline_history,
        )

        self.assertNotIn("excluded_values", variants["balanced"]["parameter_grids"]["kama"]["aggressiveness"])
        self.assertEqual(
            variants["conservative"]["parameter_grids"]["kama"]["aggressiveness"]["excluded_values"],
            [3.0],
        )

    def test_batch_autoresearch_runs_all_variants_and_writes_summary(self) -> None:
        config_path = Path("test-study-batch-autoresearch.json")
        output_dir = Path("test-output-batch-autoresearch")
        memory_seed_dir = Path("test-memory-batch-autoresearch")
        db_path = Path("test-output-batch-autoresearch.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        config_path.write_text(json.dumps(_fixture_payload("batch-run")), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "batch-prior-promoted-a",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2, "mean_threshold_offset": 0.08}},
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "batch-prior-promoted-b",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2, "mean_threshold_offset": 0.08}},
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "batch-autoresearch",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["run_id"], "batch-run")
            self.assertTrue(str(payload["batch_report_path"]).endswith("batch-run.variant-batch.json"))
            self.assertEqual(set(payload["variant_runs"].keys()), {"balanced", "conservative", "exploratory"})
            self.assertTrue((output_dir / "batch-run-next.runcard.json").exists())
            self.assertTrue((output_dir / "batch-run-next-conservative.runcard.json").exists())
            self.assertTrue((output_dir / "batch-run-next-exploratory.runcard.json").exists())
            batch_payload = json.loads((output_dir / "batch-run.variant-batch.json").read_text(encoding="utf-8"))
            self.assertEqual(batch_payload["run_id"], "batch-run")
            self.assertEqual(batch_payload["base_run"]["run_id"], "batch-run")
            self.assertEqual(batch_payload["preferred_variant"]["variant"], "balanced")
            self.assertEqual(len(batch_payload["variant_results"]), 3)
            self.assertEqual(batch_payload["variant_results"][0]["variant"], "balanced")
            self.assertIn("compare_to_base", batch_payload["variant_results"][0])
            self.assertIn("metric_deltas", batch_payload["variant_results"][0]["compare_to_base"])
            self.assertIn("ranking", batch_payload["variant_results"][0])
            balanced_report = json.loads((output_dir / "batch-run-next.autoresearch.json").read_text(encoding="utf-8"))
            self.assertEqual(balanced_report["memory_summary"]["prior_runs"], 4)
            self.assertEqual(balanced_report["memory_summary"]["promoted_runs"], 4)
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)
                        
                    

    def test_batch_autoresearch_prefers_variant_with_stronger_duplicate_baseline_history(self) -> None:
        config_path = Path("test-study-batch-history-ranked.json")
        output_dir = Path("test-output-batch-history-ranked")
        memory_seed_dir = Path("test-memory-batch-history-ranked")
        db_path = Path("test-output-batch-history-ranked.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        payload = _fixture_payload("batch-history-ranked")
        payload["research_lineage"] = {
            "accepted_duplicate_match_run_id": "seed-baseline-a",
            "accepted_duplicate_match_type": "duplicate_match",
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "history-conservative-a",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2, "mean_threshold_offset": 0.08}},
            research_lineage={
                "selected_variant": "conservative",
                "accepted_duplicate_match_run_id": "seed-baseline-a",
                "accepted_duplicate_match_type": "duplicate_match",
            },
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "history-conservative-b",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2, "mean_threshold_offset": 0.08}},
            research_lineage={
                "selected_variant": "conservative",
                "accepted_duplicate_match_run_id": "seed-baseline-a",
                "accepted_duplicate_match_type": "duplicate_match",
            },
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "history-balanced-a",
            "blocked",
            [],
            ["flat9"],
            research_lineage={
                "selected_variant": "balanced",
                "accepted_duplicate_match_run_id": "seed-baseline-a",
                "accepted_duplicate_match_type": "duplicate_match",
            },
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "batch-autoresearch",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload_out = json.loads(completed.stdout)
            self.assertEqual(payload_out["preferred_variant"]["variant"], "conservative")
            batch_payload = json.loads((output_dir / "batch-history-ranked.variant-batch.json").read_text(encoding="utf-8"))
            self.assertEqual(batch_payload["preferred_variant"]["variant"], "conservative")
            self.assertEqual(batch_payload["variant_results"][0]["variant"], "conservative")
            self.assertEqual(batch_payload["variant_results"][0]["duplicate_baseline_history"]["sample_count"], 2)
            self.assertEqual(batch_payload["variant_results"][0]["duplicate_baseline_history"]["promoted_count"], 2)
            self.assertEqual(batch_payload["variant_results"][0]["duplicate_baseline_history"]["success_rate"], 1.0)
            self.assertEqual(batch_payload["variant_results"][0]["duplicate_baseline_score"], 11.53)
            self.assertEqual(batch_payload["variant_results"][0]["duplicate_baseline_delta_vs_preferred"], 0.0)
            balanced_result = next(
                result for result in batch_payload["variant_results"] if result["variant"] == "balanced"
            )
            self.assertEqual(balanced_result["duplicate_baseline_score"], 1.36)
            self.assertEqual(balanced_result["duplicate_baseline_delta_vs_preferred"], -10.17)

            query_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "query-memory",
                    "--db",
                    str(db_path),
                    "--selected-variant",
                    "conservative",
                    "--accepted-duplicate-match-run-id",
                    "seed-baseline-a",
                    "--format",
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            rows = json.loads(query_completed.stdout)
            run_ids = [row["run_id"] for row in rows]
            self.assertIn("batch-history-ranked-next-conservative", run_ids)
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)
                        
                    

    def test_batch_autoresearch_prefers_variant_with_stronger_scenario_profile_avoidance_history(self) -> None:
        config_path = Path("test-study-batch-scenario-avoidance-ranked.json")
        output_dir = Path("test-output-batch-scenario-avoidance-ranked")
        memory_seed_dir = Path("test-memory-batch-scenario-avoidance-ranked")
        db_path = Path("test-output-batch-scenario-avoidance-ranked.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        payload = _fixture_payload("batch-scenario-avoidance-ranked")
        payload["research_lineage"] = {
            "accepted_duplicate_match_run_id": "seed-baseline-scenarios",
            "accepted_duplicate_match_type": "duplicate_match",
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-seed-baseline",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2}},
        )
        for run_id in ("history-conservative-a", "history-conservative-b"):
            _write_memory_artifacts(
                memory_seed_dir,
                run_id,
                "blocked",
                [],
                ["flat9"],
                {"kama": {"aggressiveness": 2}},
                research_lineage={
                    "accepted_duplicate_match_run_id": "seed-baseline-scenarios",
                    "accepted_duplicate_match_type": "duplicate_match",
                    "selected_variant": "conservative",
                },
            )
        _write_memory_artifacts(
            memory_seed_dir,
            "history-balanced-a",
            "blocked",
            [],
            ["flat9"],
            {"kama": {"aggressiveness": 2}},
            research_lineage={
                "accepted_duplicate_match_run_id": "seed-baseline-scenarios",
                "accepted_duplicate_match_type": "duplicate_match",
                "selected_variant": "balanced",
            },
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "history-balanced-b",
            "blocked",
            [],
            ["flat9"],
            {"kama": {"aggressiveness": 2}},
            research_lineage={
                "accepted_duplicate_match_run_id": "seed-baseline-scenarios",
                "accepted_duplicate_match_type": "duplicate_match",
                "selected_variant": "balanced",
            },
            scenario_profiles={},
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "batch-autoresearch",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload_out = json.loads(completed.stdout)
            self.assertEqual(payload_out["preferred_variant"]["variant"], "conservative")
            batch_payload = json.loads((output_dir / "batch-scenario-avoidance-ranked.variant-batch.json").read_text(encoding="utf-8"))
            self.assertEqual(batch_payload["preferred_variant"]["variant"], "conservative")
            self.assertEqual(
                batch_payload["variant_results"][0]["duplicate_baseline_history"]["scenario_profile_avoidance_count"],
                2,
            )
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)
                        
                    

    def test_autoresearch_uses_memory_summary_and_ingests_new_run(self) -> None:
        config_path = Path("test-study-autoresearch.json")
        output_dir = Path("test-output-autoresearch")
        memory_seed_dir = Path("test-memory-autoresearch")
        db_path = Path("test-output-autoresearch.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        config_path.write_text(json.dumps(_fixture_payload("auto-run")), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-promoted-a",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2, "mean_threshold_offset": 0.08}},
            research_lineage={
                "accepted_duplicate_match_run_id": "seed-baseline-a",
                "accepted_duplicate_match_type": "duplicate_match",
                "accepted_duplicate_source_config_path": "test-memory-autoresearch/prior-promoted-a.accepted-duplicate.json",
                "accepted_duplicate_source_report_path": "test-memory-autoresearch/prior-promoted-a.autoresearch.json",
            },
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-promoted-b",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2, "mean_threshold_offset": 0.08}},
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-blocked-flat9",
            "blocked",
            [],
            ["flat9"],
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-blocked-kama",
            "blocked",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 1, "mean_threshold_offset": 0.16}},
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-dirty-promoted",
            "promoted",
            ["flat9"],
            [],
            {"flat9": {"strictness": 3}},
            quality_status="dirty",
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
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["run_id"], "auto-run")
            self.assertEqual(payload["status"], "promoted")
            self.assertEqual(payload["memory_summary"]["prior_runs"], 5)
            self.assertEqual(payload["memory_summary"]["promoted_runs"], 3)
            self.assertEqual(payload["memory_summary"]["blocked_runs"], 2)
            self.assertEqual(payload["memory_summary"]["excluded_dirty_runs"], 1)
            self.assertEqual(payload["memory_summary"]["recovered_duplicate_runs"], 1)
            self.assertEqual(payload["memory_summary"]["top_duplicate_matches"][0]["run_id"], "seed-baseline-a")
            self.assertEqual(payload["memory_summary"]["promising_layers"][0]["layer_name"], "kama")
            self.assertEqual(payload["memory_summary"]["fragile_layers"][0]["layer_name"], "flat9")
            self.assertTrue(str(payload["autoresearch_report_path"]).endswith("auto-run.autoresearch.json"))
            self.assertTrue(str(payload["next_study_config_path"]).endswith("auto-run.next-study.json"))
            self.assertEqual(
                set(payload["next_study_variant_paths"].keys()),
                {"balanced", "conservative", "exploratory"},
            )
            self.assertTrue((output_dir / "auto-run.runcard.json").exists())
            self.assertTrue((output_dir / "auto-run.autoresearch.json").exists())
            self.assertTrue((output_dir / "auto-run.next-study.json").exists())
            self.assertTrue((output_dir / "auto-run.next-study.conservative.json").exists())
            self.assertTrue((output_dir / "auto-run.next-study.exploratory.json").exists())
            self.assertTrue(db_path.exists())
            report_payload = json.loads((output_dir / "auto-run.autoresearch.json").read_text(encoding="utf-8"))
            self.assertEqual(report_payload["run_id"], "auto-run")
            self.assertEqual(report_payload["status"], "promoted")
            self.assertEqual(report_payload["memory_summary"]["prior_runs"], 5)
            self.assertEqual(report_payload["memory_summary"]["promoted_runs"], 3)
            self.assertEqual(report_payload["memory_summary"]["excluded_dirty_runs"], 1)
            self.assertEqual(report_payload["memory_summary"]["recovered_duplicate_runs"], 1)
            self.assertEqual(report_payload["hypotheses"][0]["type"], "promising_layer")
            self.assertEqual(report_payload["hypotheses"][1]["type"], "fragile_layer")
            self.assertEqual(report_payload["hypotheses"][2]["type"], "duplicate_recovery_baseline")
            self.assertEqual(report_payload["hypotheses"][3]["type"], "fragile_scenario_profile")
            self.assertEqual(report_payload["hypotheses"][3]["scenario_name"], "outage-shock")
            next_payload = json.loads((output_dir / "auto-run.next-study.json").read_text(encoding="utf-8"))
            self.assertEqual(next_payload["run_id"], "auto-run-next")
            self.assertEqual(next_payload["directional_layers"], ["kama"])
            self.assertEqual(next_payload["known_good_filters"], [])
            self.assertEqual(next_payload["research_hypotheses"]["fragile_layers"][0]["layer_name"], "flat9")
            self.assertEqual(next_payload["research_hypotheses"]["top_duplicate_matches"][0]["run_id"], "seed-baseline-a")
            self.assertEqual(next_payload["research_hypotheses"]["parameter_hints"]["kama"]["aggressiveness"]["confidence"], "high")
            self.assertEqual(next_payload["research_hypotheses"]["parameter_hints"]["kama"]["aggressiveness"]["promoted_count"], 3)
            self.assertEqual(next_payload["research_hypotheses"]["parameter_hints"]["kama"]["aggressiveness"]["blocked_values"], [1])
            self.assertEqual(
                next_payload["research_hypotheses"]["scenario_profile_avoidance"]["outage-shock"]["profile"]["latency_delta_bars"],
                3,
            )
            self.assertEqual(next_payload["parameter_avoidance"]["kama"]["aggressiveness"], [1])
            self.assertEqual(next_payload["parameter_avoidance"]["kama"]["mean_threshold_offset"], [0.16])
            self.assertEqual(next_payload["parameter_grids"]["kama"]["aggressiveness"]["minimum"], 2)
            self.assertEqual(next_payload["parameter_grids"]["kama"]["aggressiveness"]["maximum"], 2)
            self.assertEqual(next_payload["parameter_grids"]["kama"]["mean_threshold_offset"]["minimum"], 0.08)
            self.assertEqual(next_payload["parameter_grids"]["kama"]["mean_threshold_offset"]["maximum"], 0.08)
            self.assertNotIn("flat9", next_payload["parameter_grids"])
            conservative_payload = json.loads((output_dir / "auto-run.next-study.conservative.json").read_text(encoding="utf-8"))
            self.assertEqual(conservative_payload["research_variant"]["name"], "conservative")
            self.assertGreaterEqual(conservative_payload["runtime"]["bootstrap_samples"], 16)
            self.assertGreaterEqual(conservative_payload["runtime"]["holdout_sharpe_floor"], 0.08)
            exploratory_payload = json.loads((output_dir / "auto-run.next-study.exploratory.json").read_text(encoding="utf-8"))
            self.assertEqual(exploratory_payload["research_variant"]["name"], "exploratory")
            self.assertEqual(exploratory_payload["run_id"], "auto-run-next-exploratory")
            self.assertEqual(exploratory_payload["parameter_grids"]["kama"]["aggressiveness"]["minimum"], 1.0)
            self.assertEqual(exploratory_payload["parameter_grids"]["kama"]["aggressiveness"]["maximum"], 3.0)
            self.assertGreaterEqual(exploratory_payload["runtime"]["max_parameter_permutations"], 128)

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
                    "json",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(query_completed.returncode, 0, msg=query_completed.stderr)
            rows = json.loads(query_completed.stdout)
            run_ids = [row["run_id"] for row in rows]
            self.assertIn("auto-run", run_ids)
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)
                        
                    

    def test_batch_autoresearch_surfaces_accepted_duplicate_config_when_base_run_is_skipped(self) -> None:
        config_path = Path("test-study-batch-autoresearch-duplicate.json")
        output_dir = Path("test-output-batch-autoresearch-duplicate")
        memory_seed_dir = Path("test-memory-batch-autoresearch-duplicate")
        db_path = Path("test-output-batch-autoresearch-duplicate.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        payload = _fixture_payload("batch-duplicate")
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-same-batch-study",
            "promoted",
            ["kama"],
            [],
            study_signature=build_study_signature_from_payload(payload),
        )
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "batch-autoresearch",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload_out = json.loads(completed.stdout)
            self.assertEqual(payload_out["status"], "skipped")
            self.assertTrue(str(payload_out["accepted_duplicate_config_path"]).endswith("batch-duplicate.accepted-duplicate.json"))
            self.assertTrue((output_dir / "batch-duplicate.accepted-duplicate.json").exists())
            batch_payload = json.loads((output_dir / "batch-duplicate.variant-batch.json").read_text(encoding="utf-8"))
            self.assertEqual(batch_payload["status"], "skipped")
            self.assertTrue(str(batch_payload["accepted_duplicate_config_path"]).endswith("batch-duplicate.accepted-duplicate.json"))
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)
                        
                    

    def test_autoresearch_can_include_dirty_memory_when_requested(self) -> None:
        config_path = Path("test-study-autoresearch-include-dirty.json")
        output_dir = Path("test-output-autoresearch-include-dirty")
        memory_seed_dir = Path("test-memory-autoresearch-include-dirty")
        db_path = Path("test-output-autoresearch-include-dirty.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        config_path.write_text(json.dumps(_fixture_payload("auto-include-dirty")), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-promoted-a",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2, "mean_threshold_offset": 0.08}},
            research_lineage={
                "accepted_duplicate_match_run_id": "seed-baseline-a",
                "accepted_duplicate_match_type": "duplicate_match",
                "accepted_duplicate_source_config_path": "test-memory-autoresearch/prior-promoted-a.accepted-duplicate.json",
                "accepted_duplicate_source_report_path": "test-memory-autoresearch/prior-promoted-a.autoresearch.json",
            },
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-promoted-b",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2, "mean_threshold_offset": 0.08}},
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-blocked-flat9",
            "blocked",
            [],
            ["flat9"],
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-blocked-kama",
            "blocked",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 1, "mean_threshold_offset": 0.16}},
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-dirty-promoted",
            "promoted",
            ["flat9"],
            [],
            {"flat9": {"strictness": 3}},
            quality_status="dirty",
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
                    "--memory-dir",
                    str(memory_seed_dir),
                    "--memory-quality-policy",
                    "all",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["memory_summary"]["prior_runs"], 6)
            self.assertEqual(payload["memory_summary"]["promoted_runs"], 4)
            self.assertEqual(payload["memory_summary"]["blocked_runs"], 2)
            self.assertEqual(payload["memory_summary"]["excluded_dirty_runs"], 0)
            self.assertEqual(payload["memory_summary"]["memory_quality_policy"], "all")
            self.assertIn(
                "flat9",
                [item["layer_name"] for item in payload["memory_summary"]["promising_layers"]],
            )
            report_payload = json.loads((output_dir / "auto-include-dirty.autoresearch.json").read_text(encoding="utf-8"))
            self.assertEqual(report_payload["memory_summary"]["memory_quality_policy"], "all")
            self.assertEqual(report_payload["memory_summary"]["prior_runs"], 6)
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)
                        
                    

    def test_autoresearch_skips_duplicate_run_id(self) -> None:
        config_path = Path("test-study-autoresearch-duplicate.json")
        output_dir = Path("test-output-autoresearch-duplicate")
        memory_seed_dir = Path("test-memory-autoresearch-duplicate")
        db_path = Path("test-output-autoresearch-duplicate.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        config_path.write_text(json.dumps(_fixture_payload("auto-duplicate")), encoding="utf-8")
        _write_memory_artifacts(memory_seed_dir, "auto-duplicate", "promoted", ["kama"], [])
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
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "skipped")
            self.assertEqual(payload["skip_reason"], "duplicate_run_id")
            self.assertEqual(payload["duplicate_match"]["match_type"], "run_id")
            self.assertEqual(payload["duplicate_match"]["run_id"], "auto-duplicate")
            self.assertTrue(str(payload["accepted_duplicate_config_path"]).endswith("auto-duplicate.accepted-duplicate.json"))
            self.assertTrue((output_dir / "auto-duplicate.autoresearch.json").exists())
            self.assertTrue((output_dir / "auto-duplicate.accepted-duplicate.json").exists())
            self.assertTrue((output_dir / "auto-duplicate.next-study.json").exists())
            self.assertTrue((output_dir / "auto-duplicate.next-study.conservative.json").exists())
            self.assertTrue((output_dir / "auto-duplicate.next-study.exploratory.json").exists())
            report_payload = json.loads((output_dir / "auto-duplicate.autoresearch.json").read_text(encoding="utf-8"))
            self.assertEqual(report_payload["status"], "skipped")
            self.assertEqual(report_payload["skip_reason"], "duplicate_run_id")
            self.assertEqual(report_payload["duplicate_match"]["match_type"], "run_id")
            self.assertEqual(report_payload["duplicate_match"]["run_id"], "auto-duplicate")
            self.assertTrue(str(report_payload["accepted_duplicate_config_path"]).endswith("auto-duplicate.accepted-duplicate.json"))
            next_payload = json.loads((output_dir / "auto-duplicate.next-study.json").read_text(encoding="utf-8"))
            self.assertEqual(next_payload["run_id"], "auto-duplicate-next")
            self.assertEqual(next_payload["parameter_avoidance"], {})
            accepted_duplicate_payload = json.loads((output_dir / "auto-duplicate.accepted-duplicate.json").read_text(encoding="utf-8"))
            self.assertEqual(accepted_duplicate_payload["incumbent"]["layers"], ["kama"])
            self.assertFalse((output_dir / "auto-duplicate.runcard.json").exists())
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)
                        
                    

    def test_autoresearch_skips_duplicate_study_signature_when_run_id_changes(self) -> None:
        config_path = Path("test-study-autoresearch-duplicate-signature.json")
        output_dir = Path("test-output-autoresearch-duplicate-signature")
        memory_seed_dir = Path("test-memory-autoresearch-duplicate-signature")
        db_path = Path("test-output-autoresearch-duplicate-signature.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        payload = _fixture_payload("auto-new-run-id")
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-same-study",
            "promoted",
            ["kama"],
            [],
            study_signature=build_study_signature_from_payload(payload),
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
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload_out = json.loads(completed.stdout)
            self.assertEqual(payload_out["status"], "skipped")
            self.assertEqual(payload_out["skip_reason"], "duplicate_study_signature")
            self.assertEqual(payload_out["duplicate_match"]["match_type"], "study_signature")
            self.assertEqual(payload_out["duplicate_match"]["run_id"], "prior-same-study")
            self.assertEqual(payload_out["duplicate_match"]["study_signature"], build_study_signature_from_payload(payload))
            self.assertTrue(str(payload_out["accepted_duplicate_config_path"]).endswith("auto-new-run-id.accepted-duplicate.json"))
            self.assertTrue((output_dir / "auto-new-run-id.autoresearch.json").exists())
            self.assertTrue((output_dir / "auto-new-run-id.accepted-duplicate.json").exists())
            self.assertTrue((output_dir / "auto-new-run-id.next-study.json").exists())
            self.assertFalse((output_dir / "auto-new-run-id.runcard.json").exists())
            report_payload = json.loads((output_dir / "auto-new-run-id.autoresearch.json").read_text(encoding="utf-8"))
            self.assertEqual(report_payload["skip_reason"], "duplicate_study_signature")
            self.assertEqual(report_payload["duplicate_match"]["match_type"], "study_signature")
            self.assertEqual(report_payload["duplicate_match"]["run_id"], "prior-same-study")
            self.assertTrue(str(report_payload["accepted_duplicate_config_path"]).endswith("auto-new-run-id.accepted-duplicate.json"))
            accepted_duplicate_payload = json.loads((output_dir / "auto-new-run-id.accepted-duplicate.json").read_text(encoding="utf-8"))
            self.assertEqual(accepted_duplicate_payload["incumbent"]["layers"], ["kama"])
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)

    def test_autoresearch_does_not_skip_duplicate_study_signature_from_incompatible_snapshot_build(self) -> None:
        config_path = Path("test-study-autoresearch-duplicate-signature-incompatible-build.json")
        output_dir = Path("test-output-autoresearch-duplicate-signature-incompatible-build")
        memory_seed_dir = Path("test-memory-autoresearch-duplicate-signature-incompatible-build")
        db_path = Path("test-output-autoresearch-duplicate-signature-incompatible-build.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        payload = _fixture_payload("auto-new-build-run")
        payload["snapshot"]["provenance"] = {
            "build_version": "phase1_snapshot_builder_v1",
            "source_hash": "hash-current-build",
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-same-study-other-build",
            "promoted",
            ["kama"],
            [],
            study_signature=build_study_signature_from_payload(payload),
            snapshot_build_version="phase1_snapshot_builder_v1",
            snapshot_source_hash="hash-other-build",
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
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload_out = json.loads(completed.stdout)
            self.assertEqual(payload_out["status"], "promoted")
            self.assertIsNone(payload_out["skip_reason"])
            self.assertIsNone(payload_out["duplicate_match"])
            self.assertTrue((output_dir / "auto-new-build-run.runcard.json").exists())
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)

    def test_autoresearch_skips_duplicate_run_id_even_when_existing_run_has_other_symbol(self) -> None:
        config_path = Path("test-study-autoresearch-cross-symbol-duplicate.json")
        output_dir = Path("test-output-autoresearch-cross-symbol-duplicate")
        memory_seed_dir = Path("test-memory-autoresearch-cross-symbol-duplicate")
        db_path = Path("test-output-autoresearch-cross-symbol-duplicate.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        payload = _fixture_payload("auto-cross-symbol-duplicate")
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        other_symbol_payload = _fixture_payload("other-symbol-run")
        other_symbol_payload["snapshot"]["symbol"] = "BTCUSDT"
        _write_memory_artifacts(memory_seed_dir, "auto-cross-symbol-duplicate", "promoted", ["kama"], [])
        run_card = json.loads((memory_seed_dir / "auto-cross-symbol-duplicate.runcard.json").read_text(encoding="utf-8"))
        run_card["artifacts"]["symbol"] = "BTCUSDT"
        (memory_seed_dir / "auto-cross-symbol-duplicate.runcard.json").write_text(
            json.dumps(run_card, sort_keys=True),
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
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload_out = json.loads(completed.stdout)
            self.assertEqual(payload_out["status"], "skipped")
            self.assertEqual(payload_out["skip_reason"], "duplicate_run_id")
            self.assertEqual(payload_out["duplicate_match"]["run_id"], "auto-cross-symbol-duplicate")
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)

    def test_autoresearch_memory_summary_is_scoped_to_same_symbol_and_venue(self) -> None:
        config_path = Path("test-study-autoresearch-venue-scope.json")
        output_dir = Path("test-output-autoresearch-venue-scope")
        memory_seed_dir = Path("test-memory-autoresearch-venue-scope")
        db_path = Path("test-output-autoresearch-venue-scope.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        payload = _fixture_payload("auto-venue-scope")
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_memory_artifacts(memory_seed_dir, "same-symbol-same-venue", "promoted", ["kama"], [])
        _write_memory_artifacts(memory_seed_dir, "same-symbol-other-venue", "promoted", ["flat9"], [])
        other_venue_runcard = json.loads((memory_seed_dir / "same-symbol-other-venue.runcard.json").read_text(encoding="utf-8"))
        other_venue_runcard["artifacts"]["venue"] = "bybit"
        (memory_seed_dir / "same-symbol-other-venue.runcard.json").write_text(
            json.dumps(other_venue_runcard, sort_keys=True),
            encoding="utf-8",
        )
        _write_memory_artifacts(memory_seed_dir, "other-symbol-same-venue", "promoted", ["dema_exit"], [])
        other_symbol_runcard = json.loads((memory_seed_dir / "other-symbol-same-venue.runcard.json").read_text(encoding="utf-8"))
        other_symbol_runcard["artifacts"]["symbol"] = "BTCUSDT"
        (memory_seed_dir / "other-symbol-same-venue.runcard.json").write_text(
            json.dumps(other_symbol_runcard, sort_keys=True),
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
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload_out = json.loads(completed.stdout)
            self.assertEqual(payload_out["memory_summary"]["prior_runs"], 2)
            self.assertEqual(payload_out["memory_summary"]["promoted_runs"], 2)
            self.assertEqual(
                [item["layer_name"] for item in payload_out["memory_summary"]["promising_layers"]],
                ["kama"],
            )
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)

    def test_autoresearch_memory_summary_prefers_compatible_snapshot_build(self) -> None:
        config_path = Path("test-study-autoresearch-build-scope.json")
        output_dir = Path("test-output-autoresearch-build-scope")
        memory_seed_dir = Path("test-memory-autoresearch-build-scope")
        db_path = Path("test-output-autoresearch-build-scope.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        payload = _fixture_payload("auto-build-scope")
        payload["snapshot"]["provenance"] = {
            "build_version": "phase1_snapshot_builder_v1",
            "source_hash": "hash-compatible",
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "same-symbol-compatible-build",
            "promoted",
            ["kama"],
            [],
            snapshot_build_version="phase1_snapshot_builder_v1",
            snapshot_source_hash="hash-compatible",
        )
        _write_memory_artifacts(
            memory_seed_dir,
            "same-symbol-incompatible-build",
            "promoted",
            ["flat9"],
            [],
            snapshot_build_version="phase1_snapshot_builder_v1",
            snapshot_source_hash="hash-incompatible",
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
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload_out = json.loads(completed.stdout)
            self.assertEqual(payload_out["memory_summary"]["prior_runs"], 2)
            self.assertEqual(payload_out["memory_summary"]["promoted_runs"], 2)
            self.assertEqual(
                [item["layer_name"] for item in payload_out["memory_summary"]["promising_layers"]],
                ["kama"],
            )
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)
                        
                    

    def test_autoresearch_requires_multiple_promoted_runs_before_narrowing_grid(self) -> None:
        config_path = Path("test-study-autoresearch-low-confidence.json")
        output_dir = Path("test-output-autoresearch-low-confidence")
        memory_seed_dir = Path("test-memory-autoresearch-low-confidence")
        db_path = Path("test-output-autoresearch-low-confidence.sqlite")
        output_dir.mkdir(exist_ok=True)
        memory_seed_dir.mkdir(exist_ok=True)
        config_path.write_text(json.dumps(_fixture_payload("auto-low-confidence")), encoding="utf-8")
        _write_memory_artifacts(
            memory_seed_dir,
            "prior-single-promoted",
            "promoted",
            ["kama"],
            [],
            {"kama": {"aggressiveness": 2, "mean_threshold_offset": 0.08}},
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
                    "--memory-dir",
                    str(memory_seed_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            next_payload = json.loads((output_dir / "auto-low-confidence.next-study.json").read_text(encoding="utf-8"))
            self.assertEqual(next_payload["parameter_grids"]["kama"]["aggressiveness"]["minimum"], 2)
            self.assertEqual(next_payload["parameter_grids"]["kama"]["aggressiveness"]["maximum"], 2)
            self.assertEqual(next_payload["research_hypotheses"]["parameter_hints"]["kama"]["aggressiveness"]["confidence"], "high")
            self.assertTrue(next_payload["research_hypotheses"]["parameter_hints"]["kama"]["aggressiveness"]["narrowed"])
            self.assertEqual(next_payload["parameter_avoidance"], {})
            exploratory_payload = json.loads((output_dir / "auto-low-confidence.next-study.exploratory.json").read_text(encoding="utf-8"))
            self.assertEqual(exploratory_payload["research_variant"]["name"], "exploratory")
        finally:
            if config_path.exists():
                config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            for directory in (output_dir, memory_seed_dir):
                if directory.exists():
                    import shutil; shutil.rmtree(directory, ignore_errors=True)
                        
                    


if __name__ == "__main__":
    unittest.main()
