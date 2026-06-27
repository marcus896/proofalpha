from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


def build_run_log_path(output_dir: Path, run_id: str) -> Path:
    return output_dir / f"{run_id}.events.jsonl"


def append_run_log_event(path: Path, event: str, **fields: Any) -> None:
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        **{key: _normalize_value(value) for key, value in fields.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value
