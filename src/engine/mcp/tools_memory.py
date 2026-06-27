from __future__ import annotations

import json
from pathlib import Path

from engine.mcp.config import MCPSettings
from engine.memory.insights import build_memory_summary, select_memory_rows
from engine.memory.query import (
    query_agent_decisions,
    query_data_snapshots,
    query_meta_policies,
    query_resource_index,
    query_run_memory,
    query_run_resource_links,
    query_stress_runs,
    query_validation_runs,
)


def _resolve_output_artifact_path(
    path_raw: object,
    *,
    output_dir: Path,
    allowed_suffixes: tuple[str, ...] = (),
) -> tuple[Path | None, str | None]:
    if not isinstance(path_raw, str):
        return None, "path is required"
    candidate = Path(path_raw)
    if not candidate.is_absolute():
        candidate = output_dir / candidate
    try:
        resolved = candidate.resolve(strict=False)
        output_root = output_dir.resolve(strict=False)
    except OSError as exc:
        return None, str(exc)
    try:
        resolved.relative_to(output_root)
    except ValueError:
        return None, f"path must be inside output dir: {output_root}"
    if allowed_suffixes and not any(str(resolved).endswith(suffix) for suffix in allowed_suffixes):
        return None, f"path must end with one of: {', '.join(allowed_suffixes)}"
    if not resolved.exists():
        return None, f"file not found: {resolved}"
    return resolved, None


