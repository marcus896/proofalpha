from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from engine.io.sqlite import connect_sqlite
from engine.memory.store import initialize_memory_db


PUBLIC_STREAM_KINDS = {"bookTicker", "depth"}
MARKET_STREAM_KINDS = {"aggTrade", "markPrice", "markPrice@1s", "forceOrder"}


@dataclass(frozen=True)
class NormalizedPaperStreamEvent:
    stream_event_id: str
    session_id: str
    received_at_utc: str
    exchange_event_time: str | None
    stream_name: str
    symbol: str | None
    sequence_id: str | None
    payload_hash: str
    payload: dict[str, object]
    parse_status: str
    lag_ms: float | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class LocalOrderBookSnapshot:
    symbol: str
    last_update_id: int
    bids: list[list[str]]
    asks: list[list[str]]
    received_at_utc: str | None = None


class PaperBookStateBuilder:
    def __init__(self, *, max_staleness_ms: int = 5_000) -> None:
        self.max_staleness_ms = max_staleness_ms
        self._books: dict[str, dict[str, object]] = {}

    def seed_snapshot(self, snapshot: LocalOrderBookSnapshot) -> None:
        symbol = snapshot.symbol.upper()
        self._books[symbol] = {
            "symbol": symbol,
            "snapshot_update_id": int(snapshot.last_update_id),
            "last_depth_update_id": int(snapshot.last_update_id),
            "bids": _price_qty_map(snapshot.bids),
            "asks": _price_qty_map(snapshot.asks),
            "status": "seeded",
            "depth_gap_count": 0,
            "dropped_stale_count": 0,
            "applied_update_count": 0,
            "last_received_at_utc": snapshot.received_at_utc,
            "last_exchange_event_time": None,
            "resync_reason": None,
        }

    def apply_depth_payload(self, payload: dict[str, object], *, received_at_utc: str | None = None) -> dict[str, object]:
        symbol = _symbol_from_payload("", payload)
        if symbol is None:
            return {"action": "parse_error", "reason": "missing_symbol"}
        symbol = symbol.upper()
        book = self._books.get(symbol)
        if book is None:
            return {"action": "awaiting_snapshot", "symbol": symbol}
        first_u = _int_or_none(payload.get("U"))
        final_u = _int_or_none(payload.get("u"))
        previous_from_payload = _int_or_none(payload.get("pu"))
        if final_u is None:
            return {"action": "parse_error", "symbol": symbol, "reason": "missing_final_update_id"}
        snapshot_update_id = int(book["snapshot_update_id"])
        last_depth_update_id = int(book["last_depth_update_id"])
        if final_u < snapshot_update_id:
            book["dropped_stale_count"] = int(book["dropped_stale_count"]) + 1
            return {"action": "dropped_stale", "symbol": symbol, "final_update_id": final_u}
        applied_count = int(book["applied_update_count"])
        if applied_count == 0:
            if first_u is not None and not (first_u <= snapshot_update_id <= final_u):
                return self._mark_resync(book, symbol, "first_update_does_not_bridge_snapshot")
        elif previous_from_payload is not None and previous_from_payload != last_depth_update_id:
            return self._mark_resync(book, symbol, "depth_pu_gap")
        elif previous_from_payload is None and first_u is not None and first_u > last_depth_update_id + 1:
            return self._mark_resync(book, symbol, "depth_update_gap")

        _apply_book_side(book["bids"], payload.get("b"))  # type: ignore[arg-type]
        _apply_book_side(book["asks"], payload.get("a"))  # type: ignore[arg-type]
        book["last_depth_update_id"] = final_u
        book["applied_update_count"] = applied_count + 1
        book["last_received_at_utc"] = received_at_utc
        event_time_ms = _int_or_none(payload.get("E"))
        book["last_exchange_event_time"] = _ms_to_utc(event_time_ms) if event_time_ms is not None else None
        if book["status"] != "resync_required":
            book["status"] = "active"
        return {"action": "applied", "symbol": symbol, "final_update_id": final_u}

    def snapshot(self, symbol: str, *, now_utc: str | None = None) -> dict[str, object]:
        symbol = symbol.upper()
        book = self._books[symbol]
        bids = dict(book["bids"])  # type: ignore[arg-type]
        asks = dict(book["asks"])  # type: ignore[arg-type]
        best_bid, bid_qty = _best_bid(bids)
        best_ask, ask_qty = _best_ask(asks)
        mid = ((best_bid or 0.0) + (best_ask or 0.0)) / 2.0 if best_bid is not None and best_ask is not None else None
        spread_bps = ((best_ask - best_bid) / mid) * 10_000.0 if mid else None
        last_received = book.get("last_received_at_utc")
        stale = _is_stale(str(last_received) if last_received else None, now_utc, self.max_staleness_ms)
        payload = {
            "symbol": symbol,
            "status": book["status"],
            "stale": stale,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "mid": mid,
            "spread_bps": round(spread_bps, 12) if spread_bps is not None else None,
            "visible_depth_qty": round((bid_qty or 0.0) + (ask_qty or 0.0), 12),
            "topn_depth_qty": round(sum(bids.values()) + sum(asks.values()), 12),
            "bid_levels": len(bids),
            "ask_levels": len(asks),
            "last_depth_update_id": book["last_depth_update_id"],
            "snapshot_update_id": book["snapshot_update_id"],
            "depth_gap_count": book["depth_gap_count"],
            "dropped_stale_count": book["dropped_stale_count"],
            "applied_update_count": book["applied_update_count"],
            "last_received_at_utc": book.get("last_received_at_utc"),
            "last_exchange_event_time": book.get("last_exchange_event_time"),
            "resync_reason": book.get("resync_reason"),
        }
        payload["book_checksum"] = _stable_hash(
            {
                "symbol": symbol,
                "last_depth_update_id": payload["last_depth_update_id"],
                "bids": sorted(bids.items(), reverse=True),
                "asks": sorted(asks.items()),
            }
        )
        return payload

    def _mark_resync(self, book: dict[str, object], symbol: str, reason: str) -> dict[str, object]:
        book["status"] = "resync_required"
        book["resync_reason"] = reason
        book["depth_gap_count"] = int(book["depth_gap_count"]) + 1
        return {"action": "resync_required", "symbol": symbol, "reason": reason}


