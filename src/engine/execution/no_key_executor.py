from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from engine.io.artifacts import write_json_atomic
from engine.memory.store import append_execution_event, initialize_memory_db, rebuild_execution_projections


SOURCE = "phase2_no_key_fake_gateway"
ARTIFACT_TYPE = "phase2_no_key_executor_chaos_report"


@dataclass(frozen=True)
class NoKeyExecutorConfig:
    db_path: Path
    scenario_id: str = "normal"
    session_id: str = "phase2-no-key"
    base_timestamp: str = "2026-04-30T00:00:00Z"
    allow_live_private_path: bool = False


@dataclass(frozen=True)
class NoKeyOrderRequest:
    symbol: str
    side: str
    qty: float
    price: float
    client_order_id: str
    reduce_only: bool = False


class FakeBinancePrivateGateway:
    def __init__(self, *, exchange_order_seed: int = 1000) -> None:
        self._exchange_order_id = int(exchange_order_seed)
        self.orders: dict[str, dict[str, object]] = {}
        self.orphan_orders: dict[str, dict[str, object]] = {}
        self.clock_drift_seconds = 0
        self.network_partitioned = False
        self.error_storm = False
        self.stale_account_snapshot = False

    def submit_order(self, request: NoKeyOrderRequest, *, reject_reason: str | None = None) -> dict[str, object]:
        if reject_reason:
            return {
                "event_type": "ORDER_REJECT",
                "status": "REJECTED",
                "reason_code": reject_reason,
                "order_id_client": request.client_order_id,
            }
        self._exchange_order_id += 1
        order = {
            "order_id_client": request.client_order_id,
            "order_id_exchange": f"fake-{self._exchange_order_id}",
            "symbol": request.symbol,
            "side": request.side.upper(),
            "qty": float(request.qty),
            "price": float(request.price),
            "status": "ACKED",
        }
        self.orders[request.client_order_id] = order
        return order

    def fill_order(
        self,
        request: NoKeyOrderRequest,
        *,
        qty: float,
        fill_id: str,
        status: str = "PARTIALLY_FILLED",
    ) -> dict[str, object]:
        order = self.orders.get(request.client_order_id, {})
        return {
            "order_id_exchange": order.get("order_id_exchange"),
            "fill_id": fill_id,
            "qty": float(qty),
            "price": float(request.price),
            "status": status,
            "fee": round(abs(float(qty)) * float(request.price) * 0.0005, 12),
            "maker_taker": "TAKER",
            "liquidity_flag": "taker",
        }

    def cancel_order(self, request: NoKeyOrderRequest, *, reject_reason: str | None = None) -> dict[str, object]:
        order = self.orders.get(request.client_order_id, {})
        if reject_reason:
            return {
                "event_type": "ORDER_CANCEL_REJECT",
                "status": "CANCEL_REJECTED",
                "reason_code": reject_reason,
                "order_id_exchange": order.get("order_id_exchange"),
            }
        order["status"] = "CANCELED"
        return {
            "event_type": "ORDER_CANCEL_ACK",
            "status": "CANCELED",
            "order_id_exchange": order.get("order_id_exchange"),
        }

    def inject_orphan_order(self, request: NoKeyOrderRequest) -> dict[str, object]:
        self._exchange_order_id += 1
        order = {
            "order_id_client": f"{request.client_order_id}-orphan",
            "order_id_exchange": f"fake-{self._exchange_order_id}",
            "symbol": request.symbol,
            "side": request.side.upper(),
            "qty": float(request.qty),
            "price": float(request.price),
            "status": "ACKED",
        }
        self.orphan_orders[str(order["order_id_client"])] = order
        return order

    def account_snapshot(self) -> dict[str, object]:
        return {
            "stale": self.stale_account_snapshot,
            "clock_drift_seconds": self.clock_drift_seconds,
            "open_order_count": len(self.orders) + len(self.orphan_orders),
            "network_partitioned": self.network_partitioned,
            "error_storm": self.error_storm,
        }


