from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

from engine.execution import paper_collector, reconciliation
from engine.io.sqlite import connect_sqlite
from engine.memory.store import initialize_memory_db


class ExecutorSQLiteMigrationTests(unittest.TestCase):
    def test_executor_sqlite_call_sites_use_shared_helper(self) -> None:
        execution_root = Path("src/engine/execution")
        target_modules = {
            "paper.py",
            "paper_closeout.py",
            "paper_collector.py",
            "paper_hosting.py",
            "paper_soak.py",
            "reconciliation.py",
        }
        offenders = []
        for module_name in sorted(target_modules):
            source = (execution_root / module_name).read_text(encoding="utf-8")
            if "sqlite3.connect(" in source:
                offenders.append(module_name)

        self.assertEqual(offenders, [])

    def test_collector_uses_write_and_read_only_shared_connections(self) -> None:
        root = Path("test-sqlite-executor-collector")
        db_path = root / "memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            calls: list[bool] = []

            def tracked_connect(path: Path, **kwargs: object):
                calls.append(bool(kwargs.get("read_only", False)))
                return connect_sqlite(path, **kwargs)

            with mock.patch("engine.execution.paper_collector.connect_sqlite", side_effect=tracked_connect, create=True):
                paper_collector._upsert_collector_session(
                    db_path,
                    session_id="collector-session",
                    host_id="host",
                    status="running",
                    started_at_utc="2026-01-01T00:00:00Z",
                    heartbeat_at_utc="2026-01-01T00:00:00Z",
                    symbols=["BTCUSDT"],
                    streams=["aggTrade"],
                    payload={"mode": "fixture_public_ws"},
                )
                paper_collector._heartbeat_cadence_seconds(db_path, "collector-session")

            self.assertIn(False, calls)
            self.assertIn(True, calls)
        finally:
            _remove_tree(root)

    def test_reconciliation_uses_write_and_read_only_shared_connections(self) -> None:
        root = Path("test-sqlite-executor-reconciliation")
        db_path = root / "memory.sqlite"
        root.mkdir(exist_ok=True)
        try:
            initialize_memory_db(db_path)
            calls: list[bool] = []

            def tracked_connect(path: Path, **kwargs: object):
                calls.append(bool(kwargs.get("read_only", False)))
                return connect_sqlite(path, **kwargs)

            with mock.patch("engine.execution.reconciliation.connect_sqlite", side_effect=tracked_connect, create=True):
                reconciliation._rebuild_phase3_once(db_path)
                reconciliation._load_local_projection(db_path)
                reconciliation._local_duplicate_fill_count(db_path)

            self.assertIn(False, calls)
            self.assertIn(True, calls)
        finally:
            _remove_tree(root)


def _remove_tree(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    root.rmdir()

