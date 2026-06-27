import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.execution.paper_hosting import (
    HostedPaperOpsConfig,
    build_paper_host_doctor_report,
    write_hosted_paper_ops_templates,
)
from engine.memory.store import initialize_memory_db


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


class Phase9AHostedOpsTests(unittest.TestCase):
    def test_host_doctor_checks_dirs_disk_sqlite_templates_and_no_secret_env(self) -> None:
        root = Path("test-phase9a-hosted-ops")
        db_path = root / "var" / "lib" / "trading-strategy" / "memory.sqlite"
        state_dir = db_path.parent
        log_dir = root / "var" / "log" / "trading-strategy"
        backup_dir = root / "var" / "backups" / "trading-strategy"
        template_root = root / "deploy"
        try:
            state_dir.mkdir(parents=True)
            log_dir.mkdir(parents=True)
            backup_dir.mkdir(parents=True)
            initialize_memory_db(db_path)
            write_hosted_paper_ops_templates(template_root)

            report = build_paper_host_doctor_report(
                HostedPaperOpsConfig(
                    repo_dir=Path.cwd(),
                    state_dir=state_dir,
                    log_dir=log_dir,
                    backup_dir=backup_dir,
                    db_path=db_path,
                    template_root=template_root,
                    min_free_mb=0,
                )
            )

            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["secrets"]["status"], "pass")
            self.assertEqual(report["sqlite"]["quick_check"], "ok")
            self.assertEqual(report["templates"]["status"], "pass")
            self.assertEqual(report["directories"]["status"], "pass")
            self.assertIn("trading-strategy-paper.service", report["templates"]["files"])
            self.assertIn("paper-daemon.env.example", report["templates"]["files"])
            self.assertIn("trading-strategy", report["templates"]["files"])
        finally:
            _clean_tree(root)

    def test_templates_are_safe_systemd_logrotate_and_no_secret_env(self) -> None:
        root = Path("test-phase9a-hosted-templates")
        try:
            paths = write_hosted_paper_ops_templates(root)

            service = paths["systemd_unit"].read_text(encoding="utf-8")
            env = paths["env_template"].read_text(encoding="utf-8")
            logrotate = paths["logrotate"].read_text(encoding="utf-8")

            self.assertIn("User=trading-strategy", service)
            self.assertIn("WatchdogSec=60", service)
            self.assertIn("ExecStart=", service)
            self.assertIn("PAPER_DB=/var/lib/trading-strategy/memory.sqlite", env)
            self.assertNotIn("BINANCE_API_KEY", env)
            self.assertNotIn("BINANCE_API_SECRET", env)
            self.assertIn("/var/log/trading-strategy/*.log", logrotate)
            self.assertIn("rotate 14", logrotate)
        finally:
            _clean_tree(root)

    def test_host_doctor_reports_fail_instead_of_crashing_when_dirs_are_missing(self) -> None:
        root = Path("test-phase9a-hosted-missing")
        try:
            report = build_paper_host_doctor_report(
                HostedPaperOpsConfig(
                    repo_dir=root / "missing-repo",
                    state_dir=root / "missing-state",
                    log_dir=root / "missing-logs",
                    backup_dir=root / "missing-backups",
                    db_path=root / "missing-state" / "memory.sqlite",
                    template_root=root / "missing-deploy",
                    min_free_mb=0,
                )
            )

            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["directories"]["status"], "fail")
            self.assertEqual(report["sqlite"]["status"], "fail")
            self.assertEqual(report["disk"]["status"], "fail")
        finally:
            _clean_tree(root)

    def test_cli_paper_host_doctor_writes_templates_and_reports_json(self) -> None:
        root = Path("test-phase9a-hosted-cli")
        db_path = root / "state" / "memory.sqlite"
        try:
            (root / "state").mkdir(parents=True)
            (root / "logs").mkdir(parents=True)
            (root / "backups").mkdir(parents=True)
            initialize_memory_db(db_path)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "paper-host-doctor",
                        "--repo-dir",
                        str(Path.cwd()),
                        "--state-dir",
                        str(root / "state"),
                        "--log-dir",
                        str(root / "logs"),
                        "--backup-dir",
                        str(root / "backups"),
                        "--db",
                        str(db_path),
                        "--template-root",
                        str(root / "deploy"),
                        "--min-free-mb",
                        "0",
                        "--write-templates",
                    ]
                )

            payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["templates"]["status"], "pass")
            self.assertTrue((root / "deploy" / "systemd" / "trading-strategy-paper.service").exists())
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
