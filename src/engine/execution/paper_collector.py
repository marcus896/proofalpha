from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
from queue import Empty, Full, Queue
import sqlite3
from threading import Event, Thread
import time
from typing import Any

from engine.execution.paper_streams import (
    NormalizedPaperStreamEvent,
    build_binance_usdm_stream_url,
    normalize_binance_usdm_ws_event,
    record_paper_stream_event,
)
from engine.io.sqlite import connect_sqlite
from engine.memory.store import append_execution_event, initialize_memory_db
from engine.strategy.artifacts import load_strategy_artifact, validate_strategy_artifact


DEFAULT_COLLECTOR_STREAMS = ("aggTrade", "bookTicker", "markPrice@1s", "depth", "forceOrder")
LiveMessageSource = Callable[[str], Iterable[dict[str, Any]]]
NowSource = Callable[[], str]


@dataclass(frozen=True)
class PaperWsCollectorConfig:
    db_path: Path
    artifact_paths: tuple[Path, ...]
    fixture_path: Path
    session_id: str | None = None
    host_id: str | None = None
    symbols: tuple[str, ...] = ("BTCUSDT",)
    stream_kinds: tuple[str, ...] = DEFAULT_COLLECTOR_STREAMS
    max_stream_staleness_seconds: int = 300


@dataclass(frozen=True)
class PaperWsLiveCollectorConfig:
    db_path: Path
    artifact_paths: tuple[Path, ...]
    session_id: str | None = None
    host_id: str | None = None
    symbols: tuple[str, ...] = ("BTCUSDT",)
    stream_kinds: tuple[str, ...] = DEFAULT_COLLECTOR_STREAMS
    max_stream_staleness_seconds: int = 300
    max_messages: int | None = None
    max_duration_seconds: float | None = None
    no_message_timeout_seconds: float | None = None
    heartbeat_interval_seconds: float | None = None
    reconnect_attempts: int = 3
    backoff_seconds: float = 1.0
    capture_only: bool = False
    message_source: LiveMessageSource | None = None
    now: NowSource | None = None


def run_paper_ws_collector_fixture(config: PaperWsCollectorConfig) -> dict[str, object]:
    initialize_memory_db(config.db_path)
    fixture = _load_fixture(config.fixture_path)
    try:
        artifacts = [load_strategy_artifact(path) for path in config.artifact_paths]
    except ValueError as exc:
        raise ValueError("paper WS collector requires approved immutable artifact inputs") from exc
    if artifacts or not config.capture_only:
        _validate_artifacts(artifacts)

    session_id = config.session_id or _session_id(config, artifacts, fixture)
    host_id = config.host_id or platform.node() or "local"
    started_at = _first_fixture_time(fixture) or _utc_now()
    stream_url = build_binance_usdm_stream_url(list(config.symbols), list(config.stream_kinds))
    _upsert_collector_session(
        config.db_path,
        session_id=session_id,
        host_id=host_id,
        status="running",
        started_at_utc=started_at,
        heartbeat_at_utc=started_at,
        symbols=list(config.symbols),
        streams=list(config.stream_kinds),
        payload={
            "mode": "fixture_public_ws",
            "fixture_path": str(config.fixture_path),
            "stream_url": stream_url,
            "private_keys_required": False,
        },
    )
    for artifact in artifacts:
        _upsert_session_artifact(config.db_path, session_id, artifact)

    append_execution_event(
        config.db_path,
        ts_exchange=started_at,
        ts_gateway=started_at,
        ts_engine=started_at,
        source="paper_ws_collector",
        event_type="ENGINE_START",
        status="running",
        reason_code="paper_ws_collector_fixture_start",
        metadata={"session_id": session_id, "host_id": host_id, "stream_url": stream_url},
    )
    _record_health(
        config.db_path,
        session_id=session_id,
        ts_utc=started_at,
        status="running",
        metadata={"source": "paper_ws_collector", "private_keys_required": False},
    )

    state = _CollectorState(max_stream_staleness_seconds=config.max_stream_staleness_seconds)
    for ordinal, item in enumerate(fixture["items"], start=1):
        item_type = str(item.get("type") or "message")
        if item_type == "message":
            _record_message(config.db_path, session_id=session_id, item=item, ordinal=ordinal, state=state)
        elif item_type == "reconnect":
            state.reconnect_count += 1
            ts_utc = str(item.get("at_utc") or _utc_now())
            _record_health(
                config.db_path,
                session_id=session_id,
                ts_utc=ts_utc,
                status="reconnecting",
                websocket_lag_ms=state.last_lag_ms,
                metadata={
                    "source": "paper_ws_collector",
                    "reason": item.get("reason") or "reconnect",
                    "backoff_seconds": _float(item.get("backoff_seconds")),
                    "reconnect_count": state.reconnect_count,
                    "message_count": state.message_count,
                },
            )
        elif item_type in {"shutdown", "resume"}:
            _record_marker(config.db_path, session_id=session_id, item=item, ordinal=ordinal, state=state)
        else:
            state.dropped_count += 1

    stopped_at = state.last_seen_at or started_at
    _finish_collector_session(config.db_path, session_id, stopped_at, status="completed")
    _record_health(
        config.db_path,
        session_id=session_id,
        ts_utc=stopped_at,
        status="completed",
        websocket_lag_ms=state.last_lag_ms,
        metadata={"source": "paper_ws_collector", "counters": state.counters()},
    )
    append_execution_event(
        config.db_path,
        ts_exchange=stopped_at,
        ts_gateway=stopped_at,
        ts_engine=stopped_at,
        source="paper_ws_collector",
        event_type="ENGINE_STOP",
        status="completed",
        reason_code="paper_ws_collector_fixture_completed",
        metadata={"session_id": session_id, "counters": state.counters()},
    )
    _insert_collector_summary(config.db_path, session_id=session_id, ts_utc=stopped_at, state=state)
    return {
        "status": "completed",
        "session_id": session_id,
        "host_id": host_id,
        "stream_url": stream_url,
        "private_keys_required": False,
        "counters": state.counters(),
    }