def run_no_key_executor_fixture(
    config: NoKeyExecutorConfig,
    *,
    order_requests: list[NoKeyOrderRequest],
) -> dict[str, object]:
    _assert_no_live_private_path(config)
    initialize_memory_db(config.db_path)
    gateway = FakeBinancePrivateGateway()
    event_types: list[str] = []
    blocker_codes: list[str] = []

    _append(config, event_types, "ENGINE_START", status="STARTED", metadata={"scenario_id": config.scenario_id})
    for request in order_requests:
        _record_order_lifecycle(config, gateway, request, event_types, blocker_codes)
    _append(config, event_types, "POSITION_RECONCILE", status="RECONCILED", metadata=gateway.account_snapshot())
    _append(config, event_types, "ENGINE_STOP", status="STOPPED", metadata={"scenario_id": config.scenario_id})

    projection = _rebuild_twice(config.db_path)
    return {
        "artifact_type": ARTIFACT_TYPE,
        "status": "completed",
        "scenario_id": config.scenario_id,
        "session_id": config.session_id,
        "private_keys_required": False,
        "live_order_path_enabled": False,
        "event_types": event_types,
        "blocker_codes": blocker_codes,
        "safe_actions": [],
        "projection": projection,
    }


def run_single_chaos_scenario(
    config: NoKeyExecutorConfig,
    *,
    order_request: NoKeyOrderRequest,
    scenario_id: str | None = None,
) -> dict[str, object]:
    scenario = scenario_id or config.scenario_id
    scenario_config = replace(config, scenario_id=scenario)
    _assert_no_live_private_path(scenario_config)
    _reset_db(scenario_config.db_path)
    initialize_memory_db(scenario_config.db_path)
    gateway = FakeBinancePrivateGateway()
    event_types: list[str] = []
    blocker_codes: list[str] = []
    safe_actions: list[str] = []

    _append(scenario_config, event_types, "ENGINE_START", status="STARTED", metadata={"scenario_id": scenario})

    if scenario == "normal":
        _record_order_lifecycle(scenario_config, gateway, order_request, event_types, blocker_codes)
    elif scenario == "mid_order_crash":
        _append_submit(scenario_config, event_types, order_request)
        _append(scenario_config, event_types, "ENGINE_STOP", status="CRASHED", reason_code="mid_order_crash")
        _append(scenario_config, event_types, "ENGINE_RECOVER_REPLAY", status="RECOVERED")
        _append_ack_and_fill(scenario_config, gateway, order_request, event_types, qty=order_request.qty, status="FILLED")
    elif scenario == "partial_fill_restart":
        _append_submit(scenario_config, event_types, order_request)
        _append_ack_and_fill(
            scenario_config,
            gateway,
            order_request,
            event_types,
            qty=order_request.qty / 2.0,
            status="PARTIALLY_FILLED",
        )
        _append(scenario_config, event_types, "ENGINE_RECOVER_REPLAY", status="RECOVERED")
        _append_fill(scenario_config, gateway, order_request, event_types, qty=order_request.qty / 2.0, fill_ordinal=2, status="FILLED")
    elif scenario == "duplicate_fill":
        _append_submit(scenario_config, event_types, order_request)
        _append_ack(scenario_config, gateway, order_request, event_types)
        fill_id = f"{order_request.client_order_id}:fill:duplicate"
        _append_fill(scenario_config, gateway, order_request, event_types, qty=order_request.qty, fill_id=fill_id, status="FILLED")
        _append_fill(scenario_config, gateway, order_request, event_types, qty=order_request.qty, fill_id=fill_id, status="FILLED")
        blocker_codes.append("duplicate_fill_ignored")
    elif scenario == "orphan_order":
        orphan = gateway.inject_orphan_order(order_request)
        _append_order_event(scenario_config, event_types, "ORDER_ACK", orphan, reason_code="orphan_exchange_order")
        blocker_codes.append("orphan_order_detected")
        safe_actions.append("cancel_all_simulated")
    elif scenario == "stale_websocket":
        gateway.stale_account_snapshot = True
        _append_submit(scenario_config, event_types, order_request)
        _append_ack(scenario_config, gateway, order_request, event_types)
        _append(scenario_config, event_types, "ACCOUNT_SNAPSHOT", status="STALE", reason_code="stale_account_snapshot", metadata=gateway.account_snapshot())
        _append(scenario_config, event_types, "RISK_BLOCK", status="BLOCKED", reason_code="stale_websocket")
        blocker_codes.append("stale_websocket_detected")
    elif scenario == "network_partition":
        gateway.network_partitioned = True
        _append_submit(scenario_config, event_types, order_request)
        _append(scenario_config, event_types, "ORDER_REJECT", symbol=order_request.symbol, side=order_request.side, order_id_client=order_request.client_order_id, qty=order_request.qty, price=order_request.price, status="REJECTED", reason_code="network_partition")
        _append(scenario_config, event_types, "KILL_SWITCH_TRIGGER", status="TRIGGERED", reason_code="network_partition")
        blocker_codes.append("network_partition_detected")
        safe_actions.append("kill_switch_simulated")
    elif scenario == "clock_drift":
        gateway.clock_drift_seconds = 42
        _append(scenario_config, event_types, "ACCOUNT_SNAPSHOT", status="CLOCK_DRIFT", reason_code="clock_drift", metadata=gateway.account_snapshot())
        _append(scenario_config, event_types, "RISK_BLOCK", status="BLOCKED", reason_code="clock_drift")
        blocker_codes.append("clock_drift_detected")
    elif scenario == "reduce_only_reject":
        reject = gateway.submit_order(order_request, reject_reason="reduce_only_reject")
        _append_submit(scenario_config, event_types, order_request)
        _append(scenario_config, event_types, "ORDER_REJECT", symbol=order_request.symbol, side=order_request.side, order_id_client=order_request.client_order_id, qty=order_request.qty, price=order_request.price, status=str(reject["status"]), reason_code=str(reject["reason_code"]))
        blocker_codes.append("reduce_only_reject")
    elif scenario == "exchange_error_storm":
        gateway.error_storm = True
        for ordinal in range(3):
            _append(scenario_config, event_types, "ORDER_REJECT", symbol=order_request.symbol, side=order_request.side, order_id_client=f"{order_request.client_order_id}-err-{ordinal}", qty=order_request.qty, price=order_request.price, status="REJECTED", reason_code="exchange_error_storm")
        _append(scenario_config, event_types, "KILL_SWITCH_TRIGGER", status="TRIGGERED", reason_code="exchange_error_storm")
        blocker_codes.append("exchange_error_storm")
        safe_actions.append("kill_switch_simulated")
    elif scenario == "disk_full":
        _append(scenario_config, event_types, "RISK_BLOCK", status="BLOCKED", reason_code="disk_full_simulated")
        blocker_codes.append("disk_full_simulated")
        safe_actions.append("engine_pause_simulated")
    elif scenario == "db_lock_retry":
        _append(scenario_config, event_types, "RISK_BLOCK", status="RETRY", reason_code="db_lock_retry")
        blocker_codes.append("db_lock_retry")
    elif scenario == "corrupted_projection":
        _record_order_lifecycle(scenario_config, gateway, order_request, event_types, blocker_codes)
        _append(scenario_config, event_types, "ENGINE_RECOVER_REPLAY", status="RECOVERED", reason_code="corrupted_projection")
        blocker_codes.append("corrupted_projection_rebuilt")
    else:
        raise ValueError(f"unknown chaos scenario: {scenario}")

    _append(scenario_config, event_types, "POSITION_RECONCILE", status="RECONCILED", metadata=gateway.account_snapshot())
    if "cancel_all_simulated" not in safe_actions and scenario in {"stale_websocket", "disk_full", "db_lock_retry"}:
        safe_actions.append("cancel_all_simulated")
    _append(scenario_config, event_types, "ENGINE_STOP", status="STOPPED", metadata={"scenario_id": scenario})

    projection = _rebuild_twice(scenario_config.db_path)
    return {
        "artifact_type": ARTIFACT_TYPE,
        "status": "completed",
        "scenario_id": scenario,
        "session_id": scenario_config.session_id,
        "private_keys_required": False,
        "live_order_path_enabled": False,
        "event_types": event_types,
        "blocker_codes": sorted(set(blocker_codes)),
        "safe_actions": sorted(set(safe_actions)),
        "projection": projection,
        "replay_deterministic": bool(projection["replay_deterministic"]),
    }


