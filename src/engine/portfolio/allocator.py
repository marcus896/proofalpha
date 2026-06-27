from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import uuid4

from engine.memory.store import append_execution_event, initialize_memory_db
from engine.strategy.artifacts import paper_authority_decision


PORTFOLIO_ROLES = {"core", "defensive", "opportunistic", "carry", "crash_hedge"}
ACTIVE_ARTIFACT_STATES = {"paper", "shadow_live", "tiny_live", "pilot_live", "scaled_live"}
OVERRIDE_ACTIONS = {
    "pause_artifact",
    "resume_artifact",
    "cancel_all",
    "flatten_all",
    "kill_switch",
    "rollback_artifact",
    "view_journal",
    "force_reconcile",
}
DESTRUCTIVE_OVERRIDES = {"cancel_all", "flatten_all", "kill_switch", "rollback_artifact"}


@dataclass
class PortfolioArtifactCandidate:
    artifact_id: str
    strategy_id: str
    symbol_scope: tuple[str, ...]
    regime_scope: tuple[str, ...]
    portfolio_role: str
    target_notional: float
    max_notional: float
    expected_return_bps: float
    max_drawdown: float
    artifact_health: str = "paper"
    approved: bool = True
    paper_live_divergence_bps: float = 0.0
    stress_loss_by_scenario: dict[str, float] | None = None
    correlation_by_artifact: dict[str, float] | None = None
    artifact_payload: dict[str, object] | None = None


@dataclass(frozen=True)
class PortfolioConstraints:
    equity: float
    max_per_symbol_exposure: float
    max_aggregate_leverage: float
    drawdown_budget: float
    max_pairwise_correlation: float
    max_role_fraction: float = 1.0


@dataclass(frozen=True)
class PortfolioAllocation:
    artifact_id: str
    strategy_id: str
    symbols: tuple[str, ...]
    portfolio_role: str
    notional: float
    expected_return_bps: float
    max_drawdown: float


@dataclass(frozen=True)
class PortfolioRejection:
    artifact_id: str
    reason_code: str
    reason: str


@dataclass(frozen=True)
class PortfolioPlan:
    portfolio_plan_id: str
    accepted: bool
    allocations: tuple[PortfolioAllocation, ...]
    rejections: tuple[PortfolioRejection, ...]
    constraints: PortfolioConstraints
    active_regimes: dict[str, str]
    exposure_by_symbol: dict[str, float]
    notional_by_symbol: dict[str, float]
    aggregate_leverage: float
    drawdown_usage: float
    created_at_utc: str
    candidate_payloads: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class CorrelationBreakDecision:
    artifact_id: str
    triggered: bool
    baseline_correlation: float
    observed_correlation: float
    delta: float
    allowed_actions: tuple[str, ...]
    reason_code: str


@dataclass(frozen=True)
class HumanOverrideRequest:
    action: Literal[
        "pause_artifact",
        "resume_artifact",
        "cancel_all",
        "flatten_all",
        "kill_switch",
        "rollback_artifact",
        "view_journal",
        "force_reconcile",
    ]
    operator_id: str
    artifact_id: str | None = None
    confirmation: str | None = None
    reason: str | None = None
    payload: dict[str, object] | None = None


@dataclass(frozen=True)
class HumanOverrideResult:
    applied: bool
    override_event_id: str
    action: str
    reasons: tuple[str, ...]
    journal: tuple[dict[str, object], ...] = ()


