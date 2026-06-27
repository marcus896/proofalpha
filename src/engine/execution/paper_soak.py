from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from engine.execution.paper_closeout import (
    Phase9ACloseoutConfig,
    build_phase9a_closeout_report,
)
from engine.io.artifacts import write_json_atomic
from engine.io.sqlite import connect_sqlite
from engine.memory.store import initialize_memory_db


@dataclass(frozen=True)
class PaperSoakCloseoutConfig:
    db_path: Path
    session_id: str
    export_dir: Path
    restore_db_path: Path
    hosted_repo_dir: Path
    hosted_state_dir: Path
    hosted_log_dir: Path
    hosted_backup_dir: Path
    hosted_template_root: Path
    minimum_soak_seconds: int


def build_public_ws_soak_closeout_report(config: PaperSoakCloseoutConfig) -> dict[str, object]:
    initialize_memory_db(config.db_path)
    soak = build_public_ws_soak_metadata(config.db_path, config.session_id)
    closeout = build_phase9a_closeout_report(
        Phase9ACloseoutConfig(
            db_path=config.db_path,
            session_id=config.session_id,
            export_dir=config.export_dir,
            restore_db_path=config.restore_db_path,
            hosted_repo_dir=config.hosted_repo_dir,
            hosted_state_dir=config.hosted_state_dir,
            hosted_log_dir=config.hosted_log_dir,
            hosted_backup_dir=config.hosted_backup_dir,
            hosted_template_root=config.hosted_template_root,
            minimum_soak_seconds=config.minimum_soak_seconds,
            require_live_network_soak=True,
        )
    )
    blockers = list(closeout.get("blockers", []))
    if soak.get("stream_source") != "live_public_ws" and "real_live_public_ws_soak_not_observed" not in blockers:
        blockers.append("real_live_public_ws_soak_not_observed")
    if float(soak.get("uptime_seconds") or 0.0) < int(config.minimum_soak_seconds):
        if "real_live_public_ws_soak_not_observed" not in blockers:
            blockers.append("real_live_public_ws_soak_not_observed")
    status = "ready_to_close" if not blockers and closeout.get("status") == "ready_to_close" else "blocked"
    report: dict[str, object] = {
        "artifact_type": "public_ws_soak_closeout",
        "schema_version": 1,
        "created_at_utc": _utc_now(),
        "status": status,
        "session_id": config.session_id,
        "requires_private_keys": False,
        "live_order_path_enabled": False,
        "minimum_soak_seconds": int(config.minimum_soak_seconds),
        "soak": soak,
        "phase9a_closeout": closeout,
        "blockers": sorted(str(item) for item in blockers),
    }
    report["artifact_id"] = "public-ws-soak-" + _stable_hash(report)[:16]
    report["artifact_sha256"] = _stable_hash(report)
    return report


def write_public_ws_soak_closeout_report(path: Path, report: dict[str, object]) -> Path:
    return write_json_atomic(path, report)