def run_phase2_chaos_replay(
    config: NoKeyExecutorConfig,
    *,
    order_request: NoKeyOrderRequest,
) -> dict[str, object]:
    scenarios = [
        "mid_order_crash",
        "stale_websocket",
        "duplicate_fill",
        "orphan_order",
        "partial_fill_restart",
        "corrupted_projection",
        "disk_full",
        "db_lock_retry",
        "network_partition",
        "clock_drift",
        "reduce_only_reject",
        "exchange_error_storm",
    ]
    reports = []
    safe_actions: set[str] = set()
    for scenario in scenarios:
        scenario_db = _scenario_db_path(config.db_path, scenario)
        report = run_single_chaos_scenario(
            replace(config, db_path=scenario_db, scenario_id=scenario),
            order_request=replace(order_request, client_order_id=f"{order_request.client_order_id}-{scenario}"),
        )
        reports.append(report)
        safe_actions.update(str(action) for action in report.get("safe_actions", []))
    safe_actions.update({"cancel_all_simulated", "kill_switch_simulated"})
    return {
        "artifact_type": ARTIFACT_TYPE,
        "status": "completed",
        "scenario_id": config.scenario_id,
        "session_id": config.session_id,
        "private_keys_required": False,
        "live_order_path_enabled": False,
        "scenarios": reports,
        "safe_actions": sorted(safe_actions),
    }


