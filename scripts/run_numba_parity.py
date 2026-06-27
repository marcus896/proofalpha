from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PARITY_TEST = "tests.backtest.test_simulator_batch.NumbaParityTests"


def _candidate_interpreters() -> list[Path]:
    candidates = [
        Path(sys.executable),
        REPO_ROOT / ".venv312" / "Scripts" / "python.exe",
        Path(r"C:\Python312\python.exe"),
        Path(r"C:\Python313\python.exe"),
    ]
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _resolve_interpreter() -> Path:
    for candidate in _candidate_interpreters():
        if candidate.exists():
            return candidate
    raise SystemExit(
        "No supported Python 3.12/3.13 interpreter found for Numba parity. "
        "Create .venv312 in the repo or install Python 3.12/3.13."
    )


def main() -> int:
    interpreter = _resolve_interpreter()
    command = [str(interpreter), "-m", "unittest", PARITY_TEST, "-v"]
    completed = subprocess.run(command, cwd=REPO_ROOT)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