def run_paper_ws_collector_live(config: PaperWsLiveCollectorConfig) -> dict[str, object]:
    initialize_memory_db(config.db_path)
    if not config.artifact_paths and not config.capture_only:
        raise ValueError("paper WS collector requires approved immutable artifact inputs unless capture_only is enabled")
    try:
        artifacts = [load_strategy_artifact(path) for path in config.artifact_paths]
    except ValueError as exc:
        raise ValueError("paper WS collector requires approved immutable artifact inputs") from exc
    if artifacts or not config.capture_only:
        _validate_artifacts(artifacts)

    now = config.now or _utc_now
    started_at = now()
    session_id = config.session_id or _live_session_id(config, artifacts, started_at)
    host_id = config.host_id or platform.node() or "local"
    stream_url = build_binance_usdm_stream_url(list(config.symbols), list(config.stream_kinds))
    _upsert_collector_session(
        config.db_path,
        session_id=session_id,
        host_id=host_id,
        status="running",
        started_at_utc=started_at,
        heartbeat_at_utc=started_at,
        symbols=list(config.symbols),
        streams=list(config.stream_kinds),
        payload={
            "mode": "live_public_ws",
            "stream_url": stream_url,
            "private_keys_required": False,
            "max_messages": config.max_messages,
            "max_duration_seconds": config.max_duration_seconds,
            "no_message_timeout_seconds": config.no_message_timeout_seconds,
            "heartbeat_interval_seconds": config.heartbeat_interval_seconds,
            "reconnect_attempts": config.reconnect_attempts,
            "backoff_seconds": config.backoff_seconds,
            "capture_only": bool(config.capture_only),
        },
    )
    for artifact in artifacts:
        _upsert_session_artifact(config.db_path, session_id, artifact)

    append_execution_event(
        config.db_path,
        ts_exchange=started_at,
        ts_gateway=started_at,
        ts_engine=started_at,
        source="paper_ws_collector",
        event_type="ENGINE_START",
        status="running",
        reason_code="paper_ws_collector_live_start",
        metadata={"session_id": session_id, "host_id": host_id, "stream_url": stream_url},
    )

    max_messages = config.max_messages if config.max_messages and config.max_messages > 0 else None
    max_duration_seconds = config.max_duration_seconds if config.max_duration_seconds and config.max_duration_seconds > 0 else None
    no_message_timeout_seconds = (
        config.no_message_timeout_seconds
        if config.no_message_timeout_seconds and config.no_message_timeout_seconds > 0
        else None
    )
    heartbeat_interval_seconds = (
        config.heartbeat_interval_seconds
        if config.heartbeat_interval_seconds and config.heartbeat_interval_seconds > 0
        else None
    )
    recv_timeout_seconds = _minimum_positive(no_message_timeout_seconds, max_duration_seconds)
    source = config.message_source or _source_for_stream_url(
        stream_url,
        recv_timeout_seconds=recv_timeout_seconds,
    )
    state = _CollectorState(max_stream_staleness_seconds=config.max_stream_staleness_seconds)
    state.last_heartbeat_at = started_at
    state.last_session_touch_at = started_at
    ordinal = 0
    final_status = "completed"
    stop_reason = "source_exhausted"
    max_attempts = max(1, int(config.reconnect_attempts) + 1)
    live_connection = connect_sqlite(config.db_path, wal=False)

    for attempt in range(1, max_attempts + 1):
        state.connection_attempt_count += 1
        attempt_ts = now()
        _record_health(
            config.db_path,
            session_id=session_id,
            ts_utc=attempt_ts,
            status="connecting",
            websocket_lag_ms=state.last_lag_ms,
            metadata={
                "source": "paper_ws_collector",
                "mode": "live_public_ws",
                "attempt": attempt,
                "stream_url": stream_url["url"],
                "private_keys_required": False,
            },
            connection=live_connection,
        )
        attempt_message_count = state.message_count
        try:
            for raw_item in source(str(stream_url["url"])):
                ordinal += 1
                _record_live_message(
                    config.db_path,
                    session_id=session_id,
                    raw_item=raw_item,
                    ordinal=ordinal,
                    state=state,
                    connection=live_connection,
                )
                heartbeat_at = state.last_seen_at or now()
                _touch_collector_session_if_due(
                    config.db_path,
                    session_id,
                    heartbeat_at,
                    state=state,
                    connection=live_connection,
                )
                _record_heartbeat_if_due(
                    config.db_path,
                    session_id=session_id,
                    now_utc=now(),
                    state=state,
                    heartbeat_interval_seconds=heartbeat_interval_seconds,
                    reconnect_budget=max_attempts - attempt,
                    connection=live_connection,
                )
                if max_messages is not None and state.message_count >= max_messages:
                    stop_reason = "max_messages_reached"
                    raise _CollectorStop()
                if max_duration_seconds is not None and _seconds_between(started_at, now()) >= max_duration_seconds:
                    stop_reason = "max_duration_reached"
                    raise _CollectorStop()
            if (
                no_message_timeout_seconds is not None
                and state.message_count == attempt_message_count
                and _seconds_between(attempt_ts, now()) >= no_message_timeout_seconds
            ):
                final_status = "stale_incomplete"
                stop_reason = "no_message_timeout"
                _record_health(
                    config.db_path,
                    session_id=session_id,
                    ts_utc=now(),
                    status=final_status,
                    websocket_lag_ms=state.last_lag_ms,
                    metadata={
                        "source": "paper_ws_collector",
                        "mode": "live_public_ws",
                        "reason": stop_reason,
                        "message_count": state.message_count,
                        "reconnect_budget_remaining": max_attempts - attempt,
                    },
                    connection=live_connection,
                )
                break
            stop_reason = "source_exhausted"
            break
        except _CollectorStop:
            break
        except TimeoutError:
            elapsed_seconds = _seconds_between(started_at, now())
            if max_duration_seconds is not None and elapsed_seconds >= max_duration_seconds:
                final_status = "completed"
                stop_reason = "max_duration_reached"
            else:
                final_status = "stale_incomplete"
                stop_reason = "no_message_timeout"
            _record_health(
                config.db_path,
                session_id=session_id,
                ts_utc=now(),
                status=final_status,
                websocket_lag_ms=state.last_lag_ms,
                metadata={
                    "source": "paper_ws_collector",
                    "mode": "live_public_ws",
                    "reason": stop_reason,
                    "attempt": attempt,
                    "message_count": state.message_count,
                    "reconnect_budget_remaining": max_attempts - attempt,
                },
                connection=live_connection,
            )
            break
        except Exception as exc:  # noqa: BLE001 - network connectors raise varied transport exceptions.
            if attempt >= max_attempts:
                final_status = "failed"
                stop_reason = str(exc) or exc.__class__.__name__
                _record_health(
                    config.db_path,
                    session_id=session_id,
                    ts_utc=now(),
                    status="failed",
                    websocket_lag_ms=state.last_lag_ms,
                    metadata={
                        "source": "paper_ws_collector",
                        "mode": "live_public_ws",
                        "reason": stop_reason,
                        "attempt": attempt,
                        "message_count": state.message_count,
                    },
                    connection=live_connection,
                )
                break
            state.reconnect_count += 1
            reconnect_ts = state.last_seen_at or now()
            _record_health(
                config.db_path,
                session_id=session_id,
                ts_utc=reconnect_ts,
                status="reconnecting",
                websocket_lag_ms=state.last_lag_ms,
                metadata={
                    "source": "paper_ws_collector",
                    "mode": "live_public_ws",
                    "reason": str(exc) or exc.__class__.__name__,
                    "backoff_seconds": float(config.backoff_seconds),
                    "reconnect_count": state.reconnect_count,
                    "message_count": state.message_count,
                },
                connection=live_connection,
            )
            if config.backoff_seconds > 0:
                time.sleep(config.backoff_seconds)

    stopped_at = state.last_seen_at or now()
    _record_marker(
        config.db_path,
        session_id=session_id,
        item={"type": "shutdown", "at_utc": stopped_at, "reason": stop_reason},
        ordinal=ordinal + 1,
        state=state,
        connection=live_connection,
    )
    live_connection.commit()
    live_connection.close()
    _finish_collector_session(config.db_path, session_id, stopped_at, status=final_status)
    _record_health(
        config.db_path,
        session_id=session_id,
        ts_utc=stopped_at,
        status=final_status,
        websocket_lag_ms=state.last_lag_ms,
        metadata={"source": "paper_ws_collector", "mode": "live_public_ws", "reason": stop_reason, "counters": state.counters()},
    )
    append_execution_event(
        config.db_path,
        ts_exchange=stopped_at,
        ts_gateway=stopped_at,
        ts_engine=stopped_at,
        source="paper_ws_collector",
        event_type="ENGINE_STOP",
        status=final_status,
        reason_code=f"paper_ws_collector_live_{final_status}",
        metadata={"session_id": session_id, "reason": stop_reason, "counters": state.counters()},
    )
    _insert_collector_summary(config.db_path, session_id=session_id, ts_utc=stopped_at, state=state, status=final_status)
    return {
        "status": final_status,
        "mode": "live_public_ws",
        "session_id": session_id,
        "host_id": host_id,
        "stream_url": stream_url,
        "private_keys_required": False,
        "stop_reason": stop_reason,
        "counters": state.counters(),
    }


