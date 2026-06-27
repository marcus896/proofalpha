from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import uuid4

from engine.memory.store import initialize_memory_db


LifecycleState = Literal[
    "research_candidate",
    "validated_candidate",
    "paper",
    "pilot_live",
    "scaled_live",
    "paused",
    "retired",
]

Automation = Literal[
    "ignore",
    "pause",
    "cancel",
    "flatten",
    "rollback",
    "rotate_key",
    "restart",
    "manual_review",
]


@dataclass(frozen=True)
class ScenarioPack:
    name: str
    scenario_pack_version: str
    status: str
    stressors: dict[str, float | int | bool | str]
    approved_by: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RevalidationDecision:
    required: bool
    reasons: list[str]
    days_since_validation: int


@dataclass(frozen=True)
class ArtifactHealthSnapshot:
    artifact_id: str
    lifecycle_state: LifecycleState
    liquidation_events: int = 0
    checksum_valid: bool = True
    venue_rules_match: bool = True
    trailing_30d_live_sharpe: float | None = None
    live_sample_count: int = 0
    realized_slippage_over_modeled_5d: float | None = None
    fill_rejection_cluster: bool = False
    pause_count_90d: int = 0
    holdout_assumptions_invalidated: bool = False
    drawdown_limit_breached: bool = False
    capacity_drift_breached: bool = False
    validation_expired: bool = False
    scenario_pack_changed: bool = False
    venue_api_rules_changed: bool = False
    data_quality_degraded: bool = False


@dataclass(frozen=True)
class LifecycleDecision:
    artifact_id: str
    source_state: str
    target_state: str
    revalidation_required: bool
    primary_reason: str
    reasons: list[str]
    runbook_code: str
    default_automation: Automation
    severity: str


@dataclass(frozen=True)
class AlertRunbook:
    alert_code: str
    severity: str
    owner_action: str
    default_automation: Automation
    required_evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceValidation:
    passed: bool
    reasons: list[str]


@dataclass(frozen=True)
class LifecycleApplyResult:
    applied: bool
    lifecycle_event_id: str
    reasons: list[str]


DEFAULT_ALERT_RUNBOOKS: dict[str, AlertRunbook] = {
    "none": AlertRunbook("none", "info", "No action.", "ignore", ("operator",)),
    "liquidation": AlertRunbook("liquidation", "critical", "Retire artifact and rollback deployment.", "rollback", ("operator", "metric_window", "review_notes")),
    "artifact_checksum_mismatch": AlertRunbook("artifact_checksum_mismatch", "critical", "Retire artifact and block execution.", "rollback", ("operator", "artifact_sha256", "review_notes")),
    "venue_rule_mismatch": AlertRunbook("venue_rule_mismatch", "critical", "Retire artifact until venue rules are revalidated.", "rollback", ("operator", "exchange_rules_version", "review_notes")),
    "trailing_30d_live_sharpe_below_floor": AlertRunbook("trailing_30d_live_sharpe_below_floor", "warning", "Pause to paper and require review.", "pause", ("operator", "metric_window", "review_notes")),
    "realized_slippage_gt_2x_modeled_5d": AlertRunbook("realized_slippage_gt_2x_modeled_5d", "warning", "Pause to paper and recalibrate costs.", "pause", ("operator", "metric_window", "review_notes")),
    "pause_to_paper": AlertRunbook("pause_to_paper", "warning", "Pause to paper and record closeout evidence.", "pause", ("operator", "metric_window", "review_notes")),
    "fill_rejection_cluster": AlertRunbook("fill_rejection_cluster", "warning", "Pause and inspect order rejection cluster.", "pause", ("operator", "metric_window", "review_notes")),
    "drawdown_limit_breached": AlertRunbook("drawdown_limit_breached", "critical", "Flatten exposure and pause artifact.", "flatten", ("operator", "metric_window", "review_notes")),
    "capacity_drift_breached": AlertRunbook("capacity_drift_breached", "warning", "Pause artifact and rerun capacity calibration.", "pause", ("operator", "metric_window", "review_notes")),
    "data_quality_degraded": AlertRunbook("data_quality_degraded", "warning", "Pause artifact until data quality recovers.", "pause", ("operator", "metric_window", "review_notes")),
    "two_pauses_within_90d": AlertRunbook("two_pauses_within_90d", "critical", "Retire unstable artifact.", "rollback", ("operator", "metric_window", "review_notes")),
    "holdout_assumptions_invalidated": AlertRunbook("holdout_assumptions_invalidated", "critical", "Retire artifact and block promotion lineage.", "rollback", ("operator", "review_notes")),
    "revalidation_required": AlertRunbook("revalidation_required", "warning", "Manual review and validation rerun required.", "manual_review", ("operator", "review_notes")),
    "venue_outage": AlertRunbook("venue_outage", "critical", "Cancel open orders during venue outage.", "cancel", ("operator", "metric_window", "review_notes")),
    "secret_rotation_due": AlertRunbook("secret_rotation_due", "warning", "Rotate execution keys.", "rotate_key", ("operator", "review_notes")),
    "executor_restart_required": AlertRunbook("executor_restart_required", "warning", "Restart executor after health failure.", "restart", ("operator", "review_notes")),
}


