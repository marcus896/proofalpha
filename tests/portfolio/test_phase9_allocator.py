from __future__ import annotations

import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.memory.store import initialize_memory_db
from engine.portfolio.allocator import (
    HumanOverrideRequest,
    PortfolioArtifactCandidate,
    PortfolioConstraints,
    apply_human_override,
    build_portfolio_artifact,
    build_portfolio_risk_dashboard,
    build_portfolio_plan,
    detect_correlation_break,
    persist_portfolio_plan,
)


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _candidate(
    artifact_id: str,
    *,
    symbol: str = "BTCUSDT",
    role: str = "core",
    target_notional: float = 100_000.0,
    max_drawdown: float = 0.08,
    regime_scope: tuple[str, ...] = ("bull", "neutral"),
    lifecycle_state: str = "paper",
    paper_live_divergence_bps: float = 4.0,
) -> PortfolioArtifactCandidate:
    return PortfolioArtifactCandidate(
        artifact_id=artifact_id,
        strategy_id=f"strategy-{artifact_id}",
        symbol_scope=(symbol,),
        regime_scope=regime_scope,
        portfolio_role=role,
        target_notional=target_notional,
        max_notional=target_notional * 1.5,
        expected_return_bps=18.0,
        max_drawdown=max_drawdown,
        artifact_health=lifecycle_state,
        paper_live_divergence_bps=paper_live_divergence_bps,
        stress_loss_by_scenario={"mild": 0.02, "medium": 0.05, "severe": 0.11},
        correlation_by_artifact={},
    )