def build_portfolio_plan(
    candidates: list[PortfolioArtifactCandidate],
    constraints: PortfolioConstraints,
    *,
    active_regimes: dict[str, str],
    now_utc: str | None = None,
) -> PortfolioPlan:
    allocations: list[PortfolioAllocation] = []
    rejections: list[PortfolioRejection] = []
    exposure_by_symbol: dict[str, float] = {}
    notional_by_symbol: dict[str, float] = {}
    drawdown_usage = 0.0

    for candidate in candidates:
        rejection = _candidate_rejection(candidate, active_regimes)
        if rejection is not None:
            rejections.append(rejection)
            continue
        notional = min(float(candidate.target_notional), float(candidate.max_notional))
        symbol_count = max(1, len(candidate.symbol_scope))
        per_symbol_notional = notional / symbol_count

        crowded = _crowding_rejection(candidate, allocations, candidates, constraints)
        if crowded is not None:
            rejections.append(crowded)
            continue

        if any(
            exposure_by_symbol.get(symbol, 0.0) + per_symbol_notional > constraints.max_per_symbol_exposure
            for symbol in candidate.symbol_scope
        ):
            rejections.append(
                PortfolioRejection(
                    candidate.artifact_id,
                    "per_symbol_exposure_limit",
                    "candidate would breach max per-symbol exposure",
                )
            )
            continue

        gross_after = sum(allocation.notional for allocation in allocations) + notional
        if constraints.equity <= 0 or gross_after / constraints.equity > constraints.max_aggregate_leverage:
            rejections.append(
                PortfolioRejection(candidate.artifact_id, "aggregate_leverage_limit", "candidate would breach aggregate leverage")
            )
            continue

        drawdown_after = drawdown_usage + (notional / constraints.equity) * float(candidate.max_drawdown)
        if drawdown_after > constraints.drawdown_budget:
            rejections.append(
                PortfolioRejection(candidate.artifact_id, "drawdown_budget_limit", "candidate would breach drawdown budget")
            )
            continue

        allocations.append(
            PortfolioAllocation(
                artifact_id=candidate.artifact_id,
                strategy_id=candidate.strategy_id,
                symbols=tuple(candidate.symbol_scope),
                portfolio_role=candidate.portfolio_role,
                notional=round(notional, 8),
                expected_return_bps=float(candidate.expected_return_bps),
                max_drawdown=float(candidate.max_drawdown),
            )
        )
        drawdown_usage = drawdown_after
        for symbol in candidate.symbol_scope:
            exposure_by_symbol[symbol] = round(exposure_by_symbol.get(symbol, 0.0) + per_symbol_notional, 8)
            notional_by_symbol[symbol] = exposure_by_symbol[symbol]

    role_rejections = _role_fraction_rejections(allocations, constraints)
    if role_rejections:
        rejected_ids = {rejection.artifact_id for rejection in role_rejections}
        allocations = [allocation for allocation in allocations if allocation.artifact_id not in rejected_ids]
        rejections.extend(role_rejections)
        exposure_by_symbol = _exposure_from_allocations(allocations)
        notional_by_symbol = dict(exposure_by_symbol)
        drawdown_usage = sum((allocation.notional / constraints.equity) * allocation.max_drawdown for allocation in allocations)

    created_at = now_utc or _now_utc()
    payloads = tuple(_candidate_payload(candidate) for candidate in candidates)
    accepted = bool(allocations) and not rejections
    plan_without_id = {
        "allocations": [asdict(allocation) for allocation in allocations],
        "rejections": [asdict(rejection) for rejection in rejections],
        "constraints": asdict(constraints),
        "active_regimes": active_regimes,
        "exposure_by_symbol": exposure_by_symbol,
        "drawdown_usage": round(drawdown_usage, 8),
    }
    plan_id = "portfolio-" + _stable_hash(plan_without_id)[:16]
    aggregate_leverage = 0.0 if constraints.equity <= 0 else sum(a.notional for a in allocations) / constraints.equity
    return PortfolioPlan(
        portfolio_plan_id=plan_id,
        accepted=accepted,
        allocations=tuple(allocations),
        rejections=tuple(rejections),
        constraints=constraints,
        active_regimes=dict(active_regimes),
        exposure_by_symbol=exposure_by_symbol,
        notional_by_symbol=notional_by_symbol,
        aggregate_leverage=round(aggregate_leverage, 8),
        drawdown_usage=round(drawdown_usage, 8),
        created_at_utc=created_at,
        candidate_payloads=payloads,
    )