def build_binance_usdm_stream_url(symbols: list[str], stream_kinds: list[str]) -> dict[str, object]:
    stream_names = _stream_names(symbols, stream_kinds)
    route = _route_for_stream_kinds(stream_kinds)
    stream_path = "/".join(quote(stream_name, safe="@") for stream_name in stream_names)
    route_prefix = "" if route == "mixed" else f"{route}/"
    payload: dict[str, object] = {
        "base_url": "wss://fstream.binance.com",
        "route": route,
        "mode": "combined",
        "stream_names": stream_names,
        "url": f"wss://fstream.binance.com/{route_prefix}stream?streams={stream_path}",
    }
    if route == "mixed":
        route_payloads: list[dict[str, object]] = []
        public_kinds = [kind for kind in stream_kinds if kind in PUBLIC_STREAM_KINDS]
        market_kinds = [kind for kind in stream_kinds if kind in MARKET_STREAM_KINDS]
        if public_kinds:
            route_payloads.append(build_binance_usdm_stream_url(symbols, public_kinds))
        if market_kinds:
            route_payloads.append(build_binance_usdm_stream_url(symbols, market_kinds))
        payload["route_urls"] = route_payloads
    return payload


def _stream_names(symbols: list[str], stream_kinds: list[str]) -> list[str]:
    return [
        f"{symbol.lower()}@{stream_kind}"
        for symbol in symbols
        for stream_kind in stream_kinds
    ]


def normalize_binance_usdm_ws_event(
    *,
    session_id: str,
    stream_name: str,
    payload: dict[str, object],
    received_at_utc: str | None = None,
) -> NormalizedPaperStreamEvent:
    received_at_utc = received_at_utc or _utc_now()
    raw_payload = _unwrap_combined_payload(stream_name, payload)
    actual_stream_name = str(payload.get("stream") or stream_name)
    payload_hash = _stable_hash(raw_payload)
    event_time_ms = _int_or_none(raw_payload.get("E"))
    exchange_event_time = _ms_to_utc(event_time_ms) if event_time_ms is not None else None
    lag_ms = _lag_ms(received_at_utc, event_time_ms)
    symbol = _symbol_from_payload(actual_stream_name, raw_payload)
    sequence_id = _sequence_id(raw_payload)
    parse_status = "parsed" if symbol else "parse_error"
    return NormalizedPaperStreamEvent(
        stream_event_id=f"{session_id}:{actual_stream_name}:{payload_hash[:16]}",
        session_id=session_id,
        received_at_utc=received_at_utc,
        exchange_event_time=exchange_event_time,
        stream_name=actual_stream_name,
        symbol=symbol,
        sequence_id=sequence_id,
        payload_hash=payload_hash,
        payload=raw_payload,
        parse_status=parse_status,
        lag_ms=lag_ms,
        metadata={
            "venue": "binance_usdm",
            "event_type": raw_payload.get("e"),
            "event_time_ms": event_time_ms,
            "transaction_time_ms": _int_or_none(raw_payload.get("T")),
            "source": "binance_public_ws",
        },
    )


