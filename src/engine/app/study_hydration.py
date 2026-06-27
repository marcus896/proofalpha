from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.app.examples import serialize_snapshot
from engine.data.providers import build_snapshot_from_bundle
from engine.io.artifacts import write_json_atomic


def hydrate_study_liquidations(
    *,
    config_path: Path,
    liquidations_path: Path,
    output_path: Path,
) -> dict[str, object]:
    try:
        payload, hydrated_payload, summary = _build_hydrated_payload(config_path=config_path, liquidations_path=liquidations_path)
    except Exception as exc:
        return _sidecar_error_payload(
            artifact_type="study_liquidation_hydration",
            config_path=config_path,
            liquidations_path=liquidations_path,
            status="hydration_error",
            error=exc,
            output_path=output_path,
        )
    payload["snapshot"] = hydrated_payload
    write_json_atomic(output_path, payload)

    return {
        **summary,
        "status": _hydration_status(summary),
        "output": str(output_path),
    }


def verify_study_liquidations(
    *,
    config_path: Path,
    liquidations_path: Path,
    output_path: Path | None = None,
) -> dict[str, object]:
    try:
        _, _, summary = _build_hydrated_payload(config_path=config_path, liquidations_path=liquidations_path)
        payload = {
            **summary,
            "artifact_type": "liquidation_sidecar_verification",
            "status": "ready" if _hydration_status(summary) == "hydrated" else "not_ready",
        }
    except Exception as exc:
        payload = _sidecar_error_payload(
            artifact_type="liquidation_sidecar_verification",
            config_path=config_path,
            liquidations_path=liquidations_path,
            status="not_ready",
            error=exc,
        )
    if output_path is not None:
        write_json_atomic(output_path, payload)
    return payload


def _sidecar_error_payload(
    *,
    artifact_type: str,
    config_path: Path,
    liquidations_path: Path,
    status: str,
    error: Exception,
    output_path: Path | None = None,
) -> dict[str, object]:
    payload = {
        "artifact_type": artifact_type,
        "status": status,
        "config": str(config_path),
        "liquidations": str(liquidations_path),
        "error": f"{type(error).__name__}: {error}",
        "missing_liquidation_notional_count": None,
        "quality_flags": [],
        "quality_issues": [],
        "liquidation_coverage": {
            "series": "liquidation_notional",
            "covered": 0,
            "total": 0,
            "missing": None,
            "coverage_ratio": 0.0,
        },
    }
    if output_path is not None:
        payload["output"] = str(output_path)
    return payload


