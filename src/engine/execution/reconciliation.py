from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from engine.io.artifacts import write_json_atomic
from engine.io.sqlite import connect_sqlite
from engine.memory.store import initialize_memory_db, rebuild_execution_projections
from engine.portfolio.allocator import HumanOverrideRequest, apply_human_override


ARTIFACT_TYPE = "phase3_projection_reconciliation_report"
EPSILON = 1e-9


@dataclass(frozen=True)
class GatewayAccountSnapshot:
    account_id: str = "account"
    stale: bool = False
    equity: float | None = None
    cash_balance: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    margin_usage: float | None = None
    exposure: float | None = None


@dataclass(frozen=True)
class GatewayOrderSnapshot:
    order_id_client: str
    symbol: str
    side: str
    qty: float
    filled_qty: float = 0.0
    status: str = "NEW"
    reduce_only: bool = False


@dataclass(frozen=True)
class GatewayPositionSnapshot:
    symbol: str
    net_qty: float
    entry_price: float | None = None
    unrealized_pnl: float | None = None


@dataclass(frozen=True)
class GatewayStateSnapshot:
    account: GatewayAccountSnapshot
    open_orders: list[GatewayOrderSnapshot]
    fills: list[dict[str, object]]
    positions: list[GatewayPositionSnapshot]
    funding: list[dict[str, object]]


def rebuild_phase3_execution_projection(db_path: Path) -> dict[str, object]:
    first = _rebuild_phase3_once(db_path)
    second = _rebuild_phase3_once(db_path)
    return {
        **second,
        "first_projection_digest": first["phase3_projection_digest"],
        "second_projection_digest": second["phase3_projection_digest"],
        "replay_deterministic": first["phase3_projection_digest"] == second["phase3_projection_digest"],
    }


def reconcile_projection_with_gateway(
    db_path: Path,
    snapshot: GatewayStateSnapshot,
    *,
    operator_id: str,
    artifact_id: str,
) -> dict[str, object]:
    projection = rebuild_phase3_execution_projection(db_path)
    local = _load_local_projection(db_path)
    blocker_codes = _reconciliation_blockers(db_path, local, snapshot)
    safe_actions = _safe_actions_for_blockers(blocker_codes)
    operator_journal = _journal_safe_actions(
        db_path,
        safe_actions,
        operator_id=operator_id,
        artifact_id=artifact_id,
        blocker_codes=blocker_codes,
    )
    return {
        "artifact_type": ARTIFACT_TYPE,
        "status": "matched" if not blocker_codes else "blocked",
        "blocker_codes": blocker_codes,
        "safe_actions": safe_actions,
        "operator_journal": operator_journal,
        "projection": projection,
        "gateway_snapshot": snapshot_to_payload(snapshot),
    }


def load_gateway_snapshot(path: Path) -> GatewayStateSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("gateway snapshot must be a JSON object")
    return gateway_snapshot_from_payload(payload)


def gateway_snapshot_from_payload(payload: dict[str, object]) -> GatewayStateSnapshot:
    account_payload = payload.get("account", {})
    if not isinstance(account_payload, dict):
        account_payload = {}
    open_orders = [
        GatewayOrderSnapshot(
            order_id_client=str(item.get("order_id_client", "")),
            symbol=str(item.get("symbol", "")),
            side=str(item.get("side", "")),
            qty=float(item.get("qty", 0.0) or 0.0),
            filled_qty=float(item.get("filled_qty", 0.0) or 0.0),
            status=str(item.get("status", "NEW")),
            reduce_only=bool(item.get("reduce_only", False)),
        )
        for item in payload.get("open_orders", [])
        if isinstance(item, dict)
    ]
    positions = [
        GatewayPositionSnapshot(
            symbol=str(item.get("symbol", "")),
            net_qty=float(item.get("net_qty", 0.0) or 0.0),
            entry_price=_float_or_none(item.get("entry_price")),
            unrealized_pnl=_float_or_none(item.get("unrealized_pnl")),
        )
        for item in payload.get("positions", [])
        if isinstance(item, dict)
    ]
    fills = [dict(item) for item in payload.get("fills", []) if isinstance(item, dict)]
    funding = [dict(item) for item in payload.get("funding", []) if isinstance(item, dict)]
    return GatewayStateSnapshot(
        account=GatewayAccountSnapshot(
            account_id=str(account_payload.get("account_id", "account")),
            stale=bool(account_payload.get("stale", False)),
            equity=_float_or_none(account_payload.get("equity")),
            cash_balance=_float_or_none(account_payload.get("cash_balance")),
            realized_pnl=_float_or_none(account_payload.get("realized_pnl")),
            unrealized_pnl=_float_or_none(account_payload.get("unrealized_pnl")),
            margin_usage=_float_or_none(account_payload.get("margin_usage")),
            exposure=_float_or_none(account_payload.get("exposure")),
        ),
        open_orders=open_orders,
        fills=fills,
        positions=positions,
        funding=funding,
    )


