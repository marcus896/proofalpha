"""Tests for the Phase 13 fetch pipeline."""
from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


@contextlib.contextmanager
def _workspace_tempdir() -> Path:
    root = Path("test-output-fetch-temp")
    root.mkdir(exist_ok=True)
    tmp_name = f"tmp-{next(tempfile._get_candidate_names())}"
    tmp_path = root / tmp_name
    tmp_path.mkdir()
    try:
        yield tmp_path
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def _zip_csv_bytes(filename: str, rows: list[list[object]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        text_buffer = io.StringIO()
        writer = csv.writer(text_buffer)
        writer.writerows(rows)
        archive.writestr(filename, text_buffer.getvalue())
    return buffer.getvalue()


class TestDeriveSymbols(unittest.TestCase):
    def _derive(self, symbol: str) -> str:
        base = symbol.split("/")[0].upper()
        return f"{base}USDT"

    def test_btc_usd_to_btcusdt(self) -> None:
        self.assertEqual(self._derive("BTC/USD"), "BTCUSDT")

    def test_eth_usd_to_ethusdt(self) -> None:
        self.assertEqual(self._derive("ETH/USD"), "ETHUSDT")


class TestWriteZeroSeries(unittest.TestCase):
    def setUp(self) -> None:
        from engine.data.fetch import _write_zero_series

        self._write_zero_series = _write_zero_series

    def test_writes_header_and_rows(self) -> None:
        with _workspace_tempdir() as tmp:
            path = tmp / "funding.csv"
            self._write_zero_series(
                path,
                ["2024-01-01T00:00:00+00:00", "2024-01-01T01:00:00+00:00"],
                "funding_rate",
            )
            rows = list(csv.DictReader(path.open(encoding="utf-8")))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["funding_rate"], "0.0")


class TestNormalizeDt(unittest.TestCase):
    def setUp(self) -> None:
        from engine.data.fetch import _normalize_dt

        self._normalize = _normalize_dt

    def test_tz_aware_datetime_passthrough(self) -> None:
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(self._normalize(dt), dt)

    def test_pandas_timestamp_like_object(self) -> None:
        mock_ts = MagicMock()
        mock_ts.to_pydatetime.return_value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(self._normalize(mock_ts).tzinfo, timezone.utc)


class TestTimeframeMapping(unittest.TestCase):
    def setUp(self) -> None:
        from engine.data.fetch import _ALPACA_TIMEFRAME_MAP, _BINANCE_INTERVAL_MAP, _MINUTES_PER_BAR

        self.alpaca_map = _ALPACA_TIMEFRAME_MAP
        self.binance_map = _BINANCE_INTERVAL_MAP
        self.minutes_map = _MINUTES_PER_BAR

    def test_same_keys_across_maps(self) -> None:
        self.assertEqual(set(self.alpaca_map), set(self.binance_map))
        self.assertEqual(set(self.binance_map), set(self.minutes_map))

    def test_1hour_maps_correctly(self) -> None:
        self.assertEqual(self.binance_map["1Hour"], "1h")
        self.assertEqual(self.alpaca_map["1Hour"], "Hour")
        self.assertEqual(self.minutes_map["1Hour"], 60)


class TestAlignSeriesToTimestamps(unittest.TestCase):
    def test_forward_fills_sparse_sidecar_values(self) -> None:
        from engine.data.fetch import _align_series_to_timestamps

        aligned = _align_series_to_timestamps(
            [
                "2024-01-01T00:00:00+00:00",
                "2024-01-01T01:00:00+00:00",
                "2024-01-01T02:00:00+00:00",
            ],
            [
                ("2024-01-01T00:00:00+00:00", 0.01),
                ("2024-01-01T02:00:00+00:00", 0.02),
            ],
        )

        self.assertEqual(aligned[0], ("2024-01-01T00:00:00+00:00", 0.01))
        self.assertEqual(aligned[1], ("2024-01-01T01:00:00+00:00", 0.01))
        self.assertEqual(aligned[2], ("2024-01-01T02:00:00+00:00", 0.02))


class TestFetchSnapshotInvalidTimeframe(unittest.TestCase):
    def test_raises_on_unknown_timeframe(self) -> None:
        from engine.data.fetch import fetch_binance_perps_snapshot

        with _workspace_tempdir() as tmp:
            with self.assertRaises(ValueError):
                fetch_binance_perps_snapshot(
                    output_dir=tmp,
                    symbol="BTCUSDT",
                    timeframe="3Hour",
                    lookback_days=30,
                )


class TestFetchSnapshotImportError(unittest.TestCase):
    def test_alpaca_reference_import_error_has_hint(self) -> None:
        from engine.data.fetch import fetch_alpaca_spot_snapshot

        with patch.dict(
            "sys.modules",
            {
                "alpaca": None,
                "alpaca.data": None,
                "alpaca.data.historical": None,
                "alpaca.data.requests": None,
                "alpaca.data.timeframe": None,
            },
        ):
            with _workspace_tempdir() as tmp:
                with self.assertRaises(ImportError) as ctx:
                    fetch_alpaca_spot_snapshot(
                        output_dir=tmp,
                        symbol="BTC/USD",
                        timeframe="1Hour",
                        lookback_days=30,
                    )
        self.assertIn("alpaca-py", str(ctx.exception).lower())


class TestBinanceGet(unittest.TestCase):
    class _Response:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return self._payload

    def test_network_failure_raises_runtime_error(self) -> None:
        import urllib.error
        from engine.data.fetch import _binance_get

        with patch("engine.data.fetch.time.sleep") as sleep_mock:
            with patch("builtins.print") as print_mock:
                with patch(
                    "urllib.request.urlopen",
                    side_effect=urllib.error.URLError("connection refused"),
                ):
                    with self.assertRaises(RuntimeError):
                        _binance_get("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT")

        self.assertEqual(print_mock.call_count, 2)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_retry_helper_records_network_error_metadata_with_injected_sleeper_and_logger(self) -> None:
        import urllib.error
        from engine.data.fetch import _binance_get

        retry_events: list[dict[str, object]] = []
        sleeps: list[float] = []
        logs: list[str] = []
        calls = [
            urllib.error.URLError("temporary outage"),
            urllib.error.URLError("temporary outage"),
            self._Response(b'{"ok": true}'),
        ]

        def opener(url: str, timeout: float):
            result = calls.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        payload = _binance_get(
            "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT",
            opener=opener,
            sleeper=sleeps.append,
            logger=logs.append,
            retry_events=retry_events,
        )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(sleeps, [2.0, 4.0])
        self.assertEqual(len(logs), 2)
        self.assertEqual([event["attempt"] for event in retry_events], [1, 2, 3])
        self.assertEqual(retry_events[0]["status"], "network_error")
        self.assertEqual(retry_events[0]["backoff_seconds"], 2.0)
        self.assertEqual(retry_events[2]["status"], "ok")
        self.assertEqual(retry_events[2]["backoff_seconds"], 0.0)

    def test_retry_helper_records_rate_limit_metadata(self) -> None:
        import urllib.error
        from engine.data.fetch import _binance_get

        retry_events: list[dict[str, object]] = []
        sleeps: list[float] = []
        calls = [
            urllib.error.HTTPError("url", 429, "rate limited", {}, None),
            self._Response(b'{"ok": true}'),
        ]

        def opener(url: str, timeout: float):
            result = calls.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        payload = _binance_get(
            "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT",
            opener=opener,
            sleeper=sleeps.append,
            logger=lambda _message: None,
            retry_events=retry_events,
        )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(retry_events[0]["status"], "rate_limited")
        self.assertEqual(retry_events[0]["http_status"], 429)
        self.assertEqual(retry_events[0]["backoff_seconds"], 2.0)
        self.assertEqual(retry_events[1]["status"], "ok")


class TestFetchBinancePerpsSnapshot(unittest.TestCase):
    def test_writes_aligned_engine_ready_csvs(self) -> None:
        from engine.data.fetch import fetch_binance_perps_snapshot

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

        with _workspace_tempdir() as tmp:
            paths = fetch_binance_perps_snapshot(
                output_dir=tmp,
                symbol="BTCUSDT",
                timeframe="1Hour",
                lookback_days=30,
                json_getter=fake_get,
            )
            candles = list(csv.DictReader(paths["candles"].open(encoding="utf-8")))
            funding = list(csv.DictReader(paths["funding"].open(encoding="utf-8")))
            open_interest = list(csv.DictReader(paths["open_interest"].open(encoding="utf-8")))
            liquidation = list(csv.DictReader(paths["liquidation_notional"].open(encoding="utf-8")))
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))

        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0]["close"], "105.00000000")
        self.assertEqual(funding[1]["funding_rate"], "0.0100000000")
        self.assertEqual(open_interest[1]["open_interest"], "225.0000000000")
        self.assertEqual(liquidation, [])
        self.assertEqual(manifest["provider"], "binance_perps")
        self.assertEqual(manifest["symbol"], "BTCUSDT")
        self.assertEqual(manifest["timeframe"], "1Hour")
        self.assertIn("candles", manifest["artifacts"])
        self.assertEqual(manifest["retry_metadata"]["json_requests"], [])

    def test_open_interest_requests_are_windowed_to_exchange_limits(self) -> None:
        from engine.data.fetch import fetch_binance_perps_snapshot

        seen_urls: list[str] = []

        def fake_get(url: str) -> object:
            seen_urls.append(url)
            if "klines" in url:
                return [[1704067200000, "100", "110", "95", "105", "1000"]]
            if "fundingRate" in url:
                return [{"fundingTime": 1704067200000, "fundingRate": "0.01"}]
            if "openInterestHist" in url:
                if seen_urls.count(url) > 1:
                    return []
                return [{"timestamp": 1704067200000, "sumOpenInterest": "200"}]
            return []

        with _workspace_tempdir() as tmp:
            fetch_binance_perps_snapshot(
                output_dir=tmp,
                symbol="BTCUSDT",
                timeframe="1Hour",
                lookback_days=365,
                json_getter=fake_get,
            )

        open_interest_urls = [url for url in seen_urls if "openInterestHist" in url]
        self.assertGreaterEqual(len(open_interest_urls), 2)


