from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterable, Mapping

from engine.io.artifacts import write_json_atomic


Timer = Callable[[], float]
ProfilingCallable = Callable[[], Mapping[str, object] | None]


@dataclass(frozen=True)
class LocalProfilingTask:
    task_id: str
    run: ProfilingCallable
    subsystem: str | None = None


def run_local_profiling_harness(
    tasks: Iterable[LocalProfilingTask],
    *,
    timer: Timer = perf_counter,
    profile_id: str = "optimization_phase_7_local_profile",
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    sql_events: list[dict[str, object]] = []

    for task in tasks:
        start = timer()
        try:
            raw_payload = task.run() or {}
            status = str(raw_payload.get("status", "ok"))
            error = None
        except Exception as exc:  # pragma: no cover - defensive report path.
            raw_payload = {}
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = round(max(0.0, timer() - start) * 1000.0, 6)
        task_sql_events = _normalize_sql_events(
            raw_payload.get("sql_events") if isinstance(raw_payload, Mapping) else None,
            task_id=task.task_id,
            subsystem=task.subsystem,
        )
        sql_events.extend(task_sql_events)
        row: dict[str, object] = {
            "task_id": task.task_id,
            "subsystem": task.subsystem or task.task_id,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "sql_event_count": len(task_sql_events),
        }
        if error is not None:
            row["error"] = error
        results.append(row)

    runtime_hotspots = sorted(results, key=lambda row: float(row["elapsed_ms"]), reverse=True)
    sql_hotspots = sorted(sql_events, key=lambda row: float(row["elapsed_ms"]), reverse=True)
    status = "completed" if all(row["status"] == "ok" for row in results) else "completed_with_errors"
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "created_at_utc": datetime.now(tz=UTC).isoformat(),
        "status": status,
        "task_count": len(results),
        "results": results,
        "top_runtime_hotspots": runtime_hotspots[:10],
        "top_sql_hotspots": sql_hotspots[:10],
    }


def build_fixture_profiling_tasks() -> list[LocalProfilingTask]:
    return [
        LocalProfilingTask("autoresearch_fixture", _profile_autoresearch_fixture, "autoresearch"),
        LocalProfilingTask("memory_ingest_query_fixture", _profile_memory_fixture, "memory"),
        LocalProfilingTask("batch_simulator_fixture", _profile_batch_simulator_fixture, "batch_simulator"),
        LocalProfilingTask("paper_ws_collector_fixture", _profile_paper_ws_fixture, "paper_ws_collector"),
        LocalProfilingTask("data_fetch_retry_manifest_fixture", _profile_data_fetch_fixture, "data_fetch"),
    ]


def write_local_profile_report(path: Path | str, report: Mapping[str, object]) -> Path:
    return write_json_atomic(Path(path), dict(report))


def _normalize_sql_events(raw_events: object, *, task_id: str, subsystem: str | None) -> list[dict[str, object]]:
    if not isinstance(raw_events, list):
        return []
    events: list[dict[str, object]] = []
    for index, raw_event in enumerate(raw_events):
        if not isinstance(raw_event, Mapping):
            continue
        elapsed = _float_or_zero(raw_event.get("elapsed_ms"))
        events.append(
            {
                "task_id": task_id,
                "subsystem": subsystem or task_id,
                "operation": str(raw_event.get("operation", f"sql_event_{index}")),
                "elapsed_ms": round(elapsed, 6),
                "rows": int(_float_or_zero(raw_event.get("rows"))),
            }
        )
    return events


def _float_or_zero(value: object) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _profile_autoresearch_fixture() -> dict[str, object]:
    variants = [{"variant_id": f"v{i}", "score": i % 3} for i in range(32)]
    selected = sorted(variants, key=lambda row: row["score"], reverse=True)[:4]
    return {"status": "ok", "selected_variant_count": len(selected), "sql_events": []}


def _profile_memory_fixture() -> dict[str, object]:
    rows = [{"run_id": f"run-{i}", "sharpe": i / 10.0} for i in range(24)]
    filtered = [row for row in rows if row["sharpe"] >= 1.0]
    return {
        "status": "ok",
        "row_count": len(filtered),
        "sql_events": [
            {"operation": "memory.insert_fixture_rows", "elapsed_ms": 2.5, "rows": len(rows)},
            {"operation": "memory.query_candidate_rows", "elapsed_ms": 4.0, "rows": len(filtered)},
        ],
    }


def _profile_batch_simulator_fixture() -> dict[str, object]:
    equity = 10_000.0
    for step in range(128):
        equity *= 1.0 + ((step % 7) - 3) / 100_000.0
    return {"status": "ok", "ending_equity": round(equity, 6), "sql_events": []}


def _profile_paper_ws_fixture() -> dict[str, object]:
    events = [{"sequence": i, "bid": 100.0 + i, "ask": 100.5 + i} for i in range(16)]
    spread_sum = sum(event["ask"] - event["bid"] for event in events)
    return {"status": "ok", "event_count": len(events), "spread_sum": spread_sum, "sql_events": []}


def _profile_data_fetch_fixture() -> dict[str, object]:
    manifest = {
        "provider": "fixture",
        "retry_metadata": [
            {"attempt": 1, "status": "rate_limited", "backoff_seconds": 2.0},
            {"attempt": 2, "status": "ok", "backoff_seconds": 0.0},
        ],
    }
    return {
        "status": "ok",
        "retry_event_count": len(manifest["retry_metadata"]),
        "sql_events": [
            {"operation": "fetch_manifest.load_previous", "elapsed_ms": 1.0, "rows": 1},
        ],
    }