class _CollectorStop(Exception):
    pass


class _CollectorState:
    def __init__(self, *, max_stream_staleness_seconds: int) -> None:
        self.max_stream_staleness_seconds = max_stream_staleness_seconds
        self.message_count = 0
        self.recorded_event_count = 0
        self.reconnect_count = 0
        self.shutdown_marker_count = 0
        self.resume_marker_count = 0
        self.duplicate_count = 0
        self.gap_count = 0
        self.dropped_count = 0
        self.parse_error_count = 0
        self.stale_stream_count = 0
        self.heartbeat_count = 0
        self.connection_attempt_count = 0
        self.last_seen_at: str | None = None
        self.last_heartbeat_at: str | None = None
        self.last_session_touch_at: str | None = None
        self.last_lag_ms: float | None = None
        self._seen_payload_hashes: set[str] = set()
        self._last_sequence_by_stream: dict[str, int] = {}
        self._last_received_by_stream: dict[str, str] = {}

    def update_message(self, event: NormalizedPaperStreamEvent) -> dict[str, object]:
        self.message_count += 1
        self.recorded_event_count += 1
        self.last_seen_at = event.received_at_utc
        self.last_lag_ms = event.lag_ms
        metadata: dict[str, object] = {
            "source": "paper_ws_collector",
            "message_count": self.message_count,
            "recorded_event_count": self.recorded_event_count,
            "reconnect_count": self.reconnect_count,
            "dropped_count": self.dropped_count,
        }
        if event.payload_hash in self._seen_payload_hashes:
            self.duplicate_count += 1
            metadata["duplicate_count"] = 1
        self._seen_payload_hashes.add(event.payload_hash)
        sequence = _int_or_none(event.sequence_id)
        if sequence is not None:
            previous = self._last_sequence_by_stream.get(event.stream_name)
            if previous is not None and sequence > previous + 1:
                self.gap_count += 1
                metadata["gap_count"] = 1
            self._last_sequence_by_stream[event.stream_name] = sequence
        previous_received = self._last_received_by_stream.get(event.stream_name)
        if previous_received and _seconds_between(previous_received, event.received_at_utc) > self.max_stream_staleness_seconds:
            self.stale_stream_count += 1
            metadata["stale_stream_state"] = True
        self._last_received_by_stream[event.stream_name] = event.received_at_utc
        if event.parse_status != "parsed":
            self.parse_error_count += 1
        return metadata

    def counters(self) -> dict[str, int]:
        return {
            "message_count": self.message_count,
            "recorded_event_count": self.recorded_event_count,
            "reconnect_count": self.reconnect_count,
            "shutdown_marker_count": self.shutdown_marker_count,
            "resume_marker_count": self.resume_marker_count,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "dropped_count": self.dropped_count,
            "parse_error_count": self.parse_error_count,
            "stale_stream_count": self.stale_stream_count,
            "heartbeat_count": self.heartbeat_count,
            "connection_attempt_count": self.connection_attempt_count,
        }