def build_required_scenario_packs(*, approved_by: str | None = None) -> list[ScenarioPack]:
    definitions: dict[str, dict[str, float | int | bool | str]] = {
        "mild": {
            "spread_multiplier": 2.0,
            "slippage_multiplier": 1.5,
            "one_bar_gap_sigma": 3.0,
            "data_outage_seconds": 30,
        },
        "medium": {
            "spread_multiplier": 3.0,
            "slippage_multiplier": 2.0,
            "one_bar_gap_sigma": 5.0,
            "data_outage_seconds": 120,
            "funding_shock_multiplier": 2.0,
        },
        "severe": {
            "spread_multiplier": 5.0,
            "slippage_multiplier": 3.0,
            "one_bar_gap_sigma": 8.0,
            "data_outage_seconds": 600,
            "funding_sign_inversion_burst": True,
            "forced_taker_liquidation_path": True,
        },
        "venue-outage": {
            "venue_outage": True,
            "data_outage_seconds": 600,
            "cancel_reject_risk": True,
            "stale_book_seconds": 120,
        },
    }
    return [
        ScenarioPack(
            name=name,
            scenario_pack_version=_scenario_pack_version(name, stressors),
            status="active" if approved_by else "draft",
            stressors=stressors,
            approved_by=approved_by,
        )
        for name, stressors in definitions.items()
    ]


