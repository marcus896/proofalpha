"""Public Binance futures microstructure capture and Phase 5 feature derivation."""
from __future__ import annotations

import csv
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from engine.data.fetch import BINANCE_FAPI_BASE, JsonGetter, _normalize_binance_symbol, _request_json
from engine.io.sqlite import connect_sqlite
from engine.io.artifacts import write_json_atomic

_PHASE5_FEATURES = [
    "signed_trade_delta_usd",
    "stacked_imbalance_count",
    "absorption_score",
    "depth_replenishment_rate",
    "spread_spike_flag",
]


def fetch_binance_microstructure_snapshot(
    *,
    output_dir: Path,
    symbol: str,
    depth_limit: int = 100,
    agg_trade_limit: int = 1000,
    samples: int = 1,
    sample_interval_seconds: float = 0.0,
    retention_hours: int = 24,
    max_raw_events: int = 100_000,
    json_getter: JsonGetter | None = None,
) -> dict[str, Path]:
    """Fetch a bounded public Binance USD-M microstructure sample.

    This intentionally uses public market-data endpoints only. It does not use
    API secrets, account state, or order/trade endpoints.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    market_symbol = _normalize_binance_symbol(symbol)
    depth_limit = _clamp_int(depth_limit, minimum=5, maximum=1000)
    agg_trade_limit = _clamp_int(agg_trade_limit, minimum=1, maximum=1000)
    samples = _clamp_int(samples, minimum=1, maximum=10_000)
    sample_interval_seconds = max(0.0, float(sample_interval_seconds))
    retention_hours = _clamp_int(retention_hours, minimum=1, maximum=24 * 30)
    max_raw_events = _clamp_int(max_raw_events, minimum=1, maximum=10_000_000)

    depth_snapshots: list[dict[str, object]] = []
    for sample_index in range(samples):
        depth = _request_json(
            f"{BINANCE_FAPI_BASE}/fapi/v1/depth?"
            + urllib.parse.urlencode({"symbol": market_symbol, "limit": depth_limit}),
            json_getter=json_getter,
        )
        if isinstance(depth, dict):
            depth_snapshots.append(depth)
        if sample_index < samples - 1 and sample_interval_seconds > 0.0:
            time.sleep(sample_interval_seconds)
    agg_trades = _request_json(
        f"{BINANCE_FAPI_BASE}/fapi/v1/aggTrades?"
        + urllib.parse.urlencode({"symbol": market_symbol, "limit": agg_trade_limit}),
        json_getter=json_getter,
    )
    open_interest = _request_json(
        f"{BINANCE_FAPI_BASE}/fapi/v1/openInterest?"
        + urllib.parse.urlencode({"symbol": market_symbol}),
        json_getter=json_getter,
    )

    raw_events_path = output_dir / "microstructure_events.jsonl"
    features_path = output_dir / "microstructure_features.csv"
    manifest_path = output_dir / "microstructure_manifest.json"

    raw_events = _raw_event_rows(
        symbol=market_symbol,
        depth_snapshots=depth_snapshots,
        agg_trades=agg_trades if isinstance(agg_trades, list) else [],
        open_interest=open_interest if isinstance(open_interest, dict) else {},
    )
    _write_jsonl(raw_events_path, raw_events[:max_raw_events])
    feature_rows = build_microstructure_features(
        symbol=market_symbol,
        depth_snapshots=depth_snapshots,
        agg_trades=agg_trades if isinstance(agg_trades, list) else [],
        open_interest=open_interest if isinstance(open_interest, dict) else None,
    )
    _write_feature_csv(features_path, feature_rows)

    manifest = {
        "provider": "binance_futures_microstructure",
        "venue": "binance",
        "symbol": market_symbol,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "data_policy": {
            "source": "public_market_data",
            "uses_api_secret": False,
            "trading_or_order_endpoint_used": False,
            "historical_l2_limit": "REST depth is current snapshot only; this collector creates local history by repeated capture.",
        },
        "capture": {
            "samples": samples,
            "sample_interval_seconds": sample_interval_seconds,
            "depth_limit": depth_limit,
            "agg_trade_limit": agg_trade_limit,
        },
        "retention_policy": {
            "storage": "local_jsonl_and_csv",
            "retention_hours": retention_hours,
            "max_raw_events": max_raw_events,
            "operator_approved_by": "user_phase5_request",
        },
        "binance_endpoints": [
            "/fapi/v1/depth",
            "/fapi/v1/aggTrades",
            "/fapi/v1/openInterest",
        ],
        "stream_endpoints_for_live_extension": [
            "<symbol>@depth@100ms",
            "<symbol>@aggTrade",
            "<symbol>@forceOrder",
        ],
        "feature_schema": {
            "phase5_features": list(_PHASE5_FEATURES),
            "notes": "force-order liquidation events require websocket capture; REST sample records liquidation_notional_usd as 0 unless supplied later.",
        },
        "artifacts": {
            "raw_events": str(raw_events_path),
            "features": str(features_path),
        },
    }
    write_json_atomic(manifest_path, manifest)
    return {"raw_events": raw_events_path, "features": features_path, "manifest": manifest_path}


def export_force_order_liquidation_sidecar(
    *,
    db_path: Path,
    session_id: str,
    output_path: Path,
    timeframe: str = "1Hour",
    include_observed_zero_buckets: bool = False,
) -> dict[str, object]:
    """Export public forceOrder stream events into a sparse liquidation sidecar.

    The output intentionally contains only observed force-order buckets. Missing
    bars remain missing so downstream quality gates do not treat unavailable
    liquidation data as true zeroes.
    """

    bucket_seconds = _timeframe_seconds(timeframe)
    rows: dict[str, float] = {}
    observed_buckets: set[str] = set()
    event_count = 0
    connection = connect_sqlite(db_path, read_only=True)
    try:
        if include_observed_zero_buckets:
            observed_cursor = connection.execute(
                """
                SELECT payload_json
                FROM paper_stream_events
                WHERE session_id = ?
                  AND parse_status = 'parsed'
                ORDER BY exchange_event_time, stream_event_id
                """,
                (session_id,),
            )
            for (payload_json,) in observed_cursor.fetchall():
                try:
                    payload = json.loads(str(payload_json))
                except json.JSONDecodeError:
                    continue
                timestamp = _event_bucket_timestamp(payload, bucket_seconds=bucket_seconds)
                if timestamp is not None:
                    observed_buckets.add(timestamp)
        cursor = connection.execute(
            """
            SELECT payload_json
            FROM paper_stream_events
            WHERE session_id = ?
              AND stream_name LIKE ?
              AND parse_status = 'parsed'
            ORDER BY exchange_event_time, stream_event_id
            """,
            (session_id, "%forceOrder%"),
        )
        for (payload_json,) in cursor.fetchall():
            try:
                payload = json.loads(str(payload_json))
            except json.JSONDecodeError:
                continue
            parsed = _parse_force_order_payload(payload, bucket_seconds=bucket_seconds)
            if parsed is None:
                continue
            timestamp, notional = parsed
            observed_buckets.add(timestamp)
            rows[timestamp] = rows.get(timestamp, 0.0) + notional
            event_count += 1
    finally:
        connection.close()

    if include_observed_zero_buckets:
        for timestamp in observed_buckets:
            rows.setdefault(timestamp, 0.0)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "liquidation_notional"])
        writer.writeheader()
        for timestamp in sorted(rows):
            writer.writerow(
                {
                    "timestamp": timestamp,
                    "liquidation_notional": _format_csv_value(rows[timestamp]),
                }
            )
    return {
        "status": "exported" if event_count else "no_events",
        "session_id": session_id,
        "db_path": str(db_path),
        "output": str(output_path),
        "timeframe": timeframe,
        "event_count": event_count,
        "bucket_count": len(rows),
        "observed_zero_bucket_count": sum(1 for value in rows.values() if value == 0.0),
        "total_liquidation_notional": round(sum(rows.values()), 12),
        "data_policy": {
            "source": "binance_public_ws_forceOrder",
            "uses_api_secret": False,
            "trading_or_order_endpoint_used": False,
            "missing_buckets_are_not_zero": True,
            "observed_zero_buckets_enabled": bool(include_observed_zero_buckets),
        },
    }


def build_microstructure_features(
    *,
    symbol: str,
    depth_snapshots: list[dict[str, object]],
    agg_trades: list[object],
    open_interest: dict[str, object] | None = None,
    imbalance_threshold: float = 0.5,
    spread_spike_multiplier: float = 3.0,
) -> list[dict[str, object]]:
    ordered_depths = sorted(
        [snapshot for snapshot in depth_snapshots if isinstance(snapshot, dict)],
        key=_depth_timestamp_ms,
    )
    rows: list[dict[str, object]] = []
    previous: dict[str, object] | None = None
    for snapshot in ordered_depths:
        timestamp_ms = _depth_timestamp_ms(snapshot)
        previous_timestamp_ms = _depth_timestamp_ms(previous) if previous else None
        bid_levels = _parse_levels(snapshot.get("bids"))
        ask_levels = _parse_levels(snapshot.get("asks"))
        best_bid = bid_levels[0][0] if bid_levels else 0.0
        best_ask = ask_levels[0][0] if ask_levels else 0.0
        mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else 0.0
        spread_bps = ((best_ask - best_bid) / mid * 10_000.0) if mid else 0.0
        bid_depth_1bp = _depth_within_bps(bid_levels, mid=mid, side="bid", bps=1.0)
        ask_depth_1bp = _depth_within_bps(ask_levels, mid=mid, side="ask", bps=1.0)
        top_bid_depth = _top_notional(bid_levels)
        top_ask_depth = _top_notional(ask_levels)
        signed_delta = _signed_trade_delta_usd(
            agg_trades,
            start_ms=previous_timestamp_ms,
            end_ms=timestamp_ms,
        )
        total_top_depth = top_bid_depth + top_ask_depth
        previous_top_depth = _snapshot_top_depth(previous) if previous else 0.0
        replenishment = (
            (total_top_depth - previous_top_depth) / previous_top_depth
            if previous_top_depth > 0
            else 0.0
        )
        previous_spread = _snapshot_spread_bps(previous) if previous else 0.0
        spread_spike = int(previous_spread > 0 and spread_bps >= previous_spread * float(spread_spike_multiplier))
        trade_count = _trade_count(agg_trades, start_ms=previous_timestamp_ms, end_ms=timestamp_ms)
        rows.append(
            {
                "timestamp_ms": timestamp_ms,
                "timestamp": datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).isoformat(),
                "symbol": _normalize_binance_symbol(symbol),
                "last_update_id": int(float(snapshot.get("lastUpdateId", 0) or 0)),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_bps": spread_bps,
                "depth_bid_1bp_usd": bid_depth_1bp,
                "depth_ask_1bp_usd": ask_depth_1bp,
                "signed_trade_delta_usd": signed_delta,
                "stacked_imbalance_count": _stacked_imbalance_count(
                    bid_levels,
                    ask_levels,
                    threshold=imbalance_threshold,
                ),
                "absorption_score": _absorption_score(
                    signed_delta_usd=signed_delta,
                    top_depth_usd=total_top_depth,
                    spread_spike=bool(spread_spike),
                ),
                "depth_replenishment_rate": replenishment,
                "spread_spike_flag": spread_spike,
                "trade_count": trade_count,
                "liquidation_notional_usd": 0.0,
                "open_interest": _open_interest_value(open_interest),
            }
        )
        previous = snapshot
    return rows


def _parse_force_order_payload(payload: dict[str, object], *, bucket_seconds: int) -> tuple[str, float] | None:
    if str(payload.get("e", "")) != "forceOrder":
        return None
    order = payload.get("o")
    if not isinstance(order, dict):
        return None
    event_time_ms = _int_or_none(order.get("T")) or _int_or_none(payload.get("E"))
    if event_time_ms is None:
        return None
    qty = _float_from_order(order, "z", "l", "q")
    price = _float_from_order(order, "ap", "p")
    notional = max(0.0, qty * price)
    if notional <= 0.0:
        return None
    bucket_start_ms = (event_time_ms // (bucket_seconds * 1000)) * bucket_seconds * 1000
    timestamp = datetime.fromtimestamp(bucket_start_ms / 1000.0, tz=timezone.utc).isoformat()
    return timestamp, notional


def _event_bucket_timestamp(payload: dict[str, object], *, bucket_seconds: int) -> str | None:
    order = payload.get("o")
    event_time_ms = None
    if isinstance(order, dict):
        event_time_ms = _int_or_none(order.get("T"))
    event_type = str(payload.get("e") or "")
    if event_time_ms is None and event_type == "markPriceUpdate":
        event_time_ms = _int_or_none(payload.get("E"))
    event_time_ms = event_time_ms or _int_or_none(payload.get("T")) or _int_or_none(payload.get("E"))
    if event_time_ms is None:
        return None
    bucket_start_ms = (event_time_ms // (bucket_seconds * 1000)) * bucket_seconds * 1000
    return datetime.fromtimestamp(bucket_start_ms / 1000.0, tz=timezone.utc).isoformat()


def _float_from_order(order: dict[str, object], *keys: str) -> float:
    for key in keys:
        try:
            value = float(order.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return 0.0


def _int_or_none(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _timeframe_seconds(timeframe: str) -> int:
    normalized = str(timeframe)
    if normalized == "1Min":
        return 60
    if normalized == "15Min":
        return 15 * 60
    if normalized == "1Hour":
        return 60 * 60
    if normalized == "1Day":
        return 24 * 60 * 60
    raise ValueError(f"unsupported_timeframe:{timeframe}")


def _raw_event_rows(
    *,
    symbol: str,
    depth_snapshots: list[dict[str, object]],
    agg_trades: list[object],
    open_interest: dict[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for depth in depth_snapshots:
        rows.append(
            {
                "event_type": "depth_snapshot",
                "symbol": symbol,
                "event_time_ms": _depth_timestamp_ms(depth),
                "payload": depth,
            }
        )
    for trade in agg_trades:
        if isinstance(trade, dict):
            rows.append(
                {
                    "event_type": "agg_trade",
                    "symbol": symbol,
                    "event_time_ms": int(float(trade.get("T", 0) or 0)),
                    "payload": trade,
                }
            )
    rows.append(
        {
            "event_type": "open_interest",
            "symbol": symbol,
            "event_time_ms": int(float(open_interest.get("time", 0) or 0)),
            "payload": open_interest,
        }
    )
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_feature_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "timestamp_ms",
        "timestamp",
        "symbol",
        "last_update_id",
        "best_bid",
        "best_ask",
        "spread_bps",
        "depth_bid_1bp_usd",
        "depth_ask_1bp_usd",
        "signed_trade_delta_usd",
        "stacked_imbalance_count",
        "absorption_score",
        "depth_replenishment_rate",
        "spread_spike_flag",
        "trade_count",
        "liquidation_notional_usd",
        "open_interest",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _format_csv_value(row.get(name)) for name in fieldnames})


def _format_csv_value(value: object) -> object:
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def _parse_levels(raw: object) -> list[tuple[float, float]]:
    if not isinstance(raw, list):
        return []
    levels: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        try:
            price = float(item[0])
            qty = float(item[1])
        except (TypeError, ValueError):
            continue
        if price > 0 and qty > 0:
            levels.append((price, qty))
    return levels


def _depth_timestamp_ms(snapshot: dict[str, object] | None) -> int:
    if not snapshot:
        return 0
    for key in ("T", "E", "time"):
        try:
            value = snapshot.get(key)
            if value is not None:
                return int(float(value))
        except (TypeError, ValueError):
            continue
    return 0


def _depth_within_bps(levels: list[tuple[float, float]], *, mid: float, side: str, bps: float) -> float:
    if mid <= 0:
        return 0.0
    if side == "bid":
        threshold = mid * (1.0 - bps / 10_000.0)
        eligible = [(price, qty) for price, qty in levels if price >= threshold]
    else:
        threshold = mid * (1.0 + bps / 10_000.0)
        eligible = [(price, qty) for price, qty in levels if price <= threshold]
    return sum(price * qty for price, qty in eligible)


def _top_notional(levels: list[tuple[float, float]], *, limit: int = 5) -> float:
    return sum(price * qty for price, qty in levels[:limit])


def _trade_count(trades: list[object], *, start_ms: int | None, end_ms: int) -> int:
    return len(_windowed_trades(trades, start_ms=start_ms, end_ms=end_ms))


def _signed_trade_delta_usd(trades: list[object], *, start_ms: int | None, end_ms: int) -> float:
    delta = 0.0
    for trade in _windowed_trades(trades, start_ms=start_ms, end_ms=end_ms):
        try:
            price = float(trade.get("p", 0.0) or 0.0)
            qty = float(trade.get("q", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        # Binance aggTrade `m=True` means buyer is maker, so taker flow is sell.
        sign = -1.0 if bool(trade.get("m")) else 1.0
        delta += sign * price * qty
    return delta


def _windowed_trades(trades: list[object], *, start_ms: int | None, end_ms: int) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        try:
            trade_time = int(float(trade.get("T", 0) or 0))
        except (TypeError, ValueError):
            continue
        if start_ms is not None and trade_time <= start_ms:
            continue
        if end_ms and trade_time > end_ms:
            continue
        selected.append(trade)
    return selected


def _stacked_imbalance_count(
    bid_levels: list[tuple[float, float]],
    ask_levels: list[tuple[float, float]],
    *,
    threshold: float,
) -> int:
    count = 0
    for index in range(min(len(bid_levels), len(ask_levels), 5)):
        bid_notional = bid_levels[index][0] * bid_levels[index][1]
        ask_notional = ask_levels[index][0] * ask_levels[index][1]
        total = bid_notional + ask_notional
        if total > 0 and abs(bid_notional - ask_notional) / total >= threshold:
            count += 1
    return count


def _absorption_score(*, signed_delta_usd: float, top_depth_usd: float, spread_spike: bool) -> float:
    del spread_spike
    if signed_delta_usd == 0.0 or top_depth_usd <= 0.0:
        return 0.0
    return min(1.0, top_depth_usd / max(abs(signed_delta_usd), 1.0))


def _snapshot_top_depth(snapshot: dict[str, object] | None) -> float:
    if not snapshot:
        return 0.0
    return _top_notional(_parse_levels(snapshot.get("bids"))) + _top_notional(_parse_levels(snapshot.get("asks")))


def _snapshot_spread_bps(snapshot: dict[str, object] | None) -> float:
    if not snapshot:
        return 0.0
    bid_levels = _parse_levels(snapshot.get("bids"))
    ask_levels = _parse_levels(snapshot.get("asks"))
    if not bid_levels or not ask_levels:
        return 0.0
    best_bid = bid_levels[0][0]
    best_ask = ask_levels[0][0]
    mid = (best_bid + best_ask) / 2.0
    return ((best_ask - best_bid) / mid * 10_000.0) if mid else 0.0


def _open_interest_value(open_interest: dict[str, object] | None) -> float:
    if not isinstance(open_interest, dict):
        return 0.0
    try:
        return float(open_interest.get("openInterest", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))