class Phase9PortfolioAllocatorTests(unittest.TestCase):
    def test_multiple_approved_artifacts_become_bounded_role_aware_plan(self) -> None:
        candidates = [
            _candidate("core-btc", symbol="BTCUSDT", role="core", target_notional=100_000.0),
            _candidate("def-eth", symbol="ETHUSDT", role="defensive", target_notional=60_000.0),
            _candidate("carry-sol", symbol="SOLUSDT", role="carry", target_notional=40_000.0),
        ]

        plan = build_portfolio_plan(
            candidates,
            PortfolioConstraints(
                equity=200_000.0,
                max_per_symbol_exposure=120_000.0,
                max_aggregate_leverage=1.25,
                drawdown_budget=0.20,
                max_pairwise_correlation=0.75,
                max_role_fraction=0.65,
            ),
            active_regimes={"BTCUSDT": "bull", "ETHUSDT": "neutral", "SOLUSDT": "bull"},
        )

        self.assertTrue(plan.accepted)
        self.assertEqual([row.artifact_id for row in plan.allocations], ["core-btc", "def-eth", "carry-sol"])
        self.assertEqual(plan.exposure_by_symbol["BTCUSDT"], 100_000.0)
        self.assertLessEqual(plan.aggregate_leverage, 1.25)
        self.assertEqual(plan.rejections, ())

    def test_conflicting_symbol_exposure_and_crowding_are_rejected_with_reasons(self) -> None:
        crowded = _candidate("crowded-btc", symbol="BTCUSDT", role="opportunistic", target_notional=40_000.0)
        crowded.correlation_by_artifact["core-btc"] = 0.92
        candidates = [
            _candidate("core-btc", symbol="BTCUSDT", role="core", target_notional=95_000.0),
            crowded,
            _candidate("oversized-btc", symbol="BTCUSDT", role="carry", target_notional=70_000.0),
        ]

        plan = build_portfolio_plan(
            candidates,
            PortfolioConstraints(
                equity=150_000.0,
                max_per_symbol_exposure=120_000.0,
                max_aggregate_leverage=2.0,
                drawdown_budget=0.30,
                max_pairwise_correlation=0.80,
                max_role_fraction=0.75,
            ),
            active_regimes={"BTCUSDT": "bull"},
        )

        reasons = {rejection.artifact_id: rejection.reason_code for rejection in plan.rejections}
        self.assertFalse(plan.accepted)
        self.assertEqual(reasons["crowded-btc"], "correlation_crowding")
        self.assertEqual(reasons["oversized-btc"], "per_symbol_exposure_limit")

    def test_regime_scope_gates_artifact_before_allocation(self) -> None:
        plan = build_portfolio_plan(
            [_candidate("bull-only", symbol="BTCUSDT", regime_scope=("bull",))],
            PortfolioConstraints(
                equity=100_000.0,
                max_per_symbol_exposure=100_000.0,
                max_aggregate_leverage=1.0,
                drawdown_budget=0.20,
                max_pairwise_correlation=0.75,
            ),
            active_regimes={"BTCUSDT": "crash"},
        )

        self.assertFalse(plan.accepted)
        self.assertEqual(plan.rejections[0].reason_code, "regime_scope_mismatch")

    def test_dashboard_and_portfolio_artifact_are_deterministic_outputs(self) -> None:
        plan = build_portfolio_plan(
            [
                _candidate("core-btc"),
                _candidate(
                    "hedge-eth",
                    symbol="ETHUSDT",
                    role="crash_hedge",
                    target_notional=25_000.0,
                    regime_scope=("crash", "neutral"),
                ),
            ],
            PortfolioConstraints(
                equity=150_000.0,
                max_per_symbol_exposure=100_000.0,
                max_aggregate_leverage=1.0,
                drawdown_budget=0.20,
                max_pairwise_correlation=0.75,
            ),
            active_regimes={"BTCUSDT": "bull", "ETHUSDT": "crash"},
        )

        dashboard = build_portfolio_risk_dashboard(plan)
        artifact = build_portfolio_artifact(plan)
        second = build_portfolio_artifact(plan)

        self.assertIn("correlations", dashboard)
        self.assertIn("exposure_by_symbol", dashboard)
        self.assertIn("stress_losses", dashboard)
        self.assertIn("active_regimes", dashboard)
        self.assertIn("artifact_health", dashboard)
        self.assertIn("paper_live_divergence", dashboard)
        self.assertEqual(artifact["portfolio_artifact_sha256"], second["portfolio_artifact_sha256"])
        self.assertTrue(artifact["portfolio_artifact_id"].startswith("portfolio-"))
        self.assertEqual(artifact["status"], "accepted")

    def test_correlation_break_is_risk_overlay_not_entry_signal(self) -> None:
        result = detect_correlation_break(
            artifact_id="core-btc",
            baseline_correlation=0.25,
            observed_correlation=0.91,
            threshold_delta=0.50,
            validated_actions=("reduce", "pause"),
        )

        self.assertTrue(result.triggered)
        self.assertEqual(result.allowed_actions, ("reduce", "pause"))
        self.assertNotIn("enter_trade", result.allowed_actions)

    def test_persist_portfolio_plan_writes_memory_row(self) -> None:
        root = Path("test-phase9-plan-db")
        db_path = root / "memory.sqlite"
        try:
            plan = build_portfolio_plan(
                [_candidate("core-btc")],
                PortfolioConstraints(
                    equity=100_000.0,
                    max_per_symbol_exposure=100_000.0,
                    max_aggregate_leverage=1.2,
                    drawdown_budget=0.20,
                    max_pairwise_correlation=0.75,
                ),
                active_regimes={"BTCUSDT": "bull"},
            )

            plan_id = persist_portfolio_plan(db_path, plan)

            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    "SELECT plan_id, status, payload_json FROM portfolio_plans WHERE plan_id = ?",
                    (plan_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertIsNotNone(row)
            self.assertEqual(row[1], "accepted")
            self.assertEqual(json.loads(row[2])["portfolio_plan_id"], plan_id)
        finally:
            _clean_tree(root)


class Phase9HumanOverrideTests(unittest.TestCase):
    def test_destructive_override_requires_operator_confirmation_and_logs_event(self) -> None:
        root = Path("test-phase9-overrides")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)

            missing = apply_human_override(
                db_path,
                HumanOverrideRequest(action="kill_switch", operator_id="ops-1", confirmation=None),
            )
            applied = apply_human_override(
                db_path,
                HumanOverrideRequest(action="kill_switch", operator_id="ops-1", confirmation="CONFIRM:kill_switch"),
            )

            connection = sqlite3.connect(db_path)
            try:
                journal_rows = connection.execute("SELECT action, operator_id, status FROM human_override_journal").fetchall()
                risk = connection.execute(
                    "SELECT reason_code, action FROM risk_events WHERE reason_code = 'human_override_kill_switch'"
                ).fetchone()
                execution = connection.execute(
                    "SELECT event_type, reason_code FROM execution_events WHERE event_type = 'KILL_SWITCH_TRIGGER'"
                ).fetchone()
            finally:
                connection.close()

            self.assertFalse(missing.applied)
            self.assertIn("confirmation_required:CONFIRM:kill_switch", missing.reasons)
            self.assertTrue(applied.applied)
            self.assertEqual(journal_rows[-1], ("kill_switch", "ops-1", "applied"))
            self.assertEqual(risk, ("human_override_kill_switch", "kill_switch"))
            self.assertEqual(execution, ("KILL_SWITCH_TRIGGER", "human_override_kill_switch"))
        finally:
            _clean_tree(root)