class TestFetchBinanceArchiveSnapshot(unittest.TestCase):
    def _archive_getter(self, url: str) -> bytes:
        def payload_for(payload_url: str) -> bytes:
            if "/klines/" in payload_url:
                return _zip_csv_bytes(
                    "BTCUSDT-1h-2024-01-01.csv",
                    [
                        [
                            1704067200000,
                            "100",
                            "110",
                            "95",
                            "105",
                            "1000",
                            1704070799999,
                            "105000",
                            "42",
                            "500",
                            "52500",
                            "0",
                        ]
                    ],
                )
            if "/aggTrades/" in payload_url:
                return _zip_csv_bytes("BTCUSDT-aggTrades-2024-01-01.csv", [[1, "105", "0.2", 1, 2, 1704067200000, "true", "true"]])
            raise FileNotFoundError(payload_url)

        if url.endswith(".CHECKSUM"):
            payload = payload_for(url.removesuffix(".CHECKSUM"))
            return f"{hashlib.sha256(payload).hexdigest()}  {Path(url.removesuffix('.CHECKSUM')).name}\n".encode("utf-8")
        return payload_for(url)

    def test_archive_snapshot_writes_raw_files_manifest_and_source_metadata(self) -> None:
        from engine.data.fetch import fetch_binance_archive_snapshot

        with _workspace_tempdir() as tmp:
            paths = fetch_binance_archive_snapshot(
                output_dir=tmp,
                symbol="BTCUSDT",
                timeframe="1Hour",
                start_date="2024-01-01",
                end_date="2024-01-01",
                archive_getter=self._archive_getter,
            )
            with paths["candles"].open(encoding="utf-8") as handle:
                candles = list(csv.DictReader(handle))
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            raw_artifacts_exist = all(Path(path).exists() for path in manifest["archive"]["raw_artifacts"].values())

        self.assertEqual(candles[0]["close"], "105.00000000")
        self.assertEqual(candles[0]["trade_count"], "42")
        self.assertEqual(manifest["provider"], "binance_public_archive")
        self.assertEqual(manifest["build_mode"], "archive_bundle")
        self.assertEqual(manifest["parser_version"], "binance_public_archive_parser_v1")
        self.assertRegex(manifest["raw_source_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["dataset_version"], r"^[0-9a-f]{64}$")
        self.assertTrue(manifest["archive"]["checksum_validated"])
        self.assertEqual(manifest["archive"]["agg_trade_download_count"], 1)
        self.assertEqual(manifest["archive"]["retry_metadata"]["byte_requests"], [])
        self.assertIn("unavailable", manifest["field_confidence"]["liquidation_notional"])
        self.assertTrue(raw_artifacts_exist)

    def test_archive_snapshot_uses_monthly_files_for_full_months(self) -> None:
        from engine.data.fetch import fetch_binance_archive_snapshot

        requested_urls: list[str] = []

        def archive_getter(url: str) -> bytes:
            requested_urls.append(url)
            return self._archive_getter(url)

        with _workspace_tempdir() as tmp:
            fetch_binance_archive_snapshot(
                output_dir=tmp,
                symbol="BTCUSDT",
                timeframe="1Hour",
                start_date="2024-01-01",
                end_date="2024-01-31",
                archive_getter=archive_getter,
                include_agg_trades=False,
            )

        requested_zip_urls = [url for url in requested_urls if not url.endswith(".CHECKSUM")]
        self.assertEqual(
            requested_zip_urls,
            [
                "https://data.binance.vision/data/futures/um/monthly/klines/"
                "BTCUSDT/1h/BTCUSDT-1h-2024-01.zip"
            ],
        )

    def test_archive_snapshot_falls_back_to_public_rest_klines_when_archive_missing(self) -> None:
        from engine.data.fetch import fetch_binance_archive_snapshot

        def archive_getter(url: str) -> bytes:
            raise RuntimeError(f"archive missing: {url}")

        def rest_json_getter(url: str) -> object:
            return [
                [
                    1704067200000,
                    "100",
                    "110",
                    "95",
                    "105",
                    "1000",
                    1704070799999,
                    "105000",
                    "42",
                    "500",
                    "52500",
                    "0",
                ]
            ]

        with _workspace_tempdir() as tmp:
            paths = fetch_binance_archive_snapshot(
                output_dir=tmp,
                symbol="BTCUSDT",
                timeframe="1Hour",
                start_date="2024-01-01",
                end_date="2024-01-01",
                archive_getter=archive_getter,
                rest_json_getter=rest_json_getter,
                include_agg_trades=False,
            )
            with paths["candles"].open(encoding="utf-8") as handle:
                candles = list(csv.DictReader(handle))
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))

        self.assertEqual(candles[0]["close"], "105.00000000")
        self.assertEqual(manifest["archive"]["rest_fallback_count"], 1)
        self.assertEqual(
            manifest["archive"]["checksum_results"][0]["status"],
            "archive_unavailable_rest_fallback",
        )
        self.assertIn("klines_rest:2024-01-01", manifest["archive"]["raw_artifacts"])

    def test_load_fetched_snapshot_preserves_archive_metadata_and_unavailable_fields(self) -> None:
        from engine.data.fetch import fetch_binance_archive_snapshot, load_fetched_snapshot

        with _workspace_tempdir() as tmp:
            fetch_binance_archive_snapshot(
                output_dir=tmp,
                symbol="BTCUSDT",
                timeframe="1Hour",
                start_date="2024-01-01",
                end_date="2024-01-01",
                archive_getter=self._archive_getter,
            )
            snapshot = load_fetched_snapshot(
                snapshot_dir=tmp,
                snapshot_id="archive-snap",
                symbol="BTCUSDT",
                venue="binance",
                timeframe="1Hour",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )

        self.assertEqual(snapshot.provenance["provider"], "binance_public_archive")
        self.assertEqual(snapshot.provenance["build_mode"], "archive_bundle")
        self.assertRegex(snapshot.provenance["raw_source_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(snapshot.provenance["dataset_version"], r"^[0-9a-f]{64}$")
        self.assertIn("unavailable", snapshot.provenance["field_confidence"]["open_interest"])
        self.assertIn("missing_open_interest_count=1", snapshot.quality_flags)
        self.assertIn("missing_liquidation_notional_count=1", snapshot.quality_flags)
        self.assertEqual(snapshot.quality_report.source_checks["fetch_build_mode"], "archive_bundle")
        self.assertEqual(snapshot.quality_report.source_checks["dataset_version"], snapshot.provenance["dataset_version"])

    def test_archive_snapshot_rejects_non_v3_timeframe(self) -> None:
        from engine.data.fetch import fetch_binance_archive_snapshot

        with _workspace_tempdir() as tmp:
            with self.assertRaisesRegex(ValueError, "support only"):
                fetch_binance_archive_snapshot(
                    output_dir=tmp,
                    symbol="BTCUSDT",
                    timeframe="5Min",
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    archive_getter=self._archive_getter,
                )


class _FakeBybitExchange:
    id = "bybit"

    def load_markets(self) -> dict[str, dict[str, object]]:
        return {
            "BTC/USDT:USDT": {
                "symbol": "BTC/USDT:USDT",
                "swap": True,
                "linear": True,
                "quote": "USDT",
                "settle": "USDT",
                "limits": {"leverage": {"max": 100}},
                "info": {
                    "fundingInterval": "480",
                    "leverageFilter": {"minLeverage": "1", "maxLeverage": "100", "leverageStep": "0.01"},
                },
            }
        }

    def market(self, symbol: str) -> dict[str, object]:
        return self.load_markets()[symbol]

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
        params: dict[str, object] | None = None,
    ) -> list[list[object]]:
        self._assert_bybit(symbol, params)
        self.last_timeframe = timeframe
        return [
            [1704067200000, "100", "110", "95", "105", "1000"],
            [1704070800000, "105", "115", "100", "110", "1100"],
        ]

    def fetch_funding_rate_history(
        self,
        symbol: str,
        since: int | None = None,
        limit: int | None = None,
        params: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        self._assert_bybit(symbol, params)
        return [{"timestamp": 1704067200000, "fundingRate": "0.001"}]

    def fetch_open_interest_history(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
        params: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        self._assert_bybit(symbol, params)
        return [
            {"timestamp": 1704067200000, "openInterestAmount": "200"},
            {"timestamp": 1704070800000, "openInterestAmount": "225"},
        ]

    def fetch_leverage_tiers(
        self,
        symbols: list[str],
        params: dict[str, object] | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        self._assert_bybit(symbols[0], params)
        return {
            symbols[0]: [
                {
                    "minNotional": "0",
                    "maxNotional": "1000000",
                    "maxLeverage": "100",
                    "maintenanceMarginRate": "0.005",
                }
            ]
        }

    def _assert_bybit(self, symbol: str, params: dict[str, object] | None) -> None:
        if symbol != "BTC/USDT:USDT":
            raise AssertionError(symbol)
        if params != {"category": "linear"}:
            raise AssertionError(params)


class TestFetchCcxtBybitSnapshot(unittest.TestCase):
    def test_writes_bybit_bundle_manifest_and_live_contract_profile(self) -> None:
        from engine.data.fetch import fetch_bybit_perps_snapshot

        with _workspace_tempdir() as tmp:
            paths = fetch_bybit_perps_snapshot(
                output_dir=tmp,
                symbol="BTCUSDT",
                timeframe="1Hour",
                lookback_days=30,
                exchange=_FakeBybitExchange(),
            )
            candles = list(csv.DictReader(paths["candles"].open(encoding="utf-8")))
            funding = list(csv.DictReader(paths["funding"].open(encoding="utf-8")))
            open_interest = list(csv.DictReader(paths["open_interest"].open(encoding="utf-8")))
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))

        self.assertEqual(len(candles), 2)
        self.assertEqual(funding[0]["funding_rate"], "0.0010000000")
        self.assertEqual(open_interest[1]["open_interest"], "225.0000000000")
        self.assertEqual(manifest["provider"], "ccxt_perps")
        self.assertEqual(manifest["venue"], "bybit")
        self.assertEqual(manifest["exchange_id"], "bybit")
        self.assertEqual(manifest["symbol"], "BTC/USDT:USDT")
        self.assertEqual(manifest["venue_profile"]["funding_interval_h"], 8)
        self.assertEqual(manifest["venue_profile"]["quote_currency"], "USDT")
        self.assertEqual(manifest["venue_profile"]["leverage_tiers"][0]["max_leverage"], 100.0)
        self.assertIn("Bybit V5 instruments info", {item["name"] for item in manifest["references"]})

    def test_build_snapshot_accepts_bybit_and_attaches_ccxt_venue_profile(self) -> None:
        from engine.data.fetch import build_snapshot

        with _workspace_tempdir() as tmp:
            snapshot = build_snapshot(
                output_dir=tmp,
                snapshot_id="snap-bybit-build",
                symbol="BTCUSDT",
                venue="bybit",
                timeframe="1Hour",
                lookback_days=30,
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                ccxt_exchange=_FakeBybitExchange(),
            )

        self.assertEqual(snapshot.snapshot_id, "snap-bybit-build")
        self.assertEqual(snapshot.venue, "bybit")
        self.assertEqual(len(snapshot.candles), 2)
        self.assertEqual(snapshot.provenance["provider"], "ccxt_perps")
        self.assertEqual(snapshot.provenance["fetch_request"]["exchange_id"], "bybit")
        self.assertIsNotNone(snapshot.venue_profile)
        self.assertEqual(snapshot.venue_profile.funding_interval_h, 8)
        self.assertEqual(snapshot.venue_profile.settlement_currency, "USDT")
        self.assertEqual(snapshot.quality_report.source_checks["fetch_provider"], "ccxt_perps")


class TestLoadFetchedSnapshot(unittest.TestCase):
    def test_load_fetched_snapshot_attaches_fetch_manifest_metadata(self) -> None:
        from engine.data.fetch import fetch_binance_perps_snapshot, load_fetched_snapshot

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

        with _workspace_tempdir() as tmp:
            fetch_binance_perps_snapshot(
                output_dir=tmp,
                symbol="BTCUSDT",
                timeframe="1Hour",
                lookback_days=30,
                json_getter=fake_get,
            )
            snapshot = load_fetched_snapshot(
                snapshot_dir=tmp,
                snapshot_id="snap-fetch-load",
                symbol="BTCUSDT",
                venue="binance",
                timeframe="1Hour",
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
            )

        self.assertEqual(snapshot.provenance["provider"], "binance_perps")
        self.assertEqual(snapshot.provenance["build_mode"], "fetched_bundle")
        self.assertEqual(snapshot.provenance["fetch_request"]["lookback_days"], 30)
        self.assertEqual(snapshot.quality_report.source_checks["fetch_provider"], "binance_perps")
        self.assertIn("fetch_manifest", snapshot.provenance)


class TestBuildSnapshot(unittest.TestCase):
    def test_build_snapshot_fetches_and_loads_phase1_metadata(self) -> None:
        from engine.data.fetch import build_snapshot

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

        with _workspace_tempdir() as tmp:
            snapshot = build_snapshot(
                output_dir=tmp,
                snapshot_id="snap-build",
                symbol="BTCUSDT",
                venue="binance",
                timeframe="1Hour",
                lookback_days=30,
                maker_fee_bps=2.0,
                taker_fee_bps=5.0,
                json_getter=fake_get,
            )

        self.assertEqual(snapshot.snapshot_id, "snap-build")
        self.assertEqual(len(snapshot.candles), 2)
        self.assertIsNotNone(snapshot.venue_profile)
        self.assertEqual(snapshot.venue_profile.funding_interval_h, 8)
        self.assertIsNotNone(snapshot.quality_report)
        self.assertEqual(snapshot.provenance["provider"], "binance_perps")
        self.assertEqual(snapshot.provenance["build_mode"], "fetched_bundle")


class TestWriteZeroSeriesLoadable(unittest.TestCase):
    def test_funding_zero_fill_passes_bundle_loader(self) -> None:
        from engine.data.fetch import _write_zero_series
        from engine.data.providers import _load_timestamp_series

        with _workspace_tempdir() as tmp:
            path = tmp / "funding.csv"
            _write_zero_series(path, ["2024-01-01T00:00:00+00:00"], "funding_rate")
            values, invalid_count, invalid_ts_count = _load_timestamp_series(path, "funding_rate")

        self.assertEqual(invalid_count, 0)
        self.assertEqual(invalid_ts_count, 0)
        self.assertEqual(list(values.values()), [0.0])


class TestFetchAndRunScript(unittest.TestCase):
    @staticmethod
    def _load_module():
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "fetch_and_run",
            Path(__file__).parent.parent.parent / "scripts" / "fetch_and_run.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_validate_snapshot_missing_candles(self) -> None:
        module = self._load_module()
        with _workspace_tempdir() as tmp:
            warnings = module._validate_snapshot(tmp)
        self.assertTrue(any("candles.csv" in warning for warning in warnings))

    def test_write_study_config_creates_optuna_ready_json(self) -> None:
        module = self._load_module()

        with _workspace_tempdir() as tmp:
            output_root = tmp / "outputs"
            output_root.mkdir()
            (tmp / "candles.csv").write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00+00:00,100,101,99,100,1000\n",
                encoding="utf-8",
            )
            (tmp / "funding_rates.csv").write_text(
                "timestamp,funding_rate\n2024-01-01T00:00:00+00:00,0.0\n",
                encoding="utf-8",
            )
            (tmp / "open_interest.csv").write_text(
                "timestamp,open_interest\n2024-01-01T00:00:00+00:00,100.0\n",
                encoding="utf-8",
            )
            (tmp / "liquidation_notional.csv").write_text(
                "timestamp,liquidation_notional\n2024-01-01T00:00:00+00:00,0.0\n",
                encoding="utf-8",
            )

            config_path = module._write_study_config(
                snapshot_dir=tmp,
                output_root=output_root,
                run_id="BTCUSD-1Hour-20240101",
                symbol="BTC/USD",
                timeframe="1Hour",
                parameter_search_mode="optuna",
                optuna_trials=11,
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(config["runtime"]["parameter_search_mode"], "optuna")
        self.assertEqual(config["runtime"]["optuna_trials"], 11)
        self.assertEqual(
            config["research_lineage"]["memory_db_path"],
            str(output_root / "research-memory.sqlite"),
        )


if __name__ == "__main__":
    unittest.main()