def seed_governance_registry(db_path: Path, *, approved_by: str | None = None) -> dict[str, int]:
    initialize_memory_db(db_path)
    packs = build_required_scenario_packs(approved_by=approved_by)
    now = _now_utc()
    connection = sqlite3.connect(db_path)
    try:
        for pack in packs:
            connection.execute(
                """
                INSERT OR REPLACE INTO scenario_packs (
                    scenario_pack_id, scenario_pack_version, name, status,
                    approved_by, approved_at_utc, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pack.scenario_pack_version,
                    pack.scenario_pack_version,
                    pack.name,
                    pack.status,
                    pack.approved_by,
                    now if pack.approved_by else None,
                    json.dumps(pack.to_dict(), sort_keys=True),
                ),
            )
        for runbook in DEFAULT_ALERT_RUNBOOKS.values():
            connection.execute(
                """
                INSERT OR REPLACE INTO alert_runbooks (
                    alert_code, severity, owner_action, default_automation,
                    required_evidence_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    runbook.alert_code,
                    runbook.severity,
                    runbook.owner_action,
                    runbook.default_automation,
                    json.dumps(list(runbook.required_evidence), sort_keys=True),
                    json.dumps(runbook.to_dict(), sort_keys=True),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return {"scenario_packs": len(packs), "alert_runbooks": len(DEFAULT_ALERT_RUNBOOKS)}


def evaluate_revalidation_requirement(
    *,
    last_validation_at: str,
    now: str,
    artifact_scenario_pack_version: str,
    active_scenario_pack_version: str,
    artifact_exchange_rules_version: str,
    active_exchange_rules_version: str,
    cadence_days: int = 31,
) -> RevalidationDecision:
    last = _parse_utc(last_validation_at)
    current = _parse_utc(now)
    days = max(0, (current - last).days)
    reasons: list[str] = []
    if days >= cadence_days:
        reasons.append("monthly_revalidation_due")
    if artifact_scenario_pack_version != active_scenario_pack_version:
        reasons.append("scenario_pack_changed")
    if artifact_exchange_rules_version != active_exchange_rules_version:
        reasons.append("venue_api_rules_changed")
    return RevalidationDecision(required=bool(reasons), reasons=reasons, days_since_validation=days)


def evaluate_lifecycle_policy(snapshot: ArtifactHealthSnapshot) -> LifecycleDecision:
    reasons: list[str] = []
    if snapshot.liquidation_events > 0:
        reasons.append("liquidation")
    if not snapshot.checksum_valid:
        reasons.append("artifact_checksum_mismatch")
    if not snapshot.venue_rules_match:
        reasons.append("venue_rule_mismatch")
    if snapshot.pause_count_90d >= 2:
        reasons.append("two_pauses_within_90d")
    if snapshot.holdout_assumptions_invalidated:
        reasons.append("holdout_assumptions_invalidated")
    if reasons:
        primary = reasons[0]
        return _decision(snapshot, "retired", False, primary, reasons)

    pause_reasons: list[str] = []
    if snapshot.trailing_30d_live_sharpe is not None and snapshot.trailing_30d_live_sharpe < -0.5 and snapshot.live_sample_count >= 30:
        pause_reasons.append("trailing_30d_live_sharpe_below_floor")
    if snapshot.realized_slippage_over_modeled_5d is not None and snapshot.realized_slippage_over_modeled_5d > 2.0:
        pause_reasons.append("realized_slippage_gt_2x_modeled_5d")
    if snapshot.fill_rejection_cluster:
        pause_reasons.append("fill_rejection_cluster")
    if snapshot.drawdown_limit_breached:
        pause_reasons.append("drawdown_limit_breached")
    if snapshot.capacity_drift_breached:
        pause_reasons.append("capacity_drift_breached")
    if snapshot.data_quality_degraded:
        pause_reasons.append("data_quality_degraded")
    if pause_reasons:
        return _decision(snapshot, "paused", False, pause_reasons[0], pause_reasons)

    revalidation_reasons = [
        reason
        for condition, reason in (
            (snapshot.validation_expired, "validation_expired"),
            (snapshot.scenario_pack_changed, "scenario_pack_changed"),
            (snapshot.venue_api_rules_changed, "venue_api_rules_changed"),
        )
        if condition
    ]
    if revalidation_reasons:
        return _decision(snapshot, snapshot.lifecycle_state, True, "revalidation_required", revalidation_reasons)

    return _decision(snapshot, snapshot.lifecycle_state, False, "none", [])


def validate_alert_closeout(
    runbook_code: str,
    evidence: dict[str, object],
    *,
    runbooks: dict[str, AlertRunbook] = DEFAULT_ALERT_RUNBOOKS,
) -> EvidenceValidation:
    runbook = runbooks.get(runbook_code)
    if runbook is None:
        return EvidenceValidation(False, [f"unknown_runbook:{runbook_code}"])
    missing = [
        f"missing_closeout_evidence:{field}"
        for field in runbook.required_evidence
        if evidence.get(field) in (None, "")
    ]
    return EvidenceValidation(not missing, missing)


def apply_lifecycle_decision(
    db_path: Path,
    decision: LifecycleDecision,
    *,
    evidence: dict[str, object],
    runbooks: dict[str, AlertRunbook] = DEFAULT_ALERT_RUNBOOKS,
) -> LifecycleApplyResult:
    validation = validate_alert_closeout(decision.runbook_code, evidence, runbooks=runbooks)
    lifecycle_event_id = f"lifecycle:{decision.artifact_id}:{uuid4().hex[:12]}"
    if not validation.passed:
        return LifecycleApplyResult(False, lifecycle_event_id, validation.reasons)

    initialize_memory_db(db_path)
    now = _now_utc()
    connection = sqlite3.connect(db_path)
    try:
        if decision.target_state in {"paused", "retired"}:
            connection.execute(
                "UPDATE artifacts SET rollout_stage = ? WHERE artifact_id = ?",
                (decision.target_state, decision.artifact_id),
            )
        connection.execute(
            """
            INSERT OR REPLACE INTO deployments (
                deployment_id, artifact_id, rollout_stage, venue, status,
                started_at_utc, ended_at_utc, payload_json
            ) VALUES (?, ?, ?, NULL, ?, ?, NULL, ?)
            """,
            (
                f"deployment:{decision.artifact_id}:lifecycle",
                decision.artifact_id,
                decision.target_state,
                "revalidation_required" if decision.revalidation_required else decision.target_state,
                now,
                json.dumps({"decision": asdict(decision), "evidence": evidence}, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO risk_events (
                risk_event_id, ts_utc, reason_code, severity, action, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"risk:{decision.artifact_id}:{uuid4().hex[:12]}",
                now,
                decision.primary_reason,
                decision.severity,
                decision.default_automation,
                json.dumps({"lifecycle_event_id": lifecycle_event_id, "evidence": evidence}, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO lifecycle_journal (
                lifecycle_event_id, artifact_id, source_state, target_state,
                revalidation_required, reason_code, runbook_code, automation,
                severity, ts_utc, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lifecycle_event_id,
                decision.artifact_id,
                decision.source_state,
                decision.target_state,
                1 if decision.revalidation_required else 0,
                decision.primary_reason,
                decision.runbook_code,
                decision.default_automation,
                decision.severity,
                now,
                json.dumps(evidence, sort_keys=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return LifecycleApplyResult(True, lifecycle_event_id, [])


def lifecycle_status(db_path: Path, artifact_id: str) -> dict[str, object]:
    initialize_memory_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        artifact = connection.execute(
            "SELECT rollout_stage, approved FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        deployment = connection.execute(
            """
            SELECT status, rollout_stage, payload_json FROM deployments
            WHERE artifact_id = ?
            ORDER BY started_at_utc DESC
            LIMIT 1
            """,
            (artifact_id,),
        ).fetchone()
        journal = connection.execute(
            """
            SELECT target_state, revalidation_required, reason_code, runbook_code, automation, severity, ts_utc
            FROM lifecycle_journal
            WHERE artifact_id = ?
            ORDER BY ts_utc DESC
            LIMIT 1
            """,
            (artifact_id,),
        ).fetchone()
    finally:
        connection.close()

    return {
        "artifact_id": artifact_id,
        "rollout_stage": artifact[0] if artifact else None,
        "approved": bool(artifact[1]) if artifact else False,
        "deployment_status": deployment[0] if deployment else None,
        "deployment_rollout_stage": deployment[1] if deployment else None,
        "latest_lifecycle_event": {
            "target_state": journal[0],
            "revalidation_required": bool(journal[1]),
            "reason_code": journal[2],
            "runbook_code": journal[3],
            "automation": journal[4],
            "severity": journal[5],
            "ts_utc": journal[6],
        }
        if journal
        else None,
    }


def _decision(
    snapshot: ArtifactHealthSnapshot,
    target_state: str,
    revalidation_required: bool,
    primary_reason: str,
    reasons: list[str],
) -> LifecycleDecision:
    runbook_code = "pause_to_paper" if target_state == "paused" else primary_reason
    runbook = DEFAULT_ALERT_RUNBOOKS.get(runbook_code, DEFAULT_ALERT_RUNBOOKS["revalidation_required"])
    return LifecycleDecision(
        artifact_id=snapshot.artifact_id,
        source_state=snapshot.lifecycle_state,
        target_state=target_state,
        revalidation_required=revalidation_required,
        primary_reason=primary_reason,
        reasons=reasons,
        runbook_code=runbook.alert_code,
        default_automation=runbook.default_automation,
        severity=runbook.severity,
    )


def _scenario_pack_version(name: str, stressors: dict[str, float | int | bool | str]) -> str:
    digest = hashlib.sha256(
        json.dumps({"name": name, "stressors": stressors}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"scenario-pack-{name}-{digest}"


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
