from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

from engine.app.data_sufficiency import (
    PUBLIC_ONLY_ALLOWED_PROVIDERS,
    STRICT_V3_MIN_BARS,
    STRICT_V3_SYMBOLS,
)
from engine.data.microstructure import export_force_order_liquidation_sidecar
from engine.io.artifacts import write_json_atomic
from engine.io.sqlite import connect_sqlite


STRICT_V3_TIMEFRAMES = ("1Hour", "15Min")
STRICT_V3_STREAM_KINDS = ("markPrice@1s", "forceOrder", "bookTicker")
STRICT_V3_DEFAULT_PUBLIC_WS_SESSION = "strict-v3-forward-public-ws"
STRICT_V3_FIRST_WINDOW_SECONDS = 8 * 60 * 60
STRICT_V3_TARGET_WINDOW_SECONDS = 12 * 60 * 60
STRICT_V3_STRONG_WINDOW_SECONDS = 72 * 60 * 60
STRICT_V3_MAX_OBSERVED_GAP_SECONDS = 300


NowSource = Callable[[], str]


@dataclass(frozen=True)
class StrictDataCollectorSettings:
    data_root: Path = Path("outputs/data")
    public_ws_db: Path = Path("outputs/public-ws/public_stream.sqlite")
    inventory_output: Path = Path("outputs/data/strict-v3-data-inventory.json")
    plan_status_path: Path = Path("PLAN_STATUS.json")
    liquidation_output: Path = Path("outputs/public-ws/liquidation_notional.csv")
    session_id: str | None = None
    symbols: tuple[str, ...] = tuple(sorted(STRICT_V3_SYMBOLS))
    timeframes: tuple[str, ...] = STRICT_V3_TIMEFRAMES
    stream_kinds: tuple[str, ...] = STRICT_V3_STREAM_KINDS
    minimum_bars: dict[str, int] = field(default_factory=lambda: dict(STRICT_V3_MIN_BARS))
    min_forward_seconds: int = STRICT_V3_FIRST_WINDOW_SECONDS
    target_forward_seconds: int = STRICT_V3_TARGET_WINDOW_SECONDS
    strong_forward_seconds: int = STRICT_V3_STRONG_WINDOW_SECONDS
    max_observed_gap_seconds: int = STRICT_V3_MAX_OBSERVED_GAP_SECONDS
    export_timeframe: str = "1Hour"
    export_liquidations_when_ready: bool = False
    include_observed_zero_buckets: bool = True
    sync_plan_status: bool = False
    now: NowSource | None = None


def run_strict_data_collector(settings: StrictDataCollectorSettings) -> dict[str, object]:
    archive = _build_archive_inventory(settings)
    forward_capture = _build_forward_capture_inventory(settings)
    sidecar_export = _maybe_export_sidecar(settings, forward_capture)
    next_action = _next_action(settings, archive, forward_capture, sidecar_export)
    status = _collector_status(archive, forward_capture, sidecar_export, next_action)
    payload: dict[str, object] = {
        "artifact_type": "strict_v3_data_inventory",
        "status": status,
        "generated_at_utc": _now(settings),
        "profile": "strict_v3",
        "archive": archive,
        "forward_public_ws_capture": forward_capture,
        "sidecar_export": sidecar_export,
        "next_action": next_action,
        "data_policy": {
            "public_only_default": True,
            "private_keys_required": False,
            "live_orders_allowed": False,
            "missing_historical_liquidation_is_unavailable": True,
            "missing_historical_liquidation_is_zero": False,
            "observed_zero_buckets_only_inside_observed_ws_window": True,
        },
    }
    settings.inventory_output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(settings.inventory_output, payload, sort_keys=False)
    if settings.sync_plan_status:
        _sync_plan_status(settings, payload)
    return payload


