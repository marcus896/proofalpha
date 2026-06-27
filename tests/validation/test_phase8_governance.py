from __future__ import annotations

import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.governance.lifecycle import (
    ArtifactHealthSnapshot,
    DEFAULT_ALERT_RUNBOOKS,
    apply_lifecycle_decision,
    build_required_scenario_packs,
    evaluate_lifecycle_policy,
    evaluate_revalidation_requirement,
    seed_governance_registry,
    validate_alert_closeout,
)
from engine.memory.store import initialize_memory_db


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _insert_artifact(db_path: Path, artifact_id: str, rollout_stage: str = "pilot_live") -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO artifacts (
                artifact_id, strategy_id, variant_id, family, venue, signal_tf,
                execution_tf, validation_report_id, code_sha, artifact_sha256,
                rollout_stage, approved, payload_json
            ) VALUES (?, 'strategy', 'variant', 'momentum', 'binance_usdm', '1h',
                '15m', 'validation-v1', 'code', 'sha', ?, 1, '{}')
            """,
            (artifact_id, rollout_stage),
        )
        connection.commit()
    finally:
        connection.close()


class Phase8ScenarioGovernanceTests(unittest.TestCase):
    def test_required_scenario_packs_have_exact_prd_stressors_and_versions(self) -> None:
        packs = {pack.name: pack for pack in build_required_scenario_packs(approved_by="operator")}

        self.assertEqual(set(packs), {"mild", "medium", "severe", "venue-outage"})
        self.assertEqual(packs["mild"].stressors["spread_multiplier"], 2.0)
        self.assertEqual(packs["mild"].stressors["slippage_multiplier"], 1.5)
        self.assertEqual(packs["mild"].stressors["one_bar_gap_sigma"], 3.0)
        self.assertEqual(packs["mild"].stressors["data_outage_seconds"], 30)
        self.assertEqual(packs["medium"].stressors["funding_shock_multiplier"], 2.0)
        self.assertEqual(packs["severe"].stressors["funding_sign_inversion_burst"], True)
        self.assertEqual(packs["severe"].stressors["forced_taker_liquidation_path"], True)
        self.assertEqual(packs["venue-outage"].stressors["venue_outage"], True)
        self.assertTrue(packs["mild"].scenario_pack_version.startswith("scenario-pack-"))
        self.assertEqual(packs["mild"].status, "active")

    def test_governance_registry_persists_active_scenario_packs_and_runbooks(self) -> None:
        root = Path("test-phase8-registry")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)

            summary = seed_governance_registry(db_path, approved_by="operator")
            connection = sqlite3.connect(db_path)
            try:
                pack_count = connection.execute("SELECT COUNT(*) FROM scenario_packs WHERE status = 'active'").fetchone()[0]
                runbook_count = connection.execute("SELECT COUNT(*) FROM alert_runbooks").fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(summary["scenario_packs"], 4)
            self.assertEqual(pack_count, 4)
            self.assertGreaterEqual(runbook_count, len(DEFAULT_ALERT_RUNBOOKS))
        finally:
            _clean_tree(root)

    def test_revalidation_due_on_monthly_cadence_scenario_pack_or_venue_rule_change(self) -> None:
        current = evaluate_revalidation_requirement(
            last_validation_at="2026-04-01T00:00:00Z",
            now="2026-04-20T00:00:00Z",
            artifact_scenario_pack_version="scenario-pack-a",
            active_scenario_pack_version="scenario-pack-a",
            artifact_exchange_rules_version="rules-a",
            active_exchange_rules_version="rules-a",
        )
        stale = evaluate_revalidation_requirement(
            last_validation_at="2026-03-01T00:00:00Z",
            now="2026-04-20T00:00:00Z",
            artifact_scenario_pack_version="scenario-pack-a",
            active_scenario_pack_version="scenario-pack-b",
            artifact_exchange_rules_version="rules-a",
            active_exchange_rules_version="rules-b",
        )

        self.assertFalse(current.required)
        self.assertTrue(stale.required)
        self.assertIn("monthly_revalidation_due", stale.reasons)
        self.assertIn("scenario_pack_changed", stale.reasons)
        self.assertIn("venue_api_rules_changed", stale.reasons)


class Phase8LifecycleGovernanceTests(unittest.TestCase):
    def test_lifecycle_policy_retires_liquidation_and_pauses_bad_live_metrics(self) -> None:
        retire = evaluate_lifecycle_policy(
            ArtifactHealthSnapshot(
                artifact_id="artifact-1",
                lifecycle_state="pilot_live",
                liquidation_events=1,
            )
        )
        pause = evaluate_lifecycle_policy(
            ArtifactHealthSnapshot(
                artifact_id="artifact-2",
                lifecycle_state="pilot_live",
                trailing_30d_live_sharpe=-0.75,
                live_sample_count=35,
            )
        )

        self.assertEqual(retire.target_state, "retired")
        self.assertEqual(retire.default_automation, "rollback")
        self.assertIn("liquidation", retire.reasons)
        self.assertEqual(pause.target_state, "paused")
        self.assertEqual(pause.default_automation, "pause")
        self.assertIn("trailing_30d_live_sharpe_below_floor", pause.reasons)

    def test_runbook_evidence_required_before_automated_pause_or_rollback_is_journaled(self) -> None:
        root = Path("test-phase8-lifecycle")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            _insert_artifact(db_path, "artifact-1", "pilot_live")
            decision = evaluate_lifecycle_policy(
                ArtifactHealthSnapshot(
                    artifact_id="artifact-1",
                    lifecycle_state="pilot_live",
                    realized_slippage_over_modeled_5d=2.4,
                )
            )

            missing = validate_alert_closeout(decision.runbook_code, {"operator": "codex"})
            applied = apply_lifecycle_decision(
                db_path,
                decision,
                evidence={"operator": "codex", "metric_window": "5d", "review_notes": "slippage breach confirmed"},
            )

            connection = sqlite3.connect(db_path)
            try:
                artifact_stage = connection.execute(
                    "SELECT rollout_stage FROM artifacts WHERE artifact_id = 'artifact-1'"
                ).fetchone()[0]
                journal = connection.execute(
                    "SELECT target_state, reason_code, runbook_code FROM lifecycle_journal WHERE artifact_id = 'artifact-1'"
                ).fetchone()
                risk = connection.execute(
                    "SELECT reason_code, action FROM risk_events WHERE reason_code = ?",
                    (decision.primary_reason,),
                ).fetchone()
            finally:
                connection.close()

            self.assertFalse(missing.passed)
            self.assertIn("missing_closeout_evidence:metric_window", missing.reasons)
            self.assertTrue(applied.applied)
            self.assertEqual(artifact_stage, "paused")
            self.assertEqual(journal, ("paused", "realized_slippage_gt_2x_modeled_5d", "pause_to_paper"))
            self.assertEqual(risk, ("realized_slippage_gt_2x_modeled_5d", "pause"))
        finally:
            _clean_tree(root)

    def test_retire_after_two_pauses_or_holdout_invalidation(self) -> None:
        decision = evaluate_lifecycle_policy(
            ArtifactHealthSnapshot(
                artifact_id="artifact-3",
                lifecycle_state="paper",
                pause_count_90d=2,
                holdout_assumptions_invalidated=True,
            )
        )

        self.assertEqual(decision.target_state, "retired")
        self.assertIn("two_pauses_within_90d", decision.reasons)
        self.assertIn("holdout_assumptions_invalidated", decision.reasons)

    def test_cli_surfaces_lifecycle_state_without_manual_db_reads(self) -> None:
        root = Path("test-phase8-cli")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            _insert_artifact(db_path, "artifact-cli", "paper")

            with mock.patch("builtins.print"):
                exit_code = main(["lifecycle-status", "--db", str(db_path), "--artifact-id", "artifact-cli"])

            self.assertEqual(exit_code, 0)
        finally:
            _clean_tree(root)


class Phase8AlertRunbookTests(unittest.TestCase):
    def test_default_runbooks_cover_required_automations_and_evidence(self) -> None:
        automations = {runbook.default_automation for runbook in DEFAULT_ALERT_RUNBOOKS.values()}

        self.assertTrue({"ignore", "pause", "cancel", "flatten", "rollback", "rotate_key", "restart", "manual_review"}.issubset(automations))
        self.assertEqual(DEFAULT_ALERT_RUNBOOKS["liquidation"].severity, "critical")
        self.assertIn("operator", DEFAULT_ALERT_RUNBOOKS["liquidation"].required_evidence)


if __name__ == "__main__":
    unittest.main()
