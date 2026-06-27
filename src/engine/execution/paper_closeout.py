from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from engine.agent.paper_post_run import PaperPostRunSummaryConfig, build_paper_post_run_summary
from engine.execution.paper_dashboard import PaperSessionDashboardConfig, build_paper_session_dashboard
from engine.execution.paper_daemon import load_paper_status
from engine.execution.paper_export import export_paper_session, restore_paper_export_smoke
from engine.execution.paper_hosting import HostedPaperOpsConfig, build_paper_host_doctor_report
from engine.execution.paper_streams import replay_paper_stream_events
from engine.io.artifacts import write_json_atomic
from engine.io.sqlite import connect_sqlite
from engine.memory.store import initialize_memory_db


@dataclass(frozen=True)
class Phase9ACloseoutConfig:
    db_path: Path
    session_id: str
    export_dir: Path
    restore_db_path: Path
    hosted_repo_dir: Path
    hosted_state_dir: Path
    hosted_log_dir: Path
    hosted_backup_dir: Path
    hosted_template_root: Path
    minimum_soak_seconds: int = 0
    require_live_network_soak: bool = False


def build_phase9a_closeout_report(config: Phase9ACloseoutConfig) -> dict[str, object]:
    initialize_memory_db(config.db_path)
    status = load_paper_status(config.db_path, session_id=config.session_id)
    if status.get("session") is None:
        raise ValueError(f"paper session not found: {config.session_id}")

    dashboard = build_paper_session_dashboard(
        PaperSessionDashboardConfig(db_path=config.db_path, session_id=config.session_id)
    )
    post_run = build_paper_post_run_summary(
        PaperPostRunSummaryConfig(db_path=config.db_path, session_id=config.session_id)
    )
    first_replay = replay_paper_stream_events(config.db_path, session_id=config.session_id)
    second_replay = replay_paper_stream_events(config.db_path, session_id=config.session_id)
    exported = export_paper_session(config.db_path, session_id=config.session_id, output_dir=config.export_dir)
    restored = restore_paper_export_smoke(Path(str(exported["bundle_dir"])), restore_db_path=config.restore_db_path)
    host_report = build_paper_host_doctor_report(
        HostedPaperOpsConfig(
            repo_dir=config.hosted_repo_dir,
            state_dir=config.hosted_state_dir,
            log_dir=config.hosted_log_dir,
            backup_dir=config.hosted_backup_dir,
            db_path=config.db_path,
            template_root=config.hosted_template_root,
            min_free_mb=1,
        )
    )

    snapshot = _load_closeout_snapshot(config.db_path, config.session_id)
    checks = {
        "artifact_only": _check_artifact_only(snapshot),
        "no_private_keys": _check_no_private_keys(snapshot, host_report),
        "public_ws_recording": _check_public_ws_recording(snapshot),
        "replay_determinism": _check_replay_determinism(first_replay, second_replay),
        "export_restore": _check_export_restore(exported, restored),
        "hosted_ops": _check_hosted_ops(host_report),
        "paper_status_dashboard": _check_dashboard(dashboard, post_run),
        "paper_feedback_governance": _check_feedback(snapshot),
        "portfolio_loop": _check_portfolio(snapshot),
        "live_network_soak": _check_live_network_soak(
            snapshot,
            minimum_soak_seconds=config.minimum_soak_seconds,
            require_live_network_soak=config.require_live_network_soak,
        ),
    }
    blockers = sorted(
        blocker
        for check in checks.values()
        for blocker in check.get("blockers", [])
        if isinstance(blocker, str)
    )
    failed = [name for name, check in checks.items() if check.get("status") in {"fail", "blocked"}]
    report_status = "ready_to_close" if not failed else "blocked"
    report: dict[str, object] = {
        "artifact_type": "phase9a_closeout_report",
        "schema_version": 1,
        "created_at_utc": _utc_now(),
        "status": report_status,
        "session_id": config.session_id,
        "requires_private_keys": False,
        "live_order_path_enabled": False,
        "checks": checks,
        "blockers": blockers,
        "artifacts": {
            "dashboard_id": dashboard.get("artifact_id"),
            "post_run_summary_id": post_run.get("artifact_id"),
            "export_manifest_path": exported.get("manifest_path"),
            "restore_db_path": restored.get("restore_db_path"),
        },
        "evidence": {
            "paper_status": status,
            "replay_checksum": first_replay.get("replay_checksum"),
            "export_backup_id": exported.get("backup_id"),
            "restore_verification_digest": restored.get("verification_digest"),
            "host_doctor_status": host_report.get("status"),
            "dashboard_status": dashboard.get("status"),
            "post_run_status": post_run.get("status"),
        },
        "limits": {
            "minimum_soak_seconds": int(config.minimum_soak_seconds),
            "require_live_network_soak": bool(config.require_live_network_soak),
            "sandbox_note": "real Binance multi-day network soak is evidence-gated and not fabricated",
        },
    }
    report["artifact_id"] = "phase9a-closeout-" + _stable_hash(report)[:16]
    report["artifact_sha256"] = _stable_hash(report)
    return report


