from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean

from engine.io.sqlite import connect_sqlite
from engine.memory.store import initialize_memory_db
from engine.execution.order_intent import InternalOrderIntent
from engine.execution.venue_order_request import build_venue_order_request
from engine.strategy.artifacts import paper_authority_decision


PAPER_FIXTURE_MAKER_FEE_RATE = 0.0002
PAPER_FIXTURE_TAKER_FEE_RATE = 0.0005


@dataclass(frozen=True)
class PaperOrderIntent:
    symbol: str
    side: str
    qty: float
    expected_price: float
    limit_price: float | None = None
    order_type: str = "market"
    post_only: bool = False
    time_in_force: str = "GTC"
    reduce_only: bool = False


@dataclass(frozen=True)
class PaperMarketSnapshot:
    ts: str
    symbol: str
    bid: float
    ask: float
    last_trade_price: float
    traded_qty_at_price: float = 0.0
    canceled_ahead_qty: float = 0.0
    depth_ahead_qty: float = 0.0
    visible_depth_qty: float = 0.0
    topn_depth_qty: float = 0.0
    volatility_1m: float = 0.0
    volatility_15m: float = 0.0
    funding_rate: float = 0.0
    bid_depth_levels: object = ()
    ask_depth_levels: object = ()
    adverse_price_after_fill: float | None = None
    funding_time: str | None = None


@dataclass(frozen=True)
class PaperExecutionCostModel:
    cost_model: str
    source: str
    venue_source: str
    maker_fee_rate: float
    taker_fee_rate: float
    maker_fee_bps: float
    taker_fee_bps: float
    slippage_model: str
    slippage_bps: float | None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "cost_model": self.cost_model,
            "source": self.source,
            "venue_source": self.venue_source,
            "maker_fee_rate": self.maker_fee_rate,
            "taker_fee_rate": self.taker_fee_rate,
            "maker_fee_bps": self.maker_fee_bps,
            "taker_fee_bps": self.taker_fee_bps,
            "slippage_model": self.slippage_model,
        }
        if self.slippage_bps is not None:
            payload["slippage_bps"] = self.slippage_bps
        return payload


def calculate_side_aware_slippage(*, side: str, expected_price: float, live_vwap_price: float) -> dict[str, float]:
    side_multiplier = 1.0 if str(side).upper() == "BUY" else -1.0
    slip_px = side_multiplier * (float(live_vwap_price) - float(expected_price))
    slip_bps = slip_px / float(expected_price) * 10_000.0 if expected_price else 0.0
    return {"slip_px": round(slip_px, 12), "slip_bps": round(slip_bps, 12)}


def approximate_queue_fill(
    *,
    order_qty: float,
    depth_ahead_qty: float,
    traded_qty_at_price: float,
    canceled_ahead_qty: float = 0.0,
) -> dict[str, float]:
    fillable_after_queue = max(0.0, float(traded_qty_at_price) + float(canceled_ahead_qty) - float(depth_ahead_qty))
    filled_qty = min(float(order_qty), fillable_after_queue)
    fill_ratio = filled_qty / float(order_qty) if order_qty else 0.0
    return {
        "order_qty": float(order_qty),
        "depth_ahead_qty": float(depth_ahead_qty),
        "traded_qty_at_price": float(traded_qty_at_price),
        "canceled_ahead_qty": float(canceled_ahead_qty),
        "filled_qty": round(filled_qty, 12),
        "fill_ratio": round(fill_ratio, 12),
    }


