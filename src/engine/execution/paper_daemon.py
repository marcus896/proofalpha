from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3

from engine.execution.paper import (
    PaperMarketSnapshot,
    PaperOrderIntent,
    paper_fixture_from_payload,
    record_paper_execution_result,
    run_paper_executor_fixture,
)
from engine.execution.paper_streams import NormalizedPaperStreamEvent, record_paper_stream_event
from engine.io.sqlite import connect_sqlite
from engine.memory.store import append_execution_event, initialize_memory_db
from engine.strategy.artifacts import load_strategy_artifact, validate_strategy_artifact


DEFAULT_PAPER_STREAMS = (
    "aggTrade",
    "bookTicker",
    "markPrice@1s",
    "depth",
    "forceOrder",
)


@dataclass(frozen=True)
class PaperRiskLimits:
    max_per_symbol_notional: float = 100_000.0
    max_aggregate_notional: float = 250_000.0
    max_spread_bps: float = 25.0
    min_visible_depth_qty: float = 0.0
    max_order_rate_per_minute: int = 60


@dataclass(frozen=True)
class PaperDaemonDryRunConfig:
    db_path: Path
    artifact_paths: tuple[Path, ...]
    market_fixture_path: Path
    session_id: str | None = None
    host_id: str | None = None
    portfolio_plan_id: str | None = None
    streams: tuple[str, ...] = DEFAULT_PAPER_STREAMS
    risk_limits: PaperRiskLimits = PaperRiskLimits()


def run_paper_daemon_dry_run(config: PaperDaemonDryRunConfig) -> dict[str, object]:
    initialize_memory_db(config.db_path)
    fixture_payload = json.loads(config.market_fixture_path.read_text(encoding="utf-8"))
    if not isinstance(fixture_payload, dict):
        raise ValueError("market fixture must be a JSON object")
    order_intents, market_snapshots = paper_fixture_from_payload(fixture_payload)
    artifacts = [load_strategy_artifact(path) for path in config.artifact_paths]
    session_id = config.session_id or _session_id(artifacts, order_intents, market_snapshots)
    host_id = config.host_id or platform.node() or "local"
    started_at = _utc_now()
    code_hash = _code_hash()
    config_checksum = _stable_hash(
        {
            "artifact_ids": [artifact.get("artifact_id") for artifact in artifacts],
            "fixture": str(config.market_fixture_path),
            "risk_limits": asdict(config.risk_limits),
            "streams": list(config.streams),
        }
    )
    symbols = sorted(
        {
            str(value)
            for value in [
                *(intent.symbol for intent in order_intents),
                *(snapshot.symbol for snapshot in market_snapshots),
            ]
            if value
        }
    )
    _upsert_paper_session(
        config.db_path,
        session_id=session_id,
        host_id=host_id,
        status="running",
        started_at_utc=started_at,
        stopped_at_utc=None,
        heartbeat_at_utc=started_at,
        portfolio_plan_id=config.portfolio_plan_id,
        symbols=symbols,
        streams=config.streams,
        code_hash=code_hash,
        config_checksum=config_checksum,
        payload={
            "mode": "dry_run",
            "market_fixture_path": str(config.market_fixture_path),
            "risk_limits": asdict(config.risk_limits),
        },
    )
    for artifact in artifacts:
        validation = validate_strategy_artifact(artifact)
        _upsert_session_artifact(config.db_path, session_id, artifact, validation.passed)

    append_execution_event(
        config.db_path,
        ts_exchange=started_at,
        ts_gateway=started_at,
        ts_engine=started_at,
        source="paper_daemon",
        event_type="ENGINE_START",
        status="running",
        reason_code="paper_daemon_dry_run_start",
        metadata={"session_id": session_id, "host_id": host_id, "artifact_count": len(artifacts)},
    )
    _record_fixture_stream_events(config.db_path, session_id, market_snapshots)

    snapshots_by_symbol = {snapshot.symbol: snapshot for snapshot in market_snapshots}
    exposure_by_symbol: dict[str, float] = {}
    allowed_intents: list[PaperOrderIntent] = []
    risk_blocks: list[dict[str, object]] = []
    seen_intents: set[tuple[str, str, float, float]] = set()
    aggregate_notional = 0.0
    for intent in order_intents:
        snapshot = snapshots_by_symbol.get(intent.symbol)
        reasons = _risk_block_reasons(
            intent=intent,
            snapshot=snapshot,
            limits=config.risk_limits,
            exposure_by_symbol=exposure_by_symbol,
            aggregate_notional=aggregate_notional,
            seen_intents=seen_intents,
        )
        intent_key = (intent.symbol, intent.side.upper(), float(intent.qty), float(intent.expected_price))
        seen_intents.add(intent_key)
        if reasons:
            for reason in reasons:
                event_id = append_execution_event(
                    config.db_path,
                    ts_exchange=snapshot.ts if snapshot else started_at,
                    ts_gateway=_utc_now(),
                    ts_engine=_utc_now(),
                    source="paper_daemon",
                    event_type="RISK_BLOCK",
                    symbol=intent.symbol,
                    side=intent.side.upper(),
                    parent_intent_id=f"{session_id}:{len(risk_blocks) + 1}",
                    qty=float(intent.qty),
                    price=float(intent.expected_price),
                    status="blocked",
                    reason_code=reason,
                    metadata={"session_id": session_id, "intent": asdict(intent)},
                )
                _insert_risk_event(config.db_path, event_id, reason, session_id, intent)
                risk_blocks.append({"reason_code": reason, "symbol": intent.symbol, "event_id": event_id})
            continue
        notional = abs(float(intent.qty) * float(intent.expected_price))
        exposure_by_symbol[intent.symbol] = exposure_by_symbol.get(intent.symbol, 0.0) + notional
        aggregate_notional += notional
        allowed_intents.append(intent)

    aggregate_result: dict[str, object] = {
        "status": "completed",
        "session_id": session_id,
        "order_telemetry": [],
        "funding_events": [],
        "paper_live_divergence": {"sample_count": 0, "average_slip_bps": 0.0, "max_abs_slip_bps": 0.0},
    }
    for artifact in artifacts:
        result = run_paper_executor_fixture(
            artifact,
            order_intents=allowed_intents,
            market_snapshots=market_snapshots,
        )
        for row in result.get("order_telemetry", []):
            if isinstance(row, dict):
                row["telemetry_id"] = f"{session_id}:{row.get('telemetry_id')}"
        record_paper_execution_result(config.db_path, result, session_id=session_id)
        aggregate_result["order_telemetry"].extend(result.get("order_telemetry", []))  # type: ignore[union-attr]
        aggregate_result["funding_events"].extend(result.get("funding_events", []))  # type: ignore[union-attr]

    stopped_at = _utc_now()
    summary = _build_session_summary(
        session_id=session_id,
        started_at=started_at,
        stopped_at=stopped_at,
        artifact_count=len(artifacts),
        symbols=symbols,
        order_intents=order_intents,
        telemetry_rows=aggregate_result["order_telemetry"],  # type: ignore[arg-type]
        funding_rows=aggregate_result["funding_events"],  # type: ignore[arg-type]
        risk_blocks=risk_blocks,
    )
    _insert_session_summary(config.db_path, summary)
    _finish_paper_session(config.db_path, session_id, stopped_at, status="completed")
    append_execution_event(
        config.db_path,
        ts_exchange=stopped_at,
        ts_gateway=stopped_at,
        ts_engine=stopped_at,
        source="paper_daemon",
        event_type="ENGINE_STOP",
        status="completed",
        reason_code="paper_daemon_dry_run_completed",
        metadata={"session_id": session_id, "risk_block_count": len(risk_blocks)},
    )
    return load_paper_status(config.db_path, session_id=session_id)