def tool_list_runs(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    limit = int(params.get("limit", settings.pagination_limit))
    decision = params.get("decision")
    symbol = params.get("symbol")
    venue = params.get("venue")
    rows = query_run_memory(
        db_path,
        decision=str(decision) if isinstance(decision, str) else None,
        symbol=str(symbol) if isinstance(symbol, str) else None,
        venue=str(venue) if isinstance(venue, str) else None,
        limit=limit,
    )
    return {"runs": rows, "count": len(rows)}


def tool_get_run(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    run_id = params.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return {"error": "run_id is required"}
    rows = query_run_memory(db_path, run_id=run_id, limit=1)
    if not rows:
        return {"error": f"run '{run_id}' not found in memory"}
    return rows[0]


def tool_list_batches(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    limit = int(params.get("limit", settings.pagination_limit))
    batch_paths = _find_batch_report_paths(output_dir)[:limit]
    batches = []
    for path in batch_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            batches.append({"run_id": payload.get("run_id"), "status": payload.get("status"), "path": str(path)})
        except Exception:
            batches.append({"path": str(path), "error": "unreadable"})
    return {"batches": batches, "count": len(batches)}


def tool_get_batch(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    path_raw = params.get("path")
    run_id = params.get("run_id")
    if isinstance(path_raw, str):
        path, error = _resolve_output_artifact_path(
            path_raw,
            output_dir=output_dir,
            allowed_suffixes=(".variant-batch.json", ".batch.json"),
        )
        if error:
            return {"error": error}
    elif isinstance(run_id, str):
        candidates = _find_batch_report_paths(output_dir, run_id=run_id)
        if not candidates:
            return {"error": f"batch not found for run_id '{run_id}'"}
        path = candidates[0]
    else:
        return {"error": "path or run_id is required"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def tool_list_campaigns(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    limit = int(params.get("limit", settings.pagination_limit))
    campaign_paths = sorted(output_dir.glob("*.campaign.json"))[:limit]
    campaigns = []
    for path in campaign_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            campaigns.append({"campaign_id": payload.get("campaign_id"), "status": payload.get("status"), "path": str(path)})
        except Exception:
            campaigns.append({"path": str(path), "error": "unreadable"})
    return {"campaigns": campaigns, "count": len(campaigns)}


def tool_get_campaign(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    path_raw = params.get("path")
    path, error = _resolve_output_artifact_path(
        path_raw,
        output_dir=output_dir,
        allowed_suffixes=(".campaign.json",),
    )
    if error:
        return {"error": error}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def tool_query_memory_summary(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    limit = int(params.get("limit", settings.pagination_limit))
    quality_policy = str(params.get("quality_policy", "clean-only"))
    symbol = params.get("symbol")
    venue = params.get("venue")
    all_rows = query_run_memory(
        db_path,
        symbol=str(symbol) if isinstance(symbol, str) else None,
        venue=str(venue) if isinstance(venue, str) else None,
        limit=None,
    )
    selected = select_memory_rows(all_rows, memory_quality_policy=quality_policy, limit=limit)
    summary = build_memory_summary(selected)
    return {
        "total_runs": summary.get("prior_runs", 0),
        "promoted_runs": summary.get("promoted_runs", 0),
        "blocked_runs": summary.get("blocked_runs", 0),
        "promising_layers": summary.get("promising_layers", []),
        "fragile_layers": summary.get("fragile_layers", []),
    }


def tool_query_validation_runs(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    rows = query_validation_runs(
        db_path,
        run_id=str(params.get("run_id")) if isinstance(params.get("run_id"), str) else None,
        validation_status=(
            str(params.get("validation_status")) if isinstance(params.get("validation_status"), str) else None
        ),
        min_deflated_sharpe_ratio=_float_param(params.get("min_deflated_sharpe_ratio")),
        max_pbo_score=_float_param(params.get("max_pbo_score")),
        limit=int(params.get("limit", settings.pagination_limit)),
    )
    return {"validation_runs": rows, "count": len(rows)}


def tool_query_stress_runs(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    passed_raw = params.get("passed")
    rows = query_stress_runs(
        db_path,
        run_id=str(params.get("run_id")) if isinstance(params.get("run_id"), str) else None,
        scenario_name=str(params.get("scenario_name")) if isinstance(params.get("scenario_name"), str) else None,
        passed=bool(passed_raw) if isinstance(passed_raw, bool) else None,
        target_regime=str(params.get("target_regime")) if isinstance(params.get("target_regime"), str) else None,
        limit=int(params.get("limit", settings.pagination_limit)),
    )
    return {"stress_runs": rows, "count": len(rows)}


def tool_query_agent_decisions(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    rows = query_agent_decisions(
        db_path,
        run_id=str(params.get("run_id")) if isinstance(params.get("run_id"), str) else None,
        decision_family=str(params.get("decision_family")) if isinstance(params.get("decision_family"), str) else None,
        decision=str(params.get("decision")) if isinstance(params.get("decision"), str) else None,
        validation_status=(
            str(params.get("validation_status")) if isinstance(params.get("validation_status"), str) else None
        ),
        limit=int(params.get("limit", settings.pagination_limit)),
    )
    return {"agent_decisions": rows, "count": len(rows)}


def tool_query_data_snapshots(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    rows = query_data_snapshots(
        db_path,
        snapshot_id=str(params.get("snapshot_id")) if isinstance(params.get("snapshot_id"), str) else None,
        symbol=str(params.get("symbol")) if isinstance(params.get("symbol"), str) else None,
        venue=str(params.get("venue")) if isinstance(params.get("venue"), str) else None,
        build_version=str(params.get("build_version")) if isinstance(params.get("build_version"), str) else None,
        source_hash=str(params.get("source_hash")) if isinstance(params.get("source_hash"), str) else None,
        quality_status=str(params.get("quality_status")) if isinstance(params.get("quality_status"), str) else None,
        limit=int(params.get("limit", settings.pagination_limit)),
    )
    return {"data_snapshots": rows, "count": len(rows)}


def tool_query_resource_index(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    rows = query_resource_index(
        db_path,
        resource_group=str(params.get("resource_group")) if isinstance(params.get("resource_group"), str) else None,
        status=str(params.get("status")) if isinstance(params.get("status"), str) else None,
        license=str(params.get("license")) if isinstance(params.get("license"), str) else None,
        intended_usage=str(params.get("intended_usage")) if isinstance(params.get("intended_usage"), str) else None,
        limit=int(params.get("limit", settings.pagination_limit)),
    )
    return {"resource_index": rows, "count": len(rows)}


def tool_query_run_resource_links(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    rows = query_run_resource_links(
        db_path,
        run_id=str(params.get("run_id")) if isinstance(params.get("run_id"), str) else None,
        resource_id=str(params.get("resource_id")) if isinstance(params.get("resource_id"), str) else None,
        link_role=str(params.get("link_role")) if isinstance(params.get("link_role"), str) else None,
        evidence_source=str(params.get("evidence_source")) if isinstance(params.get("evidence_source"), str) else None,
        limit=int(params.get("limit", settings.pagination_limit)),
    )
    return {"run_resource_links": rows, "count": len(rows)}


def tool_query_meta_policies(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    rows = query_meta_policies(
        db_path,
        run_id=str(params.get("run_id")) if isinstance(params.get("run_id"), str) else None,
        policy_family=str(params.get("policy_family")) if isinstance(params.get("policy_family"), str) else None,
        status=str(params.get("status")) if isinstance(params.get("status"), str) else None,
        eval_validation_run_id=(
            str(params.get("eval_validation_run_id"))
            if isinstance(params.get("eval_validation_run_id"), str)
            else None
        ),
        limit=int(params.get("limit", settings.pagination_limit)),
    )
    return {"meta_policies": rows, "count": len(rows)}


MEMORY_TOOL_CATALOG: list[dict[str, object]] = [
    {
        "name": "list_runs",
        "description": "List research runs from the memory database. Supports filtering by decision and symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "description": "Filter by decision: 'accept' or 'reject'"},
                "symbol": {"type": "string", "description": "Filter by market symbol (e.g. 'BTCUSDT')"},
                "venue": {"type": "string", "description": "Filter by venue (e.g. 'binance')"},
                "limit": {"type": "integer", "description": "Max number of results"},
            },
        },
    },
    {
        "name": "get_run",
        "description": "Retrieve a single research run record by run_id.",
        "parameters": {
            "type": "object",
            "required": ["run_id"],
            "properties": {"run_id": {"type": "string", "description": "The run identifier"}},
        },
    },
    {
        "name": "list_batches",
        "description": "List batch autoresearch report files in the output directory.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "get_batch",
        "description": "Read a batch autoresearch report by file path or run_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "run_id": {"type": "string"},
            },
        },
    },
    {
        "name": "list_campaigns",
        "description": "List campaign report files in the output directory.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "get_campaign",
        "description": "Read a campaign report by file path.",
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
    },
    {
        "name": "query_memory_summary",
        "description": "Build an aggregate memory summary (total runs, promoted, blocked, top layer profiles).",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "quality_policy": {"type": "string", "description": "clean-only or all"},
                "symbol": {"type": "string", "description": "Filter by market symbol (e.g. 'BTCUSDT')"},
                "venue": {"type": "string", "description": "Filter by venue (e.g. 'binance')"},
            },
        },
    },
    {
        "name": "query_validation_runs",
        "description": "Query first-class validation lineage rows from research memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "validation_status": {"type": "string"},
                "min_deflated_sharpe_ratio": {"type": "number"},
                "max_pbo_score": {"type": "number"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_stress_runs",
        "description": "Query first-class stress lineage rows from research memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "scenario_name": {"type": "string"},
                "passed": {"type": "boolean"},
                "target_regime": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_agent_decisions",
        "description": "Query first-class agent decision lineage rows from research memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "decision_family": {"type": "string"},
                "decision": {"type": "string"},
                "validation_status": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_data_snapshots",
        "description": "Query first-class snapshot lineage rows from research memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "snapshot_id": {"type": "string"},
                "symbol": {"type": "string"},
                "venue": {"type": "string"},
                "build_version": {"type": "string"},
                "source_hash": {"type": "string"},
                "quality_status": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_resource_index",
        "description": "Query first-class resource provenance catalog rows from research memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "resource_group": {"type": "string"},
                "status": {"type": "string"},
                "license": {"type": "string"},
                "intended_usage": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_run_resource_links",
        "description": "Query explicit per-run resource provenance links from research memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "resource_id": {"type": "string"},
                "link_role": {"type": "string"},
                "evidence_source": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_meta_policies",
        "description": "Query first-class meta-policy lineage rows from research memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "policy_family": {"type": "string"},
                "status": {"type": "string"},
                "eval_validation_run_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
]


def _find_batch_report_paths(output_dir: Path, run_id: str | None = None) -> list[Path]:
    patterns = (
        [f"{run_id}.variant-batch.json", f"{run_id}.batch.json"]
        if isinstance(run_id, str)
        else ["*.variant-batch.json", "*.batch.json"]
    )
    seen: set[Path] = set()
    paths: list[Path] = []
    for pattern in patterns:
        for path in sorted(output_dir.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
    return paths


def _float_param(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
