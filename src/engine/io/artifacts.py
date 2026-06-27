from __future__ import annotations

import json
import os
from pathlib import Path
import uuid


def write_text_atomic(path: Path | str, text: str, *, encoding: str = "utf-8") -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    replaced = False
    try:
        with temp_path.open("w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, output)
        replaced = True
        return output
    finally:
        if not replaced:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def write_json_atomic(
    path: Path | str,
    payload: object,
    *,
    encoding: str = "utf-8",
    indent: int | None = 2,
    sort_keys: bool = True,
) -> Path:
    return write_text_atomic(
        path,
        json.dumps(payload, indent=indent, sort_keys=sort_keys),
        encoding=encoding,
    )