def snapshot_to_payload(snapshot: GatewayStateSnapshot) -> dict[str, object]:
    return {
        "account": {
            "account_id": snapshot.account.account_id,
            "stale": snapshot.account.stale,
            "equity": snapshot.account.equity,
            "cash_balance": snapshot.account.cash_balance,
            "realized_pnl": snapshot.account.realized_pnl,
            "unrealized_pnl": snapshot.account.unrealized_pnl,
            "margin_usage": snapshot.account.margin_usage,
            "exposure": snapshot.account.exposure,
        },
        "open_orders": [order.__dict__ for order in snapshot.open_orders],
        "fills": snapshot.fills,
        "positions": [position.__dict__ for position in snapshot.positions],
        "funding": snapshot.funding,
    }


def write_reconciliation_report(path: Path, report: dict[str, object]) -> Path:
    return write_json_atomic(path, report)


def _rebuild_phase3_once(db_path: Path) -> dict[str, object]:
    initialize_memory_db(db_path)
    base = rebuild_execution_projections(db_path)
    connection = connect_sqlite(db_path)
    try:
        _clear_accounting_tables(connection)
        rows = connection.execute(
            """
            SELECT event_id, ts_exchange, symbol, side, order_id_client, event_type, qty, price, metadata_json
            FROM execution_events
            ORDER BY event_id ASC
            """
        ).fetchall()
        seen_fill_ids: set[str] = set()
        fee_rows = funding_rows = pnl_rows = cash_rows = equity_rows = position_snapshot_rows = 0
        for row in rows:
            event_id, ts_exchange, symbol, side, order_id_client, event_type, qty, price, metadata_json = row
            metadata = _load_json_dict(metadata_json)
            if event_type in {"FILL", "ORDER_FILL", "ORDER_PARTIAL_FILL"}:
                fill_id = str(metadata.get("fill_id") or f"event:{event_id}")
                if fill_id in seen_fill_ids:
                    continue
                seen_fill_ids.add(fill_id)
                fee_rows += _insert_fee_row(connection, event_id, ts_exchange, symbol, order_id_client, metadata)
                funding_rows += _insert_funding_row(connection, event_id, ts_exchange, symbol, metadata)
                pnl_rows += _insert_pnl_row(connection, event_id, ts_exchange, symbol, metadata)
                cash_rows += _insert_cash_row(connection, event_id, ts_exchange, metadata)
                equity_rows += _insert_equity_row(connection, event_id, ts_exchange, metadata)
            if event_type in {"POSITION_RECONCILE", "ACCOUNT_SNAPSHOT"}:
                _upsert_account_risk_state(connection, event_id, metadata)
                equity_rows += _insert_equity_row(connection, event_id, ts_exchange, metadata)
                position_snapshot_rows += _upsert_position_snapshots(connection, event_id, ts_exchange, metadata)
        phase3_digest = _phase3_projection_digest(connection)
        connection.execute(
            """
            INSERT OR REPLACE INTO replay_checkpoints (
                checkpoint_id, created_at_utc, last_event_id, projection_digest, metadata_json
            ) VALUES (?, datetime('now'), ?, ?, ?)
            """,
            (
                f"phase3:{base['last_event_id']}",
                base["last_event_id"],
                phase3_digest,
                json.dumps({"event_count": base["event_count"], "phase": "phase3"}, sort_keys=True),
            ),
        )
        connection.commit()
        return {
            **base,
            "phase3_projection_digest": phase3_digest,
            "fee_rows": fee_rows,
            "funding_rows": funding_rows,
            "pnl_rows": pnl_rows,
            "cash_rows": cash_rows,
            "equity_rows": equity_rows,
            "position_snapshot_rows": position_snapshot_rows,
        }
    finally:
        connection.close()