def load_paper_status(db_path: Path, *, session_id: str | None = None) -> dict[str, object]:
    initialize_memory_db(db_path)
    connection = connect_sqlite(db_path, read_only=True)
    try:
        session = _load_session_row(connection, session_id)
        if session is None:
            return {"status": "no_sessions", "session": None}
        session_id = str(session["session_id"])
        summary = _load_summary_row(connection, session_id)
        risk_blocks = connection.execute(
            "SELECT COUNT(*) FROM risk_events WHERE json_extract(metadata_json, '$.session_id') = ?",
            (session_id,),
        ).fetchone()[0]
        telemetry = connection.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(qty_filled), 0),
                COALESCE(SUM(fee_quote), 0),
                COALESCE(SUM(CASE WHEN was_rejected THEN 1 ELSE 0 END), 0)
            FROM order_telemetry
            WHERE json_extract(metadata_json, '$.session_id') = ?
            """,
            (session_id,),
        ).fetchone()
        streams = connection.execute(
            """
            SELECT stream_name, symbol, COUNT(*), MAX(received_at_utc), AVG(lag_ms)
            FROM paper_stream_events
            WHERE session_id = ?
            GROUP BY stream_name, symbol
            ORDER BY stream_name, symbol
            """,
            (session_id,),
        ).fetchall()
        calibration_samples = connection.execute(
            """
            SELECT symbol, COUNT(*)
            FROM order_telemetry
            WHERE json_extract(metadata_json, '$.session_id') = ?
            GROUP BY symbol
            ORDER BY symbol
            """,
            (session_id,),
        ).fetchall()
        return {
            "status": session["status"],
            "session": session,
            "summary": summary,
            "telemetry": {
                "order_rows": int(telemetry[0]),
                "qty_filled": float(telemetry[1]),
                "fee_quote": float(telemetry[2]),
                "rejected_rows": int(telemetry[3]),
            },
            "risk": {"risk_block_count": int(risk_blocks)},
            "streams": [
                {
                    "stream_name": row[0],
                    "symbol": row[1],
                    "event_count": int(row[2]),
                    "last_received_at_utc": row[3],
                    "lag_avg_ms": float(row[4] or 0.0),
                }
                for row in streams
            ],
            "calibration": {
                "sample_counts": {str(row[0]): int(row[1]) for row in calibration_samples},
            },
            "storage": {"db_path": str(db_path), "db_size_bytes": db_path.stat().st_size if db_path.exists() else 0},
        }
    finally:
        connection.close()


def _risk_block_reasons(
    *,
    intent: PaperOrderIntent,
    snapshot: PaperMarketSnapshot | None,
    limits: PaperRiskLimits,
    exposure_by_symbol: dict[str, float],
    aggregate_notional: float,
    seen_intents: set[tuple[str, str, float, float]],
) -> list[str]:
    reasons: list[str] = []
    intent_key = (intent.symbol, intent.side.upper(), float(intent.qty), float(intent.expected_price))
    if intent_key in seen_intents:
        reasons.append("duplicate_intent")
    notional = abs(float(intent.qty) * float(intent.expected_price))
    if exposure_by_symbol.get(intent.symbol, 0.0) + notional > limits.max_per_symbol_notional:
        reasons.append("max_per_symbol_exposure")
    if aggregate_notional + notional > limits.max_aggregate_notional:
        reasons.append("max_aggregate_notional")
    if snapshot is None:
        reasons.append("missing_book_trade_stream")
        return reasons
    mid = (float(snapshot.bid) + float(snapshot.ask)) / 2.0
    spread_bps = ((float(snapshot.ask) - float(snapshot.bid)) / mid) * 10_000.0 if mid else 0.0
    if spread_bps > limits.max_spread_bps:
        reasons.append("spread_too_wide")
    if float(snapshot.visible_depth_qty) < limits.min_visible_depth_qty:
        reasons.append("depth_too_thin")
    if float(snapshot.topn_depth_qty) and float(intent.qty) > float(snapshot.topn_depth_qty):
        reasons.append("depth_too_thin")
    return reasons


def _upsert_paper_session(
    db_path: Path,
    *,
    session_id: str,
    host_id: str,
    status: str,
    started_at_utc: str,
    stopped_at_utc: str | None,
    heartbeat_at_utc: str | None,
    portfolio_plan_id: str | None,
    symbols: list[str],
    streams: tuple[str, ...],
    code_hash: str,
    config_checksum: str,
    payload: dict[str, object],
) -> None:
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO paper_sessions (
                session_id, host_id, status, started_at_utc, stopped_at_utc, heartbeat_at_utc,
                portfolio_plan_id, symbols_json, streams_json, code_hash, config_checksum, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                host_id,
                status,
                started_at_utc,
                stopped_at_utc,
                heartbeat_at_utc,
                portfolio_plan_id,
                json.dumps(symbols, sort_keys=True),
                json.dumps(list(streams), sort_keys=True),
                code_hash,
                config_checksum,
                json.dumps(payload, sort_keys=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _finish_paper_session(db_path: Path, session_id: str, stopped_at_utc: str, *, status: str) -> None:
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            UPDATE paper_sessions
            SET status = ?, stopped_at_utc = ?, heartbeat_at_utc = ?
            WHERE session_id = ?
            """,
            (status, stopped_at_utc, stopped_at_utc, session_id),
        )
        connection.commit()
    finally:
        connection.close()