def write_phase9a_closeout_report(path: Path, report: dict[str, object]) -> Path:
    return write_json_atomic(path, report)


def _load_closeout_snapshot(db_path: Path, session_id: str) -> dict[str, object]:
    connection = connect_sqlite(db_path, read_only=True)
    try:
        session = connection.execute("SELECT * FROM paper_sessions WHERE session_id = ?", (session_id,)).fetchone()
        artifacts = connection.execute(
            "SELECT * FROM paper_session_artifacts WHERE session_id = ? ORDER BY artifact_id",
            (session_id,),
        ).fetchall()
        streams = connection.execute(
            "SELECT * FROM paper_stream_events WHERE session_id = ? ORDER BY received_at_utc, stream_event_id",
            (session_id,),
        ).fetchall()
        feedback = connection.execute(
            """
            SELECT * FROM paper_calibration_feedback
            WHERE session_id = ?
            ORDER BY created_at_utc DESC, artifact_id DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        decisions = connection.execute(
            "SELECT * FROM paper_portfolio_decisions WHERE session_id = ? ORDER BY ts_utc DESC",
            (session_id,),
        ).fetchall()
        summary = connection.execute(
            "SELECT * FROM paper_session_summaries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        connection.close()
    return {
        "session": dict(session) if session else {},
        "artifacts": [dict(row) for row in artifacts],
        "streams": [dict(row) for row in streams],
        "feedback": dict(feedback) if feedback else None,
        "decisions": [dict(row) for row in decisions],
        "summary": dict(summary) if summary else {},
    }


def _check_artifact_only(snapshot: dict[str, object]) -> dict[str, object]:
    artifacts = _list(snapshot.get("artifacts"))
    active = [row for row in artifacts if row.get("status") == "active"]
    status = "pass" if active else "fail"
    return {
        "status": status,
        "artifact_count": len(artifacts),
        "active_artifact_count": len(active),
        "blockers": [] if status == "pass" else ["no_active_approved_artifacts"],
    }


def _check_no_private_keys(snapshot: dict[str, object], host_report: dict[str, object]) -> dict[str, object]:
    session = _dict(snapshot.get("session"))
    payload = _loads_dict(session.get("payload_json"))
    private_keys_required = bool(payload.get("private_keys_required"))
    live_order_path_enabled = bool(payload.get("live_order_path_enabled"))
    host_requires_private_keys = bool(host_report.get("requires_private_keys"))
    status = "pass" if not private_keys_required and not live_order_path_enabled and not host_requires_private_keys else "fail"
    blockers = []
    if private_keys_required:
        blockers.append("private_keys_required")
    if live_order_path_enabled:
        blockers.append("live_order_path_enabled")
    if host_requires_private_keys:
        blockers.append("host_requires_private_keys")
    return {
        "status": status,
        "private_keys_required": private_keys_required,
        "live_order_path_enabled": live_order_path_enabled,
        "host_requires_private_keys": host_requires_private_keys,
        "blockers": blockers,
    }


def _check_public_ws_recording(snapshot: dict[str, object]) -> dict[str, object]:
    streams = _list(snapshot.get("streams"))
    parsed = [row for row in streams if row.get("parse_status") == "parsed"]
    stream_names = sorted({str(row.get("stream_name")) for row in streams})
    required = {"aggTrade", "bookTicker", "depth"}
    observed_kinds = {name.split("@", 1)[1] for name in stream_names if "@" in name}
    missing = sorted(required - observed_kinds)
    status = "pass" if parsed and not missing else "fail"
    return {
        "status": status,
        "event_count": len(streams),
        "parsed_event_count": len(parsed),
        "stream_names": stream_names,
        "missing_required_stream_kinds": missing,
        "blockers": [] if status == "pass" else [f"missing_public_ws_streams:{','.join(missing)}"],
    }


def _check_replay_determinism(first: dict[str, object], second: dict[str, object]) -> dict[str, object]:
    first_checksum = str(first.get("replay_checksum") or "")
    second_checksum = str(second.get("replay_checksum") or "")
    status = "pass" if first_checksum and first_checksum == second_checksum else "fail"
    return {
        "status": status,
        "replay_checksum": first_checksum,
        "event_count": first.get("event_count", 0),
        "blockers": [] if status == "pass" else ["replay_checksum_mismatch"],
    }


def _check_export_restore(exported: dict[str, object], restored: dict[str, object]) -> dict[str, object]:
    status = "pass" if exported.get("status") == "exported" and restored.get("restore_status") == "verified" else "fail"
    return {
        "status": status,
        "backup_id": exported.get("backup_id"),
        "bundle_digest": exported.get("bundle_digest"),
        "restore_status": restored.get("restore_status"),
        "verification_digest": restored.get("verification_digest"),
        "blockers": [] if status == "pass" else ["export_restore_smoke_failed"],
    }


def _check_hosted_ops(host_report: dict[str, object]) -> dict[str, object]:
    status = "pass" if host_report.get("status") == "pass" and host_report.get("requires_private_keys") is False else "fail"
    return {
        "status": status,
        "doctor_status": host_report.get("status"),
        "requires_private_keys": host_report.get("requires_private_keys"),
        "blockers": [] if status == "pass" else ["hosted_ops_doctor_failed"],
    }


def _check_dashboard(dashboard: dict[str, object], post_run: dict[str, object]) -> dict[str, object]:
    status = "pass" if dashboard.get("status") in {"healthy", "attention"} and post_run.get("artifact_type") == "paper_post_run_summary" else "fail"
    return {
        "status": status,
        "dashboard_status": dashboard.get("status"),
        "post_run_status": post_run.get("status"),
        "blockers": [] if status == "pass" else ["dashboard_or_postrun_missing"],
    }


def _check_feedback(snapshot: dict[str, object]) -> dict[str, object]:
    feedback = _dict(snapshot.get("feedback"))
    payload = _loads_dict(feedback.get("payload_json"))
    conservative = payload.get("live_promotion_allowed") is False and payload.get("can_lower_live_costs") is False
    status = "pass" if feedback and conservative else "fail"
    return {
        "status": status,
        "feedback_status": feedback.get("status"),
        "sample_count": feedback.get("sample_count", 0),
        "live_promotion_allowed": payload.get("live_promotion_allowed"),
        "can_lower_live_costs": payload.get("can_lower_live_costs"),
        "blockers": [] if status == "pass" else ["paper_feedback_governance_missing"],
    }


def _check_portfolio(snapshot: dict[str, object]) -> dict[str, object]:
    session = _dict(snapshot.get("session"))
    decisions = _list(snapshot.get("decisions"))
    status = "pass" if session.get("portfolio_plan_id") and decisions else "fail"
    return {
        "status": status,
        "portfolio_plan_id": session.get("portfolio_plan_id"),
        "decision_count": len(decisions),
        "blockers": [] if status == "pass" else ["portfolio_loop_evidence_missing"],
    }


def _check_live_network_soak(
    snapshot: dict[str, object],
    *,
    minimum_soak_seconds: int,
    require_live_network_soak: bool,
) -> dict[str, object]:
    session = _dict(snapshot.get("session"))
    payload = _loads_dict(session.get("payload_json"))
    summary = _dict(snapshot.get("summary"))
    uptime = _session_uptime_seconds(session, summary)
    mode = str(payload.get("mode") or "")
    observed = mode == "live_public_ws" and uptime >= minimum_soak_seconds
    if require_live_network_soak and not observed:
        return {
            "status": "blocked",
            "mode": mode,
            "uptime_seconds": uptime,
            "minimum_soak_seconds": int(minimum_soak_seconds),
            "blockers": ["real_live_public_ws_soak_not_observed"],
        }
    if not require_live_network_soak:
        return {
            "status": "not_required",
            "mode": mode,
            "uptime_seconds": uptime,
            "minimum_soak_seconds": int(minimum_soak_seconds),
            "blockers": [],
        }
    return {
        "status": "pass",
        "mode": mode,
        "uptime_seconds": uptime,
        "minimum_soak_seconds": int(minimum_soak_seconds),
        "blockers": [],
    }


def _session_uptime_seconds(session: dict[str, object], summary: dict[str, object]) -> float:
    if summary.get("uptime_seconds") is not None:
        try:
            return float(summary.get("uptime_seconds") or 0.0)
        except (TypeError, ValueError):
            pass
    started = str(session.get("started_at_utc") or "")
    stopped = str(session.get("stopped_at_utc") or session.get("heartbeat_at_utc") or "")
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        stop = datetime.fromisoformat(stopped.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (stop - start).total_seconds())


def _list(value: object) -> list[dict[str, object]]:
    return value if isinstance(value, list) else []


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _loads_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _stable_hash(payload: dict[str, object]) -> str:
    canonical = dict(payload)
    canonical.pop("artifact_id", None)
    canonical.pop("artifact_sha256", None)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
