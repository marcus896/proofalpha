from __future__ import annotations

from pathlib import Path
import sqlite3


class EngineSQLiteConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        suppress = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return bool(suppress)


def connect_sqlite(
    db_path: Path | str,
    *,
    read_only: bool = False,
    busy_timeout_ms: int = 5000,
    row_factory: type[sqlite3.Row] | None = sqlite3.Row,
    wal: bool = True,
    foreign_keys: bool = False,
) -> sqlite3.Connection:
    path = Path(db_path)
    timeout_seconds = max(0.0, float(busy_timeout_ms) / 1000.0)
    if read_only:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=timeout_seconds,
            factory=EngineSQLiteConnection,
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=timeout_seconds, factory=EngineSQLiteConnection)

    connection.row_factory = row_factory
    connection.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys=ON")
    if wal and not read_only:
        connection.execute("PRAGMA journal_mode=WAL")
    return connection
