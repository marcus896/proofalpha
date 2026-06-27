import json
import os
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
import shutil

import ui_server


class UiServerTests(unittest.TestCase):
    def test_http_server_does_not_expose_project_files(self):
        server = ui_server.ReusableHTTPServer(("127.0.0.1", 0), ui_server.DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            for path in ("/.env", "/assets/../.env", "/assets/%2e%2e/.env"):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2)
                self.assertEqual(raised.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_missing_paper_database_is_not_created_by_read(self):
        root = Path("test-output-ui-server-readonly")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        missing = root / "missing.sqlite"
        try:
            self.assertIsNone(ui_server.load_paper_dashboard_file(str(missing), restrict_to_dir=str(root)))
            self.assertFalse(missing.exists())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _write_dashboard(self, path, run_id="example", symbol="BTCUSDT"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "decision": "promoted",
                    "artifacts": {"final_status": "promoted", "symbol": symbol},
                }
            ),
            encoding="utf-8",
        )

    def test_dashboard_template_includes_interactive_stage_and_render_helpers(self):
        template = Path("dashboard.html").read_text(encoding="utf-8")
        script = Path("dashboard.js").read_text(encoding="utf-8")

        self.assertIn('src="./dashboard.js?v=', template)
        self.assertIn('id="dataModeSelect"', template)
        self.assertIn('id="manualRunSelect"', template)
        self.assertNotIn("WOLFPACK ELITE DASHBOARD", template)
        self.assertNotIn("WOLFPACK ELITE DATA LOADER", template)
        self.assertNotIn("GET YOUR ACCESS: WHOP.COM/TRADETACTICS", template)
        self.assertIn("LOADING DASHBOARD", template)
        self.assertNotIn("2015-01-01T00:00:00Z", template)
        self.assertNotIn('id="headerContext"', template)
        self.assertIn("grid-template-columns: 300px 150px 146px 210px 170px 238px", template)
        self.assertIn("PROOFALPHA", template)
        self.assertIn("EVIDENCE LAB / PAPER READINESS", template)
        self.assertIn("Space Grotesk", template)
        self.assertIn("Space Mono", template)
        self.assertIn("Doto", template)
        self.assertIn("proofalpha-mark.svg", template)
        self.assertNotIn('id="sourceHint"', template)
        self.assertNotIn('id="modeAutoButton"', template)
        self.assertNotIn('id="modeManualButton"', template)
        self.assertNotIn("sourceHint.textContent", script)
        self.assertIn("syncStageScale", script)
        self.assertIn("getSimulationSnapshot", script)
        self.assertIn("pickStrategyTheme", script)
        self.assertIn("renderDashboard", script)
        self.assertIn("loadSelectedDashboard", script)
        self.assertIn("Test Backtest", script)
        self.assertIn("Paper Trading", script)

    def test_test_dashboard_is_available_even_without_real_strategy(self):
        payload = ui_server.load_test_dashboard(root="missing-output-root")

        self.assertIsNotNone(payload)
        self.assertEqual(payload["visuals"]["source_mode"], "test_backtest")
        self.assertEqual(payload["visuals"]["is_test_data"], True)
        self.assertGreater(len(payload["timeseries"]), 0)

    @unittest.skip("Private launcher assets are intentionally excluded from the public export.")
    def test_workspace_contains_hidden_ui_launcher_assets(self):
        self.assertTrue(Path("start_proofalpha_ui_hidden.pyw").exists())
        self.assertTrue(Path("create_proofalpha_desktop_shortcut.ps1").exists())
        self.assertTrue(Path("start_proofalpha_ui.ps1").exists())
        self.assertTrue(Path("assets/brand/proofalpha-mark.svg").exists())
        self.assertTrue(Path("assets/brand/proofalpha-wordmark.svg").exists())

    def test_normalize_dashboard_payload_derives_visuals_for_sparse_dashboard(self):
        payload = {
            "run_id": "example-study",
            "decision": "promoted",
            "artifacts": {
                "symbol": "SOLUSDT",
                "venue": "binance",
                "snapshot_id": "example-solusdt-1h",
                "final_status": "promoted",
                "runtime_settings_json": json.dumps(
                    {
                        "position_side": "long",
                        "position_leverage": 3.0,
                        "slippage_bps": 5.0,
                    }
                ),
            },
            "metrics": {
                "selection_oos_net_pnl": 15.23061,
                "selection_oos_drawdown": -0.010199019073569486,
                "selection_oos_sharpe": 0.2500788784146175,
            },
            "bootstrap": {
                "pass_rate": 1.0,
                "median_max_drawdown": -0.042537342207825735,
            },
            "phases": [
                {
                    "phase_name": "phase-3",
                    "layer_name": "flat9",
                    "search_summary": [
                        {
                            "bootstrap_worst_drawdown": -0.05141796304254406,
                            "oos_net_pnl": 15.23061,
                            "oos_sharpe": 0.2500788784146175,
                            "parameters": {},
                        }
                    ],
                }
            ],
        }

        normalized = ui_server.normalize_dashboard_payload(payload)

        self.assertIn("runtime_settings", normalized)
        self.assertEqual(normalized["runtime_settings"]["position_leverage"], 3.0)
        self.assertIn("visuals", normalized)
        self.assertEqual(normalized["visuals"]["timeseries"], [])
        self.assertIn("table_stats", normalized)
        self.assertEqual(normalized["visuals"]["context"]["symbol"], "SOLUSDT")
        self.assertEqual(normalized["visuals"]["ranked_parameter_sets"][0]["label"], "flat9")
        self.assertEqual(normalized["visuals"]["analysis_modes"], ["Normal Training", "Bootstrap Review", "Strategy Profile"])
        self.assertEqual(normalized["visuals"]["simulation_results"], ["Selection", "Median"])
        self.assertEqual(normalized["table_stats"], {})

    def test_list_dashboard_artifacts_excludes_fake_data_directory(self):
        root = Path("test-output-ui-server-fake-filter")
        shutil.rmtree(root, ignore_errors=True)
        (root / "fake_data").mkdir(parents=True, exist_ok=True)
        try:
            real_run = root / "real.dashboard.json"
            fake_run = root / "fake_data" / "fake.dashboard.json"

            real_run.write_text(
                json.dumps(
                    {
                        "run_id": "real",
                        "decision": "promoted",
                        "artifacts": {"final_status": "promoted", "symbol": "SOLUSDT"},
                    }
                ),
                encoding="utf-8",
            )
            fake_run.write_text(
                json.dumps(
                    {
                        "run_id": "fake",
                        "decision": "promoted",
                        "artifacts": {"final_status": "promoted", "symbol": "ETHUSDT"},
                    }
                ),
                encoding="utf-8",
            )

            artifacts = ui_server.list_dashboard_artifacts(root=str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertEqual([item["run_id"] for item in artifacts], ["real"])

    def test_list_dashboard_artifacts_excludes_demo_payloads_and_example_run(self):
        root = Path("test-output-ui-server-demo-filter")
        shutil.rmtree(root, ignore_errors=True)
        try:
            real_run = root / "real.dashboard.json"
            fake_payload = root / "fake-payload.dashboard.json"
            example_run = root / "example_run" / "example-study.dashboard.json"

            self._write_dashboard(real_run, run_id="real", symbol="BTCUSDT")
            self._write_dashboard(fake_payload, run_id="FAKE_UI_MOCK_123", symbol="ETHUSDT")
            self._write_dashboard(example_run, run_id="example-study", symbol="SOLUSDT")

            artifacts = ui_server.list_dashboard_artifacts(root=str(root))
            blocked_payload = ui_server.load_dashboard_file(str(fake_payload), restrict_to_dir=str(root))
            blocked_example = ui_server.load_dashboard_file(str(example_run), restrict_to_dir=str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertEqual([item["run_id"] for item in artifacts], ["real"])
        self.assertIsNone(blocked_payload)
        self.assertIsNone(blocked_example)

    def test_load_latest_paper_dashboard_uses_real_order_telemetry(self):
        root = Path("test-output-ui-server-paper")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        db_path = root / "paper.sqlite"
        try:
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE order_telemetry (
                        telemetry_id TEXT PRIMARY KEY,
                        symbol TEXT,
                        side TEXT,
                        ts_signal TEXT,
                        ts_send TEXT,
                        ts_ack TEXT,
                        ts_last_fill TEXT,
                        qty_submitted REAL,
                        qty_filled REAL,
                        fee_quote REAL,
                        slip_bps REAL,
                        maker_ratio REAL,
                        was_rejected INTEGER,
                        risk_blocked INTEGER
                    )
                    """
                )
                connection.execute(
                    "CREATE TABLE funding_events (funding_event_id TEXT PRIMARY KEY, ts_utc TEXT, symbol TEXT, position_notional REAL, funding_rate REAL, funding_fee REAL, metadata_json TEXT)"
                )
                connection.execute(
                    """
                    INSERT INTO order_telemetry (
                        telemetry_id, symbol, side, ts_signal, ts_send, ts_ack, ts_last_fill,
                        qty_submitted, qty_filled, fee_quote, slip_bps, maker_ratio, was_rejected, risk_blocked
                    ) VALUES ('t1', 'BTCUSDT', 'BUY', '2026-04-26T00:00:00Z', '2026-04-26T00:00:01Z', '2026-04-26T00:00:02Z', '2026-04-26T00:00:03Z', 2.0, 1.0, 0.2, 5.0, 0.5, 0, 0)
                    """
                )
                connection.execute(
                    "INSERT INTO funding_events VALUES ('f1', '2026-04-26T00:00:00Z', 'BTCUSDT', 100.0, 0.0001, 0.01, '{}')"
                )
                connection.commit()
            finally:
                connection.close()

            artifacts = ui_server.list_paper_artifacts(root=str(root))
            payload = ui_server.load_latest_paper_dashboard(root=str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["symbol"], "BTCUSDT")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["visuals"]["source_mode"], "paper_trading")
        self.assertEqual(payload["artifacts"]["symbol"], "BTCUSDT")
        self.assertEqual(payload["metrics"]["total_trades"], 1)

    def test_load_latest_promoted_dashboard_ignores_non_promoted_files(self):
        root = Path("test-output-ui-server")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        try:
            older = root / "older.dashboard.json"
            newer_rejected = root / "newer.dashboard.json"
            latest_promoted = root / "latest.dashboard.json"

            older.write_text(
                json.dumps(
                    {
                        "run_id": "older",
                        "decision": "promoted",
                        "artifacts": {"final_status": "promoted", "symbol": "ETHUSDT"},
                        "metrics": {"selection_oos_net_pnl": 12.0},
                    }
                ),
                encoding="utf-8",
            )
            newer_rejected.write_text(
                json.dumps(
                    {
                        "run_id": "rejected",
                        "decision": "reject",
                        "artifacts": {"final_status": "reject", "symbol": "ETHUSDT"},
                        "metrics": {"selection_oos_net_pnl": 9.0},
                    }
                ),
                encoding="utf-8",
            )
            latest_promoted.write_text(
                json.dumps(
                    {
                        "run_id": "latest",
                        "decision": "promoted",
                        "artifacts": {"final_status": "promoted", "symbol": "BTCUSDT"},
                        "metrics": {"selection_oos_net_pnl": 33.0},
                    }
                ),
                encoding="utf-8",
            )

            os.utime(older, (1, 1))
            os.utime(newer_rejected, (2, 2))
            os.utime(latest_promoted, (3, 3))

            latest_payload = ui_server.load_latest_promoted_dashboard(root=str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertIsNotNone(latest_payload)
        self.assertEqual(latest_payload["run_id"], "latest")
        self.assertEqual(latest_payload["visuals"]["context"]["symbol"], "BTCUSDT")

    def test_load_latest_dashboard_returns_latest_finished_artifact_even_when_not_promoted(self):
        root = Path("test-output-ui-server-finished")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        try:
            promoted = root / "older.dashboard.json"
            rejected = root / "newest.dashboard.json"

            promoted.write_text(
                json.dumps(
                    {
                        "run_id": "older-promoted",
                        "decision": "promoted",
                        "artifacts": {"final_status": "promoted", "symbol": "SOLUSDT"},
                    }
                ),
                encoding="utf-8",
            )
            rejected.write_text(
                json.dumps(
                    {
                        "run_id": "newest-reject",
                        "decision": "reject",
                        "artifacts": {"final_status": "reject", "symbol": "ETHUSDT"},
                    }
                ),
                encoding="utf-8",
            )

            os.utime(promoted, (1, 1))
            os.utime(rejected, (2, 2))

            latest_payload = ui_server.load_latest_dashboard(root=str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertIsNotNone(latest_payload)
        self.assertEqual(latest_payload["run_id"], "newest-reject")
        self.assertEqual(latest_payload["visuals"]["context"]["symbol"], "ETHUSDT")

    def test_load_dashboard_file_accepts_path_under_outputs(self):
        root = Path("outputs") / "test-ui-server-path-containment"
        shutil.rmtree(root, ignore_errors=True)
        try:
            dashboard_path = root / "nested" / "allowed.dashboard.json"
            self._write_dashboard(dashboard_path, run_id="allowed", symbol="SOLUSDT")

            payload = ui_server.load_dashboard_file(str(dashboard_path), restrict_to_dir="outputs")
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["run_id"], "allowed")
        self.assertEqual(payload["visuals"]["context"]["symbol"], "SOLUSDT")

    def test_load_dashboard_file_rejects_dot_dot_traversal(self):
        root = Path("outputs") / "test-ui-server-path-containment"
        sibling = Path("outputs-evil")
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(sibling, ignore_errors=True)
        try:
            dashboard_path = sibling / "traversed.dashboard.json"
            self._write_dashboard(dashboard_path, run_id="traversed", symbol="ETHUSDT")

            payload = ui_server.load_dashboard_file(
                str(Path("outputs") / ".." / "outputs-evil" / "traversed.dashboard.json"),
                restrict_to_dir="outputs",
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(sibling, ignore_errors=True)

        self.assertIsNone(payload)

    def test_load_dashboard_file_rejects_sibling_directory_with_matching_prefix(self):
        sibling = Path("outputs-evil")
        shutil.rmtree(sibling, ignore_errors=True)
        try:
            dashboard_path = sibling / "prefixed.dashboard.json"
            self._write_dashboard(dashboard_path, run_id="prefixed", symbol="ETHUSDT")

            payload = ui_server.load_dashboard_file(str(dashboard_path), restrict_to_dir="outputs")
        finally:
            shutil.rmtree(sibling, ignore_errors=True)

        self.assertIsNone(payload)

    def test_load_dashboard_file_returns_none_for_missing_file(self):
        missing_path = Path("outputs") / "test-ui-server-path-containment" / "missing.dashboard.json"
        shutil.rmtree(missing_path.parent, ignore_errors=True)

        payload = ui_server.load_dashboard_file(str(missing_path), restrict_to_dir="outputs")

        self.assertIsNone(payload)

    def test_load_dashboard_file_returns_none_for_malformed_json(self):
        root = Path("outputs") / "test-ui-server-path-containment"
        shutil.rmtree(root, ignore_errors=True)
        try:
            dashboard_path = root / "invalid.dashboard.json"
            dashboard_path.parent.mkdir(parents=True, exist_ok=True)
            dashboard_path.write_text("{not-valid-json", encoding="utf-8")

            payload = ui_server.load_dashboard_file(str(dashboard_path), restrict_to_dir="outputs")
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertIsNone(payload)

    def test_list_dashboard_artifacts_returns_newest_first_with_status(self):
        root = Path("test-output-ui-server-list")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        try:
            oldest = root / "a.dashboard.json"
            middle = root / "b.dashboard.json"
            newest = root / "nested" / "c.dashboard.json"
            newest.parent.mkdir(parents=True, exist_ok=True)

            oldest.write_text(
                json.dumps(
                    {
                        "run_id": "older",
                        "decision": "reject",
                        "artifacts": {"final_status": "reject", "symbol": "ETHUSDT"},
                    }
                ),
                encoding="utf-8",
            )
            middle.write_text(
                json.dumps(
                    {
                        "run_id": "middle",
                        "decision": "promoted",
                        "artifacts": {"final_status": "promoted", "symbol": "SOLUSDT"},
                    }
                ),
                encoding="utf-8",
            )
            newest.write_text(
                json.dumps(
                    {
                        "run_id": "newest",
                        "decision": "promoted",
                        "artifacts": {"final_status": "promoted", "symbol": "BTCUSDT"},
                    }
                ),
                encoding="utf-8",
            )

            os.utime(oldest, (1, 1))
            os.utime(middle, (2, 2))
            os.utime(newest, (3, 3))

            artifacts = ui_server.list_dashboard_artifacts(root=str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertEqual([item["run_id"] for item in artifacts], ["newest", "middle", "older"])
        self.assertEqual(artifacts[0]["symbol"], "BTCUSDT")
        self.assertEqual(artifacts[0]["status"], "promoted")
        self.assertEqual(artifacts[-1]["status"], "reject")


if __name__ == "__main__":
    unittest.main()