def simulate_fill_model_v2(
    *,
    intent: PaperOrderIntent,
    snapshot: PaperMarketSnapshot,
    latency_ms: float = 0.0,
    maker_fee_rate: float = PAPER_FIXTURE_MAKER_FEE_RATE,
    taker_fee_rate: float = PAPER_FIXTURE_TAKER_FEE_RATE,
) -> dict[str, object]:
    side = intent.side.upper()
    order_type = intent.order_type.lower()
    passive = order_type == "limit" and bool(intent.post_only)
    mid = (float(snapshot.bid) + float(snapshot.ask)) / 2.0
    spread_bps = ((float(snapshot.ask) - float(snapshot.bid)) / mid) * 10_000.0 if mid else 0.0

    if passive:
        queue = approximate_queue_fill(
            order_qty=float(intent.qty),
            depth_ahead_qty=float(snapshot.depth_ahead_qty),
            traded_qty_at_price=float(snapshot.traded_qty_at_price),
            canceled_ahead_qty=float(snapshot.canceled_ahead_qty),
        )
        qty_filled = float(queue["filled_qty"])
        qty_canceled = max(0.0, float(intent.qty) - qty_filled)
        live_vwap_price = float(intent.limit_price if intent.limit_price is not None else snapshot.last_trade_price)
        fill_path = "passive"
        maker_ratio = 1.0 if qty_filled else 0.0
        fee_rate = maker_fee_rate
        impact_bps = 0.0
        spread_crossing_bps = 0.0
    else:
        levels = _depth_levels_for_market_fill(intent, snapshot)
        walk = _walk_depth(levels, float(intent.qty))
        qty_filled = float(walk["qty_filled"])
        qty_canceled = max(0.0, float(intent.qty) - qty_filled)
        live_vwap_price = float(walk["vwap_price"])
        queue = {
            "order_qty": float(intent.qty),
            "depth_ahead_qty": 0.0,
            "traded_qty_at_price": float(snapshot.visible_depth_qty),
            "canceled_ahead_qty": 0.0,
            "filled_qty": round(qty_filled, 12),
            "fill_ratio": round(qty_filled / float(intent.qty), 12) if intent.qty else 0.0,
        }
        fill_path = "market"
        maker_ratio = 0.0
        fee_rate = taker_fee_rate
        top_touch = float(snapshot.ask if side == "BUY" else snapshot.bid)
        impact_bps = _side_aware_bps(side=side, base_price=top_touch, observed_price=live_vwap_price)
        spread_crossing_bps = spread_bps / 2.0

    slippage = calculate_side_aware_slippage(
        side=side,
        expected_price=float(intent.expected_price),
        live_vwap_price=live_vwap_price,
    )
    adverse_selection_bps = 0.0
    if snapshot.adverse_price_after_fill is not None and qty_filled:
        adverse_selection_bps = max(
            0.0,
            _side_aware_bps(
                side=side,
                base_price=live_vwap_price,
                observed_price=float(snapshot.adverse_price_after_fill),
            ),
        )
    non_fill_opportunity_loss = _non_fill_opportunity_loss(
        side=side,
        reference_price=live_vwap_price,
        adverse_price=snapshot.adverse_price_after_fill,
        qty_unfilled=qty_canceled,
    )
    notional = qty_filled * live_vwap_price
    return {
        "fill_model_version": "paper_fill_model_v2",
        "fill_path": fill_path,
        "time_in_force": intent.time_in_force,
        "timeout": bool(passive and qty_canceled > 0.0),
        "qty_submitted": float(intent.qty),
        "qty_filled": round(qty_filled, 12),
        "qty_canceled": round(qty_canceled, 12),
        "live_vwap_price": round(live_vwap_price, 12),
        "fee_quote": round(notional * fee_rate, 12),
        "fee_rate": fee_rate,
        "maker_ratio": maker_ratio,
        "spread_bps": round(spread_bps, 12),
        "spread_crossing_bps": round(spread_crossing_bps, 12),
        "impact_bps": round(max(0.0, impact_bps), 12),
        "drift_bps": slippage["slip_bps"],
        "adverse_selection_bps": round(adverse_selection_bps, 12),
        "non_fill_opportunity_loss_quote": round(non_fill_opportunity_loss, 12),
        "latency_bucket": _latency_bucket(latency_ms),
        "queue_ahead_qty": float(snapshot.depth_ahead_qty) if passive else 0.0,
        "queue_progress_qty": round(
            float(snapshot.traded_qty_at_price) + float(snapshot.canceled_ahead_qty),
            12,
        )
        if passive
        else 0.0,
        "queue_approximation": queue,
        **slippage,
    }


