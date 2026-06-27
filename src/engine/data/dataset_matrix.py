from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


DEFAULT_MINIMUM_DISTINCT_YEARS = 5


def build_dataset_matrix_from_inventory(
    inventory: dict[str, Any],
    *,
    workspace: Path | None = None,
    required_symbols: tuple[str, ...] | list[str] | None = None,
    required_timeframes: tuple[str, ...] | list[str] | None = None,
    minimum_distinct_years: int = DEFAULT_MINIMUM_DISTINCT_YEARS,
    required_sidecar_fields: tuple[str, ...] | list[str] | None = None,
) -> dict[str, object]:
    bundles = _archive_bundles(inventory)
    bundle_by_key = {
        (str(bundle.get("symbol") or ""), str(bundle.get("timeframe") or "")): bundle
        for bundle in bundles
    }
    symbols = _requested_values(required_symbols, (str(bundle.get("symbol") or "") for bundle in bundles))
    timeframes = _requested_values(required_timeframes, (str(bundle.get("timeframe") or "") for bundle in bundles))
    required_sidecars = tuple(str(field) for field in (required_sidecar_fields or ()) if str(field))
    min_years = max(1, int(minimum_distinct_years))

    blockers: list[str] = []
    coverage: list[dict[str, object]] = []
    all_years: set[str] = set()

    for symbol in symbols:
        for timeframe in timeframes:
            bundle = bundle_by_key.get((symbol, timeframe))
            if bundle is None:
                _add(blockers, f"missing_bundle:{symbol}:{timeframe}")
                continue
            entry = _build_coverage_entry(bundle, workspace=workspace)
            coverage.append(entry)
            for year in entry["distinct_years"]:
                all_years.add(str(year))
            for blocker in entry["blockers"]:
                _add(blockers, str(blocker))
            if int(entry["distinct_year_count"]) < min_years:
                _add(blockers, f"insufficient_distinct_years:{symbol}:{timeframe}")
            field_confidence = entry["field_confidence"]
            field_confidence = field_confidence if isinstance(field_confidence, dict) else {}
            for field in required_sidecars:
                if _sidecar_unavailable(field_confidence.get(field)):
                    _add(blockers, f"missing_required_sidecar:{symbol}:{timeframe}:{field}")

    status = "ready" if not blockers else "blocked"
    return {
        "artifact_type": "dataset_matrix",
        "profile": str(inventory.get("profile") or "strict_v3"),
        "status": status,
        "robustness_ready": status == "ready",
        "symbols": symbols,
        "timeframes": timeframes,
        "minimum_distinct_years": min_years,
        "required_sidecar_fields": list(required_sidecars),
        "distinct_years": sorted(all_years),
        "coverage": coverage,
        "blockers": blockers,
    }


def _archive_bundles(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    archive = inventory.get("archive")
    archive = archive if isinstance(archive, dict) else {}
    bundles = archive.get("bundles")
    if not isinstance(bundles, list):
        return []
    return [bundle for bundle in bundles if isinstance(bundle, dict)]


def _requested_values(values: tuple[str, ...] | list[str] | None, fallback: Any) -> list[str]:
    requested = [str(value) for value in (values or []) if str(value)]
    if requested:
        return sorted(dict.fromkeys(requested))
    return sorted(dict.fromkeys(str(value) for value in fallback if str(value)))


def _build_coverage_entry(bundle: dict[str, Any], *, workspace: Path | None) -> dict[str, object]:
    symbol = str(bundle.get("symbol") or "")
    timeframe = str(bundle.get("timeframe") or "")
    blockers: list[str] = []
    candles_path = _resolve_path(bundle.get("candles"), workspace=workspace)
    timestamps: list[str] = []
    if candles_path is None:
        _add(blockers, f"missing_candles_path:{symbol}:{timeframe}")
    elif not candles_path.exists():
        _add(blockers, f"candles_file_missing:{symbol}:{timeframe}")
    else:
        timestamps, parse_blockers = _read_candle_timestamps(candles_path, symbol=symbol, timeframe=timeframe)
        for blocker in parse_blockers:
            _add(blockers, blocker)

    if not bool(bundle.get("source_hash_present")):
        _add(blockers, f"missing_source_hash:{symbol}:{timeframe}")
    if not bool(bundle.get("fetch_manifest_present")):
        _add(blockers, f"missing_fetch_manifest:{symbol}:{timeframe}")

    year_rows = _year_rows(timestamps)
    field_confidence = bundle.get("field_confidence")
    field_confidence = field_confidence if isinstance(field_confidence, dict) else {}
    unavailable_fields = sorted(
        field for field, confidence in field_confidence.items() if _sidecar_unavailable(confidence)
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "status": str(bundle.get("status") or ""),
        "provider": bundle.get("provider"),
        "candles": str(candles_path) if candles_path is not None else None,
        "inventory_rows": _int_or_none(bundle.get("rows")),
        "actual_rows": len(timestamps),
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "distinct_years": sorted(year_rows),
        "distinct_year_count": len(year_rows),
        "year_rows": year_rows,
        "source_hash_present": bool(bundle.get("source_hash_present")),
        "fetch_manifest_present": bool(bundle.get("fetch_manifest_present")),
        "field_confidence": dict(sorted((str(k), str(v)) for k, v in field_confidence.items())),
        "unavailable_fields": unavailable_fields,
        "blockers": blockers,
    }


def _resolve_path(value: object, *, workspace: Path | None) -> Path | None:
    if value is None or not str(value):
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    root = workspace or Path(".")
    return root / path


def _read_candle_timestamps(path: Path, *, symbol: str, timeframe: str) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    timestamps: list[str] = []
    try:
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if "timestamp" not in (reader.fieldnames or []):
                return [], [f"candles_missing_timestamp_column:{symbol}:{timeframe}"]
            for row in reader:
                timestamp = str(row.get("timestamp") or "")
                if len(timestamp) < 4:
                    _add(blockers, f"invalid_timestamp:{symbol}:{timeframe}")
                    continue
                timestamps.append(timestamp)
    except OSError:
        return [], [f"candles_file_unreadable:{symbol}:{timeframe}"]
    if not timestamps:
        _add(blockers, f"empty_candles:{symbol}:{timeframe}")
    return timestamps, blockers


def _year_rows(timestamps: list[str]) -> dict[str, int]:
    rows: dict[str, int] = {}
    for timestamp in timestamps:
        year = timestamp[:4]
        rows[year] = rows.get(year, 0) + 1
    return dict(sorted(rows.items()))


def _sidecar_unavailable(confidence: object) -> bool:
    text = str(confidence or "")
    return not text or text.startswith("unavailable")


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _add(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)