class Phase9PortfolioCliTests(unittest.TestCase):
    def test_cli_builds_and_persists_portfolio_plan(self) -> None:
        root = Path("test-phase9-cli-plan")
        db_path = root / "memory.sqlite"
        input_path = root / "portfolio-input.json"
        output_path = root / "portfolio-artifact.json"
        try:
            root.mkdir(parents=True, exist_ok=True)
            input_path.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "artifact_id": "core-btc",
                                "strategy_id": "strategy-core",
                                "symbol_scope": ["BTCUSDT"],
                                "regime_scope": ["bull"],
                                "portfolio_role": "core",
                                "target_notional": 50_000.0,
                                "max_notional": 60_000.0,
                                "expected_return_bps": 12.0,
                                "max_drawdown": 0.05,
                                "artifact_health": "paper",
                            }
                        ],
                        "constraints": {
                            "equity": 100_000.0,
                            "max_per_symbol_exposure": 75_000.0,
                            "max_aggregate_leverage": 1.0,
                            "drawdown_budget": 0.20,
                            "max_pairwise_correlation": 0.75,
                        },
                        "active_regimes": {"BTCUSDT": "bull"},
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            with mock.patch("builtins.print"):
                exit_code = main(
                    [
                        "portfolio-plan",
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                        "--db",
                        str(db_path),
                    ]
                )

            connection = sqlite3.connect(db_path)
            try:
                persisted = connection.execute("SELECT COUNT(*) FROM portfolio_plans WHERE status = 'accepted'").fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(exit_code, 0)
            self.assertEqual(persisted, 1)
            self.assertTrue(output_path.exists())
        finally:
            _clean_tree(root)

    def test_cli_portfolio_override_rejects_missing_confirmation(self) -> None:
        root = Path("test-phase9-cli-override")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)

            with mock.patch("builtins.print"):
                exit_code = main(
                    [
                        "portfolio-override",
                        "--db",
                        str(db_path),
                        "--action",
                        "flatten_all",
                        "--operator-id",
                        "ops-1",
                    ]
                )

            self.assertEqual(exit_code, 2)
        finally:
            _clean_tree(root)

    def test_pause_resume_force_reconcile_and_view_journal_surfaces(self) -> None:
        root = Path("test-phase9-nondestructive")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, strategy_id, variant_id, family, venue, signal_tf,
                        execution_tf, validation_report_id, code_sha, artifact_sha256,
                        rollout_stage, approved, payload_json
                    ) VALUES ('artifact-1', 'strategy', 'variant', 'momentum', 'binance_usdm', '1h',
                        '15m', 'validation', 'code', 'sha', 'paper', 1, '{}')
                    """
                )
                connection.commit()
            finally:
                connection.close()

            paused = apply_human_override(
                db_path,
                HumanOverrideRequest(action="pause_artifact", operator_id="ops-1", artifact_id="artifact-1"),
            )
            resumed = apply_human_override(
                db_path,
                HumanOverrideRequest(action="resume_artifact", operator_id="ops-1", artifact_id="artifact-1"),
            )
            reconciled = apply_human_override(
                db_path,
                HumanOverrideRequest(action="force_reconcile", operator_id="ops-1", artifact_id="artifact-1"),
            )
            journal = apply_human_override(
                db_path,
                HumanOverrideRequest(action="view_journal", operator_id="ops-1", artifact_id="artifact-1"),
            )

            connection = sqlite3.connect(db_path)
            try:
                stage = connection.execute("SELECT rollout_stage FROM artifacts WHERE artifact_id = 'artifact-1'").fetchone()[0]
                actions = [row[0] for row in connection.execute("SELECT action FROM human_override_journal ORDER BY ts_utc")]
            finally:
                connection.close()

            self.assertTrue(paused.applied)
            self.assertTrue(resumed.applied)
            self.assertTrue(reconciled.applied)
            self.assertTrue(journal.applied)
            self.assertEqual(stage, "paper")
            self.assertEqual(actions, ["pause_artifact", "resume_artifact", "force_reconcile", "view_journal"])
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
