import logging
import os
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest import mock


class LoggingConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine_logger = logging.getLogger("engine")
        self._original_handlers = list(self.engine_logger.handlers)
        self._original_level = self.engine_logger.level
        self._original_propagate = self.engine_logger.propagate
        for handler in list(self.engine_logger.handlers):
            self.engine_logger.removeHandler(handler)
        self.addCleanup(self._restore_logger)

    def _restore_logger(self) -> None:
        for handler in list(self.engine_logger.handlers):
            self.engine_logger.removeHandler(handler)
            handler.close()
        for handler in self._original_handlers:
            self.engine_logger.addHandler(handler)
        self.engine_logger.setLevel(self._original_level)
        self.engine_logger.propagate = self._original_propagate

    def test_configure_engine_logging_creates_outputs_logs_engine_run_log(self) -> None:
        from engine.app.logging_config import configure_engine_logging

        import shutil

        scratch_dir = Path("test-output-logging-config")
        shutil.rmtree(scratch_dir, ignore_errors=True)
        scratch_dir.mkdir(exist_ok=True)
        cwd = Path.cwd()
        os.chdir(scratch_dir)
        self.addCleanup(os.chdir, cwd)
        self.addCleanup(lambda: shutil.rmtree(scratch_dir, ignore_errors=True))

        configure_engine_logging()

        log_file = Path("outputs/logs/engine_run.log")
        self.assertTrue(log_file.exists())
        self.assertEqual(log_file.parent, Path("outputs/logs"))

        rotating_handlers = [handler for handler in self.engine_logger.handlers if isinstance(handler, RotatingFileHandler)]
        self.assertEqual(len(rotating_handlers), 1)
        self.assertEqual(rotating_handlers[0].formatter._fmt, "%(asctime)s %(name)s %(levelname)s %(message)s")
        self.assertEqual(
            {handler.formatter._fmt for handler in self.engine_logger.handlers if handler.formatter is not None},
            {"%(asctime)s %(name)s %(levelname)s %(message)s"},
        )

    def test_configure_engine_logging_quiets_console_info_under_unittest(self) -> None:
        from engine.app.logging_config import configure_engine_logging

        import shutil

        scratch_dir = Path("test-output-logging-config-quiet")
        shutil.rmtree(scratch_dir, ignore_errors=True)
        scratch_dir.mkdir(exist_ok=True)
        cwd = Path.cwd()
        os.chdir(scratch_dir)
        self.addCleanup(os.chdir, cwd)
        self.addCleanup(lambda: shutil.rmtree(scratch_dir, ignore_errors=True))

        configure_engine_logging()

        console_handlers = [handler for handler in self.engine_logger.handlers if type(handler) is logging.StreamHandler]
        rotating_handlers = [handler for handler in self.engine_logger.handlers if isinstance(handler, RotatingFileHandler)]
        self.assertEqual(len(console_handlers), 1)
        self.assertEqual(console_handlers[0].level, logging.WARNING)
        self.assertEqual(rotating_handlers[0].level, logging.DEBUG)

    def test_configure_engine_logging_is_idempotent_for_engine_logger(self) -> None:
        from engine.app.logging_config import configure_engine_logging

        import shutil

        scratch_dir = Path("test-output-logging-config-idempotent")
        shutil.rmtree(scratch_dir, ignore_errors=True)
        scratch_dir.mkdir(exist_ok=True)
        cwd = Path.cwd()
        os.chdir(scratch_dir)
        self.addCleanup(os.chdir, cwd)
        self.addCleanup(lambda: shutil.rmtree(scratch_dir, ignore_errors=True))

        configure_engine_logging()
        first_handlers = list(self.engine_logger.handlers)
        configure_engine_logging()

        self.assertEqual(len(self.engine_logger.handlers), len(first_handlers))
        self.assertEqual(
            [type(handler) for handler in self.engine_logger.handlers],
            [type(handler) for handler in first_handlers],
        )

    def test_configure_engine_logging_repairs_missing_file_handler(self) -> None:
        from engine.app.logging_config import configure_engine_logging

        import shutil

        scratch_dir = Path("test-output-logging-config-repair")
        shutil.rmtree(scratch_dir, ignore_errors=True)
        scratch_dir.mkdir(exist_ok=True)
        cwd = Path.cwd()
        os.chdir(scratch_dir)
        self.addCleanup(os.chdir, cwd)
        self.addCleanup(lambda: shutil.rmtree(scratch_dir, ignore_errors=True))

        marked_console_handler = logging.StreamHandler()
        setattr(marked_console_handler, "_engine_logging_handler", True)
        setattr(marked_console_handler, "_engine_logging_console_handler", True)
        self.engine_logger.addHandler(marked_console_handler)

        configure_engine_logging()

        rotating_handlers = [handler for handler in self.engine_logger.handlers if isinstance(handler, RotatingFileHandler)]
        console_handlers = [handler for handler in self.engine_logger.handlers if type(handler) is logging.StreamHandler]
        self.assertEqual(len(rotating_handlers), 1)
        self.assertEqual(len(console_handlers), 1)
        self.assertEqual(console_handlers[0].level, logging.WARNING)
        self.assertTrue(Path("outputs/logs/engine_run.log").exists())

    def test_cli_main_configures_engine_logging_before_project_status_execution(self) -> None:
        call_order: list[str] = []

        def fake_configure_engine_logging(*args, **kwargs) -> None:
            call_order.append("logging")

        def fake_load_project_status(*args, **kwargs):
            self.assertEqual(call_order, ["logging"])
            return {
                "plan_version": "test",
                "canonical_plan_file": "PLAN.md",
                "planning_memory_mode": "repo_tracked",
                "autoresearch_memory_separation": True,
                "current_execution_state": "active",
                "highest_priority_next_step": "Phase 10",
                "phases": [],
                "deferred_work": [],
                "resume_order": [],
            }

        with mock.patch("engine.app.logging_config.configure_engine_logging", side_effect=fake_configure_engine_logging), mock.patch(
            "engine.app.cli.load_project_status",
            side_effect=fake_load_project_status,
        ), mock.patch("engine.app.cli.render_project_status", return_value="rendered"), mock.patch("builtins.print"):
            exit_code = __import__("engine.app.cli", fromlist=["main"]).main(["project-status"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(call_order, ["logging"])

    def test_fetch_binance_archive_cli_invokes_public_archive_builder_without_private_keys(self) -> None:
        from engine.app.cli import main

        with mock.patch("engine.app.cli.fetch_binance_archive_snapshot") as fetch_mock, mock.patch("builtins.print") as print_mock:
            fetch_mock.return_value = {
                "candles": Path("out/candles.csv"),
                "manifest": Path("out/fetch_manifest.json"),
            }
            exit_code = main(
                [
                    "fetch-binance-archive",
                    "--output-dir",
                    "out",
                    "--symbol",
                    "BTCUSDT",
                    "--timeframe",
                    "15Min",
                    "--start-date",
                    "2024-01-01",
                    "--end-date",
                    "2024-01-01",
                    "--skip-agg-trades",
                ]
            )

        self.assertEqual(exit_code, 0)
        fetch_mock.assert_called_once_with(
            output_dir=Path("out"),
            symbol="BTCUSDT",
            timeframe="15Min",
            start_date="2024-01-01",
            end_date="2024-01-01",
            include_agg_trades=False,
        )
        self.assertIn("fetch_manifest.json", print_mock.call_args.args[0])