def _build_hydrated_payload(*, config_path: Path, liquidations_path: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("study config must contain a snapshot object")

    provenance = snapshot.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    source_paths = provenance.get("source_paths")
    source_paths = source_paths if isinstance(source_paths, dict) else {}
    candles_path = _resolve_source_path(config_path, source_paths, "candles")
    funding_path = _resolve_optional_source_path(config_path, source_paths, "funding_rate")
    open_interest_path = _resolve_optional_source_path(config_path, source_paths, "open_interest")

    hydrated_snapshot = build_snapshot_from_bundle(
        candles_path=candles_path,
        snapshot_id=str(snapshot["snapshot_id"]),
        symbol=str(snapshot["symbol"]),
        venue=str(snapshot["venue"]),
        timeframe=str(snapshot["timeframe"]),
        maker_fee_bps=float(snapshot["maker_fee_bps"]),
        taker_fee_bps=float(snapshot["taker_fee_bps"]),
        funding_path=funding_path,
        open_interest_path=open_interest_path,
        liquidation_notional_path=liquidations_path,
    )
    hydrated_payload = serialize_snapshot(hydrated_snapshot)
    hydrated_payload["provenance"] = _merge_liquidation_provenance(
        original_provenance=provenance,
        rebuilt_provenance=hydrated_payload.get("provenance", {}),
        liquidations_path=liquidations_path,
    )
    missing_count = _missing_liquidation_count(list(hydrated_payload.get("quality_flags", [])))
    quality_issues = _quality_issues(hydrated_payload.get("quality_report"))
    candle_count = len(hydrated_payload.get("candles", [])) if isinstance(hydrated_payload.get("candles"), list) else 0
    summary = {
        "config": str(config_path),
        "liquidations": str(liquidations_path),
        "missing_liquidation_notional_count": missing_count,
        "quality_flags": list(hydrated_payload.get("quality_flags", [])),
        "quality_issues": quality_issues,
        "liquidation_coverage": {
            "series": "liquidation_notional",
            "covered": max(0, candle_count - missing_count),
            "total": candle_count,
            "missing": missing_count,
            "coverage_ratio": ((candle_count - missing_count) / candle_count) if candle_count else 0.0,
        },
    }
    return payload, hydrated_payload, summary


def _hydration_status(summary: dict[str, object]) -> str:
    missing_count = int(summary.get("missing_liquidation_notional_count", 0))
    quality_issues = summary.get("quality_issues")
    return (
        "hydrated"
        if missing_count == 0 and not quality_issues
        else ("hydrated_with_missing_liquidations" if missing_count > 0 else "hydrated_with_quality_issues")
    )


def _resolve_source_path(config_path: Path, source_paths: dict[str, Any], key: str) -> Path:
    raw = source_paths.get(key)
    if not raw:
        raise ValueError(f"snapshot provenance is missing source_paths.{key}")
    path = Path(str(raw))
    if path.is_absolute() or path.exists():
        return path
    return config_path.parent / path


def _resolve_optional_source_path(config_path: Path, source_paths: dict[str, Any], key: str) -> Path | None:
    raw = source_paths.get(key)
    if not raw:
        return None
    path = Path(str(raw))
    if path.is_absolute() or path.exists():
        return path
    return config_path.parent / path


def _merge_liquidation_provenance(
    *,
    original_provenance: dict[str, Any],
    rebuilt_provenance: object,
    liquidations_path: Path,
) -> dict[str, object]:
    rebuilt = dict(rebuilt_provenance) if isinstance(rebuilt_provenance, dict) else {}
    original_source_paths = original_provenance.get("source_paths")
    original_source_paths = original_source_paths if isinstance(original_source_paths, dict) else {}
    rebuilt_source_paths = rebuilt.get("source_paths")
    rebuilt_source_paths = rebuilt_source_paths if isinstance(rebuilt_source_paths, dict) else {}
    source_paths = {
        **rebuilt_source_paths,
        **original_source_paths,
        "liquidation_notional": str(liquidations_path),
    }
    field_confidence = dict(original_provenance.get("field_confidence", {}))
    field_confidence["liquidation_notional"] = "observed_public_forceorder_with_zero_buckets"
    return {
        **rebuilt,
        "provider": original_provenance.get("provider") or rebuilt.get("provider"),
        "fetch_manifest": original_provenance.get("fetch_manifest"),
        "source_paths": source_paths,
        "source_hash": rebuilt.get("source_hash") or original_provenance.get("source_hash"),
        "build_mode": "liquidation_sidecar_hydrated",
        "liquidation_sidecar_source": "binance_public_ws_forceOrder",
        "uses_api_secret": False,
        "trading_or_order_endpoint_used": False,
        "field_confidence": field_confidence,
    }


def _missing_liquidation_count(quality_flags: list[object]) -> int:
    prefix = "missing_liquidation_notional_count="
    for flag in quality_flags:
        text = str(flag)
        if text.startswith(prefix):
            try:
                return int(text.split("=", 1)[1])
            except ValueError:
                return 0
    return 0


def _quality_issues(quality_report: object) -> list[str]:
    if not isinstance(quality_report, dict):
        return []
    issues = quality_report.get("issues")
    if not isinstance(issues, list):
        return []
    return [str(issue) for issue in issues]