def write_no_key_executor_report(path: Path, report: dict[str, object]) -> Path:
    return write_json_atomic(path, report)


def _record_order_lifecycle(
    config: NoKeyExecutorConfig,
    gateway: FakeBinancePrivateGateway,
    request: NoKeyOrderRequest,
    event_types: list[str],
    blocker_codes: list[str],
) -> None:
    if request.reduce_only and request.side.upper() == "BUY":
        blocker_codes.append("reduce_only_reject")
        _append_submit(config, event_types, request)
        _append(config, event_types, "ORDER_REJECT", symbol=request.symbol, side=request.side, order_id_client=request.client_order_id, qty=request.qty, price=request.price, status="REJECTED", reason_code="reduce_only_reject")
        return
    _append_submit(config, event_types, request)
    _append_ack_and_fill(config, gateway, request, event_types, qty=request.qty, status="FILLED")


def _append_ack_and_fill(
    config: NoKeyExecutorConfig,
    gateway: FakeBinancePrivateGateway,
    request: NoKeyOrderRequest,
    event_types: list[str],
    *,
    qty: float,
    status: str,
) -> None:
    _append_ack(config, gateway, request, event_types)
    _append_fill(config, gateway, request, event_types, qty=qty, status=status)


def _append_submit(config: NoKeyExecutorConfig, event_types: list[str], request: NoKeyOrderRequest) -> None:
    _append(
        config,
        event_types,
        "ORDER_SUBMIT",
        symbol=request.symbol,
        side=request.side.upper(),
        order_id_client=request.client_order_id,
        qty=request.qty,
        price=request.price,
        status="SUBMITTED",
        metadata={"private_keys_required": False, "live_order_path_enabled": False},
    )


def _append_ack(
    config: NoKeyExecutorConfig,
    gateway: FakeBinancePrivateGateway,
    request: NoKeyOrderRequest,
    event_types: list[str],
) -> None:
    order = gateway.submit_order(request)
    _append_order_event(config, event_types, "ORDER_ACK", order)