def record_paper_stream_event(
    db_path: Path,
    event: NormalizedPaperStreamEvent,
    *,
    initialize_schema: bool = True,
    connection: sqlite3.Connection | None = None,
    commit: bool = True,
) -> str:
    if initialize_schema:
        initialize_memory_db(db_path)
    owns_connection = connection is None
    active_connection = connection or connect_sqlite(db_path)
    try:
        active_connection.execute(
            """
            INSERT OR REPLACE INTO paper_stream_events (
                stream_event_id, session_id, received_at_utc, exchange_event_time,
                stream_name, symbol, sequence_id, payload_hash, payload_json,
                parse_status, lag_ms, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.stream_event_id,
                event.session_id,
                event.received_at_utc,
                event.exchange_event_time,
                event.stream_name,
                event.symbol,
                event.sequence_id,
                event.payload_hash,
                json.dumps(event.payload, sort_keys=True),
                event.parse_status,
                event.lag_ms,
                json.dumps(event.metadata or {}, sort_keys=True),
            ),
        )
        if commit or owns_connection:
            active_connection.commit()
        return event.stream_event_id
    finally:
        if owns_connection:
            active_connection.close()


def record_binance_ws_payload(
    db_path: Path,
    *,
    session_id: str,
    stream_name: str,
    payload: dict[str, object],
    received_at_utc: str | None = None,
) -> str:
    event = normalize_binance_usdm_ws_event(
        session_id=session_id,
        stream_name=stream_name,
        payload=payload,
        received_at_utc=received_at_utc,
    )
    return record_paper_stream_event(db_path, event)


def replay_paper_stream_events(db_path: Path, *, session_id: str) -> dict[str, object]:
    initialize_memory_db(db_path)
    connection = connect_sqlite(db_path, read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT stream_event_id, received_at_utc, exchange_event_time, stream_name, symbol,
                   sequence_id, payload_hash, payload_json, parse_status, lag_ms
            FROM paper_stream_events
            WHERE session_id = ?
            ORDER BY
                CASE WHEN json_extract(metadata_json, '$.event_time_ms') IS NULL THEN 1 ELSE 0 END ASC,
                CAST(json_extract(metadata_json, '$.event_time_ms') AS INTEGER) ASC,
                COALESCE(exchange_event_time, received_at_utc) ASC,
                received_at_utc ASC,
                stream_event_id ASC
            """,
            (session_id,),
        ).fetchall()
    finally:
        connection.close()

    state: dict[str, dict[str, object]] = {}
    stream_counts: dict[str, int] = {}
    gap_count = 0
    duplicate_count = 0
    seen_hashes: set[str] = set()
    for row in rows:
        (
            stream_event_id,
            received_at_utc,
            exchange_event_time,
            stream_name,
            symbol,
            sequence_id,
            payload_hash,
            payload_json,
            parse_status,
            lag_ms,
        ) = row
        stream_counts[str(stream_name)] = stream_counts.get(str(stream_name), 0) + 1
        if payload_hash in seen_hashes:
            duplicate_count += 1
        seen_hashes.add(str(payload_hash))
        if parse_status != "parsed" or not symbol:
            continue
        payload = json.loads(payload_json)
        symbol_state = state.setdefault(
            str(symbol),
            {
                "symbol": str(symbol),
                "best_bid": None,
                "best_ask": None,
                "bid_qty": None,
                "ask_qty": None,
                "last_trade_price": None,
                "last_trade_qty": None,
                "mark_price": None,
                "index_price": None,
                "funding_rate": None,
                "next_funding_time": None,
                "last_depth_update_id": None,
                "depth_gap_count": 0,
                "force_order_count": 0,
                "event_count": 0,
                "last_received_at_utc": None,
                "last_exchange_event_time": None,
            },
        )
        symbol_state["event_count"] = int(symbol_state["event_count"]) + 1
        symbol_state["last_received_at_utc"] = received_at_utc
        symbol_state["last_exchange_event_time"] = exchange_event_time
        event_type = str(payload.get("e") or "")
        if event_type == "aggTrade":
            symbol_state["last_trade_price"] = _float_or_none(payload.get("p"))
            symbol_state["last_trade_qty"] = _float_or_none(payload.get("q"))
        elif event_type == "bookTicker":
            symbol_state["best_bid"] = _float_or_none(payload.get("b"))
            symbol_state["best_ask"] = _float_or_none(payload.get("a"))
            symbol_state["bid_qty"] = _float_or_none(payload.get("B"))
            symbol_state["ask_qty"] = _float_or_none(payload.get("A"))
        elif event_type == "markPriceUpdate":
            symbol_state["mark_price"] = _float_or_none(payload.get("p"))
            symbol_state["index_price"] = _float_or_none(payload.get("i"))
            symbol_state["funding_rate"] = _float_or_none(payload.get("r"))
            symbol_state["next_funding_time"] = _ms_to_utc(_int_or_none(payload.get("T")))
        elif event_type == "depthUpdate":
            previous_u = symbol_state.get("last_depth_update_id")
            first_u = _int_or_none(payload.get("U"))
            final_u = _int_or_none(payload.get("u"))
            previous_from_payload = _int_or_none(payload.get("pu"))
            depth_gap = False
            if previous_u is not None and previous_from_payload is not None:
                depth_gap = int(previous_from_payload) != int(previous_u)
            elif previous_u is not None and first_u is not None:
                depth_gap = int(first_u) > int(previous_u) + 1
            if depth_gap:
                symbol_state["depth_gap_count"] = int(symbol_state["depth_gap_count"]) + 1
                gap_count += 1
            if final_u is not None:
                symbol_state["last_depth_update_id"] = final_u
        elif event_type == "forceOrder":
            symbol_state["force_order_count"] = int(symbol_state["force_order_count"]) + 1

    replay_payload = {
        "session_id": session_id,
        "event_count": len(rows),
        "stream_counts": stream_counts,
        "symbol_state": state,
        "gap_count": gap_count,
        "duplicate_count": duplicate_count,
    }
    replay_payload["replay_checksum"] = _stable_hash(replay_payload)
    return replay_payload


