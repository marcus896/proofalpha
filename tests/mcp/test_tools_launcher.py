"""Tests for engine.mcp.tools_launcher forbidden actions and allowlist enforcement."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.mcp.config import MCPSettings
from engine.mcp.tools_launcher import (
    LAUNCHER_FORBIDDEN_ACTIONS,
    LAUNCHER_TOOL_CATALOG,
    _invoke_engine_cli,
    _is_forbidden,
    tool_create_autoresearch,
    tool_create_campaign,
    tool_create_study,
)


def _launcher_settings() -> MCPSettings:
    return MCPSettings(launcher_enabled=True)


def _disabled_settings() -> MCPSettings:
    return MCPSettings(launcher_enabled=False)


def _tmpdir() -> tuple[Path, Path]:
    tmp = Path(tempfile.mkdtemp())
    return tmp, tmp / "memory.sqlite"


class TestForbiddenActions(unittest.TestCase):
    def test_forbidden_set_is_nonempty(self) -> None:
        assert len(LAUNCHER_FORBIDDEN_ACTIONS) > 0

    def test_shell_is_forbidden(self) -> None:
        assert _is_forbidden("shell")

    def test_exec_is_forbidden(self) -> None:
        assert _is_forbidden("exec")

    def test_ingest_memory_is_forbidden(self) -> None:
        assert _is_forbidden("ingest-memory")

    def test_trade_is_forbidden(self) -> None:
        assert _is_forbidden("trade")

    def test_run_is_allowed(self) -> None:
        assert not _is_forbidden("run")

    def test_autoresearch_is_allowed(self) -> None:
        assert not _is_forbidden("autoresearch")

    def test_unknown_verb_is_forbidden(self) -> None:
        assert _is_forbidden("some_unknown_verb_xyz")


class TestInvokeEngineCli(unittest.TestCase):
    def test_forbidden_verb_returns_error(self) -> None:
        result = _invoke_engine_cli("shell", [])
        assert "error" in result
        assert "forbidden" in result["error"].lower()

    def test_unknown_verb_returns_error(self) -> None:
        result = _invoke_engine_cli("submit_live_order", [])
        assert "error" in result


class TestToolCatalog(unittest.TestCase):
    def test_catalog_nonempty(self) -> None:
        assert len(LAUNCHER_TOOL_CATALOG) > 0

    def test_all_catalog_entries_have_required_fields(self) -> None:
        for tool in LAUNCHER_TOOL_CATALOG:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool


class TestCreateStudyTool(unittest.TestCase):
    def test_disabled_launcher_returns_error(self) -> None:
        tmp, db = _tmpdir()
        result = tool_create_study(
            {"config_path": "/fake.json"},
            settings=_disabled_settings(),
            output_dir=tmp,
            db_path=db,
        )
        assert "error" in result
        assert "disabled" in result["error"].lower()

    def test_missing_config_path_returns_error(self) -> None:
        tmp, db = _tmpdir()
        result = tool_create_study(
            {},
            settings=_launcher_settings(),
            output_dir=tmp,
            db_path=db,
        )
        assert "error" in result
        assert "config_path" in result["error"]


class TestCreateAutoresearchTool(unittest.TestCase):
    def test_disabled_launcher_returns_error(self) -> None:
        tmp, db = _tmpdir()
        result = tool_create_autoresearch(
            {"config_path": "/fake.json"},
            settings=_disabled_settings(),
            output_dir=tmp,
            db_path=db,
        )
        assert "error" in result

    def test_missing_config_path_returns_error(self) -> None:
        tmp, db = _tmpdir()
        result = tool_create_autoresearch(
            {},
            settings=_launcher_settings(),
            output_dir=tmp,
            db_path=db,
        )
        assert "error" in result


class TestCreateCampaignTool(unittest.TestCase):
    def test_missing_campaign_path_returns_error(self) -> None:
        tmp, db = _tmpdir()
        result = tool_create_campaign(
            {},
            settings=_launcher_settings(),
            output_dir=tmp,
            db_path=db,
        )
        assert "error" in result
        assert "campaign_path" in result["error"]


if __name__ == "__main__":
    unittest.main()