def _build_archive_inventory(settings: StrictDataCollectorSettings) -> dict[str, object]:
    manifests = _discover_fetch_manifests(settings.data_root)
    bundles: list[dict[str, object]] = []
    for symbol in settings.symbols:
        for timeframe in settings.timeframes:
            minimum = int(settings.minimum_bars.get(timeframe, 0))
            bundle = _archive_bundle_for(manifests, symbol=symbol, timeframe=timeframe)
            if bundle is None:
                bundles.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "status": "missing",
                        "action": "collect_missing_archive",
                        "path": None,
                        "rows": 0,
                        "minimum_rows": minimum,
                        "provider": None,
                        "source_hash_present": False,
                        "fetch_manifest_present": False,
                    }
                )
                continue
            manifest_path, manifest = bundle
            bundle_dir = manifest_path.parent
            candle_path = bundle_dir / "candles.csv"
            rows = _csv_data_row_count(candle_path)
            provider = str(manifest.get("provider") or "")
            source_hash_present = bool(manifest.get("raw_source_hash") or manifest.get("source_hash"))
            ready = (
                rows >= minimum
                and provider in PUBLIC_ONLY_ALLOWED_PROVIDERS
                and source_hash_present
                and candle_path.exists()
            )
            bundles.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "collected" if ready else "invalid",
                    "action": "reuse_existing" if ready else "repair_archive_bundle",
                    "path": str(bundle_dir),
                    "candles": str(candle_path),
                    "fetch_manifest": str(manifest_path),
                    "rows": rows,
                    "minimum_rows": minimum,
                    "provider": provider or None,
                    "source_hash_present": source_hash_present,
                    "fetch_manifest_present": True,
                    "field_confidence": manifest.get("field_confidence") if isinstance(manifest.get("field_confidence"), dict) else {},
                }
            )
    ready = all(bool(item.get("status") == "collected") for item in bundles) if bundles else False
    return {
        "ready": ready,
        "bundle_count": len(bundles),
        "bundles": bundles,
    }