def _record_message(
    db_path: Path,
    *,
    session_id: str,
    item: dict[str, Any],
    ordinal: int,
    state: _CollectorState,
    connection: sqlite3.Connection | None = None,
) -> None:
    payload = item.get("payload")
    stream_name = str(item.get("stream_name") or "")
    received_at_utc = str(item.get("received_at_utc") or _utc_now())
    if not isinstance(payload, dict) or not stream_name:
        state.dropped_count += 1
        return
    event = normalize_binance_usdm_ws_event(
        session_id=session_id,
        stream_name=stream_name,
        payload=payload,
        received_at_utc=received_at_utc,
    )
    metadata = dict(event.metadata or {})
    metadata.update(state.update_message(event))
    metadata["collector_ordinal"] = ordinal
    record_paper_stream_event(
        db_path,
        NormalizedPaperStreamEvent(
            stream_event_id=f"{event.stream_event_id}:{ordinal}",
            session_id=event.session_id,
            received_at_utc=event.received_at_utc,
            exchange_event_time=event.exchange_event_time,
            stream_name=event.stream_name,
            symbol=event.symbol,
            sequence_id=event.sequence_id,
            payload_hash=event.payload_hash,
            payload=event.payload,
            parse_status=event.parse_status,
            lag_ms=event.lag_ms,
            metadata=metadata,
        ),
        initialize_schema=False,
        connection=connection,
        commit=connection is None,
    )