def _clear_accounting_tables(connection: sqlite3.Connection) -> None:
    for table_name in (
        "fee_ledger",
        "funding_ledger",
        "pnl_attribution",
        "cash_ledger",
        "transfer_ledger",
        "equity_snapshots",
        "position_snapshots",
    ):
        connection.execute(f"DELETE FROM {table_name}")


def _insert_fee_row(
    connection: sqlite3.Connection,
    event_id: int,
    ts_utc: str,
    symbol: str | None,
    order_id_client: str | None,
    metadata: dict[str, object],
) -> int:
    fee = _float_or_none(metadata.get("fee"))
    if fee is None:
        return 0
    connection.execute(
        """
        INSERT INTO fee_ledger (
            ts_utc, symbol, order_id_client, fee_quote, fee_rate, maker_taker, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_utc,
            symbol,
            order_id_client,
            fee,
            _float_or_none(metadata.get("fee_rate")),
            str(metadata.get("maker_taker")) if metadata.get("maker_taker") is not None else None,
            json.dumps({"source_event_id": event_id}, sort_keys=True),
        ),
    )
    return 1


def _insert_funding_row(
    connection: sqlite3.Connection,
    event_id: int,
    ts_utc: str,
    symbol: str | None,
    metadata: dict[str, object],
) -> int:
    funding_fee = _float_or_none(metadata.get("funding_fee"))
    if funding_fee is None:
        return 0
    connection.execute(
        """
        INSERT INTO funding_ledger (
            ts_utc, symbol, position_notional, funding_rate, funding_fee, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            ts_utc,
            symbol,
            _float_or_none(metadata.get("position_notional")),
            _float_or_none(metadata.get("funding_rate")),
            funding_fee,
            json.dumps({"source_event_id": event_id}, sort_keys=True),
        ),
    )
    return 1


def _insert_pnl_row(
    connection: sqlite3.Connection,
    event_id: int,
    ts_utc: str,
    symbol: str | None,
    metadata: dict[str, object],
) -> int:
    values = {
        "realized_strategy_pnl": _float_or_zero(metadata.get("realized_pnl")),
        "unrealized_pnl": _float_or_zero(metadata.get("unrealized_pnl")),
        "fees": _float_or_zero(metadata.get("fee")),
        "funding": _float_or_zero(metadata.get("funding_fee")),
        "slippage": _float_or_zero(metadata.get("slippage")),
        "transfers": _float_or_zero(metadata.get("transfer")),
        "cash_balance_delta": _float_or_zero(metadata.get("cash_balance_delta")),
    }
    if not any(abs(value) > EPSILON for value in values.values()):
        return 0
    connection.execute(
        """
        INSERT INTO pnl_attribution (
            ts_utc, symbol, realized_strategy_pnl, unrealized_pnl, fees, funding,
            slippage, transfers, cash_balance_delta, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_utc,
            symbol,
            values["realized_strategy_pnl"],
            values["unrealized_pnl"],
            values["fees"],
            values["funding"],
            values["slippage"],
            values["transfers"],
            values["cash_balance_delta"],
            json.dumps({"source_event_id": event_id}, sort_keys=True),
        ),
    )
    return 1


def _insert_cash_row(connection: sqlite3.Connection, event_id: int, ts_utc: str, metadata: dict[str, object]) -> int:
    cash_delta = _float_or_none(metadata.get("cash_balance_delta"))
    if cash_delta is None:
        return 0
    connection.execute(
        """
        INSERT INTO cash_ledger (
            ts_utc, account_id, currency, amount, reason, reference_id, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_utc,
            str(metadata.get("account_id") or "account"),
            str(metadata.get("currency") or "USDT"),
            cash_delta,
            str(metadata.get("cash_reason") or "execution_fill"),
            str(metadata.get("fill_id") or f"event:{event_id}"),
            json.dumps({"source_event_id": event_id}, sort_keys=True),
        ),
    )
    return 1