def _build_forward_capture_inventory(settings: StrictDataCollectorSettings) -> dict[str, object]:
    now_utc = _now(settings)
    if not settings.public_ws_db.exists():
        return _empty_forward_capture(settings, status="missing_db")
    session_id = settings.session_id or _latest_public_ws_session(
        settings.public_ws_db,
        now_utc=now_utc,
        stale_after_seconds=settings.max_observed_gap_seconds,
    )
    if not session_id:
        return _empty_forward_capture(settings, status="missing_session")

    connection = connect_sqlite(settings.public_ws_db, read_only=True)
    try:
        session = connection.execute(
            """
            SELECT status, started_at_utc, stopped_at_utc, heartbeat_at_utc, symbols_json, streams_json, payload_json
            FROM paper_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if session is None:
            return _empty_forward_capture(settings, status="missing_session", session_id=session_id)
        min_max = connection.execute(
            """
            SELECT MIN(received_at_utc), MAX(received_at_utc), COUNT(*)
            FROM paper_stream_events
            WHERE session_id = ? AND parse_status = 'parsed'
            """,
            (session_id,),
        ).fetchone()
        stream_rows = connection.execute(
            """
            SELECT stream_name, COUNT(*)
            FROM paper_stream_events
            WHERE session_id = ? AND parse_status = 'parsed'
            GROUP BY stream_name
            ORDER BY stream_name
            """,
            (session_id,),
        ).fetchall()
        stream_time_rows = connection.execute(
            """
            SELECT stream_name, received_at_utc
            FROM paper_stream_events
            WHERE session_id = ? AND parse_status = 'parsed'
            ORDER BY stream_name, received_at_utc, stream_event_id
            """,
            (session_id,),
        ).fetchall()
    finally:
        connection.close()

    status, started_at, stopped_at, heartbeat_at, symbols_json, streams_json, payload_json = session
    first_event = str(min_max[0]) if min_max and min_max[0] else None
    latest_event = str(min_max[1]) if min_max and min_max[1] else None
    event_count = int(min_max[2] or 0) if min_max else 0
    stream_counts = {str(row[0]): int(row[1]) for row in stream_rows}
    stream_times = [(str(row[0]), str(row[1])) for row in stream_time_rows]
    observed_seconds = _seconds_between(first_event, latest_event)
    symbols = [str(item).upper() for item in _loads_json_list(symbols_json)]
    streams = [str(item) for item in _loads_json_list(streams_json)]
    payload = _loads_json_dict(payload_json)
    latest_activity_at = _latest_timestamp(latest_event, str(heartbeat_at) if heartbeat_at else None)
    stale_seconds = _seconds_between(latest_activity_at, now_utc) if latest_activity_at else 0
    effective_status = str(status)
    stream_requirements = _stream_requirements(settings, streams=streams, stream_counts=stream_counts)
    required_streams_ready = all(bool(item.get("ready")) for item in stream_requirements)
    max_required_stream_gap_seconds = _max_required_stream_gap_seconds(
        settings,
        stream_times,
        window_start=first_event or str(started_at),
        window_end=latest_activity_at,
    )
    continuous_window_ready = (
        observed_seconds >= settings.min_forward_seconds
        and max_required_stream_gap_seconds is not None
        and max_required_stream_gap_seconds <= settings.max_observed_gap_seconds
    )
    first_window_ready = continuous_window_ready and required_streams_ready
    target_window_ready = (
        observed_seconds >= settings.target_forward_seconds
        and required_streams_ready
        and max_required_stream_gap_seconds is not None
        and max_required_stream_gap_seconds <= settings.max_observed_gap_seconds
    )
    strong_window_ready = (
        observed_seconds >= settings.strong_forward_seconds
        and required_streams_ready
        and max_required_stream_gap_seconds is not None
        and max_required_stream_gap_seconds <= settings.max_observed_gap_seconds
    )
    if effective_status == "running" and stale_seconds > settings.max_observed_gap_seconds:
        effective_status = "stale_complete" if first_window_ready else "stale_incomplete"
    elif effective_status == "completed" and not first_window_ready:
        effective_status = "completed_incomplete"
    return {
        "status": effective_status,
        "raw_session_status": str(status),
        "session_id": session_id,
        "db": str(settings.public_ws_db),
        "started_at_utc": str(started_at),
        "stopped_at_utc": str(stopped_at) if stopped_at else None,
        "heartbeat_at_utc": str(heartbeat_at) if heartbeat_at else None,
        "first_event_at_utc": first_event,
        "latest_event_at_utc": latest_event,
        "observed_seconds": observed_seconds,
        "event_count": event_count,
        "stream_counts": stream_counts,
        "symbols": symbols,
        "streams": streams,
        "private_keys_required": bool(payload.get("private_keys_required", False)),
        "required_streams_ready": required_streams_ready,
        "stream_requirements": stream_requirements,
        "continuous_window_ready": continuous_window_ready,
        "max_required_stream_gap_seconds": max_required_stream_gap_seconds,
        "latest_activity_at_utc": latest_activity_at,
        "stale_seconds": stale_seconds,
        "stale": effective_status.startswith("stale_"),
        "max_observed_gap_seconds": settings.max_observed_gap_seconds,
        "first_window_ready": first_window_ready,
        "target_window_ready": target_window_ready,
        "strong_window_ready": strong_window_ready,
        "min_forward_seconds": settings.min_forward_seconds,
        "target_forward_seconds": settings.target_forward_seconds,
        "strong_forward_seconds": settings.strong_forward_seconds,
        "remaining_to_first_window_seconds": max(0, settings.min_forward_seconds - observed_seconds),
    }


def _maybe_export_sidecar(
    settings: StrictDataCollectorSettings,
    forward_capture: dict[str, object],
) -> dict[str, object]:
    if not settings.export_liquidations_when_ready:
        return {
            "status": "pending_export" if forward_capture.get("first_window_ready") else "not_ready",
            "output": str(settings.liquidation_output),
            "enabled": False,
        }
    if not bool(forward_capture.get("first_window_ready")):
        return {
            "status": "blocked_min_window",
            "output": str(settings.liquidation_output),
            "enabled": True,
            "reason": "forward public WS capture has not reached the minimum observed window",
        }
    session_id = str(forward_capture.get("session_id") or "")
    if not session_id:
        return {
            "status": "blocked_missing_session",
            "output": str(settings.liquidation_output),
            "enabled": True,
        }
    return export_force_order_liquidation_sidecar(
        db_path=settings.public_ws_db,
        session_id=session_id,
        output_path=settings.liquidation_output,
        timeframe=settings.export_timeframe,
        include_observed_zero_buckets=settings.include_observed_zero_buckets,
    )


def _next_action(
    settings: StrictDataCollectorSettings,
    archive: dict[str, object],
    forward_capture: dict[str, object],
    sidecar_export: dict[str, object],
) -> dict[str, object]:
    if not bool(archive.get("ready")):
        return {
            "id": "collect_or_repair_archive_data",
            "priority": 1,
            "action": "Collect or repair strict v3 Binance public archive bundles before operating improvement loop.",
        }
    if forward_capture.get("status") in {"missing_db", "missing_session", "failed"}:
        return {
            "id": "start_public_ws_capture",
            "priority": 2,
            "action": "Start public-only WS capture for markPrice@1s, forceOrder, and bookTicker.",
            "command": _public_ws_command(settings, session_id=settings.session_id or STRICT_V3_DEFAULT_PUBLIC_WS_SESSION),
        }
    if forward_capture.get("status") in {"stale_incomplete", "completed_incomplete"}:
        return {
            "id": "restart_public_ws_capture",
            "priority": 2,
            "action": "Restart public-only WS capture from a clean session; prior capture stopped before the first observed window.",
            "remaining_seconds": forward_capture.get("remaining_to_first_window_seconds", 0),
            "command": _public_ws_command(settings, session_id=f"{settings.session_id or STRICT_V3_DEFAULT_PUBLIC_WS_SESSION}-restart"),
        }
    if not bool(forward_capture.get("first_window_ready")):
        return {
            "id": "continue_public_ws_capture",
            "priority": 2,
            "action": "Continue monitoring public WS capture until the first 8 hour observed window is ready.",
            "remaining_seconds": forward_capture.get("remaining_to_first_window_seconds", 0),
        }
    if sidecar_export.get("status") in {"not_ready", "pending_export"}:
        return {
            "id": "export_observed_liquidation_sidecar",
            "priority": 3,
            "action": "Export observed public forceOrder liquidation buckets for the completed forward window.",
        }
    return {
        "id": "start_72h_forward_capture",
        "priority": 4,
        "action": "Start or continue a 72 hour forward public WS capture for stronger paper evidence.",
        "command": _public_ws_command(settings, session_id="strict-v3-forward-public-ws-72h", duration_seconds=settings.strong_forward_seconds),
    }


def _collector_status(
    archive: dict[str, object],
    forward_capture: dict[str, object],
    sidecar_export: dict[str, object],
    next_action: dict[str, object],
) -> str:
    if not bool(archive.get("ready")):
        return "collect_archive_data"
    if forward_capture.get("status") in {"missing_db", "missing_session", "stale_incomplete", "completed_incomplete", "failed"}:
        return "start_forward_capture"
    if not bool(forward_capture.get("first_window_ready")):
        return "monitor_forward_capture"
    if next_action.get("id") == "export_observed_liquidation_sidecar":
        return "ready_for_sidecar_export"
    if sidecar_export.get("status") in {"exported", "no_events"}:
        return "sidecar_exported"
    return "monitor_forward_capture"


def _sync_plan_status(settings: StrictDataCollectorSettings, payload: dict[str, object]) -> None:
    if not settings.plan_status_path.exists():
        return
    try:
        status_payload = json.loads(settings.plan_status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(status_payload, dict):
        return
    data_collection = status_payload.setdefault("data_collection", {})
    if not isinstance(data_collection, dict):
        return
    data_collection["data_inventory"] = {
        "path": str(settings.inventory_output),
        "status": payload.get("status"),
        "archive_ready": bool(payload.get("archive", {}).get("ready")) if isinstance(payload.get("archive"), dict) else False,
        "forward_first_window_ready": bool(payload.get("forward_public_ws_capture", {}).get("first_window_ready"))
        if isinstance(payload.get("forward_public_ws_capture"), dict)
        else False,
        "next_action_id": payload.get("next_action", {}).get("id") if isinstance(payload.get("next_action"), dict) else None,
    }
    forward_payload = payload.get("forward_public_ws_capture")
    if isinstance(forward_payload, dict):
        data_collection["forward_public_ws_capture"] = {
            "status": forward_payload.get("status"),
            "raw_session_status": forward_payload.get("raw_session_status"),
            "session_id": forward_payload.get("session_id"),
            "db": forward_payload.get("db"),
            "started_at_utc": forward_payload.get("started_at_utc"),
            "stopped_at_utc": forward_payload.get("stopped_at_utc"),
            "latest_activity_at_utc": forward_payload.get("latest_activity_at_utc"),
            "observed_stream_events_at_update": forward_payload.get("event_count"),
            "observed_streams_at_update": forward_payload.get("stream_counts"),
            "elapsed_seconds_at_update": forward_payload.get("observed_seconds"),
            "remaining_to_8h_seconds_at_update": forward_payload.get("remaining_to_first_window_seconds"),
            "max_required_stream_gap_seconds": forward_payload.get("max_required_stream_gap_seconds"),
            "required_streams_ready": forward_payload.get("required_streams_ready"),
            "first_window_ready": forward_payload.get("first_window_ready"),
            "target_window_ready": forward_payload.get("target_window_ready"),
            "strong_window_ready": forward_payload.get("strong_window_ready"),
            "stale_seconds_at_update": forward_payload.get("stale_seconds"),
            "stale_at_update": forward_payload.get("stale"),
        }
    status_payload["last_updated_date"] = _now_date(settings)
    write_json_atomic(settings.plan_status_path, status_payload, sort_keys=False)


def _discover_fetch_manifests(data_root: Path) -> list[tuple[Path, dict[str, object]]]:
    if not data_root.exists():
        return []
    manifests: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(data_root.rglob("fetch_manifest.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            manifests.append((path, payload))
    return manifests


def _archive_bundle_for(
    manifests: list[tuple[Path, dict[str, object]]],
    *,
    symbol: str,
    timeframe: str,
) -> tuple[Path, dict[str, object]] | None:
    for path, payload in manifests:
        if str(payload.get("symbol", "")).upper() == symbol.upper() and str(payload.get("timeframe")) == timeframe:
            return path, payload
    return None


def _empty_forward_capture(
    settings: StrictDataCollectorSettings,
    *,
    status: str,
    session_id: str | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "session_id": session_id,
        "db": str(settings.public_ws_db),
        "observed_seconds": 0,
        "event_count": 0,
        "stream_counts": {},
        "required_streams_ready": False,
        "stream_requirements": [],
        "continuous_window_ready": False,
        "max_required_stream_gap_seconds": None,
        "max_observed_gap_seconds": settings.max_observed_gap_seconds,
        "first_window_ready": False,
        "target_window_ready": False,
        "strong_window_ready": False,
        "min_forward_seconds": settings.min_forward_seconds,
        "target_forward_seconds": settings.target_forward_seconds,
        "strong_forward_seconds": settings.strong_forward_seconds,
        "remaining_to_first_window_seconds": settings.min_forward_seconds,
        "private_keys_required": False,
    }


def _stream_requirements(
    settings: StrictDataCollectorSettings,
    *,
    streams: list[str],
    stream_counts: dict[str, int],
) -> list[dict[str, object]]:
    subscribed = {stream.lower() for stream in streams}
    requirements: list[dict[str, object]] = []
    for symbol in settings.symbols:
        lower = symbol.lower()
        for stream_kind in ("bookTicker", "markPrice@1s"):
            stream_name = f"{lower}@{stream_kind}"
            count = int(stream_counts.get(stream_name, 0))
            requirements.append(
                {
                    "stream": stream_name,
                    "required": True,
                    "count": count,
                    "ready": count > 0,
                }
            )
        force_name = f"{lower}@forceOrder"
        requirements.append(
            {
                "stream": force_name,
                "required": True,
                "count": int(stream_counts.get(force_name, 0)),
                "event_driven_zero_events_allowed": True,
                "ready": "forceorder" in subscribed,
            }
        )
    return requirements


def _max_required_stream_gap_seconds(
    settings: StrictDataCollectorSettings,
    stream_times: list[tuple[str, str]],
    *,
    window_start: str | None = None,
    window_end: str | None = None,
) -> int | None:
    by_stream: dict[str, list[str]] = {}
    required_streams = {
        f"{symbol.lower()}@{stream_kind}"
        for symbol in settings.symbols
        for stream_kind in ("bookTicker", "markPrice@1s")
    }
    for stream_name, received_at in stream_times:
        if stream_name in required_streams:
            by_stream.setdefault(stream_name, []).append(received_at)
    gaps: list[int] = []
    for stream_name in required_streams:
        timestamps = sorted(by_stream.get(stream_name, []), key=_timestamp_sort_key)
        if len(timestamps) < 2:
            return None
        if window_start:
            gaps.append(_seconds_between(window_start, timestamps[0], invalid_value=settings.max_observed_gap_seconds + 1))
        for index in range(1, len(timestamps)):
            gaps.append(
                _seconds_between(
                    timestamps[index - 1],
                    timestamps[index],
                    invalid_value=settings.max_observed_gap_seconds + 1,
                )
            )
        if window_end:
            gaps.append(_seconds_between(timestamps[-1], window_end, invalid_value=settings.max_observed_gap_seconds + 1))
    return max(gaps) if gaps else None


def _latest_public_ws_session(
    db_path: Path,
    *,
    now_utc: str | None = None,
    stale_after_seconds: int | None = None,
) -> str | None:
    del now_utc, stale_after_seconds
    connection = connect_sqlite(db_path, read_only=True)
    try:
        row = connection.execute(
            """
            SELECT session_id
            FROM paper_sessions
            ORDER BY started_at_utc DESC, session_id DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()
    return str(row[0]) if row else None


def _csv_data_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = [row for row in reader if row]
    return max(0, len(rows) - 1)


def _seconds_between(start: str | None, stop: str | None, *, invalid_value: int = 0) -> int:
    if not start or not stop:
        return invalid_value
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        stop_dt = datetime.fromisoformat(stop.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return invalid_value
    return max(0, int((stop_dt - start_dt).total_seconds()))


def _timestamp_sort_key(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_timestamp(*values: str | None) -> str | None:
    candidates = [value for value in values if value]
    if not candidates:
        return None
    valid = [value for value in candidates if _timestamp_sort_key(value) != datetime.min.replace(tzinfo=timezone.utc)]
    return max(valid, key=_timestamp_sort_key) if valid else None


def _loads_json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _loads_json_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _public_ws_command(
    settings: StrictDataCollectorSettings,
    *,
    session_id: str,
    duration_seconds: int | None = None,
) -> str:
    parts = [
        "python",
        "-m",
        "engine.app.cli",
        "paper-ws-run",
        "--db",
        str(settings.public_ws_db),
        "--capture-only",
        "--session-id",
        session_id,
    ]
    for symbol in settings.symbols:
        parts.extend(["--symbol", symbol])
    for stream_kind in settings.stream_kinds:
        parts.extend(["--stream-kind", stream_kind])
    parts.extend(
        [
            "--max-duration-seconds",
            str(duration_seconds or settings.target_forward_seconds),
            "--no-message-timeout-seconds",
            "60",
            "--heartbeat-interval-seconds",
            "60",
        ]
    )
    return " ".join(parts)


def _now(settings: StrictDataCollectorSettings) -> str:
    if settings.now is not None:
        return settings.now()
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_date(settings: StrictDataCollectorSettings) -> str:
    return _now(settings).split("T", 1)[0]
