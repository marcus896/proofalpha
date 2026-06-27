import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.calibration.cost_capacity import write_cost_capacity_calibration_artifact
from engine.calibration.paper_feedback import write_paper_calibration_feedback_artifact
from engine.config.models import PromotionDecision, RunCard
from engine.data.fetch import fetch_binance_perps_snapshot
from engine.execution.no_key_executor import write_no_key_executor_report
from engine.execution.paper_closeout import write_phase9a_closeout_report
from engine.execution.paper_dashboard import write_paper_session_dashboard_artifact
from engine.execution.paper_export import export_paper_session
from engine.execution.paper_soak import write_public_ws_soak_closeout_report
from engine.execution.reconciliation import write_reconciliation_report
from engine.reporting.runcards import save_runcard


class HighRiskAtomicWriterTests(unittest.TestCase):
    def test_remaining_high_risk_json_artifact_writers_keep_existing_file_when_replace_fails(self) -> None:
        output_dir = Path("test-output-high-risk-atomic-writers")
        writers = [
            lambda path: save_runcard(
                path,
                RunCard(
                    run_id="run-a",
                    strategy_hash="hash-a",
                    phase="holdout",
                    split_id="split-a",
                    seed=7,
                    decision=PromotionDecision(decision="reject", reasons=["fixture"]),
                    metrics={"net_pnl": 1.0},
                    artifacts={"dashboard": "dashboard.json"},
                ),
            ),
            lambda path: write_cost_capacity_calibration_artifact(path, {"artifact_type": "cost_capacity"}),
            lambda path: write_paper_calibration_feedback_artifact(path, {"artifact_type": "paper_feedback"}),
            lambda path: write_no_key_executor_report(path, {"artifact_type": "no_key_executor"}),
            lambda path: write_phase9a_closeout_report(path, {"artifact_type": "phase9a_closeout"}),
            lambda path: write_paper_session_dashboard_artifact(path, {"artifact_type": "paper_dashboard"}),
            lambda path: write_public_ws_soak_closeout_report(path, {"artifact_type": "paper_soak"}),
            lambda path: write_reconciliation_report(path, {"artifact_type": "reconciliation"}),
        ]
        try:
            for index, writer in enumerate(writers):
                path = output_dir / f"artifact-{index}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"status":"old"}', encoding="utf-8")

                with patch("engine.io.artifacts.os.replace", side_effect=OSError("simulated replace crash")):
                    with self.assertRaisesRegex(OSError, "simulated replace crash"):
                        writer(path)

                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"status": "old"})
                self.assertEqual(list(path.parent.glob(".*.tmp-*")), [])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_binance_fetch_manifest_keeps_existing_manifest_when_replace_fails(self) -> None:
        output_dir = Path("test-output-high-risk-fetch-manifest")

        def fake_get(url: str) -> object:
            if "klines" in url:
                return [
                    [1704067200000, "100", "110", "95", "105", "1000"],
                    [1704070800000, "105", "115", "100", "110", "1100"],
                ]
            if "fundingRate" in url:
                return [{"fundingTime": 1704067200000, "fundingRate": "0.01"}]
            if "openInterestHist" in url:
                return [
                    {"timestamp": 1704067200000, "sumOpenInterest": "200"},
                    {"timestamp": 1704070800000, "sumOpenInterest": "225"},
                ]
            return []

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = output_dir / "fetch_manifest.json"
            manifest_path.write_text('{"status":"old"}', encoding="utf-8")

            with patch("engine.io.artifacts.os.replace", side_effect=OSError("simulated replace crash")):
                with self.assertRaisesRegex(OSError, "simulated replace crash"):
                    fetch_binance_perps_snapshot(
                        output_dir=output_dir,
                        symbol="BTCUSDT",
                        timeframe="1Hour",
                        lookback_days=30,
                        json_getter=fake_get,
                    )

            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), {"status": "old"})
            self.assertEqual(list(output_dir.glob(".*.tmp-*")), [])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_paper_export_manifest_keeps_existing_manifest_when_replace_fails(self) -> None:
        output_dir = Path("test-output-high-risk-paper-export")
        db_path = output_dir / "memory.sqlite"
        session_id = "session-atomic"
        try:
            from tests.app.test_phase9a_paper_export import _seed_paper_session

            _seed_paper_session(output_dir, db_path, session_id)

            first = export_paper_session(db_path, session_id=session_id, output_dir=output_dir / "exports")
            manifest_path = Path(str(first["manifest_path"]))
            manifest_path.write_text('{"status":"old"}', encoding="utf-8")

            with patch("engine.io.artifacts.os.replace", side_effect=OSError("simulated replace crash")):
                with self.assertRaisesRegex(OSError, "simulated replace crash"):
                    export_paper_session(db_path, session_id=session_id, output_dir=manifest_path.parent.parent)

            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), {"status": "old"})
            self.assertEqual(list(manifest_path.parent.glob(".*.tmp-*")), [])
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)


if __name__ == "__main__":
    unittest.main()
