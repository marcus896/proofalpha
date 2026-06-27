import csv
import unittest
from pathlib import Path

from engine.data.providers import (
    build_snapshot_from_bundle,
    build_snapshot_from_csv,
    load_snapshot_bundle_from_csv,
    load_snapshot_from_csv,
)


class CsvProviderTests(unittest.TestCase):
    def test_build_snapshot_from_csv_populates_phase1_metadata(self) -> None:
        csv_path = Path("test-build-single-snapshot.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "trade_count",
                    "funding_rate",
                    "mark_price",
                    "index_price",
                    "spread_bps",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "1000",
                    "trade_count": "7",
                    "funding_rate": "0.0001",
                    "mark_price": "100.4",
                    "index_price": "100.3",
                    "spread_bps": "3.5",
                }
            )

        try:
            snapshot = build_snapshot_from_csv(
                path=csv_path,
                snapshot_id="build-single-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )
        finally:
            if csv_path.exists():
                csv_path.unlink()

        self.assertEqual(snapshot.snapshot_id, "build-single-snap")
        self.assertEqual(snapshot.provenance["build_mode"], "single_csv")
        self.assertEqual(snapshot.provenance["build_version"], "phase1_snapshot_builder_v1")
        self.assertRegex(snapshot.provenance["source_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(snapshot.provenance["raw_source_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(snapshot.provenance["dataset_version"], r"^[0-9a-f]{64}$")
        self.assertEqual(snapshot.provenance["source_metadata_version"], "v3_phase1_source_metadata_v1")
        self.assertEqual(snapshot.provenance["parser_version"], "csv_snapshot_parser_v1")
        self.assertEqual(snapshot.provenance["normalization_version"], "v3_phase1_snapshot_normalization_v1")
        self.assertEqual(snapshot.provenance["exchange_rules_version"], "runtime_venue_preset_v1")
        self.assertEqual(snapshot.provenance["feature_version"], "phase1_snapshot_features_v1")
        self.assertEqual(snapshot.provenance["scenario_pack_version"], "not_applied")
        self.assertEqual(snapshot.provenance["cost_model_version"], "not_applied")
        self.assertIsNotNone(snapshot.venue_profile)
        self.assertIsNotNone(snapshot.quality_report)
        self.assertEqual(snapshot.quality_report.source_checks["build_version"], "phase1_snapshot_builder_v1")
        self.assertEqual(snapshot.quality_report.source_checks["source_hash"], snapshot.provenance["source_hash"])
        self.assertEqual(snapshot.candles[0].trade_count, 7)
        self.assertEqual(snapshot.mark_price, [100.4])
        self.assertEqual(snapshot.index_price, [100.3])
        self.assertEqual(snapshot.spread_bps, [3.5])
        self.assertEqual(snapshot.open_interest_usd, [0.0])
        self.assertEqual(snapshot.provenance["phase1_field_population"]["mark_price"], "observed")
        self.assertEqual(snapshot.provenance["phase1_field_population"]["ret_1"], "derived")
        self.assertEqual(snapshot.quality_report.metrics["candle_count"], 1)
        self.assertEqual(snapshot.quality_report.metrics["funding_coverage_ratio"], 1.0)
        self.assertEqual(snapshot.quality_report.metrics["open_interest_coverage_ratio"], 0.0)
        self.assertEqual(snapshot.quality_report.metrics["liquidation_notional_coverage_ratio"], 0.0)

    def test_build_snapshot_from_bundle_populates_phase1_metadata(self) -> None:
        candles_path = Path("test-build-bundle-candles.csv")
        funding_path = Path("test-build-bundle-funding.csv")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "open": "100", "high": "101", "low": "99", "close": "100.5", "volume": "1000"})
            writer.writerow({"timestamp": "2024-01-01T01:00:00+00:00", "open": "101", "high": "102", "low": "100", "close": "101.5", "volume": "1100"})

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "funding_rate"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "funding_rate": "0.0001"})

        try:
            snapshot = build_snapshot_from_bundle(
                candles_path=candles_path,
                snapshot_id="build-bundle-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_path=funding_path,
            )
        finally:
            for path in (candles_path, funding_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(snapshot.snapshot_id, "build-bundle-snap")
        self.assertEqual(snapshot.provenance["build_mode"], "bundle_csv")
        self.assertEqual(snapshot.provenance["build_version"], "phase1_snapshot_builder_v1")
        self.assertRegex(snapshot.provenance["source_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(snapshot.provenance["raw_source_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(snapshot.provenance["dataset_version"], r"^[0-9a-f]{64}$")
        self.assertEqual(snapshot.provenance["source_metadata_version"], "v3_phase1_source_metadata_v1")
        self.assertEqual(snapshot.provenance["parser_version"], "csv_snapshot_parser_v1")
        self.assertEqual(snapshot.provenance["normalization_version"], "v3_phase1_snapshot_normalization_v1")
        self.assertIsNotNone(snapshot.venue_profile)
        self.assertIsNotNone(snapshot.quality_report)
        self.assertEqual(snapshot.quality_report.source_checks["build_version"], "phase1_snapshot_builder_v1")
        self.assertEqual(snapshot.quality_report.source_checks["source_hash"], snapshot.provenance["source_hash"])
        self.assertEqual(snapshot.quality_report.metrics["candle_count"], 2)
        self.assertEqual(snapshot.mark_price, [100.5, 101.5])
        self.assertEqual(snapshot.index_price, [100.5, 101.5])
        self.assertEqual(snapshot.open_interest_usd, [0.0, 0.0])
        self.assertEqual(snapshot.ret_1, [0.0, (101.5 / 100.5) - 1.0])
        self.assertEqual(snapshot.provenance["phase1_field_population"]["mark_price"], "close_fallback")
        self.assertEqual(snapshot.quality_report.metrics["funding_coverage_ratio"], 0.5)
        self.assertEqual(snapshot.quality_report.metrics["open_interest_coverage_ratio"], 0.0)
        self.assertEqual(snapshot.quality_report.metrics["liquidation_notional_coverage_ratio"], 0.0)

    def test_load_snapshot_from_csv_raises_row_context_for_invalid_required_timestamp(self) -> None:
        csv_path = Path("test-snapshot-invalid-required-ts.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["timestamp", "open", "high", "low", "close", "volume"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "not-a-real-timestamp",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "1000",
                }
            )

        try:
            with self.assertRaisesRegex(ValueError, r"row 2.*timestamp.*not-a-real-timestamp"):
                load_snapshot_from_csv(
                    path=csv_path,
                    snapshot_id="csv-snap-invalid-ts",
                    symbol="SOLUSDT",
                    venue="binance",
                    timeframe="1h",
                    maker_fee_bps=2.0,
                    taker_fee_bps=5.0,
                )
        finally:
            csv_path.unlink()

    def test_load_snapshot_from_csv_raises_row_context_for_invalid_required_numeric_field(self) -> None:
        csv_path = Path("test-snapshot-invalid-required-open.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["timestamp", "open", "high", "low", "close", "volume"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "open": "N/A",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "1000",
                }
            )

        try:
            with self.assertRaisesRegex(ValueError, r"row 2.*open.*N/A"):
                load_snapshot_from_csv(
                    path=csv_path,
                    snapshot_id="csv-snap-invalid-open",
                    symbol="SOLUSDT",
                    venue="binance",
                    timeframe="1h",
                    maker_fee_bps=2.0,
                    taker_fee_bps=5.0,
                )
        finally:
            csv_path.unlink()

    def test_load_snapshot_from_csv_supports_optional_market_fields(self) -> None:
        csv_path = Path("test-snapshot.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "funding_rate",
                    "open_interest",
                    "liquidation_notional",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "1000",
                    "funding_rate": "0.0001",
                    "open_interest": "2500",
                    "liquidation_notional": "0",
                }
            )
            writer.writerow(
                {
                    "timestamp": "2024-01-01T01:00:00+00:00",
                    "open": "101",
                    "high": "102",
                    "low": "100",
                    "close": "101.5",
                    "volume": "1100",
                    "funding_rate": "0.0002",
                    "open_interest": "2550",
                    "liquidation_notional": "25",
                }
            )

        try:
            snapshot = load_snapshot_from_csv(
                path=csv_path,
                snapshot_id="csv-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )
        finally:
            csv_path.unlink()

        self.assertEqual(snapshot.snapshot_id, "csv-snap")
        self.assertEqual(len(snapshot.candles), 2)
        self.assertEqual(snapshot.candles[0].close, 100.5)
        self.assertEqual(snapshot.funding_rates, [0.0001, 0.0002])
        self.assertEqual(snapshot.open_interest, [2500.0, 2550.0])
        self.assertEqual(snapshot.liquidation_notional, [0.0, 25.0])

    def test_load_snapshot_from_csv_populates_phase1_metadata(self) -> None:
        csv_path = Path("test-snapshot-phase1-metadata.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "funding_rate",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "1000",
                    "funding_rate": "0.0001",
                }
            )
            writer.writerow(
                {
                    "timestamp": "2024-01-01T01:00:00+00:00",
                    "open": "101",
                    "high": "102",
                    "low": "100",
                    "close": "101.5",
                    "volume": "1100",
                    "funding_rate": "0.0002",
                }
            )

        try:
            snapshot = load_snapshot_from_csv(
                path=csv_path,
                snapshot_id="csv-snap-phase1",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )
        finally:
            csv_path.unlink()

        self.assertIsNotNone(snapshot.venue_profile)
        self.assertEqual(snapshot.venue_profile.venue, "binance")
        self.assertEqual(snapshot.venue_profile.funding_interval_h, 8)
        self.assertEqual(snapshot.venue_profile.mark_price_source, "exchange_mark")
        self.assertTrue(snapshot.venue_profile.maintenance_margin_schedule)
        self.assertIsNotNone(snapshot.quality_report)
        self.assertEqual(snapshot.quality_report.snapshot_id, "csv-snap-phase1")
        self.assertTrue(snapshot.quality_report.passed)
        self.assertEqual(snapshot.provenance["provider"], "csv")
        self.assertEqual(snapshot.provenance["build_mode"], "single_csv")
        self.assertEqual(snapshot.provenance["source_paths"]["candles"], str(csv_path))

    def test_load_snapshot_bundle_from_csv_aligns_market_sidecars_by_timestamp(self) -> None:
        candles_path = Path("test-bundle-candles.csv")
        funding_path = Path("test-bundle-funding.csv")
        oi_path = Path("test-bundle-open-interest.csv")
        liquidations_path = Path("test-bundle-liquidations.csv")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "open": "100", "high": "101", "low": "99", "close": "100.5", "volume": "1000"})
            writer.writerow({"timestamp": "2024-01-01T01:00:00+00:00", "open": "101", "high": "102", "low": "100", "close": "101.5", "volume": "1100"})

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
            writer.writerow({"timestamp": "2024-01-01T01:00:00+00:00", "liquidation_notional": "25"})

        try:
            snapshot = load_snapshot_bundle_from_csv(
                candles_path=candles_path,
                snapshot_id="bundle-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_path=funding_path,
                open_interest_path=oi_path,
                liquidation_notional_path=liquidations_path,
            )
        finally:
            for path in (candles_path, funding_path, oi_path, liquidations_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(snapshot.snapshot_id, "bundle-snap")
        self.assertEqual(len(snapshot.candles), 2)
        self.assertEqual(snapshot.funding_rates, [0.0001, 0.0])
        self.assertEqual(snapshot.open_interest, [0.0, 2550.0])
        self.assertEqual(snapshot.liquidation_notional, [15.0, 25.0])
        self.assertIn("missing_funding_rate_count=1", snapshot.quality_flags)
        self.assertIn("missing_open_interest_count=1", snapshot.quality_flags)
        self.assertIsNotNone(snapshot.quality_report)
        self.assertFalse(snapshot.quality_report.passed)
        self.assertIn("missing_funding_rate_count=1", snapshot.quality_report.issues)
        self.assertIn("missing_open_interest_count=1", snapshot.quality_report.issues)
        self.assertEqual(snapshot.provenance["provider"], "csv")
        self.assertEqual(snapshot.provenance["build_mode"], "bundle_csv")
        self.assertEqual(snapshot.provenance["source_paths"]["candles"], str(candles_path))
        self.assertEqual(snapshot.provenance["source_paths"]["funding_rate"], str(funding_path))
        self.assertEqual(snapshot.provenance["source_paths"]["open_interest"], str(oi_path))
        self.assertEqual(snapshot.provenance["source_paths"]["liquidation_notional"], str(liquidations_path))

    def test_load_snapshot_bundle_from_csv_records_orphan_sidecar_rows_in_quality_flags(self) -> None:
        candles_path = Path("test-bundle-orphan-candles.csv")
        funding_path = Path("test-bundle-orphan-funding.csv")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "open": "100", "high": "101", "low": "99", "close": "100.5", "volume": "1000"})

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "funding_rate"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "funding_rate": "0.0001"})
            writer.writerow({"timestamp": "2024-01-01T02:00:00+00:00", "funding_rate": "0.0003"})

        try:
            snapshot = load_snapshot_bundle_from_csv(
                candles_path=candles_path,
                snapshot_id="bundle-orphan-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_path=funding_path,
            )
        finally:
            for path in (candles_path, funding_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(snapshot.funding_rates, [0.0001])
        self.assertIn("orphan_funding_rate_count=1", snapshot.quality_flags)

    def test_load_snapshot_from_csv_supports_common_exchange_column_aliases(self) -> None:
        csv_path = Path("test-snapshot-aliases.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "open_time",
                    "Open",
                    "High",
                    "Low",
                    "Close",
                    "Volume",
                    "fundingRate",
                    "oi",
                    "liquidations",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "open_time": "2024-01-01T00:00:00+00:00",
                    "Open": "100",
                    "High": "101",
                    "Low": "99",
                    "Close": "100.5",
                    "Volume": "1000",
                    "fundingRate": "0.0001",
                    "oi": "2500",
                    "liquidations": "10",
                }
            )
            writer.writerow(
                {
                    "open_time": "2024-01-01T01:00:00+00:00",
                    "Open": "101",
                    "High": "102",
                    "Low": "100",
                    "Close": "101.5",
                    "Volume": "1100",
                    "fundingRate": "0.0002",
                    "oi": "2550",
                    "liquidations": "20",
                }
            )

        try:
            snapshot = load_snapshot_from_csv(
                path=csv_path,
                snapshot_id="csv-snap-aliases",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )
        finally:
            csv_path.unlink()

        self.assertEqual(len(snapshot.candles), 2)
        self.assertEqual(snapshot.candles[1].open, 101.0)
        self.assertEqual(snapshot.funding_rates, [0.0001, 0.0002])
        self.assertEqual(snapshot.open_interest, [2500.0, 2550.0])
        self.assertEqual(snapshot.liquidation_notional, [10.0, 20.0])

    def test_load_snapshot_bundle_from_csv_supports_sidecar_column_aliases(self) -> None:
        candles_path = Path("test-bundle-alias-candles.csv")
        funding_path = Path("test-bundle-alias-funding.csv")
        oi_path = Path("test-bundle-alias-open-interest.csv")
        liquidations_path = Path("test-bundle-alias-liquidations.csv")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "o", "h", "l", "c", "v"])
            writer.writeheader()
            writer.writerow({"time": "2024-01-01T00:00:00+00:00", "o": "100", "h": "101", "l": "99", "c": "100.5", "v": "1000"})
            writer.writerow({"time": "2024-01-01T01:00:00+00:00", "o": "101", "h": "102", "l": "100", "c": "101.5", "v": "1100"})

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["datetime", "funding"])
            writer.writeheader()
            writer.writerow({"datetime": "2024-01-01T00:00:00+00:00", "funding": "0.0001"})

        with oi_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "openInterest"])
            writer.writeheader()
            writer.writerow({"date": "2024-01-01T01:00:00+00:00", "openInterest": "2550"})

        with liquidations_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "liquidation"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "liquidation": "15"})
            writer.writerow({"timestamp": "2024-01-01T01:00:00+00:00", "liquidation": "25"})

        try:
            snapshot = load_snapshot_bundle_from_csv(
                candles_path=candles_path,
                snapshot_id="bundle-alias-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_path=funding_path,
                open_interest_path=oi_path,
                liquidation_notional_path=liquidations_path,
            )
        finally:
            for path in (candles_path, funding_path, oi_path, liquidations_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(len(snapshot.candles), 2)
        self.assertEqual(snapshot.funding_rates, [0.0001, 0.0])
        self.assertEqual(snapshot.open_interest, [0.0, 2550.0])
        self.assertEqual(snapshot.liquidation_notional, [15.0, 25.0])
        self.assertIn("missing_funding_rate_count=1", snapshot.quality_flags)
        self.assertIn("missing_open_interest_count=1", snapshot.quality_flags)

    def test_load_snapshot_from_csv_supports_epoch_millisecond_timestamps(self) -> None:
        csv_path = Path("test-snapshot-epoch-ms.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["open_time", "open", "high", "low", "close", "volume"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "open_time": "1704067200000",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "1000",
                }
            )
            writer.writerow(
                {
                    "open_time": "1704070800000",
                    "open": "101",
                    "high": "102",
                    "low": "100",
                    "close": "101.5",
                    "volume": "1100",
                }
            )

        try:
            snapshot = load_snapshot_from_csv(
                path=csv_path,
                snapshot_id="csv-snap-epoch-ms",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )
        finally:
            csv_path.unlink()

        self.assertEqual(snapshot.candles[0].timestamp.isoformat(), "2024-01-01T00:00:00+00:00")
        self.assertEqual(snapshot.candles[1].timestamp.isoformat(), "2024-01-01T01:00:00+00:00")

    def test_load_snapshot_bundle_from_csv_aligns_epoch_second_and_millisecond_sidecars(self) -> None:
        candles_path = Path("test-bundle-epoch-candles.csv")
        funding_path = Path("test-bundle-epoch-funding.csv")
        oi_path = Path("test-bundle-epoch-open-interest.csv")
        liquidations_path = Path("test-bundle-epoch-liquidations.csv")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["open_time", "o", "h", "l", "c", "v"])
            writer.writeheader()
            writer.writerow({"open_time": "1704067200000", "o": "100", "h": "101", "l": "99", "c": "100.5", "v": "1000"})
            writer.writerow({"open_time": "1704070800000", "o": "101", "h": "102", "l": "100", "c": "101.5", "v": "1100"})

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "funding"])
            writer.writeheader()
            writer.writerow({"time": "1704067200", "funding": "0.0001"})

        with oi_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "oi"])
            writer.writeheader()
            writer.writerow({"time": "1704070800000", "oi": "2550"})

        with liquidations_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "liquidation"])
            writer.writeheader()
            writer.writerow({"time": "1704067200", "liquidation": "15"})
            writer.writerow({"time": "1704070800000", "liquidation": "25"})

        try:
            snapshot = load_snapshot_bundle_from_csv(
                candles_path=candles_path,
                snapshot_id="bundle-epoch-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_path=funding_path,
                open_interest_path=oi_path,
                liquidation_notional_path=liquidations_path,
            )
        finally:
            for path in (candles_path, funding_path, oi_path, liquidations_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(snapshot.funding_rates, [0.0001, 0.0])
        self.assertEqual(snapshot.open_interest, [0.0, 2550.0])
        self.assertEqual(snapshot.liquidation_notional, [15.0, 25.0])
        self.assertIn("missing_funding_rate_count=1", snapshot.quality_flags)
        self.assertIn("missing_open_interest_count=1", snapshot.quality_flags)

    def test_load_snapshot_from_csv_normalizes_naive_timestamps_to_utc(self) -> None:
        csv_path = Path("test-snapshot-naive.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["datetime", "open", "high", "low", "close", "volume"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "datetime": "2024-01-01 00:00:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "1000",
                }
            )

        try:
            snapshot = load_snapshot_from_csv(
                path=csv_path,
                snapshot_id="csv-snap-naive",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )
        finally:
            csv_path.unlink()

        self.assertEqual(snapshot.candles[0].timestamp.isoformat(), "2024-01-01T00:00:00+00:00")

    def test_load_snapshot_bundle_from_csv_aligns_float_epoch_and_naive_sidecars(self) -> None:
        candles_path = Path("test-bundle-float-candles.csv")
        funding_path = Path("test-bundle-float-funding.csv")
        oi_path = Path("test-bundle-float-open-interest.csv")
        liquidations_path = Path("test-bundle-float-liquidations.csv")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["open_time", "o", "h", "l", "c", "v"])
            writer.writeheader()
            writer.writerow({"open_time": "1704067200000", "o": "100", "h": "101", "l": "99", "c": "100.5", "v": "1000"})
            writer.writerow({"open_time": "1704070800000", "o": "101", "h": "102", "l": "100", "c": "101.5", "v": "1100"})

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["time", "funding"])
            writer.writeheader()
            writer.writerow({"time": "1704067200.0", "funding": "0.0001"})

        with oi_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["datetime", "oi"])
            writer.writeheader()
            writer.writerow({"datetime": "2024-01-01 01:00:00", "oi": "2550"})

        with liquidations_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["datetime", "liquidation"])
            writer.writeheader()
            writer.writerow({"datetime": "2024-01-01 00:00:00", "liquidation": "15"})
            writer.writerow({"datetime": "2024-01-01 01:00:00", "liquidation": "25"})

        try:
            snapshot = load_snapshot_bundle_from_csv(
                candles_path=candles_path,
                snapshot_id="bundle-float-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_path=funding_path,
                open_interest_path=oi_path,
                liquidation_notional_path=liquidations_path,
            )
        finally:
            for path in (candles_path, funding_path, oi_path, liquidations_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(snapshot.funding_rates, [0.0001, 0.0])
        self.assertEqual(snapshot.open_interest, [0.0, 2550.0])
        self.assertEqual(snapshot.liquidation_notional, [15.0, 25.0])
        self.assertIn("missing_funding_rate_count=1", snapshot.quality_flags)
        self.assertIn("missing_open_interest_count=1", snapshot.quality_flags)

    def test_load_snapshot_from_csv_supports_whitespace_case_headers_and_formatted_numbers(self) -> None:
        csv_path = Path("test-snapshot-formatted.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[" Timestamp ", " OPEN ", " HIGH ", " LOW ", " CLOSE ", " VOLUME ", " fundingRate "],
            )
            writer.writeheader()
            writer.writerow(
                {
                    " Timestamp ": "2024-01-01T00:00:00+00:00",
                    " OPEN ": "1,000.5",
                    " HIGH ": "1,010.0",
                    " LOW ": "990.0",
                    " CLOSE ": "1,005.25",
                    " VOLUME ": "12,345.6",
                    " fundingRate ": " 0.0001 ",
                }
            )

        try:
            snapshot = load_snapshot_from_csv(
                path=csv_path,
                snapshot_id="csv-snap-formatted",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )
        finally:
            csv_path.unlink()

        self.assertEqual(snapshot.candles[0].open, 1000.5)
        self.assertEqual(snapshot.candles[0].volume, 12345.6)
        self.assertEqual(snapshot.funding_rates, [0.0001])

    def test_load_snapshot_bundle_from_csv_supports_formatted_sidecar_numbers_and_header_spacing(self) -> None:
        candles_path = Path("test-bundle-formatted-candles.csv")
        funding_path = Path("test-bundle-formatted-funding.csv")
        oi_path = Path("test-bundle-formatted-open-interest.csv")
        liquidations_path = Path("test-bundle-formatted-liquidations.csv")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[" Time ", " O ", " H ", " L ", " C ", " V "])
            writer.writeheader()
            writer.writerow({" Time ": "2024-01-01T00:00:00+00:00", " O ": "1,000", " H ": "1,010", " L ": "990", " C ": "1,005", " V ": "12,345"})
            writer.writerow({" Time ": "2024-01-01T01:00:00+00:00", " O ": "1,001", " H ": "1,011", " L ": "991", " C ": "1,006", " V ": "12,346"})

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[" datetime ", " funding "])
            writer.writeheader()
            writer.writerow({" datetime ": "2024-01-01T00:00:00+00:00", " funding ": " 0.0001 "})

        with oi_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[" date ", " openInterest "])
            writer.writeheader()
            writer.writerow({" date ": "2024-01-01T01:00:00+00:00", " openInterest ": "2,550"})

        with liquidations_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[" timestamp ", " liquidation "])
            writer.writeheader()
            writer.writerow({" timestamp ": "2024-01-01T00:00:00+00:00", " liquidation ": "15"})
            writer.writerow({" timestamp ": "2024-01-01T01:00:00+00:00", " liquidation ": "2,500.5"})

        try:
            snapshot = load_snapshot_bundle_from_csv(
                candles_path=candles_path,
                snapshot_id="bundle-formatted-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_path=funding_path,
                open_interest_path=oi_path,
                liquidation_notional_path=liquidations_path,
            )
        finally:
            for path in (candles_path, funding_path, oi_path, liquidations_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(snapshot.candles[0].open, 1000.0)
        self.assertEqual(snapshot.funding_rates, [0.0001, 0.0])
        self.assertEqual(snapshot.open_interest, [0.0, 2550.0])
        self.assertEqual(snapshot.liquidation_notional, [15.0, 2500.5])

    def test_load_snapshot_from_csv_treats_null_like_optional_market_values_as_zero(self) -> None:
        csv_path = Path("test-snapshot-nullish.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "funding_rate",
                    "open_interest",
                    "liquidation_notional",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "1000",
                    "funding_rate": "N/A",
                    "open_interest": "null",
                    "liquidation_notional": "-",
                }
            )

        try:
            snapshot = load_snapshot_from_csv(
                path=csv_path,
                snapshot_id="csv-snap-nullish",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )
        finally:
            csv_path.unlink()

        self.assertEqual(snapshot.funding_rates, [0.0])
        self.assertEqual(snapshot.open_interest, [0.0])
        self.assertEqual(snapshot.liquidation_notional, [0.0])
        self.assertIn("invalid_funding_rate_count=1", snapshot.quality_flags)
        self.assertIn("invalid_open_interest_count=1", snapshot.quality_flags)
        self.assertIn("invalid_liquidation_notional_count=1", snapshot.quality_flags)

    def test_load_snapshot_bundle_from_csv_treats_null_like_sidecar_values_as_zero(self) -> None:
        candles_path = Path("test-bundle-nullish-candles.csv")
        funding_path = Path("test-bundle-nullish-funding.csv")
        oi_path = Path("test-bundle-nullish-open-interest.csv")
        liquidations_path = Path("test-bundle-nullish-liquidations.csv")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "open": "100", "high": "101", "low": "99", "close": "100.5", "volume": "1000"})
            writer.writerow({"timestamp": "2024-01-01T01:00:00+00:00", "open": "101", "high": "102", "low": "100", "close": "101.5", "volume": "1100"})

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "funding_rate"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "funding_rate": "N/A"})

        with oi_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open_interest"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T01:00:00+00:00", "open_interest": "--"})

        with liquidations_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "liquidation_notional"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "liquidation_notional": "null"})
            writer.writerow({"timestamp": "2024-01-01T01:00:00+00:00", "liquidation_notional": "-"})

        try:
            snapshot = load_snapshot_bundle_from_csv(
                candles_path=candles_path,
                snapshot_id="bundle-nullish-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_path=funding_path,
                open_interest_path=oi_path,
                liquidation_notional_path=liquidations_path,
            )
        finally:
            for path in (candles_path, funding_path, oi_path, liquidations_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(snapshot.funding_rates, [0.0, 0.0])
        self.assertEqual(snapshot.open_interest, [0.0, 0.0])
        self.assertEqual(snapshot.liquidation_notional, [0.0, 0.0])
        self.assertIn("invalid_funding_rate_count=1", snapshot.quality_flags)
        self.assertIn("invalid_open_interest_count=1", snapshot.quality_flags)
        self.assertIn("invalid_liquidation_notional_count=2", snapshot.quality_flags)

    def test_load_snapshot_bundle_from_csv_skips_invalid_sidecar_timestamps_and_records_flags(self) -> None:
        candles_path = Path("test-bundle-invalid-ts-candles.csv")
        funding_path = Path("test-bundle-invalid-ts-funding.csv")

        with candles_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "open": "100", "high": "101", "low": "99", "close": "100.5", "volume": "1000"})
            writer.writerow({"timestamp": "2024-01-01T01:00:00+00:00", "open": "101", "high": "102", "low": "100", "close": "101.5", "volume": "1100"})

        with funding_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "funding_rate"])
            writer.writeheader()
            writer.writerow({"timestamp": "2024-01-01T00:00:00+00:00", "funding_rate": "0.0001"})
            writer.writerow({"timestamp": "not-a-real-timestamp", "funding_rate": "0.0002"})

        try:
            snapshot = load_snapshot_bundle_from_csv(
                candles_path=candles_path,
                snapshot_id="bundle-invalid-ts-snap",
                symbol="SOLUSDT",
                venue="binance",
                timeframe="1h",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                funding_path=funding_path,
            )
        finally:
            for path in (candles_path, funding_path):
                if path.exists():
                    path.unlink()

        self.assertEqual(snapshot.funding_rates, [0.0001, 0.0])
        self.assertIn("missing_funding_rate_count=1", snapshot.quality_flags)
        self.assertIn("invalid_funding_rate_timestamp_count=1", snapshot.quality_flags)
