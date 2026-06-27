from __future__ import annotations

import json
from pathlib import Path

from engine.mcp.config import MCPSettings
from engine.validation.bundle import compare_validation_bundles, normalize_validation_bundle


def _load_dashboard(
    path_raw: object,
    *,
    output_dir: Path,
) -> tuple[dict[str, object] | None, str | None]:
    if not isinstance(path_raw, str):
        return None, "path is required"
    candidate = Path(path_raw)
    if not candidate.is_absolute():
        candidate = output_dir / candidate
    try:
        path = candidate.resolve(strict=False)
        output_root = output_dir.resolve(strict=False)
    except OSError as exc:
        return None, str(exc)
    try:
        path.relative_to(output_root)
    except ValueError:
        return None, f"path must be inside output dir: {output_root}"
    if not str(path).endswith(".dashboard.json"):
        return None, "path must end with: .dashboard.json"
    if not path.exists():
        return None, f"file not found: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, str(exc)


def tool_get_validation_protocol(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    payload, error = _load_dashboard(params.get("path"), output_dir=output_dir)
    if error:
        return {"error": error}
    protocol = payload.get("validation_protocol", {})
    if not isinstance(protocol, dict) or not protocol:
        return {"status": "legacy_validation_missing", "note": "no validation protocol in artifact"}
    result = dict(protocol)
    result["validation_bundle"] = normalize_validation_bundle(protocol)
    return result


def tool_get_regime_coverage(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    payload, error = _load_dashboard(params.get("path"), output_dir=output_dir)
    if error:
        return {"error": error}
    return {
        "regime_scenario_pass_matrix": payload.get("regime_scenario_pass_matrix", {}),
        "regime_labels": payload.get("regime_labels", []),
        "regime_coverage": payload.get("regime_coverage", {}),
        "crisis_window_coverage": payload.get("crisis_window_coverage", {}),
    }


def tool_get_scenario_matrix(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    payload, error = _load_dashboard(params.get("path"), output_dir=output_dir)
    if error:
        return {"error": error}
    return {
        "scenarios": payload.get("scenarios", []),
        "stress_liquidity_metrics": payload.get("stress_liquidity_metrics", {}),
        "scenario_profiles": payload.get("scenario_profiles", {}),
    }


def tool_compare_validation_results(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    payload_a, error_a = _load_dashboard(params.get("path_a"), output_dir=output_dir)
    payload_b, error_b = _load_dashboard(params.get("path_b"), output_dir=output_dir)
    if error_a:
        return {"error": f"path_a: {error_a}"}
    if error_b:
        return {"error": f"path_b: {error_b}"}
    bundle_compare = compare_validation_bundles(
        payload_a.get("validation_protocol", {}),
        payload_b.get("validation_protocol", {}),
    )
    bundle_a = bundle_compare.get("left", {})
    bundle_b = bundle_compare.get("right", {})
    return {
        "run_id_a": payload_a.get("run_id"),
        "run_id_b": payload_b.get("run_id"),
        "validation_bundle_change": bundle_compare,
        "validation_bundle_a": bundle_a,
        "validation_bundle_b": bundle_b,
        "status_a": bundle_a.get("status"),
        "status_b": bundle_b.get("status"),
        "dsr_a": bundle_a.get("deflated_sharpe_ratio"),
        "dsr_b": bundle_b.get("deflated_sharpe_ratio"),
        "psr_a": bundle_a.get("probabilistic_sharpe_ratio"),
        "psr_b": bundle_b.get("probabilistic_sharpe_ratio"),
        "pbo_a": bundle_a.get("pbo_score"),
        "pbo_b": bundle_b.get("pbo_score"),
        "spa_a": bundle_a.get("spa_pvalue"),
        "spa_b": bundle_b.get("spa_pvalue"),
        "failed_gates_a": bundle_a.get("failed_gates", []),
        "failed_gates_b": bundle_b.get("failed_gates", []),
    }


VALIDATION_TOOL_CATALOG: list[dict[str, object]] = [
    {
        "name": "get_validation_protocol",
        "description": "Extract the validation protocol (gates, DSR, PSR, PBO, SPA, failed gates, permutation p-values) from a dashboard artifact.",
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string", "description": "Absolute path to a .dashboard.json file"}},
        },
    },
    {
        "name": "get_regime_coverage",
        "description": "Extract regime coverage and the regime/scenario pass matrix from a dashboard artifact.",
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
    },
    {
        "name": "get_scenario_matrix",
        "description": "Extract scenario results, stress metrics, and scenario profiles from a dashboard artifact.",
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
    },
    {
        "name": "compare_validation_results",
        "description": "Compare validation evidence (status, DSR, PSR, PBO, SPA, failed gates) across two dashboard artifacts.",
        "parameters": {
            "type": "object",
            "required": ["path_a", "path_b"],
            "properties": {
                "path_a": {"type": "string"},
                "path_b": {"type": "string"},
            },
        },
    },
]