def rebuild_and_record_paper_book_state(
    db_path: Path,
    *,
    session_id: str,
    snapshots: list[LocalOrderBookSnapshot],
    now_utc: str | None = None,
    max_staleness_ms: int = 5_000,
) -> dict[str, object]:
    initialize_memory_db(db_path)
    now_utc = now_utc or _utc_now()
    builder = PaperBookStateBuilder(max_staleness_ms=max_staleness_ms)
    for snapshot in snapshots:
        builder.seed_snapshot(snapshot)

    connection = connect_sqlite(db_path, read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT received_at_utc, exchange_event_time, payload_json
            FROM paper_stream_events
            WHERE session_id = ? AND stream_name LIKE ?
            ORDER BY
                CASE WHEN json_extract(metadata_json, '$.event_time_ms') IS NULL THEN 1 ELSE 0 END ASC,
                CAST(json_extract(metadata_json, '$.event_time_ms') AS INTEGER) ASC,
                COALESCE(exchange_event_time, received_at_utc) ASC,
                received_at_utc ASC,
                stream_event_id ASC
            """,
            (session_id, "%@depth"),
        ).fetchall()
    finally:
        connection.close()

    for received_at_utc, _exchange_event_time, payload_json in rows:
        payload = json.loads(payload_json)
        if isinstance(payload, dict):
            builder.apply_depth_payload(payload, received_at_utc=str(received_at_utc))

    books = {snapshot.symbol.upper(): builder.snapshot(snapshot.symbol, now_utc=now_utc) for snapshot in snapshots}
    status = _aggregate_book_status(books)
    _record_book_state(db_path, session_id=session_id, now_utc=now_utc, status=status, books=books)
    payload = {"session_id": session_id, "status": status, "books": books}
    payload["book_state_checksum"] = _stable_hash(payload)
    return payload


def _route_for_stream_kinds(stream_kinds: list[str]) -> str:
    normalized = {kind for kind in stream_kinds}
    if normalized and normalized.issubset(PUBLIC_STREAM_KINDS):
        return "public"
    if normalized and normalized.issubset(MARKET_STREAM_KINDS):
        return "market"
    return "mixed"


def _unwrap_combined_payload(stream_name: str, payload: dict[str, object]) -> dict[str, object]:
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(payload.get("stream"), str):
        return dict(data)
    return dict(payload)


def _symbol_from_payload(stream_name: str, payload: dict[str, object]) -> str | None:
    if isinstance(payload.get("s"), str):
        return str(payload["s"]).upper()
    order = payload.get("o")
    if isinstance(order, dict) and isinstance(order.get("s"), str):
        return str(order["s"]).upper()
    if "@" in stream_name:
        return stream_name.split("@", 1)[0].upper()
    return None


def _sequence_id(payload: dict[str, object]) -> str | None:
    for key in ("u", "a", "U", "T", "E"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    order = payload.get("o")
    if isinstance(order, dict) and order.get("T") is not None:
        return str(order["T"])
    return None


def _lag_ms(received_at_utc: str, event_time_ms: int | None) -> float | None:
    if event_time_ms is None:
        return None
    try:
        received = datetime.fromisoformat(received_at_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    event_time = datetime.fromtimestamp(event_time_ms / 1000.0, tz=timezone.utc)
    return round((received - event_time).total_seconds() * 1000.0, 3)


def _ms_to_utc(value: int | None) -> str | None:
    if value is None:
        return None
    timestamp = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    if timestamp.microsecond:
        return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return timestamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _price_qty_map(levels: list[list[str]]) -> dict[float, float]:
    result: dict[float, float] = {}
    for level in levels:
        if len(level) < 2:
            continue
        price = _float_or_none(level[0])
        qty = _float_or_none(level[1])
        if price is None or qty is None or qty <= 0.0:
            continue
        result[price] = qty
    return result


def _apply_book_side(side: object, updates: object) -> None:
    if not isinstance(side, dict) or not isinstance(updates, list):
        return
    for update in updates:
        if not isinstance(update, list) or len(update) < 2:
            continue
        price = _float_or_none(update[0])
        qty = _float_or_none(update[1])
        if price is None or qty is None:
            continue
        if qty <= 0.0:
            side.pop(price, None)
        else:
            side[price] = qty


def _best_bid(bids: dict[float, float]) -> tuple[float | None, float | None]:
    if not bids:
        return None, None
    price = max(bids)
    return price, bids[price]


def _best_ask(asks: dict[float, float]) -> tuple[float | None, float | None]:
    if not asks:
        return None, None
    price = min(asks)
    return price, asks[price]


def _is_stale(last_received_at_utc: str | None, now_utc: str | None, max_staleness_ms: int) -> bool:
    if not last_received_at_utc or not now_utc:
        return False
    try:
        last_received = datetime.fromisoformat(last_received_at_utc.replace("Z", "+00:00"))
        now = datetime.fromisoformat(now_utc.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - last_received).total_seconds() * 1000.0 > max_staleness_ms


def _aggregate_book_status(books: dict[str, dict[str, object]]) -> str:
    if any(book.get("status") == "resync_required" for book in books.values()):
        return "resync_required"
    if any(book.get("stale") for book in books.values()):
        return "stale"
    return "active"


def _record_book_state(
    db_path: Path,
    *,
    session_id: str,
    now_utc: str,
    status: str,
    books: dict[str, dict[str, object]],
) -> None:
    connection = connect_sqlite(db_path)
    try:
        max_gap_count = 0
        for symbol, book in books.items():
            max_gap_count = max(max_gap_count, int(book.get("depth_gap_count", 0) or 0))
            snapshot_id = f"{session_id}:book:{symbol}:{book.get('last_depth_update_id')}:{str(book.get('book_checksum'))[:12]}"
            connection.execute(
                """
                INSERT OR REPLACE INTO market_snapshots (
                    market_snapshot_id, ts_exchange, venue, symbol, bid, ask, mid, spread_bps, depth_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    book.get("last_exchange_event_time") or book.get("last_received_at_utc") or now_utc,
                    "binance_usdm",
                    symbol,
                    book.get("best_bid"),
                    book.get("best_ask"),
                    book.get("mid"),
                    book.get("spread_bps"),
                    json.dumps(
                        {
                            "bid_qty": book.get("bid_qty"),
                            "ask_qty": book.get("ask_qty"),
                            "visible_depth_qty": book.get("visible_depth_qty"),
                            "topn_depth_qty": book.get("topn_depth_qty"),
                            "bid_levels": book.get("bid_levels"),
                            "ask_levels": book.get("ask_levels"),
                        },
                        sort_keys=True,
                    ),
                    json.dumps(
                        {
                            "session_id": session_id,
                            "source": "paper_book_state_builder",
                            "status": book.get("status"),
                            "stale": book.get("stale"),
                            "last_depth_update_id": book.get("last_depth_update_id"),
                            "depth_gap_count": book.get("depth_gap_count"),
                            "book_checksum": book.get("book_checksum"),
                        },
                        sort_keys=True,
                    ),
                ),
            )
        connection.execute(
            """
            INSERT OR REPLACE INTO executor_health (
                health_id, ts_utc, executor_id, status, websocket_lag_ms, order_ack_latency_ms, clock_drift_ms, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{session_id}:book-health:{_stable_hash({'status': status, 'books': books})[:16]}",
                now_utc,
                session_id,
                status,
                0.0,
                None,
                None,
                json.dumps(
                    {
                        "source": "paper_book_state_builder",
                        "book_count": len(books),
                        "max_depth_gap_count": max_gap_count,
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()