def run_paper_executor_fixture(
    artifact: dict[str, object],
    *,
    order_intents: list[PaperOrderIntent],
    market_snapshots: list[PaperMarketSnapshot],
    latency_ms: float = 0.0,
    maker_fee_rate: float | None = None,
    taker_fee_rate: float | None = None,
) -> dict[str, object]:
    now_utc = market_snapshots[0].ts if market_snapshots else None
    all_reduce_only = all(intent.reduce_only for intent in order_intents)
    authority = paper_authority_decision(artifact, now_utc=now_utc, reduce_only=all_reduce_only)
    if not authority.allowed:
        raise ValueError(",".join(authority.reasons))

    cost_model = resolve_paper_execution_cost_model(
        artifact,
        maker_fee_rate=maker_fee_rate,
        taker_fee_rate=taker_fee_rate,
    )
    snapshots_by_symbol = {snapshot.symbol: snapshot for snapshot in market_snapshots}
    telemetry_rows: list[dict[str, object]] = []
    funding_rows: list[dict[str, object]] = []
    for ordinal, intent in enumerate(order_intents, start=1):
        snapshot = snapshots_by_symbol.get(intent.symbol)
        if snapshot is None:
            telemetry_rows.append(_rejected_telemetry(artifact, intent, ordinal, "missing_market_snapshot"))
            continue
        telemetry = _simulate_order(
            artifact=artifact,
            intent=intent,
            snapshot=snapshot,
            ordinal=ordinal,
            latency_ms=latency_ms,
            maker_fee_rate=cost_model.maker_fee_rate,
            taker_fee_rate=cost_model.taker_fee_rate,
        )
        telemetry_rows.append(telemetry)
        if snapshot.funding_rate:
            funding_rows.append(
                {
                    "symbol": intent.symbol,
                    "position_notional": round(telemetry["live_vwap_price"] * telemetry["qty_filled"], 12),
                    "funding_rate": snapshot.funding_rate,
                    "funding_fee": round(
                        telemetry["live_vwap_price"] * telemetry["qty_filled"] * snapshot.funding_rate,
                        12,
                    ),
                }
            )

    slip_values = [float(row["slip_bps"]) for row in telemetry_rows if row.get("was_rejected") is False]
    return {
        "status": "completed",
        "artifact_id": artifact["artifact_id"],
        "rollout_stage": artifact["rollout_stage"],
        "order_count": len(order_intents),
        "filled_order_count": sum(1 for row in telemetry_rows if float(row.get("qty_filled", 0.0)) > 0.0),
        "effective_cost_model": cost_model.as_dict(),
        "order_telemetry": telemetry_rows,
        "funding_events": funding_rows,
        "paper_live_divergence": {
            "recorded_for_calibration": True,
            "average_slip_bps": round(mean(slip_values), 12) if slip_values else 0.0,
            "max_abs_slip_bps": round(max((abs(value) for value in slip_values), default=0.0), 12),
            "sample_count": len(slip_values),
        },
    }


def resolve_paper_execution_cost_model(
    artifact: dict[str, object],
    *,
    maker_fee_rate: float | None = None,
    taker_fee_rate: float | None = None,
) -> PaperExecutionCostModel:
    raw_config = artifact.get("cost_model_config")
    config = raw_config if isinstance(raw_config, dict) else {}
    source = "fixture_default"
    venue_source = "paper_fixture_default"
    slippage_model = "not_configured"
    slippage_bps: float | None = None

    resolved_maker = PAPER_FIXTURE_MAKER_FEE_RATE
    resolved_taker = PAPER_FIXTURE_TAKER_FEE_RATE
    if config:
        source = "artifact_cost_model_config"
        venue_source = str(config.get("source", "artifact_cost_model_config"))
        resolved_maker = _fee_rate_from_config(config, "maker_fee_rate", "maker_fee_bps", resolved_maker)
        resolved_taker = _fee_rate_from_config(config, "taker_fee_rate", "taker_fee_bps", resolved_taker)
        slippage_model = str(config.get("slippage_model", slippage_model))
        if "slippage_bps" in config:
            slippage_bps = float(config["slippage_bps"])

    if maker_fee_rate is not None or taker_fee_rate is not None:
        source = "explicit"
        venue_source = "executor_arguments"
        if maker_fee_rate is not None:
            resolved_maker = float(maker_fee_rate)
        if taker_fee_rate is not None:
            resolved_taker = float(taker_fee_rate)

    return PaperExecutionCostModel(
        cost_model=str(artifact.get("cost_model", "")),
        source=source,
        venue_source=venue_source,
        maker_fee_rate=round(resolved_maker, 12),
        taker_fee_rate=round(resolved_taker, 12),
        maker_fee_bps=round(resolved_maker * 10_000.0, 12),
        taker_fee_bps=round(resolved_taker * 10_000.0, 12),
        slippage_model=slippage_model,
        slippage_bps=slippage_bps,
    )