def _append_fill(
    config: NoKeyExecutorConfig,
    gateway: FakeBinancePrivateGateway,
    request: NoKeyOrderRequest,
    event_types: list[str],
    *,
    qty: float,
    status: str,
    fill_id: str | None = None,
    fill_ordinal: int = 1,
) -> None:
    fill = gateway.fill_order(
        request,
        qty=qty,
        fill_id=fill_id or f"{request.client_order_id}:fill:{fill_ordinal}",
        status=status,
    )
    _append(
        config,
        event_types,
        "FILL",
        symbol=request.symbol,
        side=request.side.upper(),
        order_id_client=request.client_order_id,
        order_id_exchange=str(fill.get("order_id_exchange")) if fill.get("order_id_exchange") else None,
        qty=float(fill["qty"]),
        price=float(fill["price"]),
        status=status,
        metadata={
            "fill_id": fill["fill_id"],
            "fee": fill["fee"],
            "maker_taker": fill["maker_taker"],
            "liquidity_flag": fill["liquidity_flag"],
        },
    )


def _append_order_event(
    config: NoKeyExecutorConfig,
    event_types: list[str],
    event_type: str,
    order: dict[str, object],
    *,
    reason_code: str | None = None,
) -> None:
    _append(
        config,
        event_types,
        event_type,
        symbol=str(order.get("symbol")) if order.get("symbol") else None,
        side=str(order.get("side")) if order.get("side") else None,
        order_id_client=str(order.get("order_id_client")) if order.get("order_id_client") else None,
        order_id_exchange=str(order.get("order_id_exchange")) if order.get("order_id_exchange") else None,
        qty=float(order["qty"]) if order.get("qty") is not None else None,
        price=float(order["price"]) if order.get("price") is not None else None,
        status=str(order.get("status")) if order.get("status") else None,
        reason_code=reason_code,
        metadata={"gateway": "fake_binance_usdm_private"},
    )


def _append(
    config: NoKeyExecutorConfig,
    event_types: list[str],
    event_type: str,
    *,
    symbol: str | None = None,
    side: str | None = None,
    order_id_client: str | None = None,
    order_id_exchange: str | None = None,
    qty: float | None = None,
    price: float | None = None,
    status: str | None = None,
    reason_code: str | None = None,
    metadata: dict[str, object] | None = None,
) -> int:
    event_types.append(event_type)
    return append_execution_event(
        config.db_path,
        ts_exchange=config.base_timestamp,
        ts_gateway=config.base_timestamp,
        ts_engine=config.base_timestamp,
        source=SOURCE,
        event_type=event_type,
        symbol=symbol,
        side=side,
        order_id_client=order_id_client,
        order_id_exchange=order_id_exchange,
        qty=qty,
        price=price,
        status=status,
        reason_code=reason_code,
        metadata={
            "session_id": config.session_id,
            "scenario_id": config.scenario_id,
            "private_keys_required": False,
            "live_order_path_enabled": False,
            **(metadata or {}),
        },
    )


def _rebuild_twice(db_path: Path) -> dict[str, object]:
    first = rebuild_execution_projections(db_path)
    second = rebuild_execution_projections(db_path)
    return {
        **second,
        "first_projection_digest": first["projection_digest"],
        "second_projection_digest": second["projection_digest"],
        "replay_deterministic": first["projection_digest"] == second["projection_digest"],
    }


def _scenario_db_path(db_path: Path, scenario_id: str) -> Path:
    stem = db_path.stem or "phase2"
    return db_path.with_name(f"{stem}-{scenario_id}{db_path.suffix or '.sqlite'}")


def _reset_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    wal = Path(f"{db_path}-wal")
    shm = Path(f"{db_path}-shm")
    for path in (wal, shm):
        if path.exists():
            path.unlink()
    if db_path.parent.exists() and db_path.parent.is_dir():
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _assert_no_live_private_path(config: NoKeyExecutorConfig) -> None:
    if config.allow_live_private_path:
        raise ValueError("phase2_no_key_executor_forbids_live_private_path")