def _record_live_message(
    db_path: Path,
    *,
    session_id: str,
    raw_item: dict[str, Any],
    ordinal: int,
    state: _CollectorState,
    connection: sqlite3.Connection | None = None,
) -> None:
    item = _coerce_live_message_item(raw_item)
    _record_message(
        db_path,
        session_id=session_id,
        item=item,
        ordinal=ordinal,
        state=state,
        connection=connection,
    )


def _record_marker(
    db_path: Path,
    *,
    session_id: str,
    item: dict[str, Any],
    ordinal: int,
    state: _CollectorState,
    connection: sqlite3.Connection | None = None,
) -> None:
    item_type = str(item.get("type") or "marker")
    ts_utc = str(item.get("at_utc") or _utc_now())
    state.last_seen_at = ts_utc
    if item_type == "shutdown":
        state.shutdown_marker_count += 1
    elif item_type == "resume":
        state.resume_marker_count += 1
    payload = {
        "type": item_type,
        "reason": item.get("reason") or item_type,
        "collector_ordinal": ordinal,
        "counters": state.counters(),
    }
    event = NormalizedPaperStreamEvent(
        stream_event_id=f"{session_id}:collector:{item_type}:{ordinal}",
        session_id=session_id,
        received_at_utc=ts_utc,
        exchange_event_time=None,
        stream_name=f"collector:{item_type}",
        symbol=None,
        sequence_id=str(ordinal),
        payload_hash=_stable_hash(payload),
        payload=payload,
        parse_status="marker",
        lag_ms=None,
        metadata={"source": "paper_ws_collector", "marker_type": item_type, "deterministic_shutdown_resume_marker": True},
    )
    record_paper_stream_event(
        db_path,
        event,
        initialize_schema=False,
        connection=connection,
        commit=connection is None,
    )


def _coerce_live_message_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_item.get("payload"), dict):
        payload = dict(raw_item["payload"])
        stream_name = str(raw_item.get("stream_name") or payload.get("stream") or raw_item.get("stream") or "")
        received_at_utc = str(raw_item.get("received_at_utc") or payload.get("received_at_utc") or _utc_now())
        return {"type": "message", "stream_name": stream_name, "received_at_utc": received_at_utc, "payload": payload}
    payload = dict(raw_item)
    stream_name = str(payload.get("stream") or raw_item.get("stream_name") or "")
    received_at_utc = str(payload.pop("received_at_utc", None) or raw_item.get("received_at_utc") or _utc_now())
    return {"type": "message", "stream_name": stream_name, "received_at_utc": received_at_utc, "payload": payload}


def _websocket_json_message_source(url: str, *, recv_timeout_seconds: float | None = None) -> Iterable[dict[str, Any]]:
    try:
        from websockets.sync.client import connect
    except Exception as exc:  # pragma: no cover - depends on optional runtime package.
        raise RuntimeError("websockets package with sync client is required for live public WS collection") from exc

    with connect(url, open_timeout=10, close_timeout=5) as websocket:  # pragma: no cover - network path.
        while True:
            raw_message = (
                websocket.recv(timeout=recv_timeout_seconds)
                if recv_timeout_seconds is not None
                else websocket.recv()
            )
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")
            payload = json.loads(raw_message)
            if isinstance(payload, dict):
                yield payload