def _upsert_session_artifact(db_path: Path, session_id: str, artifact: dict[str, object], validation_passed: bool) -> None:
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO paper_session_artifacts (
                session_id, artifact_id, artifact_sha256, lifecycle_state, status, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                str(artifact.get("artifact_id")),
                str(artifact.get("artifact_sha256") or ""),
                str(artifact.get("rollout_stage") or ""),
                "active" if validation_passed else "blocked",
                json.dumps({"family": artifact.get("family"), "variant_id": artifact.get("variant_id")}, sort_keys=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _record_fixture_stream_events(db_path: Path, session_id: str, snapshots: list[PaperMarketSnapshot]) -> None:
    for ordinal, snapshot in enumerate(snapshots, start=1):
        payload = asdict(snapshot)
        record_paper_stream_event(
            db_path,
            NormalizedPaperStreamEvent(
                stream_event_id=f"{session_id}:fixture:{ordinal}",
                session_id=session_id,
                received_at_utc=_utc_now(),
                exchange_event_time=snapshot.ts,
                stream_name="fixture:market_snapshot",
                symbol=snapshot.symbol,
                sequence_id=str(ordinal),
                payload_hash=_stable_hash(payload),
                payload=payload,
                parse_status="parsed",
                lag_ms=0.0,
                metadata={"source": "paper_daemon_dry_run"},
            ),
        )


def _insert_risk_event(
    db_path: Path,
    source_event_id: int,
    reason_code: str,
    session_id: str,
    intent: PaperOrderIntent,
) -> None:
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO risk_events (
                risk_event_id, ts_utc, source_event_id, reason_code, severity, action, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{session_id}:risk:{source_event_id}",
                _utc_now(),
                source_event_id,
                reason_code,
                "block",
                "block_intent",
                json.dumps({"session_id": session_id, "intent": asdict(intent)}, sort_keys=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _build_session_summary(
    *,
    session_id: str,
    started_at: str,
    stopped_at: str,
    artifact_count: int,
    symbols: list[str],
    order_intents: list[PaperOrderIntent],
    telemetry_rows: list[object],
    funding_rows: list[object],
    risk_blocks: list[dict[str, object]],
) -> dict[str, object]:
    rows = [row for row in telemetry_rows if isinstance(row, dict)]
    funding = [row for row in funding_rows if isinstance(row, dict)]
    filled = [row for row in rows if float(row.get("qty_filled", 0.0) or 0.0) > 0.0]
    partial = [
        row
        for row in rows
        if 0.0 < float(row.get("qty_filled", 0.0) or 0.0) < float(row.get("qty_submitted", 0.0) or 0.0)
    ]
    fees = sum(float(row.get("fee_quote", 0.0) or 0.0) for row in rows)
    funding_fee = sum(float(row.get("funding_fee", 0.0) or 0.0) for row in funding)
    total_decisions = len(order_intents) + len(risk_blocks)
    telemetry_quality = 1.0 if total_decisions == 0 else max(0.0, 1.0 - (len(risk_blocks) / total_decisions))
    return {
        "session_id": session_id,
        "created_at_utc": stopped_at,
        "status": "completed",
        "uptime_seconds": _seconds_between(started_at, stopped_at),
        "artifact_count": artifact_count,
        "symbol_count": len(symbols),
        "order_count": len(order_intents),
        "filled_count": len(filled),
        "partial_count": len(partial),
        "rejected_count": sum(1 for row in rows if row.get("was_rejected")) + len(risk_blocks),
        "risk_block_count": len(risk_blocks),
        "funding_fee": funding_fee,
        "paper_pnl": round(-(fees + funding_fee), 12),
        "drawdown": 0.0,
        "telemetry_quality_score": round(telemetry_quality, 12),
        "payload": {"risk_blocks": risk_blocks, "fee_quote": fees},
    }


def _insert_session_summary(db_path: Path, summary: dict[str, object]) -> None:
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO paper_session_summaries (
                session_id, created_at_utc, status, uptime_seconds, artifact_count, symbol_count,
                order_count, filled_count, partial_count, rejected_count, risk_block_count,
                funding_fee, paper_pnl, drawdown, telemetry_quality_score, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary["session_id"],
                summary["created_at_utc"],
                summary["status"],
                summary["uptime_seconds"],
                summary["artifact_count"],
                summary["symbol_count"],
                summary["order_count"],
                summary["filled_count"],
                summary["partial_count"],
                summary["rejected_count"],
                summary["risk_block_count"],
                summary["funding_fee"],
                summary["paper_pnl"],
                summary["drawdown"],
                summary["telemetry_quality_score"],
                json.dumps(summary.get("payload", {}), sort_keys=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _load_session_row(connection: sqlite3.Connection, session_id: str | None) -> dict[str, object] | None:
    if session_id:
        row = connection.execute("SELECT * FROM paper_sessions WHERE session_id = ?", (session_id,)).fetchone()
    else:
        row = connection.execute(
            "SELECT * FROM paper_sessions ORDER BY started_at_utc DESC, session_id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _load_summary_row(connection: sqlite3.Connection, session_id: str) -> dict[str, object] | None:
    row = connection.execute(
        "SELECT * FROM paper_session_summaries WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None


def _session_id(
    artifacts: list[dict[str, object]],
    intents: list[PaperOrderIntent],
    snapshots: list[PaperMarketSnapshot],
) -> str:
    return "paper-" + _stable_hash(
        {
            "artifact_ids": [artifact.get("artifact_id") for artifact in artifacts],
            "intents": [asdict(intent) for intent in intents],
            "snapshots": [asdict(snapshot) for snapshot in snapshots],
        }
    )[:16]


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _code_hash() -> str:
    path = Path(__file__)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _seconds_between(started_at: str, stopped_at: str) -> float:
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        stop = datetime.fromisoformat(stopped_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (stop - start).total_seconds())