def build_public_ws_soak_metadata(db_path: Path, session_id: str) -> dict[str, object]:
    snapshot = _load_soak_snapshot(db_path, session_id)
    session = snapshot["session"]
    if not session:
        raise ValueError(f"paper session not found: {session_id}")
    summary_payload = _loads_dict(snapshot.get("summary_payload"))
    collector_payload = _loads_dict(summary_payload.get("public_ws_soak"))
    session_payload = _loads_dict(session.get("payload_json"))
    counters = _counter_payload(snapshot["streams"])
    counters.update(_loads_dict(collector_payload.get("counters")))
    uptime_seconds = _float(snapshot.get("summary_uptime_seconds"))
    if uptime_seconds <= 0.0:
        uptime_seconds = _seconds_between(
            str(session.get("started_at_utc") or ""),
            str(session.get("stopped_at_utc") or session.get("heartbeat_at_utc") or ""),
        )
    event_times = [
        str(row.get("received_at_utc") or "")
        for row in snapshot["streams"]
        if str(row.get("parse_status") or "") != "marker"
    ]
    return {
        "stream_source": str(collector_payload.get("stream_source") or session_payload.get("mode") or ""),
        "started_at_utc": session.get("started_at_utc"),
        "stopped_at_utc": session.get("stopped_at_utc"),
        "uptime_seconds": uptime_seconds,
        "heartbeat_at_utc": session.get("heartbeat_at_utc"),
        "heartbeat_cadence_seconds": _heartbeat_cadence_seconds(event_times),
        "host_id": session.get("host_id"),
        "artifact_ids": sorted(str(row.get("artifact_id")) for row in snapshot["artifacts"]),
        "symbols": _loads_list(session.get("symbols_json")),
        "streams": _loads_list(session.get("streams_json")),
        "config_checksum": session.get("config_checksum"),
        "code_hash": session.get("code_hash"),
        "counters": counters,
        "health_statuses": snapshot["health_statuses"],
        "public_network_evidence": str(session_payload.get("mode") or "") == "live_public_ws",
    }


def _load_soak_snapshot(db_path: Path, session_id: str) -> dict[str, Any]:
    connection = connect_sqlite(db_path, read_only=True)
    try:
        session = connection.execute("SELECT * FROM paper_sessions WHERE session_id = ?", (session_id,)).fetchone()
        summary = connection.execute(
            "SELECT uptime_seconds, payload_json FROM paper_session_summaries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        artifacts = connection.execute(
            "SELECT artifact_id FROM paper_session_artifacts WHERE session_id = ? ORDER BY artifact_id",
            (session_id,),
        ).fetchall()
        streams = connection.execute(
            """
            SELECT received_at_utc, stream_name, parse_status, metadata_json
            FROM paper_stream_events
            WHERE session_id = ?
            ORDER BY received_at_utc, stream_event_id
            """,
            (session_id,),
        ).fetchall()
        health = connection.execute(
            "SELECT status FROM executor_health WHERE executor_id = ? ORDER BY ts_utc, health_id",
            (session_id,),
        ).fetchall()
    finally:
        connection.close()
    return {
        "session": dict(session) if session else {},
        "summary_uptime_seconds": summary["uptime_seconds"] if summary else 0.0,
        "summary_payload": summary["payload_json"] if summary else "{}",
        "artifacts": [dict(row) for row in artifacts],
        "streams": [dict(row) for row in streams],
        "health_statuses": [str(row["status"]) for row in health],
    }


def _counter_payload(streams: list[dict[str, Any]]) -> dict[str, int]:
    counters = {
        "event_count": len(streams),
        "message_count": 0,
        "reconnect_count": 0,
        "shutdown_marker_count": 0,
        "resume_marker_count": 0,
        "duplicate_count": 0,
        "gap_count": 0,
        "dropped_count": 0,
        "parse_error_count": 0,
        "stale_stream_count": 0,
    }
    for row in streams:
        metadata = _loads_dict(row.get("metadata_json"))
        for key in list(counters):
            if key in metadata:
                counters[key] = max(counters[key], int(_float(metadata.get(key))))
    return counters


def _heartbeat_cadence_seconds(event_times: list[str]) -> float:
    parsed = [_parse_utc(value) for value in event_times if value]
    parsed = [value for value in parsed if value is not None]
    if len(parsed) < 2:
        return 0.0
    spans = [
        max(0.0, (parsed[index] - parsed[index - 1]).total_seconds())
        for index in range(1, len(parsed))
    ]
    return round(sum(spans) / len(spans), 6)


def _seconds_between(started_at: str, stopped_at: str) -> float:
    start = _parse_utc(started_at)
    stop = _parse_utc(stopped_at)
    if start is None or stop is None:
        return 0.0
    return max(0.0, (stop - start).total_seconds())


def _parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _loads_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _loads_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