def _source_for_stream_url(
    stream_url: dict[str, object],
    *,
    recv_timeout_seconds: float | None,
) -> LiveMessageSource:
    route_urls = stream_url.get("route_urls")
    if not isinstance(route_urls, list) or len(route_urls) <= 1:
        return lambda url: _websocket_json_message_source(url, recv_timeout_seconds=recv_timeout_seconds)
    urls = [str(item.get("url")) for item in route_urls if isinstance(item, dict) and item.get("url")]
    if len(urls) <= 1:
        return lambda url: _websocket_json_message_source(url, recv_timeout_seconds=recv_timeout_seconds)
    return lambda _url: _merged_websocket_json_message_source(urls, recv_timeout_seconds=recv_timeout_seconds)


def _merged_websocket_json_message_source(
    urls: list[str],
    *,
    recv_timeout_seconds: float | None,
) -> Iterable[dict[str, Any]]:
    route_queues: dict[str, Queue[tuple[dict[str, Any] | None, BaseException | None, bool]]] = {
        url: Queue(maxsize=2_048) for url in urls
    }
    stop = Event()

    def put_route_item(
        url: str,
        item: tuple[dict[str, Any] | None, BaseException | None, bool],
    ) -> None:
        route_queue = route_queues[url]
        while not stop.is_set():
            try:
                route_queue.put(item, timeout=0.25)
                return
            except Full:
                continue

    def worker(url: str) -> None:
        try:
            for payload in _websocket_json_message_source(url, recv_timeout_seconds=recv_timeout_seconds):
                if stop.is_set():
                    return
                put_route_item(url, (payload, None, False))
        except BaseException as exc:  # pragma: no cover - live network path.
            put_route_item(url, (None, exc, True))
            return
        put_route_item(url, (None, None, True))

    threads = [Thread(target=worker, args=(url,), daemon=True) for url in urls]
    for thread in threads:
        thread.start()

    timeout = max(1.0, float(recv_timeout_seconds or 1.0))
    last_message_at = {url: time.monotonic() for url in urls}
    active_urls = set(urls)
    max_batch_per_route = 32
    try:
        while active_urls:
            progressed = False
            for url in urls:
                if url not in active_urls:
                    continue
                route_queue = route_queues[url]
                for _ in range(max_batch_per_route):
                    try:
                        payload, exc, finished = route_queue.get_nowait()
                    except Empty:
                        break
                    progressed = True
                    if finished:
                        active_urls.discard(url)
                        if isinstance(exc, TimeoutError):
                            raise TimeoutError(f"public WS route timed out: {url}") from exc
                        if exc is not None:
                            raise RuntimeError(f"required public WS route stopped: {url}") from exc
                        raise RuntimeError(f"required public WS route closed: {url}")
                    if payload is not None:
                        last_message_at[url] = time.monotonic()
                        yield payload

            if recv_timeout_seconds is not None:
                now_monotonic = time.monotonic()
                for url in active_urls:
                    if now_monotonic - last_message_at[url] >= timeout:
                        raise TimeoutError(f"public WS route produced no messages before timeout: {url}")
            if not progressed:
                time.sleep(min(0.01, timeout))
    finally:
        stop.set()


def _load_fixture(path: Path) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("collector fixture must be a JSON object with an items list")
    return {"items": [item for item in payload["items"] if isinstance(item, dict)]}


def _validate_artifacts(artifacts: list[dict[str, object]]) -> None:
    if not artifacts:
        raise ValueError("paper WS collector requires at least one approved immutable artifact")
    for artifact in artifacts:
        validation = validate_strategy_artifact(artifact)
        if not validation.passed:
            raise ValueError("paper WS collector requires approved immutable artifact inputs")