def build_portfolio_risk_dashboard(plan: PortfolioPlan) -> dict[str, object]:
    candidates = {str(payload["artifact_id"]): payload for payload in plan.candidate_payloads}
    stress_losses: dict[str, float] = {}
    correlations: dict[str, dict[str, float]] = {}
    artifact_health: dict[str, str] = {}
    paper_live_divergence: dict[str, float] = {}
    for artifact_id, payload in candidates.items():
        artifact_health[artifact_id] = str(payload.get("artifact_health", "unknown"))
        paper_live_divergence[artifact_id] = float(payload.get("paper_live_divergence_bps", 0.0))
        raw_stress = payload.get("stress_loss_by_scenario", {})
        if isinstance(raw_stress, dict):
            for scenario, loss in raw_stress.items():
                stress_losses[str(scenario)] = round(stress_losses.get(str(scenario), 0.0) + float(loss), 8)
        raw_corr = payload.get("correlation_by_artifact", {})
        if isinstance(raw_corr, dict):
            correlations[artifact_id] = {str(key): float(value) for key, value in raw_corr.items()}
    return {
        "portfolio_plan_id": plan.portfolio_plan_id,
        "accepted": plan.accepted,
        "correlations": correlations,
        "exposure_by_symbol": plan.exposure_by_symbol,
        "notional_by_symbol": plan.notional_by_symbol,
        "stress_losses": stress_losses,
        "active_regimes": plan.active_regimes,
        "artifact_health": artifact_health,
        "paper_live_divergence": paper_live_divergence,
        "aggregate_leverage": plan.aggregate_leverage,
        "drawdown_usage": plan.drawdown_usage,
        "rejections": [asdict(rejection) for rejection in plan.rejections],
    }


def build_portfolio_artifact(plan: PortfolioPlan) -> dict[str, object]:
    payload = {
        "schema_version": 1,
        "portfolio_plan_id": plan.portfolio_plan_id,
        "status": "accepted" if plan.accepted else "rejected",
        "created_at_utc": plan.created_at_utc,
        "allocations": [asdict(allocation) for allocation in plan.allocations],
        "rejections": [asdict(rejection) for rejection in plan.rejections],
        "constraints": asdict(plan.constraints),
        "active_regimes": plan.active_regimes,
        "exposure_by_symbol": plan.exposure_by_symbol,
        "notional_by_symbol": plan.notional_by_symbol,
        "aggregate_leverage": plan.aggregate_leverage,
        "drawdown_usage": plan.drawdown_usage,
    }
    digest = _stable_hash(payload)
    payload["portfolio_artifact_sha256"] = digest
    payload["portfolio_artifact_id"] = "portfolio-" + digest[:16]
    return payload