def record_paper_execution_result(
    db_path: Path,
    result: dict[str, object],
    *,
    session_id: str | None = None,
) -> dict[str, int]:
    initialize_memory_db(db_path)
    artifact_id = str(result.get("artifact_id", ""))
    connection = connect_sqlite(db_path)
    try:
        telemetry_count = 0
        for row in result.get("order_telemetry", []):
            if not isinstance(row, dict):
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO order_telemetry (
                    telemetry_id,
                    order_id_client,
                    intent_id,
                    symbol,
                    side,
                    ts_signal,
                    ts_send,
                    ts_ack,
                    ts_last_fill,
                    qty_submitted,
                    qty_filled,
                    qty_canceled,
                    price_limit,
                    mid_at_send,
                    mid_at_ack,
                    expected_price,
                    live_vwap_price,
                    fee_quote,
                    fee_rate,
                    slip_bps,
                    effective_spread_bps,
                    spread_bps,
                    depth_at_price,
                    topn_depth,
                    vol_1m,
                    vol_15m,
                    latency_rtt_ms,
                    maker_ratio,
                    was_canceled_by_engine,
                    was_rejected,
                    risk_blocked,
                    drift_bps,
                    impact_bps,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("telemetry_id"),
                    row.get("order_id_client"),
                    row.get("telemetry_id"),
                    row.get("symbol"),
                    row.get("side"),
                    row.get("ts_signal"),
                    row.get("ts_send"),
                    row.get("ts_ack"),
                    row.get("ts_ack"),
                    row.get("qty_submitted"),
                    row.get("qty_filled"),
                    row.get("qty_canceled"),
                    row.get("limit_price"),
                    row.get("mid_at_send"),
                    row.get("mid_at_ack"),
                    row.get("expected_price"),
                    row.get("live_vwap_price"),
                    row.get("fee_quote"),
                    row.get("fee_rate"),
                    row.get("slip_bps"),
                    row.get("spread_bps"),
                    row.get("spread_bps"),
                    row.get("depth_ahead"),
                    row.get("topn_depth"),
                    row.get("vol_1m"),
                    row.get("vol_15m"),
                    row.get("latency_rtt_ms"),
                    row.get("maker_ratio"),
                    1 if row.get("qty_canceled", 0.0) else 0,
                    1 if row.get("was_rejected") else 0,
                    1 if row.get("risk_blocked") else 0,
                    row.get("drift_bps"),
                    row.get("impact_bps"),
                    json.dumps({"source": "paper_executor", "session_id": session_id, "raw": row}, sort_keys=True),
                ),
            )
            telemetry_count += 1

        funding_count = 0
        for ordinal, row in enumerate(result.get("funding_events", []), start=1):
            if not isinstance(row, dict):
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO funding_events (
                    funding_event_id,
                    ts_utc,
                    symbol,
                    position_notional,
                    funding_rate,
                    funding_fee,
                    metadata_json
                ) VALUES (?, datetime('now'), ?, ?, ?, ?, ?)
                """,
                (
                        f"{session_id + ':' if session_id else ''}{artifact_id}:paper:funding:{ordinal}",
                    row.get("symbol"),
                    row.get("position_notional"),
                    row.get("funding_rate"),
                    row.get("funding_fee"),
                    json.dumps({"source": "paper_executor", "session_id": session_id}, sort_keys=True),
                ),
            )
            funding_count += 1

        metrics_count = 0
        divergence = result.get("paper_live_divergence", {})
        if isinstance(divergence, dict):
            for metric_name, value in (
                ("paper_live_average_slip_bps", divergence.get("average_slip_bps")),
                ("paper_live_max_abs_slip_bps", divergence.get("max_abs_slip_bps")),
                ("paper_live_sample_count", divergence.get("sample_count")),
            ):
                connection.execute(
                    """
                    INSERT OR REPLACE INTO live_metrics (
                        metric_id,
                        artifact_id,
                        ts_utc,
                        metric_name,
                        metric_value,
                        payload_json
                    ) VALUES (?, ?, datetime('now'), ?, ?, ?)
                    """,
                    (
                        f"{artifact_id}:paper:{metric_name}",
                        artifact_id,
                        metric_name,
                        value,
                        json.dumps({"source": "paper_executor", "session_id": session_id}, sort_keys=True),
                    ),
                )
                metrics_count += 1
        connection.commit()
        return {
            "order_telemetry_rows": telemetry_count,
            "funding_event_rows": funding_count,
            "live_metric_rows": metrics_count,
        }
    finally:
        connection.close()


def paper_fixture_from_payload(payload: dict[str, object]) -> tuple[list[PaperOrderIntent], list[PaperMarketSnapshot]]:
    intents = [
        PaperOrderIntent(**item)
        for item in payload.get("order_intents", [])
        if isinstance(item, dict)
    ]
    snapshots = [
        PaperMarketSnapshot(**item)
        for item in payload.get("market_snapshots", [])
        if isinstance(item, dict)
    ]
    return intents, snapshots


def _simulate_order(
    *,
    artifact: dict[str, object],
    intent: PaperOrderIntent,
    snapshot: PaperMarketSnapshot,
    ordinal: int,
    latency_ms: float,
    maker_fee_rate: float,
    taker_fee_rate: float,
) -> dict[str, object]:
    fill = simulate_fill_model_v2(
        intent=intent,
        snapshot=snapshot,
        latency_ms=latency_ms,
        maker_fee_rate=maker_fee_rate,
        taker_fee_rate=taker_fee_rate,
    )
    internal_intent = _internal_intent_from_paper_intent(artifact, intent, snapshot.ts)
    venue_order_request = build_venue_order_request(
        internal_intent,
        venue="binance_usdm",
        quantity=float(intent.qty),
        order_type=str(intent.order_type).upper(),
        time_in_force=intent.time_in_force,
        price=float(intent.limit_price if intent.limit_price is not None else intent.expected_price),
        timestamp=0,
    )
    live_vwap_price = float(fill["live_vwap_price"])
    qty_filled = float(fill["qty_filled"])
    mid = (snapshot.bid + snapshot.ask) / 2.0
    return {
        "telemetry_id": f"{artifact['artifact_id']}:paper:{ordinal}",
        "artifact_id": artifact["artifact_id"],
        "symbol": intent.symbol,
        "side": intent.side.upper(),
        "ts_signal": snapshot.ts,
        "ts_send": snapshot.ts,
        "ts_ack": snapshot.ts,
        "qty_submitted": float(intent.qty),
        "qty_filled": qty_filled,
        "qty_canceled": fill["qty_canceled"],
        "expected_price": float(intent.expected_price),
        "live_vwap_price": live_vwap_price,
        "mid_at_send": mid,
        "mid_at_ack": mid,
        "limit_price": intent.limit_price,
        "fee_quote": fill["fee_quote"],
        "fee_rate": fill["fee_rate"],
        "maker_ratio": fill["maker_ratio"],
        "spread_bps": fill["spread_bps"],
        "visible_depth": snapshot.visible_depth_qty,
        "topn_depth": snapshot.topn_depth_qty,
        "depth_ahead": fill["queue_ahead_qty"],
        "vol_1m": snapshot.volatility_1m,
        "vol_15m": snapshot.volatility_15m,
        "latency_rtt_ms": float(latency_ms),
        "was_rejected": False,
        "risk_blocked": False,
        "drift_bps": fill["drift_bps"],
        "impact_bps": fill["impact_bps"],
        "slip_px": fill["slip_px"],
        "slip_bps": fill["slip_bps"],
        "queue_approximation": fill["queue_approximation"],
        "fill_model_v2": fill,
        "internal_order_intent": internal_intent.to_dict(),
        "venue_order_request": venue_order_request.to_dict(),
    }


def _rejected_telemetry(
    artifact: dict[str, object],
    intent: PaperOrderIntent,
    ordinal: int,
    reason: str,
) -> dict[str, object]:
    return {
        "telemetry_id": f"{artifact['artifact_id']}:paper:{ordinal}",
        "artifact_id": artifact["artifact_id"],
        "symbol": intent.symbol,
        "side": intent.side.upper(),
        "qty_submitted": float(intent.qty),
        "qty_filled": 0.0,
        "qty_canceled": float(intent.qty),
        "expected_price": float(intent.expected_price),
        "live_vwap_price": 0.0,
        "fee_quote": 0.0,
        "fee_rate": 0.0,
        "maker_ratio": 0.0,
        "slip_px": 0.0,
        "slip_bps": 0.0,
        "was_rejected": True,
        "risk_blocked": False,
        "reject_reason": reason,
    }


def _internal_intent_from_paper_intent(
    artifact: dict[str, object],
    intent: PaperOrderIntent,
    created_at: str,
) -> InternalOrderIntent:
    side = intent.side.upper()
    notional = float(intent.qty) * float(intent.expected_price)
    signed_delta = -notional if side == "SELL" else notional
    intent_type = "reduction" if intent.reduce_only else "increase"
    return InternalOrderIntent.create(
        artifact_id=str(artifact.get("artifact_id", "")),
        portfolio_plan_id=str(artifact.get("portfolio_plan_id") or "paper-fixture"),
        symbol=intent.symbol,
        desired_position_delta=signed_delta,
        side=side,
        intent_type=intent_type,
        urgency="normal",
        reduce_only_required=bool(intent.reduce_only),
        max_slippage_bps=float(artifact.get("max_slippage_bps", 100.0) or 100.0),
        max_spread_bps=float(artifact.get("max_spread_bps", 100.0) or 100.0),
        max_participation_rate=float(artifact.get("max_participation_rate", 1.0) or 1.0),
        funding_guard_policy=str(artifact.get("funding_guard_policy") or "paper_guard"),
        liquidation_guard_policy=str(artifact.get("liquidation_guard_policy") or "paper_guard"),
        created_at=created_at,
        expires_at=created_at,
    )


def _fee_rate_from_config(config: dict[object, object], rate_key: str, bps_key: str, default: float) -> float:
    if rate_key in config:
        return float(config[rate_key])
    if bps_key in config:
        return float(config[bps_key]) / 10_000.0
    return float(default)


def _depth_levels_for_market_fill(intent: PaperOrderIntent, snapshot: PaperMarketSnapshot) -> list[tuple[float, float]]:
    side = intent.side.upper()
    raw_levels = snapshot.ask_depth_levels if side == "BUY" else snapshot.bid_depth_levels
    levels = _normalize_depth_levels(raw_levels)
    if levels:
        return levels
    fallback_qty = float(snapshot.visible_depth_qty or snapshot.topn_depth_qty or intent.qty)
    return [(float(snapshot.last_trade_price), fallback_qty)]


def _normalize_depth_levels(raw_levels: object) -> list[tuple[float, float]]:
    if not isinstance(raw_levels, (list, tuple)):
        return []
    levels: list[tuple[float, float]] = []
    for level in raw_levels:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        try:
            price = float(level[0])
            qty = float(level[1])
        except (TypeError, ValueError):
            continue
        if price > 0.0 and qty > 0.0:
            levels.append((price, qty))
    return levels


def _walk_depth(levels: list[tuple[float, float]], order_qty: float) -> dict[str, float]:
    remaining = max(0.0, float(order_qty))
    filled = 0.0
    notional = 0.0
    for price, available_qty in levels:
        if remaining <= 0.0:
            break
        take_qty = min(remaining, float(available_qty))
        filled += take_qty
        notional += take_qty * float(price)
        remaining -= take_qty
    if filled <= 0.0:
        fallback_price = float(levels[0][0]) if levels else 0.0
        return {"qty_filled": 0.0, "vwap_price": fallback_price}
    return {"qty_filled": round(filled, 12), "vwap_price": round(notional / filled, 12)}


def _side_aware_bps(*, side: str, base_price: float, observed_price: float) -> float:
    if not base_price:
        return 0.0
    multiplier = 1.0 if side.upper() == "BUY" else -1.0
    return multiplier * (float(observed_price) - float(base_price)) / float(base_price) * 10_000.0


def _non_fill_opportunity_loss(
    *,
    side: str,
    reference_price: float,
    adverse_price: float | None,
    qty_unfilled: float,
) -> float:
    if adverse_price is None or qty_unfilled <= 0.0:
        return 0.0
    adverse_bps = _side_aware_bps(side=side, base_price=reference_price, observed_price=float(adverse_price))
    if adverse_bps <= 0.0:
        return 0.0
    return abs(float(adverse_price) - float(reference_price)) * float(qty_unfilled)


def _latency_bucket(latency_ms: float) -> str:
    value = float(latency_ms)
    if value < 50.0:
        return "lt_50ms"
    if value < 250.0:
        return "50ms_250ms"
    if value < 1000.0:
        return "250ms_1s"
    return "gte_1s"
