import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.app.loop_readiness import build_loop_readiness_report
from engine.app.config import load_study_config


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _write_study(root: Path, *, real_source: bool, quality_flags: list[str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
    payload["run_id"] = "readiness-real" if real_source else "example-study"
    snapshot = payload["snapshot"]
    snapshot["quality_flags"] = quality_flags or []
    if real_source:
        snapshot["symbol"] = "BTCUSDT"
        snapshot["venue"] = "binance"
        snapshot["timeframe"] = "1Hour"
        snapshot["provenance"] = {
            "provider": "binance_perps",
            "fetch_manifest": "snapshots/BTCUSDT/fetch_manifest.json",
            "source_hash": "sha256:readiness-fixture",
            "field_confidence": {
                "liquidation_notional": "observed_public_forceorder_with_zero_buckets",
            },
        }
        snapshot["snapshot_id"] = "readiness-real-snapshot"
    path = root / "study.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _write_hydratable_study(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
    payload["run_id"] = "readiness-hydrate-real"
    snapshot = payload["snapshot"]
    for key, value in list(snapshot.items()):
        if isinstance(value, list) and len(value) == 120:
            snapshot[key] = value[:5]
    snapshot["snapshot_id"] = "readiness-hydrate-real-snapshot"
    snapshot["symbol"] = "BTCUSDT"
    snapshot["venue"] = "binance"
    snapshot["timeframe"] = "1Hour"
    snapshot["quality_flags"] = ["missing_liquidation_notional_count=5"]
    snapshot["liquidation_notional"] = [0.0] * 5

    candles_path = root / "candles.csv"
    funding_path = root / "funding_rates.csv"
    open_interest_path = root / "open_interest.csv"
    sidecar_path = root / "liquidation_notional.csv"
    candles = snapshot["candles"]
    candles_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        + "\n".join(
            f"{candle['timestamp']},{candle['open']},{candle['high']},{candle['low']},{candle['close']},{candle['volume']}"
            for candle in candles
        )
        + "\n",
        encoding="utf-8",
    )
    funding_path.write_text(
        "timestamp,funding_rate\n"
        + "\n".join(f"{candle['timestamp']},0.0" for candle in candles)
        + "\n",
        encoding="utf-8",
    )
    open_interest_path.write_text(
        "timestamp,open_interest\n"
        + "\n".join(f"{candle['timestamp']},100.0" for candle in candles)
        + "\n",
        encoding="utf-8",
    )
    sidecar_path.write_text(
        "timestamp,liquidation_notional\n"
        + "\n".join(
            f"{candle['timestamp']},{'12.5' if index == 0 else '0.0'}" for index, candle in enumerate(candles)
        )
        + "\n",
        encoding="utf-8",
    )
    snapshot["provenance"] = {
        "provider": "binance_perps",
        "fetch_manifest": str(root / "fetch_manifest.json"),
        "source_hash": "sha256:before-hydrate",
        "source_paths": {
            "candles": str(candles_path),
            "funding_rate": str(funding_path),
            "open_interest": str(open_interest_path),
        },
    }
    study_path = root / "study.json"
    study_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return study_path, sidecar_path


class LoopReadinessTests(unittest.TestCase):
    def test_readiness_blocks_example_study_even_when_quality_flags_are_clean(self) -> None:
        root = Path("test-loop-readiness-example")
        try:
            study_path = _write_study(root, real_source=False)
            report = build_loop_readiness_report(load_study_config(study_path), config_path=study_path)

            self.assertFalse(report["eligible"])
            self.assertIn("example_or_fixture_study", report["blockers"])
            self.assertIn("missing_real_source_provenance", report["blockers"])
        finally:
            _clean_tree(root)

    def test_readiness_blocks_dirty_real_source_study(self) -> None:
        root = Path("test-loop-readiness-dirty")
        try:
            study_path = _write_study(
                root,
                real_source=True,
                quality_flags=["missing_liquidation_notional_count=120"],
            )
            report = build_loop_readiness_report(load_study_config(study_path), config_path=study_path)

            self.assertFalse(report["eligible"])
            self.assertIn("snapshot_quality_flags_present", report["blockers"])
            self.assertIn("missing_liquidation_notional_count=120", report["quality_flags"])
        finally:
            _clean_tree(root)

    def test_readiness_accepts_clean_real_source_study(self) -> None:
        root = Path("test-loop-readiness-clean")
        try:
            study_path = _write_study(root, real_source=True)
            report = build_loop_readiness_report(load_study_config(study_path), config_path=study_path)

            self.assertTrue(report["eligible"])
            self.assertEqual(report["blockers"], [])
            self.assertEqual(report["liquidation_coverage"]["covered"], 120)
            self.assertTrue(report["run_ready"])
            self.assertFalse(report["research_ready"])
            self.assertFalse(report["improvement_ready"])
            self.assertFalse(report["can_claim_strategy_improvement"])
            self.assertEqual(report["data_sufficiency"]["profile"], "strict_v3")
            self.assertIn("insufficient_history_for_v3_improvement", report["data_sufficiency"]["blockers"])
        finally:
            _clean_tree(root)

    def test_readiness_blocks_real_source_without_liquidation_field_confidence(self) -> None:
        root = Path("test-loop-readiness-missing-liq-confidence")
        try:
            study_path = _write_study(root, real_source=True)
            payload = json.loads(study_path.read_text(encoding="utf-8"))
            payload["snapshot"]["provenance"]["field_confidence"] = {}
            study_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

            report = build_loop_readiness_report(load_study_config(study_path), config_path=study_path)

            self.assertFalse(report["eligible"])
            self.assertIn("missing_liquidation_field_confidence", report["blockers"])
        finally:
            _clean_tree(root)

    def test_readiness_blocks_real_source_with_too_few_candles(self) -> None:
        root = Path("test-loop-readiness-too-few-candles")
        try:
            study_path = _write_study(root, real_source=True)
            payload = json.loads(study_path.read_text(encoding="utf-8"))
            snapshot = payload["snapshot"]
            for key, value in list(snapshot.items()):
                if isinstance(value, list) and len(value) == 120:
                    snapshot[key] = value[:1]
            study_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

            report = build_loop_readiness_report(load_study_config(study_path), config_path=study_path)

            self.assertFalse(report["eligible"])
            self.assertEqual(report["candle_count"], 1)
            self.assertEqual(report["minimum_candle_count"], 5)
            self.assertIn("insufficient_candle_count", report["blockers"])
        finally:
            _clean_tree(root)

    def test_cli_loop_readiness_writes_json_and_uses_exit_code(self) -> None:
        root = Path("test-loop-readiness-cli")
        output_path = root / "readiness.json"
        try:
            study_path = _write_study(root, real_source=False)
            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "loop-readiness",
                        "--config",
                        str(study_path),
                        "--output",
                        str(output_path),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 2)
            self.assertFalse(printed["eligible"])
            self.assertTrue(printed["run_ready"])
            self.assertFalse(printed["research_ready"])
            self.assertEqual(written["blockers"], printed["blockers"])
            self.assertEqual(written["data_sufficiency"]["profile"], "strict_v3")
        finally:
            _clean_tree(root)

    def test_cli_loop_readiness_scan_reports_eligible_and_blocked_studies(self) -> None:
        root = Path("test-loop-readiness-scan")
        output_path = root / "scan.json"
        try:
            clean_path = _write_study(root / "clean", real_source=True)
            dirty_path = _write_study(
                root / "dirty",
                real_source=True,
                quality_flags=["missing_liquidation_notional_count=120"],
            )
            example_path = _write_study(root / "example", real_source=False)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "loop-readiness-scan",
                        "--dir",
                        str(root),
                        "--output",
                        str(output_path),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["study_count"], 3)
            self.assertEqual(printed["eligible_count"], 1)
            self.assertEqual(printed["blocked_count"], 2)
            self.assertEqual(written["eligible"][0]["config_path"], str(clean_path))
            blocked_paths = {item["config_path"] for item in written["blocked"]}
            self.assertEqual(blocked_paths, {str(dirty_path), str(example_path)})
        finally:
            _clean_tree(root)

    def test_cli_loop_readiness_scan_can_require_an_eligible_study(self) -> None:
        root = Path("test-loop-readiness-scan-require-eligible")
        try:
            _write_study(root / "example", real_source=False)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "loop-readiness-scan",
                        "--dir",
                        str(root),
                        "--require-eligible",
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["eligible_count"], 0)
            self.assertEqual(printed["blocked_count"], 1)
        finally:
            _clean_tree(root)

    def test_cli_hydrate_study_liquidations_creates_readiness_eligible_output(self) -> None:
        root = Path("test-loop-readiness-hydrate-liquidations")
        output_path = root / "hydrated-study.json"
        try:
            study_path, sidecar_path = _write_hydratable_study(root)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "hydrate-study-liquidations",
                        "--config",
                        str(study_path),
                        "--liquidations",
                        str(sidecar_path),
                        "--output",
                        str(output_path),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            hydrated = load_study_config(output_path)
            readiness = build_loop_readiness_report(hydrated, config_path=output_path)
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "hydrated")
            self.assertEqual(hydrated.snapshot.liquidation_notional, [12.5, 0.0, 0.0, 0.0, 0.0])
            self.assertEqual(hydrated.snapshot.quality_flags, [])
            self.assertTrue(readiness["eligible"])
            self.assertEqual(readiness["liquidation_coverage"]["covered"], 5)
            self.assertEqual(hydrated.snapshot.provenance["liquidation_sidecar_source"], "binance_public_ws_forceOrder")
        finally:
            _clean_tree(root)

    def test_cli_verify_study_liquidations_reports_ready_without_writing_hydrated_study(self) -> None:
        root = Path("test-loop-readiness-verify-liquidations")
        output_path = root / "sidecar-report.json"
        hydrated_path = root / "hydrated-study.json"
        try:
            study_path, sidecar_path = _write_hydratable_study(root)

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "verify-study-liquidations",
                        "--config",
                        str(study_path),
                        "--liquidations",
                        str(sidecar_path),
                        "--output",
                        str(output_path),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "ready")
            self.assertEqual(written["status"], "ready")
            self.assertEqual(printed["liquidation_coverage"]["covered"], 5)
            self.assertFalse(hydrated_path.exists())
        finally:
            _clean_tree(root)

    def test_cli_hydrate_study_liquidations_blocks_negative_sidecar_values(self) -> None:
        root = Path("test-loop-readiness-hydrate-negative-liquidations")
        output_path = root / "hydrated-study.json"
        try:
            study_path, sidecar_path = _write_hydratable_study(root)
            payload = json.loads(study_path.read_text(encoding="utf-8"))
            candles = payload["snapshot"]["candles"]
            sidecar_path.write_text(
                "timestamp,liquidation_notional\n"
                + "\n".join(
                    f"{candle['timestamp']},{'-1.0' if index == 1 else '12.5' if index == 0 else '0.0'}"
                    for index, candle in enumerate(candles)
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "hydrate-study-liquidations",
                        "--config",
                        str(study_path),
                        "--liquidations",
                        str(sidecar_path),
                        "--output",
                        str(output_path),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            hydrated = load_study_config(output_path)
            readiness = build_loop_readiness_report(hydrated, config_path=output_path)
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "hydrated_with_quality_issues")
            self.assertIn("negative_liquidation_notional_count=1", printed["quality_issues"])
            self.assertFalse(readiness["eligible"])
            self.assertIn("snapshot_quality_issues_present", readiness["blockers"])
        finally:
            _clean_tree(root)

    def test_cli_hydrate_study_liquidations_require_ready_does_not_write_bad_output(self) -> None:
        root = Path("test-loop-readiness-hydrate-require-ready-negative")
        output_path = root / "hydrated-study.json"
        try:
            study_path, sidecar_path = _write_hydratable_study(root)
            payload = json.loads(study_path.read_text(encoding="utf-8"))
            candles = payload["snapshot"]["candles"]
            sidecar_path.write_text(
                "timestamp,liquidation_notional\n"
                f"{candles[0]['timestamp']},12.5\n"
                f"{candles[1]['timestamp']},-1.0\n",
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "hydrate-study-liquidations",
                        "--config",
                        str(study_path),
                        "--liquidations",
                        str(sidecar_path),
                        "--output",
                        str(output_path),
                        "--require-ready",
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "not_ready")
            self.assertFalse(output_path.exists())
            self.assertIn("negative_liquidation_notional_count=1", printed["quality_issues"])
        finally:
            _clean_tree(root)

    def test_cli_verify_study_liquidations_blocks_negative_sidecar_values(self) -> None:
        root = Path("test-loop-readiness-verify-negative-liquidations")
        output_path = root / "sidecar-report.json"
        try:
            study_path, sidecar_path = _write_hydratable_study(root)
            payload = json.loads(study_path.read_text(encoding="utf-8"))
            candles = payload["snapshot"]["candles"]
            sidecar_path.write_text(
                "timestamp,liquidation_notional\n"
                f"{candles[0]['timestamp']},12.5\n"
                f"{candles[1]['timestamp']},-1.0\n",
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "verify-study-liquidations",
                        "--config",
                        str(study_path),
                        "--liquidations",
                        str(sidecar_path),
                        "--output",
                        str(output_path),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "not_ready")
            self.assertIn("negative_liquidation_notional_count=1", printed["quality_issues"])
            self.assertEqual(printed["liquidation_coverage"]["covered"], 2)
        finally:
            _clean_tree(root)

    def test_cli_verify_study_liquidations_blocks_unhydratable_config_without_traceback(self) -> None:
        root = Path("test-loop-readiness-verify-unhydratable")
        output_path = root / "sidecar-report.json"
        sidecar_path = root / "liquidation_notional.csv"
        try:
            root.mkdir(parents=True, exist_ok=True)
            sidecar_path.write_text(
                "timestamp,liquidation_notional\n"
                "2024-01-01T00:00:00+00:00,-1.0\n",
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "verify-study-liquidations",
                        "--config",
                        "examples/minimal_builtin_study.json",
                        "--liquidations",
                        str(sidecar_path),
                        "--output",
                        str(output_path),
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "not_ready")
            self.assertEqual(written["status"], "not_ready")
            self.assertIn("source_paths.candles", printed["error"])
        finally:
            _clean_tree(root)

    def test_cli_hydrate_study_liquidations_require_ready_blocks_unhydratable_config_without_output(self) -> None:
        root = Path("test-loop-readiness-hydrate-require-ready-unhydratable")
        output_path = root / "hydrated-study.json"
        sidecar_path = root / "liquidation_notional.csv"
        try:
            root.mkdir(parents=True, exist_ok=True)
            sidecar_path.write_text(
                "timestamp,liquidation_notional\n"
                "2024-01-01T00:00:00+00:00,-1.0\n",
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "hydrate-study-liquidations",
                        "--config",
                        "examples/minimal_builtin_study.json",
                        "--liquidations",
                        str(sidecar_path),
                        "--output",
                        str(output_path),
                        "--require-ready",
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "not_ready")
            self.assertFalse(output_path.exists())
            self.assertIn("source_paths.candles", printed["error"])
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