def _insert_equity_row(connection: sqlite3.Connection, event_id: int, ts_utc: str, metadata: dict[str, object]) -> int:
    equity = _float_or_none(metadata.get("equity"))
    if equity is None:
        return 0
    connection.execute(
        """
        INSERT INTO equity_snapshots (
            ts_utc, account_id, equity, cash_balance, unrealized_pnl, realized_pnl, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_utc,
            str(metadata.get("account_id") or "account"),
            equity,
            _float_or_none(metadata.get("cash_balance")),
            _float_or_none(metadata.get("unrealized_pnl")),
            _float_or_none(metadata.get("realized_pnl")),
            json.dumps({"source_event_id": event_id}, sort_keys=True),
        ),
    )
    return 1


def _upsert_account_risk_state(connection: sqlite3.Connection, event_id: int, metadata: dict[str, object]) -> None:
    if not any(key in metadata for key in ("exposure", "margin_usage", "realized_pnl", "unrealized_pnl", "drawdown")):
        return
    connection.execute(
        """
        INSERT OR REPLACE INTO risk_state (
            scope_id, exposure, margin_usage, realized_pnl, unrealized_pnl, drawdown, last_event_id, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "account",
            _float_or_zero(metadata.get("exposure")),
            _float_or_zero(metadata.get("margin_usage")),
            _float_or_zero(metadata.get("realized_pnl")),
            _float_or_zero(metadata.get("unrealized_pnl")),
            _float_or_zero(metadata.get("drawdown")),
            event_id,
            json.dumps({"source_event_id": event_id}, sort_keys=True),
        ),
    )


