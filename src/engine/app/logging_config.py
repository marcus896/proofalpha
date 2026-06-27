"""engine.app.logging_config - Centralized logging setup for overnight runs.

Ensures logs are written to both the console (INFO+) and a rotating
file in the outputs/logs/ directory (DEBUG+), providing an audit trail
for crash recovery and behavior diagnosis without polluting stdout.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

_ENGINE_LOGGER_NAME = "engine"
_ENGINE_LOGGER_HANDLER_MARKER = "_engine_logging_handler"
_ENGINE_LOGGER_CONSOLE_HANDLER_MARKER = "_engine_logging_console_handler"
_ENGINE_LOGGER_FILE_HANDLER_MARKER = "_engine_logging_file_handler"


def _has_console_handler(logger: logging.Logger) -> bool:
    return any(
        getattr(handler, _ENGINE_LOGGER_CONSOLE_HANDLER_MARKER, False)
        or (
            getattr(handler, _ENGINE_LOGGER_HANDLER_MARKER, False)
            and isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, RotatingFileHandler)
        )
        for handler in logger.handlers
    )


def _has_file_handler(logger: logging.Logger) -> bool:
    return any(
        getattr(handler, _ENGINE_LOGGER_FILE_HANDLER_MARKER, False)
        or (
            getattr(handler, _ENGINE_LOGGER_HANDLER_MARKER, False)
            and isinstance(handler, RotatingFileHandler)
        )
        for handler in logger.handlers
    )


def _engine_console_handler(logger: logging.Logger) -> logging.Handler | None:
    for handler in logger.handlers:
        if getattr(handler, _ENGINE_LOGGER_CONSOLE_HANDLER_MARKER, False) or (
            getattr(handler, _ENGINE_LOGGER_HANDLER_MARKER, False)
            and isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, RotatingFileHandler)
        ):
            return handler
    return None


def configure_engine_logging(
    log_dir: Path | str = "outputs/logs",
    level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> None:
    """Initialize centralized logging handlers.

    Safe to call multiple times (idempotent). Sets up:
      1. ConsoleHandler (default INFO)
      2. RotatingFileHandler (default DEBUG, max 10MB x 5 files)
    """
    logger = logging.getLogger(_ENGINE_LOGGER_NAME)
    logger.setLevel(min(level, file_level))
    console_level = _resolve_console_level(level)

    formatter = logging.Formatter(fmt="%(asctime)s %(name)s %(levelname)s %(message)s")

    console_handler = _engine_console_handler(logger)
    if console_handler is None:
        console_handler = logging.StreamHandler()
        setattr(console_handler, _ENGINE_LOGGER_HANDLER_MARKER, True)
        setattr(console_handler, _ENGINE_LOGGER_CONSOLE_HANDLER_MARKER, True)
        logger.addHandler(console_handler)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    log_file = (log_dir_path / "engine_run.log").resolve()
    for handler in list(logger.handlers):
        if not isinstance(handler, RotatingFileHandler):
            continue
        existing_path = Path(getattr(handler, "baseFilename", "")).resolve()
        if existing_path != log_file:
            logger.removeHandler(handler)
            handler.close()

    if not _has_file_handler(logger):
        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        setattr(file_handler, _ENGINE_LOGGER_HANDLER_MARKER, True)
        setattr(file_handler, _ENGINE_LOGGER_FILE_HANDLER_MARKER, True)
        logger.addHandler(file_handler)

    logger.info("Engine logging initialized. Writing to %s", log_file.absolute())


def _resolve_console_level(level: int) -> int:
    override = os.environ.get("ENGINE_CONSOLE_LOG_LEVEL")
    if override:
        numeric = logging.getLevelName(override.upper())
        if isinstance(numeric, int):
            return numeric
    if _running_under_unittest():
        return max(level, logging.WARNING)
    return level


def _running_under_unittest() -> bool:
    argv0 = Path(sys.argv[0]).name.lower() if sys.argv else ""
    return argv0.startswith("unittest") or "unittest" in sys.modules
