import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.execution.paper_daemon import PaperDaemonDryRunConfig, PaperRiskLimits, run_paper_daemon_dry_run
from engine.execution.paper_export import export_paper_session, restore_paper_export_smoke
from engine.strategy.artifacts import build_strategy_artifact, write_strategy_artifact


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _valid_artifact_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "strategy_id": "strategy-phase9a-export",
        "family": "momentum",
        "variant_id": "variant-phase9a-export",
        "venue": "binance_usdm",
        "signal_timeframe": "1h",
        "execution_timeframe": "15m",
        "symbol_scope": ["BTCUSDT"],
        "regime_scope": ["trend", "neutral"],
        "feature_version": "feature-v1",
        "data_snapshot_ids": ["snapshot-v1"],
        "execution_model": "binance_usdm_v3",
        "cost_model": "cost-v1",
        "scenario_pack": "scenario-v1",
        "parameters": {"lookback": 48},
        "risk_limits": {"max_notional": 1000.0, "max_drawdown": 0.2},
        "order_policy": {"order_type": "limit", "time_in_force": "GTX", "post_only": True},
        "validation_report_id": "validation-v1",
        "code_sha": "code-sha",
        "rollout_stage": "paper",
        "promotion_approved": True,
        "validation_status": "passed",
        "created_at_utc": "2026-04-29T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _write_fixture(root: Path) -> Path:
    fixture_path = root / "market-fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "order_intents": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "qty": 1.0,
                        "expected_price": 100.0,
                        "limit_price": 100.5,
                        "order_type": "limit",
                        "post_only": True,
                    }
                ],
                "market_snapshots": [
                    {
                        "ts": "2026-04-29T00:00:00Z",
                        "symbol": "BTCUSDT",
                        "bid": 99.9,
                        "ask": 100.1,
                        "last_trade_price": 100.0,
                        "traded_qty_at_price": 2.0,
                        "visible_depth_qty": 5.0,
                        "topn_depth_qty": 10.0,
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return fixture_path


def _seed_paper_session(root: Path, db_path: Path, session_id: str) -> None:
    artifact = build_strategy_artifact(_valid_artifact_payload())
    artifact_path = write_strategy_artifact(root / "artifact.strategy-artifact.json", artifact)
    fixture_path = _write_fixture(root)
    run_paper_daemon_dry_run(
        PaperDaemonDryRunConfig(
            db_path=db_path,
            artifact_paths=(artifact_path,),
            market_fixture_path=fixture_path,
            session_id=session_id,
            host_id="oracle-a1-export-test",
            risk_limits=PaperRiskLimits(max_per_symbol_notional=1000.0, max_spread_bps=25.0),
        )
    )


class Phase9APaperExportTests(unittest.TestCase):
    def test_export_writes_checksumed_bundle_backup_manifest_and_restore_smoke(self) -> None:
        root = Path("test-phase9a-paper-export")
        db_path = root / "memory.sqlite"
        restore_db_path = root / "restore.sqlite"
        try:
            _seed_paper_session(root, db_path, "paper-export-session")

            export = export_paper_session(
                db_path,
                session_id="paper-export-session",
                output_dir=root / "exports",
            )
            restore = restore_paper_export_smoke(
                Path(export["bundle_dir"]),
                restore_db_path=restore_db_path,
            )

            manifest_path = Path(export["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(export["status"], "exported")
            self.assertEqual(manifest["session_id"], "paper-export-session")
            self.assertEqual(manifest["table_counts"]["paper_sessions"], 1)
            self.assertGreater(manifest["table_counts"]["paper_stream_events"], 0)
            self.assertIn("paper_stream_events.jsonl", manifest["file_hashes"])
            self.assertEqual(len(export["bundle_digest"]), 64)
            self.assertTrue((Path(export["bundle_dir"]) / "sqlite" / "memory.sqlite").exists())

            connection = sqlite3.connect(db_path)
            try:
                backup_row = connection.execute(
                    "SELECT backup_id, backup_location, snapshot_digest, status FROM backup_manifests"
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(backup_row[0], export["backup_id"])
            self.assertEqual(backup_row[1], export["bundle_dir"])
            self.assertEqual(backup_row[2], export["bundle_digest"])
            self.assertEqual(backup_row[3], "exported")

            self.assertEqual(restore["restore_status"], "verified")
            self.assertEqual(restore["session_id"], "paper-export-session")
            self.assertEqual(restore["source_bundle_digest"], export["bundle_digest"])
            self.assertEqual(len(restore["verification_digest"]), 64)
        finally:
            _clean_tree(root)

    def test_cli_paper_export_can_run_restore_smoke(self) -> None:
        root = Path("test-phase9a-paper-export-cli")
        db_path = root / "memory.sqlite"
        restore_db_path = root / "restore.sqlite"
        try:
            _seed_paper_session(root, db_path, "paper-export-cli-session")

            with mock.patch("builtins.print") as print_mock:
                self.assertEqual(
                    main(
                        [
                            "paper-export",
                            "--db",
                            str(db_path),
                            "--session-id",
                            "paper-export-cli-session",
                            "--output-dir",
                            str(root / "exports"),
                            "--restore-smoke-db",
                            str(restore_db_path),
                        ]
                    ),
                    0,
                )

            payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(payload["status"], "exported")
            self.assertEqual(payload["restore_smoke"]["restore_status"], "verified")
            self.assertTrue(Path(payload["manifest_path"]).exists())
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