def persist_portfolio_plan(db_path: Path, plan: PortfolioPlan) -> str:
    initialize_memory_db(db_path)
    artifact = build_portfolio_artifact(plan)
    payload = dict(artifact)
    payload["dashboard"] = build_portfolio_risk_dashboard(plan)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO portfolio_plans (
                plan_id, status, created_at_utc, payload_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                plan.portfolio_plan_id,
                "accepted" if plan.accepted else "rejected",
                plan.created_at_utc,
                json.dumps(payload, sort_keys=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return plan.portfolio_plan_id


def detect_correlation_break(
    *,
    artifact_id: str,
    baseline_correlation: float,
    observed_correlation: float,
    threshold_delta: float,
    validated_actions: tuple[str, ...],
) -> CorrelationBreakDecision:
    delta = abs(float(observed_correlation) - float(baseline_correlation))
    allowed = tuple(action for action in validated_actions if action in {"reduce", "hedge", "pause"})
    return CorrelationBreakDecision(
        artifact_id=artifact_id,
        triggered=delta >= threshold_delta,
        baseline_correlation=float(baseline_correlation),
        observed_correlation=float(observed_correlation),
        delta=round(delta, 8),
        allowed_actions=allowed,
        reason_code="correlation_break_overlay" if delta >= threshold_delta else "correlation_within_band",
    )


def apply_human_override(db_path: Path, request: HumanOverrideRequest) -> HumanOverrideResult:
    initialize_memory_db(db_path)
    event_id = "override-" + uuid4().hex
    reasons = _override_rejections(request)
    status = "rejected" if reasons else "applied"
    payload = dict(request.payload or {})
    payload["reason"] = request.reason or ""
    now = _now_utc()
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO human_override_journal (
                override_event_id, ts_utc, operator_id, action, artifact_id,
                confirmation, status, reason_code, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                now,
                request.operator_id,
                request.action,
                request.artifact_id,
                request.confirmation,
                status,
                reasons[0] if reasons else f"human_override_{request.action}",
                json.dumps(payload, sort_keys=True),
            ),
        )
        if not reasons:
            _apply_override_db_effect(connection, request)
            connection.execute(
                """
                INSERT OR REPLACE INTO risk_events (
                    risk_event_id, ts_utc, reason_code, severity, action, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "risk-" + event_id,
                    now,
                    f"human_override_{request.action}",
                    "critical" if request.action in DESTRUCTIVE_OVERRIDES else "info",
                    request.action,
                    json.dumps({"operator_id": request.operator_id, "artifact_id": request.artifact_id}, sort_keys=True),
                ),
            )
        connection.commit()
    finally:
        connection.close()

    if not reasons and request.action == "kill_switch":
        append_execution_event(
            db_path,
            ts_exchange=now,
            ts_gateway=now,
            ts_engine=now,
            source="human_override",
            event_type="KILL_SWITCH_TRIGGER",
            status="applied",
            reason_code="human_override_kill_switch",
            metadata={"operator_id": request.operator_id},
        )
    journal = _load_override_journal(db_path, artifact_id=request.artifact_id) if request.action == "view_journal" else ()
    return HumanOverrideResult(
        applied=not reasons,
        override_event_id=event_id,
        action=request.action,
        reasons=tuple(reasons),
        journal=journal,
    )


def _candidate_rejection(
    candidate: PortfolioArtifactCandidate,
    active_regimes: dict[str, str],
) -> PortfolioRejection | None:
    if not candidate.approved:
        return PortfolioRejection(candidate.artifact_id, "artifact_not_approved", "artifact is not approved")
    if candidate.artifact_payload is not None:
        authority = paper_authority_decision(candidate.artifact_payload)
        if not authority.allowed:
            reason = (
                "missing_promotion_manifest"
                if "missing_promotion_manifest" in authority.reasons
                else authority.reasons[0] if authority.reasons else "artifact_not_paper_eligible"
            )
            return PortfolioRejection(candidate.artifact_id, reason, "artifact manifest does not permit paper allocation")
    if not candidate.symbol_scope:
        return PortfolioRejection(candidate.artifact_id, "missing_symbol_scope", "artifact must declare symbol scope")
    if not candidate.regime_scope:
        return PortfolioRejection(candidate.artifact_id, "missing_regime_scope", "artifact must declare regime scope")
    if candidate.portfolio_role not in PORTFOLIO_ROLES:
        return PortfolioRejection(candidate.artifact_id, "invalid_portfolio_role", "artifact must declare a supported portfolio role")
    if candidate.artifact_health not in ACTIVE_ARTIFACT_STATES:
        return PortfolioRejection(candidate.artifact_id, "artifact_not_active", "artifact lifecycle state cannot be allocated")
    for symbol in candidate.symbol_scope:
        active = active_regimes.get(symbol)
        if active is not None and active not in candidate.regime_scope:
            return PortfolioRejection(candidate.artifact_id, "regime_scope_mismatch", "active regime is outside artifact regime scope")
    return None


def _crowding_rejection(
    candidate: PortfolioArtifactCandidate,
    allocations: list[PortfolioAllocation],
    candidates: list[PortfolioArtifactCandidate],
    constraints: PortfolioConstraints,
) -> PortfolioRejection | None:
    candidate_corr = candidate.correlation_by_artifact or {}
    by_id = {item.artifact_id: item for item in candidates}
    for allocation in allocations:
        corr = candidate_corr.get(allocation.artifact_id)
        if corr is None:
            reverse = by_id.get(allocation.artifact_id)
            corr = (reverse.correlation_by_artifact or {}).get(candidate.artifact_id) if reverse else None
        if corr is not None and abs(float(corr)) > constraints.max_pairwise_correlation:
            return PortfolioRejection(candidate.artifact_id, "correlation_crowding", "candidate is too correlated with allocated artifact")
    return None


def _role_fraction_rejections(
    allocations: list[PortfolioAllocation],
    constraints: PortfolioConstraints,
) -> list[PortfolioRejection]:
    if constraints.max_role_fraction >= 1.0 or len(allocations) < 2:
        return []
    total = sum(allocation.notional for allocation in allocations)
    if total <= 0:
        return []
    by_role: dict[str, list[PortfolioAllocation]] = {}
    for allocation in allocations:
        by_role.setdefault(allocation.portfolio_role, []).append(allocation)
    rejections: list[PortfolioRejection] = []
    for role, rows in by_role.items():
        role_total = sum(row.notional for row in rows)
        if role_total / total <= constraints.max_role_fraction:
            continue
        for row in sorted(rows, key=lambda item: item.notional, reverse=True)[1:]:
            rejections.append(
                PortfolioRejection(row.artifact_id, "role_crowding_limit", f"portfolio role {role} exceeds fraction limit")
            )
    return rejections


def _exposure_from_allocations(allocations: list[PortfolioAllocation]) -> dict[str, float]:
    exposure: dict[str, float] = {}
    for allocation in allocations:
        per_symbol = allocation.notional / max(1, len(allocation.symbols))
        for symbol in allocation.symbols:
            exposure[symbol] = round(exposure.get(symbol, 0.0) + per_symbol, 8)
    return exposure


def _candidate_payload(candidate: PortfolioArtifactCandidate) -> dict[str, object]:
    payload = asdict(candidate)
    payload["symbol_scope"] = list(candidate.symbol_scope)
    payload["regime_scope"] = list(candidate.regime_scope)
    payload["stress_loss_by_scenario"] = dict(candidate.stress_loss_by_scenario or {})
    payload["correlation_by_artifact"] = dict(candidate.correlation_by_artifact or {})
    return payload


def _override_rejections(request: HumanOverrideRequest) -> list[str]:
    reasons: list[str] = []
    if request.action not in OVERRIDE_ACTIONS:
        reasons.append("invalid_override_action")
    if not request.operator_id:
        reasons.append("operator_id_required")
    if request.action in {"pause_artifact", "resume_artifact", "rollback_artifact", "force_reconcile"} and not request.artifact_id:
        reasons.append("artifact_id_required")
    if request.action in DESTRUCTIVE_OVERRIDES:
        expected = f"CONFIRM:{request.action}"
        if request.confirmation != expected:
            reasons.append(f"confirmation_required:{expected}")
    return reasons


def _apply_override_db_effect(connection: sqlite3.Connection, request: HumanOverrideRequest) -> None:
    if request.action == "pause_artifact" and request.artifact_id:
        connection.execute("UPDATE artifacts SET rollout_stage = 'paused' WHERE artifact_id = ?", (request.artifact_id,))
    elif request.action == "resume_artifact" and request.artifact_id:
        connection.execute("UPDATE artifacts SET rollout_stage = 'paper' WHERE artifact_id = ?", (request.artifact_id,))
    elif request.action == "rollback_artifact" and request.artifact_id:
        connection.execute("UPDATE artifacts SET rollout_stage = 'retired' WHERE artifact_id = ?", (request.artifact_id,))


def _load_override_journal(db_path: Path, *, artifact_id: str | None = None) -> tuple[dict[str, object], ...]:
    connection = sqlite3.connect(db_path)
    try:
        if artifact_id:
            rows = connection.execute(
                """
                SELECT override_event_id, ts_utc, operator_id, action, artifact_id, status, reason_code
                FROM human_override_journal
                WHERE artifact_id = ?
                ORDER BY ts_utc ASC
                """,
                (artifact_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT override_event_id, ts_utc, operator_id, action, artifact_id, status, reason_code
                FROM human_override_journal
                ORDER BY ts_utc ASC
                """
            ).fetchall()
    finally:
        connection.close()
    return tuple(
        {
            "override_event_id": row[0],
            "ts_utc": row[1],
            "operator_id": row[2],
            "action": row[3],
            "artifact_id": row[4],
            "status": row[5],
            "reason_code": row[6],
        }
        for row in rows
    )


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
