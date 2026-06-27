"""Tests for engine.mcp.server MCPServer dispatch and profile enforcement."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.mcp.config import MCPProfile
from engine.mcp.server import MCPServer, build_mcp_server


def _temp_paths() -> tuple[Path, Path]:
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "memory.sqlite"
    return tmp, db


class TestMCPServerConstruction(unittest.TestCase):
    def test_builds_read_only_server(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        assert isinstance(server, MCPServer)
        assert server.profile == MCPProfile.READ_ONLY

    def test_builds_launcher_server(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.LAUNCHER, output_dir=output_dir, db_path=db_path)
        assert server.settings.launcher_enabled

    def test_builds_discovery_server(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.DISCOVERY, output_dir=output_dir, db_path=db_path)
        assert server.settings.enable_tool_discovery


class TestListTools(unittest.TestCase):
    def test_read_only_returns_tools(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        tools = server.list_tools()
        assert len(tools) > 0

    def test_launcher_returns_more_tools(self) -> None:
        output_dir, db_path = _temp_paths()
        ro = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        la = build_mcp_server(MCPProfile.LAUNCHER, output_dir=output_dir, db_path=db_path)
        assert len(la.list_tools()) > len(ro.list_tools())

    def test_discovery_returns_no_tools(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.DISCOVERY, output_dir=output_dir, db_path=db_path)
        assert server.list_tools() == []

    def test_all_tools_have_name_and_description(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.LAUNCHER, output_dir=output_dir, db_path=db_path)
        for tool in server.list_tools():
            assert "name" in tool
            assert "description" in tool

    def test_compare_validation_results_tool_description_mentions_phase2_fields(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        tools = {tool["name"]: tool for tool in server.list_tools()}

        tool = tools["compare_validation_results"]

        assert "PBO" in tool["description"]
        assert "SPA" in tool["description"]
        assert "failed gates" in tool["description"]

    def test_get_validation_protocol_tool_description_mentions_phase2_fields(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        tools = {tool["name"]: tool for tool in server.list_tools()}

        tool = tools["get_validation_protocol"]

        assert "PBO" in tool["description"]
        assert "SPA" in tool["description"]
        assert "failed gates" in tool["description"]


class TestCallTool(unittest.TestCase):
    def test_unknown_tool_returns_error(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        result = server.call_tool("nonexistent_tool", {})
        assert "error" in result

    def test_launcher_tool_blocked_in_read_only(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        result = server.call_tool("create_study", {"config_path": "/fake/path.json"})
        assert "error" in result

    def test_get_study_template_returns_dict(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        result = server.call_tool("get_study_template", {})
        assert isinstance(result, dict)
        assert "run_id" in result

    def test_list_layer_families_returns_list(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        result = server.call_tool("list_layer_families", {})
        assert "families" in result
        assert isinstance(result["families"], list)
        assert len(result["families"]) > 0

    def test_list_layers_returns_real_approved_layer_names(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        result = server.call_tool("list_layers", {"family": "directional_filter"})
        assert result["layers"] == ["ema", "kama", "hull"]

    def test_get_layer_returns_real_layer_metadata(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        result = server.call_tool("get_layer", {"name": "kama"})
        assert result["name"] == "kama"
        assert result["family"] == "directional_filter"
        assert "len" in result["parameters"]

    def test_list_runs_returns_empty_for_missing_db(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        result = server.call_tool("list_runs", {"limit": 5})
        assert "runs" in result or "error" in result

    def test_list_artifacts_returns_count(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        result = server.call_tool("list_artifacts", {"suffix": ".dashboard.json"})
        assert "count" in result
        assert result["count"] == 0

    def test_launcher_create_study_blocked_without_config(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.LAUNCHER, output_dir=output_dir, db_path=db_path)
        result = server.call_tool("create_study", {})
        assert "error" in result

    def test_reporting_tool_rejects_path_outside_output_dir(self) -> None:
        output_dir, db_path = _temp_paths()
        outside_path = output_dir.parent / "outside.dashboard.json"
        outside_path.write_text("{}", encoding="utf-8")
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)

        result = server.call_tool("summarize_run", {"path": str(outside_path.resolve())})

        assert "error" in result
        assert "output dir" in result["error"]

    def test_validation_tool_rejects_path_outside_output_dir(self) -> None:
        output_dir, db_path = _temp_paths()
        outside_path = output_dir.parent / "outside.dashboard.json"
        outside_path.write_text("{}", encoding="utf-8")
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)

        result = server.call_tool("get_validation_protocol", {"path": str(outside_path.resolve())})

        assert "error" in result
        assert "output dir" in result["error"]

    def test_get_validation_protocol_returns_full_phase2_fields(self) -> None:
        output_dir = Path.cwd() / f"tmp_mcp_validation_protocol_{next(tempfile._get_candidate_names())}"
        db_path = output_dir / "memory.sqlite"
        output_dir.mkdir(parents=True, exist_ok=False)
        dashboard_path = output_dir / "protocol.dashboard.json"
        try:
            dashboard_path.write_text(
                json.dumps(
                    {
                        "run_id": "protocol-run",
                        "validation_protocol": {
                            "status": "failed",
                            "deflated_sharpe_ratio": 0.91,
                            "probabilistic_sharpe_ratio": 0.88,
                            "pbo_score": 0.27,
                            "spa_pvalue": 0.12,
                            "purge_bars": 7,
                            "embargo_bars": 2,
                            "n_blocks": 12,
                            "n_test_blocks": 3,
                            "cpcv_config": {
                                "method": "combinatorial_purged_cv",
                                "purge_bars": 7,
                                "embargo_bars": 2,
                                "n_blocks": 12,
                                "n_test_blocks": 3,
                            },
                            "in_sample_summary": {"trade_count": 17, "sharpe": 5.0},
                            "selection_oos_summary": {"trade_count": 5, "sharpe": 4.0},
                            "holdout_summary": {"trade_count": 5, "sharpe": 3.0},
                            "validation_gate_results": {
                                "deflated_sharpe_ratio": False,
                                "pbo": False,
                                "spa": False,
                                "final_holdout_excellence": True,
                            },
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)

            result = server.call_tool("get_validation_protocol", {"path": str(dashboard_path.resolve())})

            assert result["status"] == "failed"
            assert result["deflated_sharpe_ratio"] == 0.91
            assert result["probabilistic_sharpe_ratio"] == 0.88
            assert result["pbo_score"] == 0.27
            assert result["spa_pvalue"] == 0.12
            assert result["purge_bars"] == 7
            assert result["embargo_bars"] == 2
            assert result["n_blocks"] == 12
            assert result["n_test_blocks"] == 3
            assert result["cpcv_config"]["method"] == "combinatorial_purged_cv"
            assert result["in_sample_summary"]["trade_count"] == 17
            assert result["selection_oos_summary"]["trade_count"] == 5
            assert result["holdout_summary"]["trade_count"] == 5
            assert result["validation_gate_results"]["pbo"] is False
            assert result["validation_gate_results"]["spa"] is False
            assert result["validation_bundle"]["status"] == "failed"
            assert result["validation_bundle"]["pbo_score"] == 0.27
            assert result["validation_bundle"]["spa_pvalue"] == 0.12
            assert result["validation_bundle"]["purge_bars"] == 7
            assert result["validation_bundle"]["embargo_bars"] == 2
            assert result["validation_bundle"]["n_blocks"] == 12
            assert result["validation_bundle"]["n_test_blocks"] == 3
            assert result["validation_bundle"]["cpcv_config"]["method"] == "combinatorial_purged_cv"
            assert result["validation_bundle"]["in_sample_summary"]["trade_count"] == 17
            assert result["validation_bundle"]["selection_oos_summary"]["trade_count"] == 5
            assert result["validation_bundle"]["holdout_summary"]["trade_count"] == 5
            assert result["validation_bundle"]["failed_gates"] == ["deflated_sharpe_ratio", "pbo", "spa"]
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_compare_validation_results_surfaces_validation_bundle_drift(self) -> None:
        output_dir = Path.cwd() / f"tmp_mcp_validation_{next(tempfile._get_candidate_names())}"
        db_path = output_dir / "memory.sqlite"
        output_dir.mkdir(parents=True, exist_ok=False)
        left_path = output_dir / "left.dashboard.json"
        right_path = output_dir / "right.dashboard.json"
        try:
            left_path.write_text(
                json.dumps(
                    {
                        "run_id": "left-run",
                        "validation_protocol": {
                            "status": "failed",
                            "deflated_sharpe_ratio": 0.91,
                            "probabilistic_sharpe_ratio": 0.88,
                            "pbo_score": 0.27,
                            "spa_pvalue": 0.12,
                            "validation_gate_results": {
                                "deflated_sharpe_ratio": False,
                                "pbo": False,
                                "spa": False,
                                "final_holdout_excellence": True,
                            },
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            right_path.write_text(
                json.dumps(
                    {
                        "run_id": "right-run",
                        "validation_protocol": {
                            "status": "passed",
                            "deflated_sharpe_ratio": 0.95,
                            "probabilistic_sharpe_ratio": 0.93,
                            "pbo_score": 0.08,
                            "spa_pvalue": 0.02,
                            "validation_gate_results": {
                                "deflated_sharpe_ratio": True,
                                "pbo": True,
                                "spa": True,
                                "final_holdout_excellence": True,
                            },
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)

            result = server.call_tool(
                "compare_validation_results",
                {"path_a": str(left_path.resolve()), "path_b": str(right_path.resolve())},
            )

            assert result["run_id_a"] == "left-run"
            assert result["run_id_b"] == "right-run"
            assert result["pbo_a"] == 0.27
            assert result["pbo_b"] == 0.08
            assert result["spa_a"] == 0.12
            assert result["spa_b"] == 0.02
            assert result["failed_gates_a"] == ["deflated_sharpe_ratio", "pbo", "spa"]
            assert result["failed_gates_b"] == []
            assert result["validation_bundle_change"]["changed_fields"]["status"] == {"left": "failed", "right": "passed"}
            assert result["validation_bundle_change"]["changed_fields"]["pbo_score"] == {"left": 0.27, "right": 0.08}
            assert result["validation_bundle_change"]["changed_fields"]["spa_pvalue"] == {"left": 0.12, "right": 0.02}
            assert result["validation_bundle_change"]["changed_fields"]["failed_gates"] == {"left": ["deflated_sharpe_ratio", "pbo", "spa"], "right": []}
            assert result["validation_bundle_a"]["status"] == "failed"
            assert result["validation_bundle_a"]["pbo_score"] == 0.27
            assert result["validation_bundle_a"]["spa_pvalue"] == 0.12
            assert result["validation_bundle_a"]["failed_gates"] == ["deflated_sharpe_ratio", "pbo", "spa"]
            assert result["validation_bundle_b"]["status"] == "passed"
            assert result["validation_bundle_b"]["pbo_score"] == 0.08
            assert result["validation_bundle_b"]["spa_pvalue"] == 0.02
            assert result["validation_bundle_b"]["failed_gates"] == []
        finally:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


class TestDescribe(unittest.TestCase):
    def test_describe_shape(self) -> None:
        output_dir, db_path = _temp_paths()
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=output_dir, db_path=db_path)
        desc = server.describe()
        assert desc["profile"] == "read_only"
        assert isinstance(desc["tool_count"], int)
        assert desc["tool_count"] > 0
        assert isinstance(desc["tools"], list)


if __name__ == "__main__":
    unittest.main()
