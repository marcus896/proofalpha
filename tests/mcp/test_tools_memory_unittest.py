from __future__ import annotations

import json
import unittest
from pathlib import Path
from uuid import uuid4

from engine.config.models import PromotionDecision, RunCard
from engine.mcp.config import MCPProfile
from engine.mcp.server import build_mcp_server
from engine.memory.store import ingest_artifact_directory, initialize_memory_db
from engine.reporting.runcards import save_runcard


def _make_runcard(run_id: str, *, symbol: str, venue: str, accepted_layers: float = 1.0) -> RunCard:
    return RunCard(
        run_id=run_id,
        strategy_hash=f"{run_id}-hash",
        phase="phase-5",
        split_id="snap:60-20-20",
        seed=7,
        decision=PromotionDecision(decision="promoted", reasons=[]),
        metrics={
            "selection_oos_sharpe": 0.55,
            "selection_oos_net_pnl": 100.0,
            "selection_oos_drawdown": -0.10,
            "scenario_pass_rate": 1.0,
            "accepted_layers": accepted_layers,
        },
        artifacts={
            "snapshot_id": f"{run_id}-snap",
            "final_status": "promoted",
            "symbol": symbol,
            "venue": venue,
            "snapshot_quality_status": "clean",
            "snapshot_quality_flag_count": "0",
            "snapshot_quality_flags_json": "[]",
            "runtime_settings_json": "{}",
            "scenario_profiles_json": "{}",
            "stress_liquidity_metrics_json": "{}",
            "regime_scenario_pass_matrix_json": "{}",
            "regime_summary_json": "{}",
            "bootstrap_summary_json": "{}",
            "selected_parameters_json": '{"kama":{"aggressiveness":2}}',
            "parameter_search_json": "{}",
        },
    )


def _write_dashboard(path: Path, *, layer_name: str) -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": path.stem.replace(".dashboard", ""),
                "strategy": {"backbone": "mom_squeeze", "layers": [layer_name], "risk_guards": []},
                "phases": [
                    {
                        "phase_name": "phase-5",
                        "layer_name": layer_name,
                        "decision": "accept",
                        "accepted": True,
                        "selected_parameters": {"aggressiveness": 2},
                        "permutation_count": 1,
                        "search_summary": [],
                        "oos_sharpe": 0.55,
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


class MCPMemoryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path.cwd() / f"tmp-mcp-tools-{uuid4().hex}"
        self._tmp.mkdir(parents=True, exist_ok=True)
        self.output_dir = self._tmp / "out"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self._tmp / "memory.sqlite"
        initialize_memory_db(self.db_path)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _ingest_run(self, run_id: str, *, symbol: str, venue: str, layer_name: str) -> None:
        save_runcard(
            self.output_dir / f"{run_id}.runcard.json",
            _make_runcard(run_id, symbol=symbol, venue=venue),
        )
        _write_dashboard(self.output_dir / f"{run_id}.dashboard.json", layer_name=layer_name)
        ingest_artifact_directory(self.db_path, self.output_dir)

    def test_list_batches_finds_variant_batch_reports(self) -> None:
        report_path = self.output_dir / "batch-run.variant-batch.json"
        report_path.write_text(json.dumps({"run_id": "batch-run", "status": "promoted"}), encoding="utf-8")
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=self.output_dir, db_path=self.db_path)

        result = server.call_tool("list_batches", {"limit": 5})

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["batches"][0]["run_id"], "batch-run")

    def test_get_batch_accepts_variant_batch_run_id(self) -> None:
        report_path = self.output_dir / "batch-run.variant-batch.json"
        report_path.write_text(json.dumps({"run_id": "batch-run", "status": "promoted"}), encoding="utf-8")
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=self.output_dir, db_path=self.db_path)

        result = server.call_tool("get_batch", {"run_id": "batch-run"})

        self.assertEqual(result["run_id"], "batch-run")
        self.assertEqual(result["status"], "promoted")

    def test_get_batch_rejects_path_outside_output_dir(self) -> None:
        outside_path = self._tmp / "outside-batch.json"
        outside_path.write_text(json.dumps({"run_id": "outside", "status": "promoted"}), encoding="utf-8")
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=self.output_dir, db_path=self.db_path)

        result = server.call_tool("get_batch", {"path": str(outside_path.resolve())})

        self.assertIn("error", result)
        self.assertIn("output dir", result["error"])

    def test_get_campaign_rejects_path_outside_output_dir(self) -> None:
        outside_path = self._tmp / "outside-campaign.json"
        outside_path.write_text(json.dumps({"campaign_id": "outside", "status": "completed"}), encoding="utf-8")
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=self.output_dir, db_path=self.db_path)

        result = server.call_tool("get_campaign", {"path": str(outside_path.resolve())})

        self.assertIn("error", result)
        self.assertIn("output dir", result["error"])

    def test_list_runs_can_filter_by_venue(self) -> None:
        self._ingest_run("binance-run", symbol="SOLUSDT", venue="binance", layer_name="kama")
        self._ingest_run("bybit-run", symbol="SOLUSDT", venue="bybit", layer_name="ema")
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=self.output_dir, db_path=self.db_path)

        result = server.call_tool("list_runs", {"symbol": "SOLUSDT", "venue": "binance"})

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["runs"][0]["run_id"], "binance-run")

    def test_query_memory_summary_can_filter_by_symbol_and_venue(self) -> None:
        self._ingest_run("binance-run", symbol="SOLUSDT", venue="binance", layer_name="kama")
        self._ingest_run("bybit-run", symbol="SOLUSDT", venue="bybit", layer_name="ema")
        self._ingest_run("btc-run", symbol="BTCUSDT", venue="binance", layer_name="hull")
        server = build_mcp_server(MCPProfile.READ_ONLY, output_dir=self.output_dir, db_path=self.db_path)

        result = server.call_tool("query_memory_summary", {"symbol": "SOLUSDT", "venue": "binance", "limit": 10})

        self.assertEqual(result["total_runs"], 1)
        self.assertEqual(result["promoted_runs"], 1)
        self.assertEqual(result["promising_layers"], [{"layer_name": "kama", "count": 1}])


if __name__ == "__main__":
    unittest.main()