def _upsert_position_snapshots(
    connection: sqlite3.Connection,
    event_id: int,
    ts_utc: str,
    metadata: dict[str, object],
) -> int:
    raw_positions = metadata.get("positions", [])
    if not isinstance(raw_positions, list):
        return 0
    inserted = 0
    for position in raw_positions:
        if not isinstance(position, dict) or not position.get("symbol"):
            continue
        symbol = str(position["symbol"])
        net_qty = _float_or_zero(position.get("net_qty"))
        entry_price = _float_or_none(position.get("entry_price"))
        unrealized_pnl = _float_or_zero(position.get("unrealized_pnl"))
        connection.execute(
            """
            INSERT INTO position_snapshots (
                position_snapshot_id, ts_utc, account_id, symbol, net_qty, entry_price,
                mark_price, unrealized_pnl, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"phase3:{event_id}:{symbol}",
                ts_utc,
                str(metadata.get("account_id") or "account"),
                symbol,
                net_qty,
                entry_price,
                _float_or_none(position.get("mark_price")),
                unrealized_pnl,
                json.dumps({"source_event_id": event_id}, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO positions (
                symbol, net_qty, entry_price, unrealized_pnl, last_event_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                net_qty,
                entry_price,
                unrealized_pnl,
                event_id,
                json.dumps({"source": "phase3_position_reconcile", "source_event_id": event_id}, sort_keys=True),
            ),
        )
        inserted += 1
    return inserted


def _load_local_projection(db_path: Path) -> dict[str, object]:
    connection = connect_sqlite(db_path, read_only=True)
    try:
        orders = {
            row[0]: {
                "symbol": row[1],
                "side": row[2],
                "qty": _float_or_zero(row[3]),
                "filled_qty": _float_or_zero(row[4]),
                "status": row[5],
                "metadata": _load_json_dict(row[6]),
            }
            for row in connection.execute(
                "SELECT order_id_client, symbol, side, qty, filled_qty, status, metadata_json FROM orders_live"
            ).fetchall()
        }
        fills = {
            row[0]: {"order_id_client": row[1], "symbol": row[2], "qty": _float_or_zero(row[3])}
            for row in connection.execute("SELECT fill_id, order_id_client, symbol, qty FROM fills").fetchall()
        }
        positions = {
            row[0]: {
                "net_qty": _float_or_zero(row[1]),
                "entry_price": _float_or_none(row[2]),
                "unrealized_pnl": _float_or_zero(row[3]),
            }
            for row in connection.execute("SELECT symbol, net_qty, entry_price, unrealized_pnl FROM positions").fetchall()
        }
        risk = connection.execute(
            "SELECT exposure, margin_usage, realized_pnl, unrealized_pnl, drawdown FROM risk_state WHERE scope_id = 'account'"
        ).fetchone()
        funding = connection.execute("SELECT COALESCE(SUM(funding_fee), 0) FROM funding_ledger").fetchone()
        pnl = connection.execute(
            "SELECT COALESCE(SUM(realized_strategy_pnl), 0), COALESCE(SUM(unrealized_pnl), 0) FROM pnl_attribution"
        ).fetchone()
        equity = connection.execute(
            "SELECT equity, cash_balance FROM equity_snapshots ORDER BY equity_snapshot_id DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    return {
        "orders": orders,
        "fills": fills,
        "positions": positions,
        "risk": tuple(float(value or 0.0) for value in risk) if risk else None,
        "funding_fee": float(funding[0]) if funding else 0.0,
        "realized_pnl": float(pnl[0]) if pnl else 0.0,
        "unrealized_pnl": float(pnl[1]) if pnl else 0.0,
        "equity": float(equity[0]) if equity and equity[0] is not None else None,
        "cash_balance": float(equity[1]) if equity and equity[1] is not None else None,
    }


def _reconciliation_blockers(
    db_path: Path,
    local: dict[str, object],
    snapshot: GatewayStateSnapshot,
) -> list[str]:
    blockers: set[str] = set()
    local_orders: dict[str, dict[str, object]] = local["orders"]  # type: ignore[assignment]
    local_fills: dict[str, dict[str, object]] = local["fills"]  # type: ignore[assignment]
    local_positions: dict[str, dict[str, object]] = local["positions"]  # type: ignore[assignment]

    if snapshot.account.stale:
        blockers.add("stale_account_snapshot_detected")

    for order in snapshot.open_orders:
        local_order = local_orders.get(order.order_id_client)
        if local_order is None:
            blockers.add("orphan_order_detected")
            continue
        if not _close(float(local_order["filled_qty"]), order.filled_qty):
            blockers.add("filled_qty_mismatch")
        local_reduce_only = bool(local_order.get("metadata", {}).get("reduce_only", False))  # type: ignore[union-attr]
        if local_reduce_only != bool(order.reduce_only):
            blockers.add("reduce_only_mismatch")

    gateway_fill_ids = [str(fill.get("fill_id")) for fill in snapshot.fills if fill.get("fill_id")]
    if len(gateway_fill_ids) != len(set(gateway_fill_ids)):
        blockers.add("duplicate_fill_detected")
    for fill_id in gateway_fill_ids:
        if fill_id not in local_fills:
            blockers.add("missing_fill_detected")
    if _local_duplicate_fill_count(db_path) > 0:
        blockers.add("duplicate_fill_detected")

    for position in snapshot.positions:
        local_position = local_positions.get(position.symbol)
        if local_position is None or not _close(float(local_position["net_qty"]), position.net_qty):
            blockers.add("symbol_exposure_drift")
        elif position.entry_price is not None and local_position["entry_price"] is not None and not _close(
            float(local_position["entry_price"]), position.entry_price
        ):
            blockers.add("symbol_exposure_drift")

    local_risk = local.get("risk")
    if local_risk is None:
        if any(value is not None for value in (snapshot.account.exposure, snapshot.account.margin_usage, snapshot.account.realized_pnl, snapshot.account.unrealized_pnl)):
            blockers.add("risk_state_mismatch")
    else:
        exposure, margin_usage, realized_pnl, unrealized_pnl, _drawdown = local_risk  # type: ignore[misc]
        if snapshot.account.exposure is not None and not _close(exposure, snapshot.account.exposure):
            blockers.add("risk_state_mismatch")
        if snapshot.account.margin_usage is not None and not _close(margin_usage, snapshot.account.margin_usage):
            blockers.add("risk_state_mismatch")
        if snapshot.account.realized_pnl is not None and not _close(realized_pnl, snapshot.account.realized_pnl):
            blockers.add("risk_state_mismatch")
        if snapshot.account.unrealized_pnl is not None and not _close(unrealized_pnl, snapshot.account.unrealized_pnl):
            blockers.add("risk_state_mismatch")

    gateway_funding = sum(_float_or_zero(item.get("funding_fee")) for item in snapshot.funding if isinstance(item, dict))
    if not _close(float(local.get("funding_fee", 0.0)), gateway_funding):
        blockers.add("funding_mismatch")
    if snapshot.account.equity is not None and not _close(_optional_float(local.get("equity")), snapshot.account.equity):
        blockers.add("cash_equity_mismatch")
    if snapshot.account.cash_balance is not None and not _close(_optional_float(local.get("cash_balance")), snapshot.account.cash_balance):
        blockers.add("cash_equity_mismatch")
    if snapshot.account.realized_pnl is not None and not _close(float(local.get("realized_pnl", 0.0)), snapshot.account.realized_pnl):
        blockers.add("pnl_mismatch")
    if snapshot.account.unrealized_pnl is not None and not _close(float(local.get("unrealized_pnl", 0.0)), snapshot.account.unrealized_pnl):
        blockers.add("pnl_mismatch")

    return sorted(blockers)


def _safe_actions_for_blockers(blocker_codes: list[str]) -> list[str]:
    if not blocker_codes:
        return []
    return ["pause_artifact", "cancel_all", "flatten_all", "force_reconcile"]


def _journal_safe_actions(
    db_path: Path,
    safe_actions: list[str],
    *,
    operator_id: str,
    artifact_id: str,
    blocker_codes: list[str],
) -> list[dict[str, object]]:
    journal = []
    for action in safe_actions:
        result = apply_human_override(
            db_path,
            HumanOverrideRequest(
                action=action,  # type: ignore[arg-type]
                operator_id=operator_id,
                artifact_id=artifact_id if action in {"pause_artifact", "force_reconcile"} else None,
                confirmation=f"CONFIRM:{action}" if action in {"cancel_all", "flatten_all"} else None,
                reason="phase3_reconciliation_blocked",
                payload={"blocker_codes": blocker_codes, "source": "phase3_reconciliation"},
            ),
        )
        journal.append(
            {
                "override_event_id": result.override_event_id,
                "action": result.action,
                "status": "applied" if result.applied else "rejected",
                "reasons": list(result.reasons),
            }
        )
    return journal


def _local_duplicate_fill_count(db_path: Path) -> int:
    connection = connect_sqlite(db_path, read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT json_extract(metadata_json, '$.fill_id') AS fill_id, COUNT(*)
            FROM execution_events
            WHERE event_type IN ('FILL', 'ORDER_FILL', 'ORDER_PARTIAL_FILL')
            GROUP BY fill_id
            HAVING fill_id IS NOT NULL AND COUNT(*) > 1
            """
        ).fetchall()
    finally:
        connection.close()
    return len(rows)


