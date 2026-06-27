from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from engine.execution.paper_daemon import load_paper_status
from engine.io.artifacts import write_json_atomic
from engine.io.sqlite import connect_sqlite
from engine.memory.store import initialize_memory_db


SESSION_TABLES = (
    "paper_sessions",
    "paper_session_artifacts",
    "paper_stream_events",
    "paper_session_summaries",
    "order_telemetry",
    "funding_events",
    "live_metrics",
    "risk_events",
    "execution_events",
    "market_snapshots",
    "executor_health",
)


def export_paper_session(
    db_path: Path,
    *,
    session_id: str,
    output_dir: Path,
) -> dict[str, object]:
    initialize_memory_db(db_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = _utc_now()
    bundle_stem = f"{session_id}-paper-export-{_safe_timestamp(started_at)}"
    bundle_dir = output_dir / bundle_stem
    tables_dir = bundle_dir / "tables"
    streams_dir = bundle_dir / "streams"
    sqlite_dir = bundle_dir / "sqlite"
    tables_dir.mkdir(parents=True, exist_ok=True)
    streams_dir.mkdir(parents=True, exist_ok=True)
    sqlite_dir.mkdir(parents=True, exist_ok=True)

    snapshot_db_path = sqlite_dir / "memory.sqlite"
    _sqlite_backup(db_path, snapshot_db_path)

    connection = connect_sqlite(db_path)
    try:
        status = load_paper_status(db_path, session_id=session_id)
        if status.get("session") is None:
            raise ValueError(f"paper session not found: {session_id}")
        table_counts: dict[str, int] = {}
        file_hashes: dict[str, str] = {}
        for table_name in SESSION_TABLES:
            rows = _session_rows(connection, table_name, session_id)
            table_counts[table_name] = len(rows)
            file_path = tables_dir / f"{table_name}.jsonl"
            _write_jsonl(file_path, rows)
            file_hashes[file_path.name] = _sha256_file(file_path)
            if table_name == "paper_stream_events":
                raw_path = streams_dir / "paper_stream_events.jsonl"
                _write_jsonl(raw_path, rows)
                file_hashes[raw_path.name] = _sha256_file(raw_path)
        file_hashes["memory.sqlite"] = _sha256_file(snapshot_db_path)
        backup_id = "paper-backup-" + _stable_hash(
            {"session_id": session_id, "created_at_utc": started_at, "file_hashes": file_hashes}
        )[:16]
        bundle_digest = _stable_hash(
            {
                "backup_id": backup_id,
                "session_id": session_id,
                "table_counts": table_counts,
                "file_hashes": file_hashes,
            }
        )
        manifest = {
            "schema_version": 1,
            "kind": "paper_session_export",
            "backup_id": backup_id,
            "session_id": session_id,
            "created_at_utc": started_at,
            "bundle_digest": bundle_digest,
            "bundle_dir": str(bundle_dir),
            "status": "exported",
            "table_counts": table_counts,
            "file_hashes": file_hashes,
            "paper_status": status,
        }
        manifest_path = bundle_dir / "manifest.json"
        write_json_atomic(manifest_path, manifest)
        file_hashes["manifest.json"] = _sha256_file(manifest_path)
        _record_backup_manifest(
            connection,
            backup_id=backup_id,
            created_at_utc=started_at,
            backup_location=str(bundle_dir),
            snapshot_digest=bundle_digest,
            table_count=sum(1 for count in table_counts.values() if count > 0),
            metadata={
                "session_id": session_id,
                "manifest_path": str(manifest_path),
                "file_hashes": file_hashes,
                "table_counts": table_counts,
            },
        )
        return {
            "status": "exported",
            "backup_id": backup_id,
            "session_id": session_id,
            "bundle_dir": str(bundle_dir),
            "manifest_path": str(manifest_path),
            "bundle_digest": bundle_digest,
            "table_counts": table_counts,
            "file_hashes": file_hashes,
        }
    finally:
        connection.close()


def restore_paper_export_smoke(bundle_dir: Path, *, restore_db_path: Path) -> dict[str, object]:
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("paper export manifest must be a JSON object")
    source_db_path = bundle_dir / "sqlite" / "memory.sqlite"
    expected_hash = str(manifest.get("file_hashes", {}).get("memory.sqlite", ""))
    actual_hash = _sha256_file(source_db_path)
    if expected_hash and actual_hash != expected_hash:
        raise ValueError("paper export SQLite checksum mismatch")

    restore_db_path.parent.mkdir(parents=True, exist_ok=True)
    if restore_db_path.exists():
        restore_db_path.unlink()
    _sqlite_backup(source_db_path, restore_db_path)
    initialize_memory_db(restore_db_path)
    session_id = str(manifest["session_id"])
    status = load_paper_status(restore_db_path, session_id=session_id)
    if status.get("session") is None:
        restore_status = "failed"
    else:
        restore_status = "verified"
    verification = _verification_payload(restore_db_path, session_id=session_id)
    verification_digest = _stable_hash(verification)
    restored_at = _utc_now()
    connection = connect_sqlite(restore_db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO restore_manifests (
                restore_id, backup_id, restored_at_utc, restore_status, verification_digest, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "restore-" + verification_digest[:16],
                manifest.get("backup_id"),
                restored_at,
                restore_status,
                verification_digest,
                json.dumps(
                    {
                        "session_id": session_id,
                        "source_bundle": str(bundle_dir),
                        "source_bundle_digest": manifest.get("bundle_digest"),
                        "verification": verification,
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return {
        "restore_status": restore_status,
        "backup_id": manifest.get("backup_id"),
        "session_id": session_id,
        "restore_db_path": str(restore_db_path),
        "source_bundle_digest": manifest.get("bundle_digest"),
        "verification_digest": verification_digest,
        "paper_status": status,
    }


def _session_rows(connection: sqlite3.Connection, table_name: str, session_id: str) -> list[dict[str, object]]:
    if table_name in {"paper_sessions", "paper_session_artifacts", "paper_stream_events", "paper_session_summaries"}:
        rows = connection.execute(f"SELECT * FROM {table_name} WHERE session_id = ? ORDER BY 1", (session_id,)).fetchall()
    elif table_name in {"order_telemetry", "risk_events"}:
        rows = connection.execute(
            f"SELECT * FROM {table_name} WHERE json_extract(metadata_json, '$.session_id') = ? ORDER BY 1",
            (session_id,),
        ).fetchall()
    elif table_name == "funding_events":
        rows = connection.execute(
            "SELECT * FROM funding_events WHERE json_extract(metadata_json, '$.session_id') = ? ORDER BY 1",
            (session_id,),
        ).fetchall()
    elif table_name == "live_metrics":
        rows = connection.execute(
            "SELECT * FROM live_metrics WHERE json_extract(payload_json, '$.session_id') = ? ORDER BY 1",
            (session_id,),
        ).fetchall()
    elif table_name == "execution_events":
        rows = connection.execute(
            "SELECT * FROM execution_events WHERE json_extract(metadata_json, '$.session_id') = ? ORDER BY event_id",
            (session_id,),
        ).fetchall()
    elif table_name == "market_snapshots":
        rows = connection.execute(
            "SELECT * FROM market_snapshots WHERE json_extract(metadata_json, '$.session_id') = ? ORDER BY 1",
            (session_id,),
        ).fetchall()
    elif table_name == "executor_health":
        rows = connection.execute(
            "SELECT * FROM executor_health WHERE executor_id = ? OR json_extract(metadata_json, '$.session_id') = ? ORDER BY 1",
            (session_id, session_id),
        ).fetchall()
    else:
        rows = []
    return [dict(row) for row in rows]


def _verification_payload(db_path: Path, *, session_id: str) -> dict[str, object]:
    connection = connect_sqlite(db_path, read_only=True)
    try:
        counts = {
            table_name: int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table_name}"
                    + (
                        " WHERE session_id = ?"
                        if table_name in {"paper_sessions", "paper_session_artifacts", "paper_stream_events", "paper_session_summaries"}
                        else ""
                    ),
                    (session_id,)
                    if table_name in {"paper_sessions", "paper_session_artifacts", "paper_stream_events", "paper_session_summaries"}
                    else (),
                ).fetchone()[0]
            )
            for table_name in ("paper_sessions", "paper_session_artifacts", "paper_stream_events", "paper_session_summaries")
        }
    finally:
        connection.close()
    return {"session_id": session_id, "table_counts": counts, "db_sha256": _sha256_file(db_path)}


def _record_backup_manifest(
    connection: sqlite3.Connection,
    *,
    backup_id: str,
    created_at_utc: str,
    backup_location: str,
    snapshot_digest: str,
    table_count: int,
    metadata: dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO backup_manifests (
            backup_id, created_at_utc, backup_location, snapshot_digest, table_count, status, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            backup_id,
            created_at_utc,
            backup_location,
            snapshot_digest,
            table_count,
            "exported",
            json.dumps(metadata, sort_keys=True),
        ),
    )
    connection.commit()


def _sqlite_backup(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = connect_sqlite(source_path, read_only=True)
    try:
        target = connect_sqlite(target_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_timestamp(timestamp: str) -> str:
    return timestamp.replace(":", "").replace("-", "").replace("Z", "Z")