def _upsert_collector_session(
    db_path: Path,
    *,
    session_id: str,
    host_id: str,
    status: str,
    started_at_utc: str,
    heartbeat_at_utc: str,
    symbols: list[str],
    streams: list[str],
    payload: dict[str, object],
) -> None:
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO paper_sessions (
                session_id, host_id, status, started_at_utc, stopped_at_utc, heartbeat_at_utc,
                portfolio_plan_id, symbols_json, streams_json, code_hash, config_checksum, payload_json
            ) VALUES (?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                host_id,
                status,
                started_at_utc,
                heartbeat_at_utc,
                json.dumps(symbols, sort_keys=True),
                json.dumps(streams, sort_keys=True),
                _code_hash(),
                _stable_hash(payload),
                json.dumps(payload, sort_keys=True),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _finish_collector_session(db_path: Path, session_id: str, stopped_at_utc: str, *, status: str) -> None:
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


def _touch_collector_session_if_due(
    db_path: Path,
    session_id: str,
    heartbeat_at_utc: str,
    *,
    state: _CollectorState,
    interval_seconds: float = 1.0,
    connection: sqlite3.Connection | None = None,
) -> None:
    previous = state.last_session_touch_at
    if previous is not None and _seconds_between(previous, heartbeat_at_utc) < interval_seconds:
        return
    _touch_collector_session(
        db_path,
        session_id,
        heartbeat_at_utc,
        connection=connection,
    )
    state.last_session_touch_at = heartbeat_at_utc


def _touch_collector_session(
    db_path: Path,
    session_id: str,
    heartbeat_at_utc: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    owns_connection = connection is None
    active_connection = connection or connect_sqlite(db_path)
    try:
        active_connection.execute(
            "UPDATE paper_sessions SET heartbeat_at_utc = ? WHERE session_id = ?",
            (heartbeat_at_utc, session_id),
        )
        active_connection.commit()
    finally:
        if owns_connection:
            active_connection.close()


def _upsert_session_artifact(db_path: Path, session_id: str, artifact: dict[str, object]) -> None:
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO paper_session_artifacts (
                session_id, artifact_id, artifact_sha256, lifecycle_state, status, payload_json
            ) VALUES (?, ?, ?, ?, 'active', ?)
            """,
            (
                session_id,
                str(artifact.get("artifact_id")),
                str(artifact.get("artifact_sha256") or ""),
                str(artifact.get("rollout_stage") or ""),
                json.dumps(
                    {
                        "family": artifact.get("family"),
                        "variant_id": artifact.get("variant_id"),
                        "source": "paper_ws_collector",
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _record_health(
    db_path: Path,
    *,
    session_id: str,
    ts_utc: str,
    status: str,
    websocket_lag_ms: float | None = None,
    metadata: dict[str, object] | None = None,
    connection: sqlite3.Connection | None = None,
) -> None:
    owns_connection = connection is None
    active_connection = connection or connect_sqlite(db_path)
    try:
        health_id = f"{session_id}:collector-health:{ts_utc}:{status}"
        active_connection.execute(
            """
            INSERT OR REPLACE INTO executor_health (
                health_id, ts_utc, executor_id, status, websocket_lag_ms,
                order_ack_latency_ms, clock_drift_ms, metadata_json
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)
            """,
            (
                health_id,
                ts_utc,
                session_id,
                status,
                websocket_lag_ms,
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )
        active_connection.commit()
    finally:
        if owns_connection:
            active_connection.close()


def _record_heartbeat_if_due(
    db_path: Path,
    *,
    session_id: str,
    now_utc: str,
    state: _CollectorState,
    heartbeat_interval_seconds: float | None,
    reconnect_budget: int,
    connection: sqlite3.Connection | None = None,
) -> None:
    if heartbeat_interval_seconds is None:
        return
    previous = state.last_heartbeat_at or now_utc
    if _seconds_between(previous, now_utc) < heartbeat_interval_seconds:
        return
    state.heartbeat_count += 1
    state.last_heartbeat_at = now_utc
    _record_health(
        db_path,
        session_id=session_id,
        ts_utc=now_utc,
        status="heartbeat",
        websocket_lag_ms=state.last_lag_ms,
        metadata={
            "source": "paper_ws_collector",
            "mode": "live_public_ws",
            "message_count": state.message_count,
            "reconnect_count": state.reconnect_count,
            "reconnect_budget_remaining": max(0, reconnect_budget),
            "counters": state.counters(),
        },
        connection=connection,
    )


def _insert_collector_summary(db_path: Path, *, session_id: str, ts_utc: str, state: _CollectorState, status: str = "completed") -> None:
    connection = connect_sqlite(db_path)
    try:
        session = connection.execute(
            """
            SELECT host_id, started_at_utc, stopped_at_utc, heartbeat_at_utc,
                   symbols_json, streams_json, config_checksum, code_hash, payload_json
            FROM paper_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        session_payload = _loads_dict(session[8] if session else "{}")
        started_at = str(session[1] if session else "")
        stopped_at = str(session[2] if session and session[2] else ts_utc)
        uptime_seconds = max(_seconds_between(started_at, stopped_at), _event_span_seconds(db_path, session_id))
        artifact_rows = connection.execute(
            "SELECT artifact_id FROM paper_session_artifacts WHERE session_id = ? ORDER BY artifact_id",
            (session_id,),
        ).fetchall()
        artifact_ids = [str(row[0]) for row in artifact_rows]
        soak_payload = {
            "stream_source": session_payload.get("mode"),
            "started_at_utc": started_at,
            "stopped_at_utc": stopped_at,
            "uptime_seconds": uptime_seconds,
            "heartbeat_at_utc": str(session[3] if session and session[3] else stopped_at),
            "heartbeat_cadence_seconds": _heartbeat_cadence_seconds(db_path, session_id),
            "host_id": str(session[0] if session else ""),
            "artifact_ids": artifact_ids,
            "symbols": _loads_list(session[4] if session else "[]"),
            "streams": _loads_list(session[5] if session else "[]"),
            "config_checksum": str(session[6] if session else ""),
            "code_hash": str(session[7] if session else ""),
            "counters": state.counters(),
            "private_keys_required": False,
            "live_order_path_enabled": False,
        }
        connection.execute(
            """
            INSERT OR REPLACE INTO paper_session_summaries (
                session_id, created_at_utc, status, uptime_seconds, artifact_count,
                symbol_count, order_count, filled_count, partial_count, rejected_count,
                risk_block_count, funding_fee, paper_pnl, drawdown,
                telemetry_quality_score, payload_json
            )
            SELECT
                ps.session_id, ?, ?,
                ?, COUNT(psa.artifact_id), json_array_length(ps.symbols_json),
                0, 0, 0, ?, 0, 0, 0, 0, ?, ?
            FROM paper_sessions ps
            LEFT JOIN paper_session_artifacts psa ON psa.session_id = ps.session_id
            WHERE ps.session_id = ?
            GROUP BY ps.session_id
            """,
            (
                ts_utc,
                status,
                uptime_seconds,
                state.parse_error_count + state.dropped_count,
                _telemetry_quality(state),
                json.dumps(
                    {
                        "paper_ws_collector": {"counters": state.counters()},
                        "public_ws_soak": soak_payload,
                    },
                    sort_keys=True,
                ),
                session_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _telemetry_quality(state: _CollectorState) -> float:
    total = max(1, state.message_count + state.dropped_count)
    penalties = state.dropped_count + state.parse_error_count + state.stale_stream_count + state.gap_count
    return round(max(0.0, 1.0 - (penalties / total)), 12)


def _first_fixture_time(fixture: dict[str, list[dict[str, Any]]]) -> str | None:
    for item in fixture["items"]:
        for key in ("received_at_utc", "at_utc"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _session_id(config: PaperWsCollectorConfig, artifacts: list[dict[str, object]], fixture: dict[str, object]) -> str:
    return "paper-ws-" + _stable_hash(
        {
            "artifact_ids": [artifact.get("artifact_id") for artifact in artifacts],
            "fixture": fixture,
            "symbols": config.symbols,
            "stream_kinds": config.stream_kinds,
        }
    )[:16]


def _live_session_id(config: PaperWsLiveCollectorConfig, artifacts: list[dict[str, object]], started_at: str) -> str:
    return "paper-ws-live-" + _stable_hash(
        {
            "artifact_ids": [artifact.get("artifact_id") for artifact in artifacts],
            "symbols": config.symbols,
            "stream_kinds": config.stream_kinds,
            "started_at": started_at,
        }
    )[:16]


def _minimum_positive(*values: float | None) -> float | None:
    positive = [float(value) for value in values if value is not None and float(value) > 0.0]
    return min(positive) if positive else None


def _seconds_between(started_at: str, stopped_at: str) -> float:
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        stop = datetime.fromisoformat(stopped_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (stop - start).total_seconds())


def _heartbeat_cadence_seconds(db_path: Path, session_id: str) -> float:
    connection = connect_sqlite(db_path, read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT received_at_utc
            FROM paper_stream_events
            WHERE session_id = ? AND parse_status != 'marker'
            ORDER BY received_at_utc, stream_event_id
            """,
            (session_id,),
        ).fetchall()
    finally:
        connection.close()
    parsed = []
    for row in rows:
        try:
            parsed.append(datetime.fromisoformat(str(row[0]).replace("Z", "+00:00")))
        except ValueError:
            continue
    if len(parsed) < 2:
        return 0.0
    spans = [
        max(0.0, (parsed[index] - parsed[index - 1]).total_seconds())
        for index in range(1, len(parsed))
    ]
    return round(sum(spans) / len(spans), 6)


def _event_span_seconds(db_path: Path, session_id: str) -> float:
    connection = connect_sqlite(db_path, read_only=True)
    try:
        row = connection.execute(
            """
            SELECT MIN(received_at_utc), MAX(received_at_utc)
            FROM paper_stream_events
            WHERE session_id = ? AND parse_status != 'marker'
            """,
            (session_id,),
        ).fetchone()
    finally:
        connection.close()
    if not row or not row[0] or not row[1]:
        return 0.0
    return _seconds_between(str(row[0]), str(row[1]))


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


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _code_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