def _phase3_projection_digest(connection: sqlite3.Connection) -> str:
    payload: dict[str, object] = {}
    stable_queries = {
        "orders_live": "SELECT * FROM orders_live ORDER BY order_id_client",
        "fills": "SELECT * FROM fills ORDER BY fill_id",
        "positions": "SELECT * FROM positions ORDER BY symbol",
        "risk_state": "SELECT * FROM risk_state ORDER BY scope_id",
        "fee_ledger": "SELECT ts_utc, run_id, symbol, order_id_client, fee_quote, fee_rate, maker_taker, metadata_json FROM fee_ledger ORDER BY ts_utc, symbol, order_id_client",
        "funding_ledger": "SELECT ts_utc, run_id, symbol, position_notional, funding_rate, funding_fee, metadata_json FROM funding_ledger ORDER BY ts_utc, symbol",
        "pnl_attribution": "SELECT ts_utc, run_id, symbol, realized_strategy_pnl, unrealized_pnl, fees, funding, slippage, transfers, cash_balance_delta, metadata_json FROM pnl_attribution ORDER BY ts_utc, symbol",
        "cash_ledger": "SELECT ts_utc, account_id, currency, amount, reason, reference_id, metadata_json FROM cash_ledger ORDER BY ts_utc, account_id, reference_id",
        "equity_snapshots": "SELECT ts_utc, account_id, equity, cash_balance, unrealized_pnl, realized_pnl, metadata_json FROM equity_snapshots ORDER BY ts_utc, account_id, equity",
        "position_snapshots": "SELECT * FROM position_snapshots ORDER BY position_snapshot_id",
    }
    for table_name, query in stable_queries.items():
        rows = connection.execute(query).fetchall()
        payload[table_name] = [tuple(row) for row in rows]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _load_json_dict(value: object) -> dict[str, object]:
    if not isinstance(value, str) or not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: object) -> float:
    number = _float_or_none(value)
    return 0.0 if number is None else number


def _optional_float(value: object) -> float | None:
    return value if isinstance(value, float) else _float_or_none(value)


def _close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs(float(left) - float(right)) <= EPSILON
