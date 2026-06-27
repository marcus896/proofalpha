from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from engine.execution.ledger import LedgerEvent
from engine.execution.state_projection import rebuild_state_projection


@dataclass(frozen=True)
class ReconciliationRepairPlan:
    status: str
    issues: list[str]
    repair_actions: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_reconciliation_repair_plan(
    events: list[LedgerEvent] | tuple[LedgerEvent, ...],
    *,
    gateway_fills: list[dict[str, Any]],
    gateway_positions: dict[str, float],
    gateway_cash_balance: float,
    local_cash_balance: float,
    stale_websocket: bool = False,
    clock_drift_seconds: int = 0,
) -> ReconciliationRepairPlan:
    issues: list[str] = []
    local_fill_ids = {
        str(event.payload.get("fill_id") or event.event_id)
        for event in events
        if event.event_type == "FILL"
    }
    for fill in gateway_fills:
        fill_id = str(fill.get("fill_id", ""))
        if fill_id and fill_id not in local_fill_ids:
            issues.append(f"missing_fill:{fill_id}")
    duplicates = detect_duplicate_fills([event.payload for event in events if event.event_type == "FILL"])
    issues.extend(f"duplicate_fill:{fill_id}" for fill_id in duplicates)
    projection = rebuild_state_projection(events)
    for symbol, gateway_qty in sorted(gateway_positions.items()):
        if abs(float(gateway_qty) - projection.positions.get(symbol, 0.0)) > 1e-9:
            issues.append(f"position_mismatch:{symbol}")
    if abs(float(gateway_cash_balance) - float(local_cash_balance)) > 1e-9:
        issues.append("balance_mismatch")
    if stale_websocket:
        issues.append("stale_websocket")
    if abs(int(clock_drift_seconds)) > 5:
        issues.append("clock_drift")
    actions = _repair_actions(issues)
    status = "PASS" if not issues else "REPAIR_REQUIRED"
    return ReconciliationRepairPlan(status=status, issues=issues, repair_actions=actions)


def reconciliation_allows_new_exposure(status: str, *, action: str) -> bool:
    if action in {"reduce", "close"}:
        return True
    return status == "PASS"


def detect_orphan_orders(*, local_order_ids: set[str], gateway_order_ids: set[str]) -> list[str]:
    return sorted(gateway_order_ids - local_order_ids)


def detect_duplicate_fills(fills: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for fill in fills:
        fill_id = str(fill.get("fill_id", ""))
        if not fill_id:
            continue
        if fill_id in seen:
            duplicates.add(fill_id)
        seen.add(fill_id)
    return sorted(duplicates)


def _repair_actions(issues: list[str]) -> list[str]:
    actions: list[str] = []
    for issue in issues:
        if issue.startswith("missing_fill:"):
            actions.append("ingest_missing_fill")
        elif issue.startswith("duplicate_fill:"):
            actions.append("dedupe_fill")
        elif issue.startswith("position_mismatch:"):
            actions.append("force_position_reconcile")
        elif issue == "balance_mismatch":
            actions.append("force_balance_reconcile")
        elif issue in {"stale_websocket", "clock_drift"}:
            actions.append("pause_new_exposure")
    return sorted(set(actions))
