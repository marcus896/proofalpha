from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from engine.memory.store import initialize_memory_db
from engine.portfolio.allocator import (
    PortfolioArtifactCandidate,
    PortfolioConstraints,
    build_portfolio_artifact,
    build_portfolio_plan,
    build_portfolio_risk_dashboard,
    persist_portfolio_plan,
)
from engine.portfolio.delta_order_plan import build_delta_order_plan
from engine.portfolio.target_portfolio import build_target_portfolio


@dataclass(frozen=True)
class PaperPortfolioLoopConfig:
    db_path: Path
    session_id: str
    constraints: dict[str, object]
    active_regimes: dict[str, str]
    interval_seconds: int = 900
    min_calibration_samples: int = 10
    max_paper_slip_bps: float = 25.0


def build_paper_portfolio_loop_input(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("paper portfolio loop input must be a JSON object")
    constraints = payload.get("constraints")
    active_regimes = payload.get("active_regimes")
    if not isinstance(constraints, dict):
        raise ValueError("paper portfolio loop input requires constraints object")
    if not isinstance(active_regimes, dict):
        raise ValueError("paper portfolio loop input requires active_regimes object")
    return {
        "constraints": constraints,
        "active_regimes": {str(key): str(value) for key, value in active_regimes.items()},
        "interval_seconds": int(payload.get("interval_seconds", 900)),
        "min_calibration_samples": int(payload.get("min_calibration_samples", 10)),
        "max_paper_slip_bps": float(payload.get("max_paper_slip_bps", 25.0)),
    }


def run_paper_portfolio_allocator_tick(config: PaperPortfolioLoopConfig) -> dict[str, object]:
    initialize_memory_db(config.db_path)
    constraints = _constraints_from_payload(config.constraints)
    current_exposure = _load_current_exposure(config.db_path, config.session_id)
    telemetry = _load_paper_telemetry(config.db_path)
    candidates, resized_targets, loop_rejections = _load_candidates(
        config.db_path,
        session_id=config.session_id,
        constraints=constraints,
        current_exposure=current_exposure,
        telemetry=telemetry,
        min_calibration_samples=config.min_calibration_samples,
        max_paper_slip_bps=config.max_paper_slip_bps,
    )
    plan = build_portfolio_plan(candidates, constraints, active_regimes=config.active_regimes)
    target_portfolio = build_target_portfolio(
        universe_id="paper-session",
        artifact_set_id=plan.portfolio_plan_id,
        capital_base=constraints.equity,
        allocations=plan.allocations,
    )
    delta_order_plan = build_delta_order_plan(
        plan_id=target_portfolio.target_portfolio_id,
        current_positions=current_exposure,
        target_positions=list(target_portfolio.symbol_targets),
    )
    persist_portfolio_plan(config.db_path, plan)
    _link_session_plan(config.db_path, config.session_id, plan.portfolio_plan_id)
    dashboard = build_portfolio_risk_dashboard(plan)
    artifact = build_portfolio_artifact(plan)
    result = {
        "status": "accepted" if plan.accepted else "rejected",
        "session_id": config.session_id,
        "portfolio_plan_id": plan.portfolio_plan_id,
        "interval_seconds": int(config.interval_seconds),
        "allocations": artifact["allocations"],
        "rejections": artifact["rejections"],
        "dashboard": dashboard,
        "current_exposure_by_symbol": current_exposure,
        "target_portfolio": target_portfolio.to_dict(),
        "delta_order_plan": delta_order_plan.to_dict(),
        "internal_order_intents": delta_order_plan.to_internal_order_intents(),
        "resized_targets": resized_targets,
        "loop_rejections": loop_rejections,
        "candidate_count": len(candidates),
    }
    _journal_decision(config.db_path, config, result)
    return result


def _load_candidates(
    db_path: Path,
    *,
    session_id: str,
    constraints: PortfolioConstraints,
    current_exposure: dict[str, float],
    telemetry: dict[str, dict[str, float]],
    min_calibration_samples: int,
    max_paper_slip_bps: float,
) -> tuple[list[PortfolioArtifactCandidate], dict[str, float], dict[str, list[str]]]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        session = connection.execute("SELECT session_id FROM paper_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if session is None:
            raise ValueError(f"paper session not found: {session_id}")
        rows = connection.execute(
            """
            SELECT
                psa.artifact_id,
                psa.lifecycle_state,
                psa.status AS session_status,
                psa.payload_json AS session_payload_json,
                a.strategy_id,
                a.rollout_stage,
                a.approved,
                a.payload_json AS artifact_payload_json
            FROM paper_session_artifacts psa
            LEFT JOIN artifacts a ON a.artifact_id = psa.artifact_id
            WHERE psa.session_id = ?
            ORDER BY psa.artifact_id
            """,
            (session_id,),
        ).fetchall()
    finally:
        connection.close()

    candidates: list[PortfolioArtifactCandidate] = []
    resized_targets: dict[str, float] = {}
    loop_rejections: dict[str, list[str]] = {}
    for row in rows:
        artifact_id = str(row["artifact_id"])
        payload = _merge_payloads(row["artifact_payload_json"], row["session_payload_json"])
        reasons = _loop_rejection_reasons(
            telemetry.get(artifact_id, {}),
            min_calibration_samples=min_calibration_samples,
            max_paper_slip_bps=max_paper_slip_bps,
        )
        if reasons:
            loop_rejections[artifact_id] = reasons
        target = float(payload.get("target_notional", 0.0) or 0.0)
        symbol_scope = _string_tuple(payload.get("symbol_scope"))
        resized = _resize_target_for_current_exposure(target, symbol_scope, constraints, current_exposure)
        if resized < target:
            resized_targets[artifact_id] = round(resized, 8)
        health = str(row["rollout_stage"] or row["lifecycle_state"] or "paper")
        if row["session_status"] != "active" or reasons:
            health = "sample_guarded"
        candidates.append(
            PortfolioArtifactCandidate(
                artifact_id=artifact_id,
                strategy_id=str(row["strategy_id"] or payload.get("strategy_id") or artifact_id),
                symbol_scope=symbol_scope,
                regime_scope=_string_tuple(payload.get("regime_scope")),
                portfolio_role=str(payload.get("portfolio_role") or "core"),
                target_notional=resized,
                max_notional=min(float(payload.get("max_notional", resized) or resized), resized) if resized < target else float(payload.get("max_notional", target) or target),
                expected_return_bps=float(payload.get("expected_return_bps", 0.0) or 0.0),
                max_drawdown=float(payload.get("max_drawdown", 0.0) or 0.0),
                artifact_health=health,
                approved=bool(row["approved"] if row["approved"] is not None else True),
                paper_live_divergence_bps=float(telemetry.get(artifact_id, {}).get("paper_live_max_abs_slip_bps", 0.0)),
                stress_loss_by_scenario=_dict_of_float(payload.get("stress_loss_by_scenario")),
                correlation_by_artifact=_dict_of_float(payload.get("correlation_by_artifact")),
            )
        )
    return candidates, resized_targets, loop_rejections


def _loop_rejection_reasons(
    telemetry: dict[str, float],
    *,
    min_calibration_samples: int,
    max_paper_slip_bps: float,
) -> list[str]:
    sample_count = int(telemetry.get("paper_live_sample_count", 0))
    max_slip = abs(float(telemetry.get("paper_live_max_abs_slip_bps", 0.0)))
    reasons: list[str] = []
    if sample_count < min_calibration_samples:
        reasons.append(f"insufficient_paper_samples:{sample_count}<{min_calibration_samples}")
    if max_slip > max_paper_slip_bps:
        reasons.append(f"paper_slip_too_wide:{max_slip}>{max_paper_slip_bps}")
    return reasons


def _load_paper_telemetry(db_path: Path) -> dict[str, dict[str, float]]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT artifact_id, metric_name, metric_value
            FROM live_metrics
            WHERE metric_name IN ('paper_live_sample_count', 'paper_live_max_abs_slip_bps')
            ORDER BY ts_utc, metric_id
            """
        ).fetchall()
    finally:
        connection.close()
    result: dict[str, dict[str, float]] = {}
    for artifact_id, metric_name, metric_value in rows:
        result.setdefault(str(artifact_id), {})[str(metric_name)] = float(metric_value or 0.0)
    return result


def _load_current_exposure(db_path: Path, session_id: str) -> dict[str, float]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT symbol, COALESCE(SUM(ABS(qty_filled * live_vwap_price)), 0)
            FROM order_telemetry
            WHERE COALESCE(was_rejected, 0) = 0
              AND COALESCE(risk_blocked, 0) = 0
              AND json_extract(metadata_json, '$.session_id') = ?
            GROUP BY symbol
            ORDER BY symbol
            """,
            (session_id,),
        ).fetchall()
    finally:
        connection.close()
    return {str(symbol): round(float(value or 0.0), 8) for symbol, value in rows}


def _resize_target_for_current_exposure(
    target: float,
    symbol_scope: tuple[str, ...],
    constraints: PortfolioConstraints,
    current_exposure: dict[str, float],
) -> float:
    if not symbol_scope:
        return target
    per_symbol_target = target / max(1, len(symbol_scope))
    allowed_per_symbol = [
        max(0.0, constraints.max_per_symbol_exposure - current_exposure.get(symbol, 0.0))
        for symbol in symbol_scope
    ]
    if not allowed_per_symbol:
        return target
    max_target = min(allowed_per_symbol) * max(1, len(symbol_scope))
    if per_symbol_target <= min(allowed_per_symbol):
        return target
    return round(min(target, max_target), 8)


def _journal_decision(db_path: Path, config: PaperPortfolioLoopConfig, result: dict[str, object]) -> None:
    now = _now_utc()
    decision_id = "paper-portfolio-" + _stable_hash({"session_id": config.session_id, "plan": result["portfolio_plan_id"], "ts": now})[:16]
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO paper_portfolio_decisions (
                decision_id, session_id, portfolio_plan_id, ts_utc, interval_seconds,
                status, reason_code, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                config.session_id,
                str(result["portfolio_plan_id"]),
                now,
                int(config.interval_seconds),
                str(result["status"]),
                "paper_portfolio_loop_tick",
                json.dumps(result, sort_keys=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _link_session_plan(db_path: Path, session_id: str, plan_id: str) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("UPDATE paper_sessions SET portfolio_plan_id = ? WHERE session_id = ?", (plan_id, session_id))
        connection.commit()
    finally:
        connection.close()


def _constraints_from_payload(payload: dict[str, object]) -> PortfolioConstraints:
    return PortfolioConstraints(
        equity=float(payload["equity"]),
        max_per_symbol_exposure=float(payload["max_per_symbol_exposure"]),
        max_aggregate_leverage=float(payload["max_aggregate_leverage"]),
        drawdown_budget=float(payload["drawdown_budget"]),
        max_pairwise_correlation=float(payload["max_pairwise_correlation"]),
        max_role_fraction=float(payload.get("max_role_fraction", 1.0)),
    )


def _merge_payloads(*raw_values: object) -> dict[str, object]:
    merged: dict[str, object] = {}
    for raw in raw_values:
        if not raw:
            continue
        payload = json.loads(str(raw))
        if isinstance(payload, dict):
            merged.update(payload)
    return merged


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    if isinstance(value, str) and value:
        return (value,)
    return ()


def _dict_of_float(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {str(key): float(raw) for key, raw in value.items()}


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
