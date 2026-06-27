import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.io.sqlite import connect_sqlite


class SQLiteConnectionHelperTests(unittest.TestCase):
    def test_connect_sqlite_configures_wal_busy_timeout_row_factory_and_parent_dir(self) -> None:
        root = Path("test-output-sqlite-helper")
        db_path = root / "nested" / "memory.sqlite"
        try:
            with connect_sqlite(db_path) as connection:
                connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
                connection.execute("INSERT INTO sample (value) VALUES (?)", ("ok",))
                row = connection.execute("SELECT value FROM sample").fetchone()
                busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
                journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                connection.commit()

            self.assertTrue(db_path.exists())
            self.assertIsInstance(row, sqlite3.Row)
            self.assertEqual(row["value"], "ok")
            self.assertEqual(busy_timeout, 5000)
            self.assertEqual(journal_mode, "wal")
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_connect_sqlite_read_only_does_not_create_or_write(self) -> None:
        root = Path("test-output-sqlite-helper")
        db_path = root / "memory.sqlite"
        try:
            with connect_sqlite(db_path) as connection:
                connection.execute("CREATE TABLE sample (value TEXT)")
                connection.commit()

            with connect_sqlite(db_path, read_only=True) as connection:
                row = connection.execute("SELECT COUNT(*) AS count FROM sample").fetchone()
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("INSERT INTO sample (value) VALUES ('blocked')")

            self.assertEqual(row["count"], 0)
            with self.assertRaises(sqlite3.OperationalError):
                connect_sqlite(root / "missing.sqlite", read_only=True).close()
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_memory_snapshot_query_uses_shared_read_only_connection(self) -> None:
        from engine.memory import query as memory_query

        class _Rows:
            def fetchall(self) -> list[object]:
                return []

        class _Connection:
            def __init__(self) -> None:
                self.closed = False

            def execute(self, *args: object, **kwargs: object) -> _Rows:
                return _Rows()

            def close(self) -> None:
                self.closed = True

        root = Path("test-output-sqlite-helper")
        db_path = root / "memory.sqlite"
        try:
            root.mkdir(parents=True, exist_ok=True)
            db_path.write_text("", encoding="utf-8")
            fake_connection = _Connection()

            with patch("engine.memory.query.connect_sqlite", return_value=fake_connection) as mocked:
                rows = memory_query.query_data_snapshots(db_path)

            self.assertEqual(rows, [])
            self.assertTrue(fake_connection.closed)
            mocked.assert_called_once_with(db_path, read_only=True)
        finally:
            if root.exists():
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
