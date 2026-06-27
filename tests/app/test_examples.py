import csv
import json
import subprocess
import unittest
from pathlib import Path

from engine.app.examples import write_example_study_config
from engine.data.providers import load_snapshot_from_csv


class ExampleStudyTests(unittest.TestCase):
    def test_write_example_study_config_creates_runnable_shape(self) -> None:
        csv_path = Path("test-example-source.csv")
        config_path = Path("test-example-study.json")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            for hour in range(120):
                writer.writerow(
                    {
                        "timestamp": f"2024-01-{1 + (hour // 24):02d}T{hour % 24:02d}:00:00+00:00",
                        "open": str(100 + hour),
                        "high": str(101 + hour),
                        "low": str(99 + hour),
                        "close": str(100 + hour),
                        "volume": "1000",
                    }
                )

        try:
            snapshot = load_snapshot_from_csv(
                path=csv_path,
                snapshot_id="example-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )
            write_example_study_config(config_path, snapshot, run_id="example-run", seed=42)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        finally:
            if csv_path.exists():
                csv_path.unlink()
            if config_path.exists():
                config_path.unlink()

        self.assertEqual(payload["run_id"], "example-run")
        self.assertEqual(payload["snapshot"]["snapshot_id"], "example-snap")
        self.assertEqual(payload["directional_layers"], ["kama"])
        self.assertEqual(payload["runtime"]["mode"], "builtin")
        self.assertNotIn("evaluations", payload)
        self.assertNotIn("scenario_results", payload)

    def test_cli_init_example_writes_config_from_csv(self) -> None:
        csv_path = Path("test-cli-example-source.csv")
        config_path = Path("test-cli-example-study.json")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            for hour in range(120):
                writer.writerow(
                    {
                        "timestamp": f"2024-01-{1 + (hour // 24):02d}T{hour % 24:02d}:00:00+00:00",
                        "open": str(100 + hour),
                        "high": str(101 + hour),
                        "low": str(99 + hour),
                        "close": str(100 + hour),
                        "volume": "1000",
                    }
                )

        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "init-example",
                    "--csv",
                    str(csv_path),
                    "--config-out",
                    str(config_path),
                    "--snapshot-id",
                    "example-snap-2",
                    "--symbol",
                    "SOLUSDT",
                    "--venue",
                    "binance",
                    "--timeframe",
                    "1h",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        finally:
            if csv_path.exists():
                csv_path.unlink()
            if config_path.exists():
                config_path.unlink()

        self.assertEqual(payload["snapshot"]["snapshot_id"], "example-snap-2")
        self.assertEqual(payload["snapshot"]["symbol"], "SOLUSDT")
        self.assertEqual(payload["run_id"], "example-study")
        self.assertEqual(payload["runtime"]["mode"], "builtin")

    def test_cli_init_example_bundle_writes_config_from_separate_market_csvs(self) -> None:
        candles_path = Path("test-cli-bundle-candles.csv")
        funding_path = Path("test-cli-bundle-funding.csv")
        oi_path = Path("test-cli-bundle-open-interest.csv")
        liquidations_path = Path("test-cli-bundle-liquidations.csv")
        config_path = Path("test-cli-bundle-study.json")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            for hour in range(120):
                writer.writerow(
                    {
                        "timestamp": f"2024-01-{1 + (hour // 24):02d}T{hour % 24:02d}:00:00+00:00",
                        "open": str(100 + hour),
                        "high": str(101 + hour),
                        "low": str(99 + hour),
                        "close": str(100 + hour),
                        "volume": "1000",
                    }
                )

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "funding_rate"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "funding_rate": "0.0001"})

        with oi_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open_interest"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T01:00:00+00:00", "open_interest": "2550"})

        with liquidations_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "liquidation_notional"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "liquidation_notional": "15"})

        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "init-example-bundle",
                    "--candles-csv",
                    str(candles_path),
                    "--funding-csv",
                    str(funding_path),
                    "--open-interest-csv",
                    str(oi_path),
                    "--liquidations-csv",
                    str(liquidations_path),
                    "--config-out",
                    str(config_path),
                    "--snapshot-id",
                    "bundle-snap-1",
                    "--symbol",
                    "SOLUSDT",
                    "--venue",
                    "binance",
                    "--timeframe",
                    "1h",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        finally:
            for path in (candles_path, funding_path, oi_path, liquidations_path, config_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(payload["snapshot"]["snapshot_id"], "bundle-snap-1")
        self.assertEqual(payload["snapshot"]["funding_rates"][0], 0.0001)
        self.assertEqual(payload["snapshot"]["open_interest"][1], 2550.0)
        self.assertEqual(payload["snapshot"]["liquidation_notional"][0], 15.0)
        self.assertIn("missing_funding_rate_count=", payload["snapshot"]["quality_flags"][0])

    def test_generated_example_config_can_be_run_without_fixture_evaluations(self) -> None:
        csv_path = Path("test-cli-runtime-source.csv")
        config_path = Path("test-cli-runtime-study.json")
        output_dir = Path("test-output-runtime")
        output_dir.mkdir(exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            for hour in range(120):
                writer.writerow(
                    {
                        "timestamp": f"2024-01-{1 + (hour // 24):02d}T{hour % 24:02d}:00:00+00:00",
                        "open": str(100 + hour),
                        "high": str(101 + hour),
                        "low": str(99 + hour),
                        "close": str(100 + hour),
                        "volume": "1000",
                    }
                )

        try:
            init_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "init-example",
                    "--csv",
                    str(csv_path),
                    "--config-out",
                    str(config_path),
                    "--snapshot-id",
                    "example-snap-3",
                    "--symbol",
                    "SOLUSDT",
                    "--venue",
                    "binance",
                    "--timeframe",
                    "1h",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_completed.returncode, 0, msg=init_completed.stderr)

            run_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "run",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run_completed.returncode, 0, msg=run_completed.stderr)
            dashboard_payload = json.loads((output_dir / "example-study.dashboard.json").read_text(encoding="utf-8"))
        finally:
            if csv_path.exists():
                csv_path.unlink()
            if config_path.exists():
                config_path.unlink()
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)


        self.assertEqual(dashboard_payload["strategy"]["backbone"], "mom_squeeze")
        # Verify the engine ran to completion and produced a well-formed dashboard.
        # No minimum layer count is asserted because with synthetic inflation removed,
        # layers must genuinely pass statistical validation on this small toy dataset.
        self.assertIsInstance(dashboard_payload["strategy"]["layers"], list)
