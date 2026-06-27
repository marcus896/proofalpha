from __future__ import annotations

import json
from pathlib import Path

from engine.mcp.config import MCPSettings
from engine.reporting.compare import (
    compare_dashboard_payloads,
    compare_runcards,
    format_compare_payload,
)
from engine.reporting.summary import (
    build_dashboard_summary,
)


def _load_json(
    path_raw: object,
    *,
    output_dir: Path,
    allowed_suffixes: tuple[str, ...] = (".dashboard.json",),
) -> tuple[dict[str, object] | None, str | None]:
    if not isinstance(path_raw, str):
        return None, "path is required"
    candidate = Path(path_raw)
    if not candidate.is_absolute():
        candidate = output_dir / candidate
    try:
        p = candidate.resolve(strict=False)
        output_root = output_dir.resolve(strict=False)
    except OSError as exc:
        return None, str(exc)
    try:
        p.relative_to(output_root)
    except ValueError:
        return None, f"path must be inside output dir: {output_root}"
    if allowed_suffixes and not any(str(p).endswith(suffix) for suffix in allowed_suffixes):
        return None, f"path must end with one of: {', '.join(allowed_suffixes)}"
    if not p.exists():
        return None, f"file not found: {p}"
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, str(exc)


def tool_summarize_run(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    payload, error = _load_json(params.get("path"), output_dir=output_dir)
    if error:
        return {"error": error}
    try:
        summary = build_dashboard_summary(payload)
        return {"summary": summary}
    except Exception as exc:
        return {"error": str(exc)}


def tool_compare_runs(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    left_payload, error_l = _load_json(params.get("left_path"), output_dir=output_dir)
    right_payload, error_r = _load_json(params.get("right_path"), output_dir=output_dir)
    if error_l:
        return {"error": f"left_path: {error_l}"}
    if error_r:
        return {"error": f"right_path: {error_r}"}

    fmt = str(params.get("fmt", "text"))
    try:
        comparison = compare_dashboard_payloads(left_payload, right_payload)
        if fmt == "json":
            return comparison
        return {"comparison": format_compare_payload(comparison)}
    except Exception as exc:
        return {"error": str(exc)}


def tool_list_artifacts(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    limit = int(params.get("limit", settings.pagination_limit))
    suffix = str(params.get("suffix", ".dashboard.json"))
    matched = sorted(output_dir.rglob(f"*{suffix}"))[:limit]
    return {
        "artifacts": [str(p) for p in matched],
        "count": len(matched),
    }


REPORTING_TOOL_CATALOG: list[dict[str, object]] = [
    {
        "name": "summarize_run",
        "description": "Build a human-readable summary of a single research run dashboard artifact.",
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string", "description": "Absolute path to a dashboard JSON file"}},
        },
    },
    {
        "name": "compare_runs",
        "description": "Compare two research run dashboard artifacts and return metric deltas and layer changes.",
        "parameters": {
            "type": "object",
            "required": ["left_path", "right_path"],
            "properties": {
                "left_path": {"type": "string"},
                "right_path": {"type": "string"},
                "fmt": {"type": "string", "description": "Output format: 'text' (default) or 'json'"},
            },
        },
    },
    {
        "name": "list_artifacts",
        "description": "List artifact files in the output directory matching an optional suffix pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "suffix": {"type": "string", "description": "File suffix to match, e.g. '.dashboard.json'"},
            },
        },
    },
]
