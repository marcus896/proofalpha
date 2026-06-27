"""Market-data fetch helpers for the Phase 13 overnight pipeline.

The engine-ready snapshot format expects four aligned CSV files:

    candles.csv
    funding_rates.csv
    open_interest.csv
    liquidation_notional.csv

Phase 13 makes Binance USD-M perpetuals the primary source for the tradable
snapshot so the overnight runner does not depend on Alpaca/Pandas. Alpaca spot
data remains available as an optional reference artifact.
"""
from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import io
import json
import os
import site
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from engine.config.models import VenueProfile
from engine.data.snapshots import clone_snapshot
from engine.io.artifacts import write_json_atomic

# Load .env fallback if python-dotenv is not being used.
_ENV_PATH = Path(".env")
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip())

_VENDOR_SITE = Path(".vendor")
if str(_VENDOR_SITE) not in sys.path:
    sys.path.append(str(_VENDOR_SITE))
_USER_SITE = site.getusersitepackages()
if isinstance(_USER_SITE, str) and _USER_SITE and _USER_SITE not in sys.path:
    sys.path.append(_USER_SITE)

BINANCE_FAPI_BASE = "https://fapi.binance.com"
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0
_BINANCE_MAX_KLINES = 1_500
_BINANCE_MAX_FUNDING = 1_000
_BINANCE_MAX_OPEN_INTEREST = 500

_BINANCE_INTERVAL_MAP: dict[str, str] = {
    "1Min": "1m",
    "5Min": "5m",
    "15Min": "15m",
    "30Min": "30m",
    "1Hour": "1h",
    "2Hour": "2h",
    "4Hour": "4h",
    "1Day": "1d",
}

_ALPACA_TIMEFRAME_MAP: dict[str, str] = {
    "1Min": "Minute",
    "5Min": "Minute",
    "15Min": "Minute",
    "30Min": "Minute",
    "1Hour": "Hour",
    "2Hour": "Hour",
    "4Hour": "Hour",
    "1Day": "Day",
}

_MINUTES_PER_BAR: dict[str, int] = {
    "1Min": 1,
    "5Min": 5,
    "15Min": 15,
    "30Min": 30,
    "1Hour": 60,
    "2Hour": 120,
    "4Hour": 240,
    "1Day": 1_440,
}

_OPEN_INTEREST_INTERVAL_MINUTES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "12h": 720,
    "1d": 1_440,
}


JsonGetter = Callable[[str], object]
CcxtExchangeFactory = Callable[[str], object]
ArchiveGetter = Callable[[str], bytes]
Sleeper = Callable[[float], None]
Logger = Callable[[str], None]
UrlOpener = Callable[..., object]

BINANCE_PUBLIC_DATA_BASE = "https://data.binance.vision"
BINANCE_ARCHIVE_MARKET = "um"
BINANCE_ARCHIVE_SUPPORTED_TIMEFRAMES = {"1Hour", "15Min"}
BINANCE_ARCHIVE_PARSER_VERSION = "binance_public_archive_parser_v1"
BINANCE_ARCHIVE_NORMALIZATION_VERSION = "v3_phase1_binance_archive_normalization_v1"


def fetch_snapshot(
    output_dir: Path,
    symbol_alpaca: str = "BTC/USD",
    symbol_binance: str = "BTCUSDT",
    timeframe: str = "1Hour",
    lookback_days: int = 365,
    include_spot_reference: bool = True,
) -> dict[str, Path]:
    """Fetch an engine-ready snapshot plus optional Alpaca spot reference."""

    output_dir = Path(output_dir)
    snapshot_paths = fetch_binance_perps_snapshot(
        output_dir=output_dir,
        symbol=symbol_binance or symbol_alpaca,
        timeframe=timeframe,
        lookback_days=lookback_days,
    )
    if include_spot_reference:
        try:
            snapshot_paths["alpaca_spot_reference"] = fetch_alpaca_spot_snapshot(
                output_dir=output_dir,
                symbol=symbol_alpaca,
                timeframe=timeframe,
                lookback_days=lookback_days,
            )
        except ImportError:
            # Alpaca is optional for this phase; the tradable snapshot is already present.
            pass
    return snapshot_paths


def build_snapshot(
    *,
    output_dir: Path,
    snapshot_id: str,
    symbol: str,
    venue: str,
    timeframe: str,
    lookback_days: int,
    maker_fee_bps: float,
    taker_fee_bps: float,
    json_getter: JsonGetter | None = None,
    ccxt_exchange: object | None = None,
    ccxt_exchange_factory: CcxtExchangeFactory | None = None,
):
    normalized_venue = str(venue).strip().lower()
    if normalized_venue == "binance":
        fetch_binance_perps_snapshot(
            output_dir=output_dir,
            symbol=symbol,
            timeframe=timeframe,
            lookback_days=lookback_days,
            json_getter=json_getter,
        )
    else:
        fetch_ccxt_perps_snapshot(
            output_dir=output_dir,
            venue=normalized_venue,
            symbol=symbol,
            timeframe=timeframe,
            lookback_days=lookback_days,
            exchange=ccxt_exchange,
            exchange_factory=ccxt_exchange_factory,
        )
    return load_fetched_snapshot(
        snapshot_dir=output_dir,
        snapshot_id=snapshot_id,
        symbol=symbol,
        venue=venue,
        timeframe=timeframe,
        maker_fee_bps=maker_fee_bps,
        taker_fee_bps=taker_fee_bps,
    )


def fetch_ccxt_perps_snapshot(
    *,
    output_dir: Path,
    venue: str,
    symbol: str,
    timeframe: str,
    lookback_days: int,
    exchange: object | None = None,
    exchange_factory: CcxtExchangeFactory | None = None,
) -> dict[str, Path]:
    """Fetch a perp snapshot through CCXT into the engine-ready CSV bundle."""
    if timeframe not in _BINANCE_INTERVAL_MAP:
        raise ValueError(f"unsupported timeframe: {timeframe!r}. Choose from: {sorted(_BINANCE_INTERVAL_MAP)}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_venue = str(venue).strip().lower()
    exchange = exchange or _create_ccxt_exchange(normalized_venue, exchange_factory=exchange_factory)
    exchange_id = str(getattr(exchange, "id", normalized_venue) or normalized_venue)
    markets = _load_ccxt_markets(exchange)
    market_symbol = _resolve_ccxt_market_symbol(symbol=symbol, venue=normalized_venue, markets=markets)
    market = _resolve_ccxt_market(exchange=exchange, symbol=market_symbol, markets=markets)

    end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)

    candle_rows = _fetch_ccxt_ohlcv_rows(
        exchange=exchange,
        symbol=market_symbol,
        timeframe=timeframe,
        start_dt=start_dt,
        end_dt=end_dt,
        venue=normalized_venue,
    )
    candle_path = output_dir / "candles.csv"
    candle_timestamps = _write_candle_rows(candle_path, candle_rows)

    funding_rows = _fetch_ccxt_funding_rows(
        exchange=exchange,
        symbol=market_symbol,
        start_dt=start_dt,
        end_dt=end_dt,
        venue=normalized_venue,
    )
    funding_path = output_dir / "funding_rates.csv"
    _write_series_rows(
        funding_path,
        "funding_rate",
        _align_series_to_timestamps(candle_timestamps, funding_rows),
    )

    open_interest_rows = _fetch_ccxt_open_interest_rows(
        exchange=exchange,
        symbol=market_symbol,
        timeframe=timeframe,
        start_dt=start_dt,
        end_dt=end_dt,
        venue=normalized_venue,
    )
    open_interest_path = output_dir / "open_interest.csv"
    _write_series_rows(
        open_interest_path,
        "open_interest",
        _align_series_to_timestamps(candle_timestamps, open_interest_rows),
    )

    liquidation_path = output_dir / "liquidation_notional.csv"
    _write_empty_series(liquidation_path, "liquidation_notional")

    leverage_tiers = _fetch_ccxt_leverage_tiers(exchange=exchange, symbol=market_symbol, venue=normalized_venue)
    venue_profile = _build_ccxt_venue_profile_payload(
        venue=normalized_venue,
        exchange_id=exchange_id,
        symbol=market_symbol,
        market=market,
        leverage_tiers=leverage_tiers,
    )

    manifest_path = output_dir / "fetch_manifest.json"
    manifest_payload = {
        "provider": "ccxt_perps",
        "venue": normalized_venue,
        "exchange_id": exchange_id,
        "symbol": market_symbol,
        "timeframe": timeframe,
        "lookback_days": int(lookback_days),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "adapter": {
            "name": "ccxt",
            "methods": [
                "load_markets",
                "fetch_ohlcv",
                "fetch_funding_rate_history",
                "fetch_open_interest_history",
                "fetch_leverage_tiers",
            ],
            "params": _ccxt_params(normalized_venue),
        },
        "references": _ccxt_reference_manifest(normalized_venue),
        "venue_profile": venue_profile,
        "artifacts": {
            "candles": str(candle_path),
            "funding": str(funding_path),
            "open_interest": str(open_interest_path),
            "liquidation_notional": str(liquidation_path),
        },
    }
    write_json_atomic(manifest_path, manifest_payload)

    return {
        "candles": candle_path,
        "funding": funding_path,
        "open_interest": open_interest_path,
        "liquidation_notional": liquidation_path,
        "manifest": manifest_path,
    }


def fetch_bybit_perps_snapshot(
    *,
    output_dir: Path,
    symbol: str,
    timeframe: str,
    lookback_days: int,
    exchange: object | None = None,
    exchange_factory: CcxtExchangeFactory | None = None,
) -> dict[str, Path]:
    """Convenience wrapper for the Phase 1 live Bybit ingestion path."""
    return fetch_ccxt_perps_snapshot(
        output_dir=output_dir,
        venue="bybit",
        symbol=symbol,
        timeframe=timeframe,
        lookback_days=lookback_days,
        exchange=exchange,
        exchange_factory=exchange_factory,
    )


def fetch_binance_perps_snapshot(
    *,
    output_dir: Path,
    symbol: str,
    timeframe: str,
    lookback_days: int,
    json_getter: JsonGetter | None = None,
) -> dict[str, Path]:
    """Fetch Binance USD-M perpetual market data into aligned CSV artifacts."""
    if timeframe not in _BINANCE_INTERVAL_MAP:
        raise ValueError(
            f"unsupported timeframe: {timeframe!r}. Choose from: {sorted(_BINANCE_INTERVAL_MAP)}"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)
    market_symbol = _normalize_binance_symbol(symbol)
    retry_events: list[dict[str, object]] = []

    candle_rows = _fetch_binance_klines(
        symbol=market_symbol,
        timeframe=timeframe,
        start_dt=start_dt,
        end_dt=end_dt,
        json_getter=json_getter,
        retry_events=retry_events,
    )
    candle_path = output_dir / "candles.csv"
    candle_timestamps = _write_candle_rows(candle_path, candle_rows)

    funding_rows = _fetch_binance_funding_rows(
        symbol=market_symbol,
        start_dt=start_dt,
        end_dt=end_dt,
        json_getter=json_getter,
        retry_events=retry_events,
    )
    funding_path = output_dir / "funding_rates.csv"
    _write_series_rows(
        funding_path,
        "funding_rate",
        _align_series_to_timestamps(candle_timestamps, funding_rows),
    )

    open_interest_rows = _fetch_binance_open_interest_rows(
        symbol=market_symbol,
        timeframe=timeframe,
        start_dt=start_dt,
        end_dt=end_dt,
        json_getter=json_getter,
        retry_events=retry_events,
    )
    open_interest_path = output_dir / "open_interest.csv"
    _write_series_rows(
        open_interest_path,
        "open_interest",
        _align_series_to_timestamps(candle_timestamps, open_interest_rows),
    )

    liquidation_path = output_dir / "liquidation_notional.csv"
    _write_empty_series(liquidation_path, "liquidation_notional")

    manifest_path = output_dir / "fetch_manifest.json"
    manifest_payload = {
        "provider": "binance_perps",
        "venue": "binance",
        "symbol": market_symbol,
        "timeframe": timeframe,
        "lookback_days": int(lookback_days),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "retry_metadata": {
            "json_requests": retry_events,
        },
        "artifacts": {
            "candles": str(candle_path),
            "funding": str(funding_path),
            "open_interest": str(open_interest_path),
            "liquidation_notional": str(liquidation_path),
        },
    }
    write_json_atomic(manifest_path, manifest_payload)

    return {
        "candles": candle_path,
        "funding": funding_path,
        "open_interest": open_interest_path,
        "liquidation_notional": liquidation_path,
        "manifest": manifest_path,
    }


def fetch_binance_archive_snapshot(
    *,
    output_dir: Path,
    symbol: str,
    timeframe: str,
    start_date: str | date,
    end_date: str | date,
    archive_getter: ArchiveGetter | None = None,
    rest_json_getter: JsonGetter | None = None,
    include_agg_trades: bool = True,
) -> dict[str, Path]:
    """Build a v3 snapshot bundle from Binance's public USD-M futures archive.

    The archive is the preferred Phase 1 history source.  It needs no private
    keys and stores downloaded ZIP/CHECKSUM files under ``raw/`` for replayable
    source hashing.
    """
    if timeframe not in BINANCE_ARCHIVE_SUPPORTED_TIMEFRAMES:
        raise ValueError(
            "Binance archive v3 snapshots support only "
            f"{sorted(BINANCE_ARCHIVE_SUPPORTED_TIMEFRAMES)}; got {timeframe!r}"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    market_symbol = _normalize_binance_symbol(symbol)
    interval = _BINANCE_INTERVAL_MAP[timeframe]
    start_day = _parse_archive_date(start_date)
    end_day = _parse_archive_date(end_date)
    if end_day < start_day:
        raise ValueError("end_date must be on or after start_date")

    raw_artifacts: dict[str, str] = {}
    checksum_results: list[dict[str, object]] = []
    candle_rows: list[dict[str, object]] = []
    agg_trade_download_count = 0
    rest_fallback_count = 0
    retry_events: list[dict[str, object]] = []

    for period_type, period_start, period_end in _iter_archive_periods(start_day, end_day):
        period_label = _archive_period_label(period_type, period_start)
        kline_url = _binance_archive_url(
            data_type="klines",
            symbol=market_symbol,
            interval=interval,
            day=period_start,
            period_type=period_type,
        )
        raw_path = _binance_archive_raw_path(
            output_dir=output_dir,
            data_type="klines",
            symbol=market_symbol,
            interval=interval,
            day=period_start,
            period_type=period_type,
        )
        try:
            raw_bytes = _download_archive_bytes(
                kline_url,
                raw_path,
                archive_getter=archive_getter,
                retry_events=retry_events,
            )
            raw_artifacts[f"klines:{period_label}"] = str(raw_path)
            checksum_result = _download_and_validate_archive_checksum(
                url=kline_url,
                raw_path=raw_path,
                archive_getter=archive_getter,
                retry_events=retry_events,
            )
            checksum_results.append(checksum_result)
            candle_rows.extend(_parse_binance_archive_kline_zip(raw_bytes))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, RuntimeError, FileNotFoundError) as exc:
            period_start_dt = datetime(
                period_start.year,
                period_start.month,
                period_start.day,
                tzinfo=timezone.utc,
            )
            next_day = period_end + timedelta(days=1)
            period_end_dt = datetime(next_day.year, next_day.month, next_day.day, tzinfo=timezone.utc)
            fallback_rows = _fetch_binance_klines(
                symbol=market_symbol,
                timeframe=timeframe,
                start_dt=period_start_dt,
                end_dt=period_end_dt,
                json_getter=rest_json_getter,
                retry_events=retry_events,
            )
            fallback_path = _binance_rest_fallback_raw_path(
                output_dir=output_dir,
                symbol=market_symbol,
                interval=interval,
                period_type=period_type,
                period_start=period_start,
            )
            write_json_atomic(
                fallback_path,
                {
                    "provider": "binance_fapi_rest",
                    "source": "public_fapi_klines_archive_fallback",
                    "failed_archive_url": kline_url,
                    "failure": str(exc),
                    "symbol": market_symbol,
                    "interval": interval,
                    "timeframe": timeframe,
                    "period_type": period_type,
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "rows": fallback_rows,
                },
            )
            raw_artifacts[f"klines_rest:{period_label}"] = str(fallback_path)
            checksum_results.append(
                {
                    "url": kline_url,
                    "path": str(raw_path),
                    "status": "archive_unavailable_rest_fallback",
                    "fallback_path": str(fallback_path),
                }
            )
            candle_rows.extend(fallback_rows)
            rest_fallback_count += 1

        if include_agg_trades:
            agg_url = _binance_archive_url(
                data_type="aggTrades",
                symbol=market_symbol,
                interval=None,
                day=period_start,
                period_type=period_type,
            )
            agg_path = _binance_archive_raw_path(
                output_dir=output_dir,
                data_type="aggTrades",
                symbol=market_symbol,
                interval=None,
                day=period_start,
                period_type=period_type,
            )
            _download_archive_bytes(
                agg_url,
                agg_path,
                archive_getter=archive_getter,
                retry_events=retry_events,
            )
            raw_artifacts[f"aggTrades:{period_label}"] = str(agg_path)
            checksum_results.append(
                _download_and_validate_archive_checksum(
                    url=agg_url,
                    raw_path=agg_path,
                    archive_getter=archive_getter,
                    retry_events=retry_events,
                )
            )
            agg_trade_download_count += 1

    candle_path = output_dir / "candles.csv"
    candle_timestamps = _write_candle_rows(candle_path, sorted(candle_rows, key=lambda row: str(row["timestamp"])))
    funding_path = output_dir / "funding_rates.csv"
    open_interest_path = output_dir / "open_interest.csv"
    liquidation_path = output_dir / "liquidation_notional.csv"
    _write_empty_series(funding_path, "funding_rate")
    _write_empty_series(open_interest_path, "open_interest")
    _write_empty_series(liquidation_path, "liquidation_notional")

    raw_source_hash = _compute_paths_content_hash([Path(path) for path in raw_artifacts.values()])
    validated_checksum_count = sum(1 for item in checksum_results if item.get("status") == "validated")
    checksum_validated = validated_checksum_count > 0 and all(
        item.get("status") in {"validated", "unavailable"}
        for item in checksum_results
    )
    raw_source_id = (
        f"binance_public_archive:futures/{BINANCE_ARCHIVE_MARKET}:monthly_full_daily_partial:"
        f"klines:{market_symbol}:{interval}:{start_day.isoformat()}:{end_day.isoformat()}"
    )
    dataset_version = _dataset_version(
        raw_source_id=raw_source_id,
        raw_source_hash=raw_source_hash,
        parser_version=BINANCE_ARCHIVE_PARSER_VERSION,
        normalization_version=BINANCE_ARCHIVE_NORMALIZATION_VERSION,
    )
    manifest_path = output_dir / "fetch_manifest.json"
    manifest_payload = {
        "provider": "binance_public_archive",
        "build_mode": "archive_bundle",
        "venue": "binance",
        "symbol": market_symbol,
        "timeframe": timeframe,
        "archive_interval": interval,
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_metadata_version": "v3_phase1_source_metadata_v1",
        "raw_source_id": raw_source_id,
        "raw_source_hash": raw_source_hash,
        "parser_version": BINANCE_ARCHIVE_PARSER_VERSION,
        "normalization_version": BINANCE_ARCHIVE_NORMALIZATION_VERSION,
        "exchange_rules_version": "runtime_venue_preset_v1",
        "feature_version": "phase1_snapshot_features_v1",
        "scenario_pack_version": "not_applied",
        "cost_model_version": "not_applied",
        "dataset_version": dataset_version,
        "archive": {
            "base_url": BINANCE_PUBLIC_DATA_BASE,
            "market": BINANCE_ARCHIVE_MARKET,
            "period_mode": "monthly_full_months_daily_partial_edges",
            "storage": "raw_zip_with_optional_checksum",
            "checksum_validated": checksum_validated,
            "validated_checksum_count": validated_checksum_count,
            "checksum_results": checksum_results,
            "raw_artifacts": raw_artifacts,
            "agg_trade_download_count": agg_trade_download_count,
            "rest_fallback_count": rest_fallback_count,
            "retry_metadata": {
                "byte_requests": retry_events,
            },
        },
        "field_confidence": {
            "ohlcv": "high" if checksum_validated else "medium",
            "trades_or_aggtrades_raw": "high" if include_agg_trades and agg_trade_download_count else "unavailable",
            "funding_rate": "unavailable_archive_sidecar_empty_use_rest_backfill_later",
            "open_interest": "unavailable_archive_sidecar_empty_use_recent_rest_backfill_later",
            "liquidation_notional": "unavailable_archive_sidecar_empty_do_not_treat_zero_as_truth",
            "historical_l2": "unavailable_without_tardis_or_self_recorded_replay",
        },
        "artifacts": {
            "candles": str(candle_path),
            "funding": str(funding_path),
            "open_interest": str(open_interest_path),
            "liquidation_notional": str(liquidation_path),
        },
        "references": [
            {
                "name": "Binance public data archive",
                "url": BINANCE_PUBLIC_DATA_BASE,
            }
        ],
        "row_count": len(candle_timestamps),
    }
    write_json_atomic(manifest_path, manifest_payload)

    return {
        "candles": candle_path,
        "funding": funding_path,
        "open_interest": open_interest_path,
        "liquidation_notional": liquidation_path,
        "manifest": manifest_path,
    }


def _legacy_parse_archive_date(value: str | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _legacy_iter_archive_days(start_day: date, end_day: date):
    current_day = start_day
    while current_day <= end_day:
        yield current_day
        current_day += timedelta(days=1)


def _legacy_binance_archive_url(
    *,
    data_type: str,
    symbol: str,
    interval: str | None,
    day: date,
) -> str:
    normalized_type = str(data_type)
    if normalized_type == "klines":
        if not interval:
            raise ValueError("klines archive URL requires interval")
        filename = f"{symbol}-{interval}-{day.isoformat()}.zip"
        return (
            f"{BINANCE_PUBLIC_DATA_BASE}/data/futures/{BINANCE_ARCHIVE_MARKET}/daily/"
            f"klines/{symbol}/{interval}/{filename}"
        )
    if normalized_type in {"aggTrades", "trades"}:
        filename = f"{symbol}-{normalized_type}-{day.isoformat()}.zip"
        return (
            f"{BINANCE_PUBLIC_DATA_BASE}/data/futures/{BINANCE_ARCHIVE_MARKET}/daily/"
            f"{normalized_type}/{symbol}/{filename}"
        )
    raise ValueError(f"unsupported Binance archive data_type: {data_type!r}")


def _legacy_binance_archive_raw_path(
    *,
    output_dir: Path,
    data_type: str,
    symbol: str,
    interval: str | None,
    day: date,
) -> Path:
    base = (
        Path(output_dir)
        / "raw"
        / "binance_public_archive"
        / "futures"
        / BINANCE_ARCHIVE_MARKET
        / "daily"
        / data_type
        / symbol
    )
    if data_type == "klines":
        if not interval:
            raise ValueError("klines raw path requires interval")
        base = base / interval
        filename = f"{symbol}-{interval}-{day.isoformat()}.zip"
    else:
        filename = f"{symbol}-{data_type}-{day.isoformat()}.zip"
    return base / filename


def _legacy_download_archive_bytes(url: str, raw_path: Path, *, archive_getter: ArchiveGetter | None) -> bytes:
    raw_bytes = _legacy_request_archive_bytes(url, archive_getter=archive_getter)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw_bytes)
    return raw_bytes


def _legacy_request_archive_bytes(url: str, *, archive_getter: ArchiveGetter | None) -> bytes:
    if archive_getter is not None:
        payload = archive_getter(url)
        if not isinstance(payload, bytes):
            raise TypeError(f"archive_getter must return bytes for {url}")
        return payload
    with urllib.request.urlopen(url, timeout=60) as response:  # nosec B310 - public market-data archive.
        return response.read()


def _legacy_download_and_validate_archive_checksum(
    *,
    url: str,
    raw_path: Path,
    archive_getter: ArchiveGetter | None,
) -> dict[str, object]:
    checksum_url = f"{url}.CHECKSUM"
    checksum_path = raw_path.with_name(f"{raw_path.name}.CHECKSUM")
    try:
        checksum_bytes = _legacy_request_archive_bytes(checksum_url, archive_getter=archive_getter)
    except (urllib.error.HTTPError, urllib.error.URLError, FileNotFoundError):
        return {
            "url": checksum_url,
            "raw_path": str(raw_path),
            "status": "unavailable",
        }
    checksum_path.write_bytes(checksum_bytes)
    checksum_text = checksum_bytes.decode("utf-8", errors="replace").strip()
    expected_hash = checksum_text.split()[0] if checksum_text else ""
    actual_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if expected_hash and expected_hash.lower() != actual_hash.lower():
        raise ValueError(
            f"Binance archive checksum mismatch for {raw_path}: "
            f"expected {expected_hash}, got {actual_hash}"
        )
    return {
        "url": checksum_url,
        "raw_path": str(raw_path),
        "checksum_path": str(checksum_path),
        "status": "validated",
        "expected_sha256": expected_hash,
        "actual_sha256": actual_hash,
    }


def _legacy_parse_binance_archive_kline_zip(raw_bytes: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
        for member_name in archive.namelist():
            if member_name.endswith("/"):
                continue
            with archive.open(member_name) as member:
                text = io.TextIOWrapper(member, encoding="utf-8")
                reader = csv.reader(text)
                for raw_row in reader:
                    if not raw_row:
                        continue
                    try:
                        open_time_ms = int(float(raw_row[0]))
                    except (TypeError, ValueError):
                        continue
                    rows.append(
                        {
                            "timestamp": datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).isoformat(),
                            "open": float(raw_row[1]),
                            "high": float(raw_row[2]),
                            "low": float(raw_row[3]),
                            "close": float(raw_row[4]),
                            "volume": float(raw_row[5]),
                            "trade_count": int(float(raw_row[8])) if len(raw_row) > 8 and raw_row[8] != "" else 0,
                        }
                    )
    return rows


def _legacy_compute_paths_content_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _legacy_dataset_version(
    *,
    raw_source_id: str,
    raw_source_hash: str,
    parser_version: str,
    normalization_version: str,
) -> str:
    payload = {
        "raw_source_id": raw_source_id,
        "raw_source_hash": raw_source_hash,
        "parser_version": parser_version,
        "normalization_version": normalization_version,
    }
    return hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()


def load_fetched_snapshot(
    *,
    snapshot_dir: Path,
    snapshot_id: str,
    symbol: str,
    venue: str,
    timeframe: str,
    maker_fee_bps: float,
    taker_fee_bps: float,
):
    from engine.data.providers import build_snapshot_from_bundle

    snapshot_dir = Path(snapshot_dir)
    snapshot = build_snapshot_from_bundle(
        candles_path=snapshot_dir / "candles.csv",
        snapshot_id=snapshot_id,
        symbol=symbol,
        venue=venue,
        timeframe=timeframe,
        maker_fee_bps=maker_fee_bps,
        taker_fee_bps=taker_fee_bps,
        funding_path=snapshot_dir / "funding_rates.csv",
        open_interest_path=snapshot_dir / "open_interest.csv",
        liquidation_notional_path=snapshot_dir / "liquidation_notional.csv",
    )
    return _attach_fetch_metadata(
        snapshot=snapshot,
        manifest_path=snapshot_dir / "fetch_manifest.json",
    )


def fetch_alpaca_spot_snapshot(
    *,
    output_dir: Path,
    symbol: str,
    timeframe: str,
    lookback_days: int,
) -> Path:
    """Fetch Alpaca spot bars into an optional reference CSV artifact."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)
    bars = _fetch_alpaca_spot_rows(symbol=symbol, timeframe=timeframe, start_dt=start_dt, end_dt=end_dt)
    output_path = output_dir / "alpaca_spot_reference.csv"
    _write_candle_rows(output_path, bars)
    return output_path


def _fetch_alpaca_spot_rows(
    *,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict[str, object]]:
    try:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError as exc:
        raise ImportError(
            "alpaca-py is required for Alpaca spot reference fetching. "
            "Install with: pip install 'alpaca-py>=0.30' or pip install .[data]"
        ) from exc

    timeframe_name = _ALPACA_TIMEFRAME_MAP.get(timeframe)
    if timeframe_name is None:
        raise ValueError(f"unsupported timeframe for Alpaca spot reference: {timeframe!r}")

    if timeframe_name == "Day":
        alpaca_timeframe = TimeFrame.Day
    elif timeframe_name == "Hour":
        alpaca_timeframe = TimeFrame.Hour
    else:
        alpaca_timeframe = TimeFrame.Minute

    client = CryptoHistoricalDataClient(
        api_key=os.environ.get("ALPACA_API_KEY"),
        secret_key=os.environ.get("ALPACA_SECRET_KEY"),
    )
    request = CryptoBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=alpaca_timeframe,
        start=start_dt,
        end=end_dt,
    )
    bars = client.get_crypto_bars(request)
    rows = bars[symbol] if hasattr(bars, "__getitem__") else list(bars)
    return [
        {
            "timestamp": _normalize_dt(bar.timestamp).isoformat(),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        }
        for bar in rows
    ]


def _fetch_binance_klines(
    *,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    json_getter: JsonGetter | None,
    retry_events: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    interval = _BINANCE_INTERVAL_MAP[timeframe]
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    rows: list[dict[str, object]] = []

    current_start = start_ms
    while current_start < end_ms:
        url = (
            f"{BINANCE_FAPI_BASE}/fapi/v1/klines?"
            + urllib.parse.urlencode(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": _BINANCE_MAX_KLINES,
                    "startTime": current_start,
                    "endTime": end_ms,
                }
            )
        )
        payload = _coerce_list(_request_json(url, json_getter=json_getter, retry_events=retry_events))
        if not payload:
            break

        for item in payload:
            if not isinstance(item, list) or len(item) < 6:
                continue
            timestamp = datetime.fromtimestamp(float(item[0]) / 1000.0, tz=timezone.utc).isoformat()
            rows.append(
                {
                    "timestamp": timestamp,
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                }
            )

        last_open_time = int(payload[-1][0])
        if last_open_time <= current_start or len(payload) < _BINANCE_MAX_KLINES:
            break
        current_start = last_open_time + 1

    return rows


def _fetch_binance_funding_rows(
    *,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    json_getter: JsonGetter | None,
    retry_events: list[dict[str, object]] | None = None,
) -> list[tuple[str, float]]:
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    rows: list[tuple[str, float]] = []

    current_start = start_ms
    while current_start < end_ms:
        url = (
            f"{BINANCE_FAPI_BASE}/fapi/v1/fundingRate?"
            + urllib.parse.urlencode(
                {
                    "symbol": symbol,
                    "limit": _BINANCE_MAX_FUNDING,
                    "startTime": current_start,
                    "endTime": end_ms,
                }
            )
        )
        payload = _coerce_list(_request_json(url, json_getter=json_getter, retry_events=retry_events))
        if not payload:
            break

        for record in payload:
            if not isinstance(record, dict):
                continue
            timestamp = datetime.fromtimestamp(
                float(record["fundingTime"]) / 1000.0, tz=timezone.utc
            ).isoformat()
            rows.append((timestamp, float(record["fundingRate"])))

        last_timestamp = int(payload[-1]["fundingTime"])
        if last_timestamp <= current_start or len(payload) < _BINANCE_MAX_FUNDING:
            break
        current_start = last_timestamp + 1

    return rows


def _fetch_binance_open_interest_rows(
    *,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    json_getter: JsonGetter | None,
    retry_events: list[dict[str, object]] | None = None,
) -> list[tuple[str, float]]:
    interval = _BINANCE_INTERVAL_MAP.get(timeframe, "1h")
    if interval not in {"5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}:
        interval = "1h"

    # Binance only serves recent open-interest history; older requests return 400.
    capped_start_dt = max(start_dt, end_dt - timedelta(days=29))

    start_ms = int(capped_start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    rows: list[tuple[str, float]] = []
    max_window_ms = _open_interest_window_ms(interval)

    current_start = start_ms
    while current_start < end_ms:
        current_end = min(end_ms, current_start + max_window_ms)
        url = (
            f"{BINANCE_FAPI_BASE}/futures/data/openInterestHist?"
            + urllib.parse.urlencode(
                {
                    "symbol": symbol,
                    "period": interval,
                    "limit": _BINANCE_MAX_OPEN_INTEREST,
                    "startTime": current_start,
                    "endTime": current_end,
                }
            )
        )
        payload = _coerce_list(_request_json(url, json_getter=json_getter, retry_events=retry_events))
        if not payload:
            break

        for record in payload:
            if not isinstance(record, dict):
                continue
            timestamp = datetime.fromtimestamp(
                float(record["timestamp"]) / 1000.0, tz=timezone.utc
            ).isoformat()
            rows.append((timestamp, float(record["sumOpenInterest"])))

        last_timestamp = int(payload[-1]["timestamp"])
        if last_timestamp <= current_start or len(payload) < _BINANCE_MAX_OPEN_INTEREST:
            current_start = current_end + 1
            continue
        current_start = last_timestamp + 1

    return rows


def _create_ccxt_exchange(venue: str, *, exchange_factory: CcxtExchangeFactory | None = None) -> object:
    if exchange_factory is not None:
        return exchange_factory(venue)
    try:
        import ccxt  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("ccxt is required for multi-venue perp fetching. Install with: pip install .[data]") from exc

    try:
        exchange_cls = getattr(ccxt, venue)
    except AttributeError as exc:
        raise ValueError(f"unsupported CCXT venue: {venue!r}") from exc
    return exchange_cls({"enableRateLimit": True})


def _load_ccxt_markets(exchange: object) -> dict[str, object]:
    method = _exchange_method(exchange, ("load_markets", "loadMarkets"))
    if method is None:
        return {}
    payload = method()
    return payload if isinstance(payload, dict) else {}


def _resolve_ccxt_market_symbol(*, symbol: str, venue: str, markets: dict[str, object]) -> str:
    raw_symbol = str(symbol).strip().upper()
    candidates = [str(symbol).strip()]
    if "/" not in raw_symbol:
        for quote in ("USDT", "USDC", "USD"):
            if raw_symbol.endswith(quote) and len(raw_symbol) > len(quote):
                base = raw_symbol[: -len(quote)]
                candidates.extend([f"{base}/{quote}:{quote}", f"{base}/{quote}"])
                break
    elif ":" not in raw_symbol and venue == "bybit":
        base_quote = raw_symbol
        quote = raw_symbol.split("/", 1)[1]
        candidates.append(f"{base_quote}:{quote}")

    for candidate in candidates:
        if candidate in markets:
            return candidate
    return candidates[-1] if len(candidates) > 1 else candidates[0]


def _resolve_ccxt_market(*, exchange: object, symbol: str, markets: dict[str, object]) -> dict[str, object]:
    if symbol in markets and isinstance(markets[symbol], dict):
        return dict(markets[symbol])
    method = _exchange_method(exchange, ("market",))
    if method is None:
        return {}
    try:
        payload = method(symbol)
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _fetch_ccxt_ohlcv_rows(
    *,
    exchange: object,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    venue: str,
) -> list[dict[str, object]]:
    method = _exchange_method(exchange, ("fetch_ohlcv", "fetchOHLCV"))
    if method is None:
        raise RuntimeError(f"CCXT exchange {getattr(exchange, 'id', venue)!r} does not expose fetch_ohlcv")

    interval = _BINANCE_INTERVAL_MAP[timeframe]
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    rows: list[dict[str, object]] = []
    current_start = start_ms
    limit = 1_000

    while current_start < end_ms:
        payload = _coerce_list(method(symbol, interval, current_start, limit, _ccxt_params(venue)))
        if not payload:
            break
        for item in payload:
            if not isinstance(item, (list, tuple)) or len(item) < 6:
                continue
            timestamp_ms = int(float(item[0]))
            if timestamp_ms > end_ms:
                continue
            rows.append(
                {
                    "timestamp": datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).isoformat(),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                }
            )
        last_open_time = int(float(payload[-1][0]))
        if last_open_time <= current_start or len(payload) < limit:
            break
        current_start = last_open_time + 1
    return rows


def _fetch_ccxt_funding_rows(
    *,
    exchange: object,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    venue: str,
) -> list[tuple[str, float]]:
    method = _exchange_method(exchange, ("fetch_funding_rate_history", "fetchFundingRateHistory"))
    if method is None:
        return []
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    current_start = start_ms
    rows: list[tuple[str, float]] = []
    limit = 1_000
    while current_start < end_ms:
        payload = _coerce_list(method(symbol, current_start, limit, _ccxt_params(venue)))
        if not payload:
            break
        last_timestamp = current_start
        for record in payload:
            if not isinstance(record, dict):
                continue
            timestamp_ms = _record_ms(record, ("timestamp", "fundingTime", "fundingRateTimestamp"))
            value = _record_float(record, ("fundingRate", "rate"))
            if timestamp_ms is None or value is None or timestamp_ms > end_ms:
                continue
            rows.append((datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).isoformat(), value))
            last_timestamp = max(last_timestamp, timestamp_ms)
        if last_timestamp <= current_start or len(payload) < limit:
            break
        current_start = last_timestamp + 1
    return rows


def _fetch_ccxt_open_interest_rows(
    *,
    exchange: object,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    venue: str,
) -> list[tuple[str, float]]:
    method = _exchange_method(exchange, ("fetch_open_interest_history", "fetchOpenInterestHistory"))
    if method is None:
        return []
    interval = _BINANCE_INTERVAL_MAP.get(timeframe, "1h")
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    current_start = start_ms
    rows: list[tuple[str, float]] = []
    limit = 500
    while current_start < end_ms:
        payload = _coerce_list(method(symbol, interval, current_start, limit, _ccxt_params(venue)))
        if not payload:
            break
        last_timestamp = current_start
        for record in payload:
            if not isinstance(record, dict):
                continue
            timestamp_ms = _record_ms(record, ("timestamp", "openTime"))
            value = _record_float(
                record,
                ("openInterestAmount", "openInterestValue", "openInterest", "sumOpenInterest"),
            )
            if timestamp_ms is None or value is None or timestamp_ms > end_ms:
                continue
            rows.append((datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).isoformat(), value))
            last_timestamp = max(last_timestamp, timestamp_ms)
        if last_timestamp <= current_start or len(payload) < limit:
            break
        current_start = last_timestamp + 1
    return rows


def _fetch_ccxt_leverage_tiers(*, exchange: object, symbol: str, venue: str) -> list[dict[str, float]]:
    method = _exchange_method(exchange, ("fetch_leverage_tiers", "fetchLeverageTiers"))
    if method is None:
        return []
    try:
        payload = method([symbol], _ccxt_params(venue))
    except TypeError:
        try:
            payload = method(symbol, _ccxt_params(venue))
        except Exception:
            return []
    except Exception:
        return []
    if isinstance(payload, dict):
        raw_tiers = payload.get(symbol, payload.get("tiers", []))
    else:
        raw_tiers = payload
    if not isinstance(raw_tiers, list):
        return []
    tiers: list[dict[str, float]] = []
    for item in raw_tiers:
        if not isinstance(item, dict):
            continue
        tier: dict[str, float] = {}
        for source_key, target_key in (
            ("minNotional", "min_notional"),
            ("maxNotional", "max_notional"),
            ("maxLeverage", "max_leverage"),
            ("maintenanceMarginRate", "maintenance_margin_ratio"),
        ):
            value = _record_float(item, (source_key,))
            if value is not None:
                tier[target_key] = value
        if tier:
            tiers.append(tier)
    return tiers


def _request_json(
    url: str,
    *,
    json_getter: JsonGetter | None = None,
    retry_events: list[dict[str, object]] | None = None,
) -> object:
    if json_getter is not None:
        return json_getter(url)
    return _binance_get(url, retry_events=retry_events)


def _binance_get(
    url: str,
    *,
    opener: UrlOpener | None = None,
    sleeper: Sleeper | None = None,
    logger: Logger | None = None,
    retry_events: list[dict[str, object]] | None = None,
) -> object:
    """HTTP GET against a Binance public endpoint with retry + backoff."""
    raw = _http_read_with_retry(
        url,
        timeout=15,
        opener=opener,
        sleeper=sleeper,
        logger=logger,
        retry_events=retry_events,
    )
    return json.loads(raw.decode("utf-8"))


def _http_read_with_retry(
    url: str,
    *,
    timeout: float,
    attempts: int = _RETRY_ATTEMPTS,
    backoff_seconds: float = _RETRY_BACKOFF_SECONDS,
    opener: UrlOpener | None = None,
    sleeper: Sleeper | None = None,
    logger: Logger | None = None,
    retry_events: list[dict[str, object]] | None = None,
) -> bytes:
    last_exc: Exception | None = None
    active_opener = opener or urllib.request.urlopen
    active_sleeper = sleeper or time.sleep
    active_logger = logger or print
    for attempt_index in range(attempts):
        attempt = attempt_index + 1
        try:
            with active_opener(url, timeout=timeout) as response:
                raw = response.read()
            _record_retry_event(retry_events, url=url, attempt=attempt, status="ok", backoff_seconds=0.0)
            return raw
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429:
                wait = backoff_seconds * (4 ** attempt_index)
                will_retry = attempt < attempts
                _record_retry_event(
                    retry_events,
                    url=url,
                    attempt=attempt,
                    status="rate_limited",
                    backoff_seconds=wait if will_retry else 0.0,
                    http_status=exc.code,
                    error=str(exc),
                )
                if will_retry:
                    active_logger(f"[fetch] Binance rate-limited (429). Waiting {wait:.0f}s")
                    active_sleeper(wait)
                    continue
                break
            _record_retry_event(
                retry_events,
                url=url,
                attempt=attempt,
                status="http_error",
                backoff_seconds=0.0,
                http_status=exc.code,
                error=str(exc),
            )
            raise
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_exc = exc
            wait = backoff_seconds * (2 ** attempt_index)
            will_retry = attempt < attempts
            _record_retry_event(
                retry_events,
                url=url,
                attempt=attempt,
                status="network_error",
                backoff_seconds=wait if will_retry else 0.0,
                error=str(exc),
            )
            if will_retry:
                active_logger(f"[fetch] Network error (attempt {attempt}): {exc}. Retrying in {wait:.0f}s")
                active_sleeper(wait)
                continue
    raise RuntimeError(f"Binance fetch failed after {attempts} attempts: {url}") from last_exc


def _record_retry_event(
    retry_events: list[dict[str, object]] | None,
    *,
    url: str,
    attempt: int,
    status: str,
    backoff_seconds: float,
    http_status: int | None = None,
    error: str | None = None,
) -> None:
    if retry_events is None:
        return
    event: dict[str, object] = {
        "url": url,
        "attempt": int(attempt),
        "status": status,
        "backoff_seconds": float(backoff_seconds),
    }
    if http_status is not None:
        event["http_status"] = int(http_status)
    if error:
        event["error"] = error
    retry_events.append(event)


def _align_series_to_timestamps(
    candle_timestamps: list[str],
    series_rows: list[tuple[str, float]],
) -> list[tuple[str, float]]:
    """Forward-fill sparse sidecar series onto candle timestamps."""
    if not candle_timestamps:
        return []

    ordered_series = sorted(
        ((datetime.fromisoformat(timestamp), float(value)) for timestamp, value in series_rows),
        key=lambda item: item[0],
    )
    aligned: list[tuple[str, float]] = []
    current_value = 0.0
    series_index = 0

    for candle_timestamp in candle_timestamps:
        candle_dt = datetime.fromisoformat(candle_timestamp)
        while series_index < len(ordered_series) and ordered_series[series_index][0] <= candle_dt:
            current_value = ordered_series[series_index][1]
            series_index += 1
        aligned.append((candle_timestamp, current_value))
    return aligned


def _write_candle_rows(path: Path, rows: list[dict[str, object]]) -> list[str]:
    timestamps: list[str] = []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "trade_count"])
        for row in rows:
            timestamp = str(row["timestamp"])
            writer.writerow(
                [
                    timestamp,
                    f"{float(row['open']):.8f}",
                    f"{float(row['high']):.8f}",
                    f"{float(row['low']):.8f}",
                    f"{float(row['close']):.8f}",
                    f"{float(row['volume']):.8f}",
                    str(int(float(row.get("trade_count", 0) or 0))),
                ]
            )
            timestamps.append(timestamp)
    return timestamps


def _write_series_rows(path: Path, column: str, rows: list[tuple[str, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", column])
        for timestamp, value in rows:
            writer.writerow([timestamp, f"{float(value):.10f}"])


def _write_zero_series(path: Path, timestamps: list[str], column: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", column])
        for timestamp in timestamps:
            writer.writerow([timestamp, "0.0"])


def _write_empty_series(path: Path, column: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", column])


def _exchange_method(exchange: object, names: tuple[str, ...]):
    for name in names:
        method = getattr(exchange, name, None)
        if callable(method):
            return method
    return None


def _ccxt_params(venue: str) -> dict[str, object]:
    if str(venue).strip().lower() == "bybit":
        return {"category": "linear"}
    return {}


def _record_ms(record: dict[str, object], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = record.get(key)
        if value is None and isinstance(record.get("info"), dict):
            value = record["info"].get(key)  # type: ignore[index]
        if value is None:
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def _record_float(record: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = record.get(key)
        if value is None and isinstance(record.get("info"), dict):
            value = record["info"].get(key)  # type: ignore[index]
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _build_ccxt_venue_profile_payload(
    *,
    venue: str,
    exchange_id: str,
    symbol: str,
    market: dict[str, object],
    leverage_tiers: list[dict[str, float]],
) -> dict[str, object]:
    info = market.get("info") if isinstance(market.get("info"), dict) else {}
    quote_currency = str(market.get("quote") or _infer_symbol_quote(symbol) or "").upper() or None
    settlement_currency = str(market.get("settle") or market.get("settlement") or quote_currency or "").upper() or None
    max_leverage = _market_max_leverage(market)
    profile_tiers = [dict(item) for item in leverage_tiers]
    if not profile_tiers and max_leverage is not None:
        profile_tiers = [{"max_leverage": max_leverage}]
    maintenance_schedule = [
        {
            key: value
            for key, value in item.items()
            if key in {"min_notional", "max_notional", "max_leverage", "maintenance_margin_ratio"}
        }
        for item in leverage_tiers
        if "maintenance_margin_ratio" in item or "max_leverage" in item
    ]
    return {
        "venue": venue,
        "contract_type": "perpetual" if bool(market.get("swap", True)) else str(market.get("type", "perpetual")),
        "quote_currency": quote_currency,
        "settlement_currency": settlement_currency,
        "funding_interval_h": _market_funding_interval_h(market, venue),
        "mark_price_source": "exchange_mark",
        "leverage_tiers": profile_tiers,
        "maintenance_margin_schedule": maintenance_schedule,
        "liquidation_fee_schedule": [],
        "liquidation_style": "partial" if maintenance_schedule else "full",
        "partial_liquidation_ratio": 0.5 if maintenance_schedule else 1.0,
        "liquidation_cooldown_bars": 0,
        "liquidation_mark_price_weight": 0.0,
        "liquidation_mark_premium_bps": 0.0,
        "notes": [
            "phase1_ccxt_market_metadata",
            f"exchange_id={exchange_id}",
            f"ccxt_symbol={symbol}",
            "bybit_v5_reference" if venue == "bybit" else "ccxt_reference",
        ],
    }


def _market_funding_interval_h(market: dict[str, object], venue: str) -> int | None:
    info = market.get("info") if isinstance(market.get("info"), dict) else {}
    for key in ("fundingInterval", "funding_interval"):
        value = market.get(key)
        if value is None:
            value = info.get(key)  # type: ignore[union-attr]
        if value is None:
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue
        if numeric_value >= 24:
            return max(1, int(round(numeric_value / 60.0)))
        return max(1, int(round(numeric_value)))
    normalized = str(venue).strip().lower()
    if normalized in {"binance", "bybit"}:
        return 8
    return None


def _market_max_leverage(market: dict[str, object]) -> float | None:
    limits = market.get("limits") if isinstance(market.get("limits"), dict) else {}
    leverage = limits.get("leverage") if isinstance(limits.get("leverage"), dict) else {}
    for value in (
        leverage.get("max") if isinstance(leverage, dict) else None,
        market.get("maxLeverage"),
    ):
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    info = market.get("info") if isinstance(market.get("info"), dict) else {}
    leverage_filter = info.get("leverageFilter") if isinstance(info.get("leverageFilter"), dict) else {}
    value = leverage_filter.get("maxLeverage") if isinstance(leverage_filter, dict) else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _infer_symbol_quote(symbol: str) -> str | None:
    normalized = str(symbol).strip().upper()
    if "/" in normalized:
        rhs = normalized.split("/", 1)[1]
        return rhs.split(":", 1)[0]
    for suffix in ("USDT", "USDC", "USD"):
        if normalized.endswith(suffix):
            return suffix
    return None


def _ccxt_reference_manifest(venue: str) -> list[dict[str, str]]:
    references = [
        {
            "name": "CCXT manual",
            "url": "https://github.com/ccxt/ccxt/wiki/Manual",
            "intended_usage": "unified OHLCV, funding, open-interest, and market metadata adapter surface",
        }
    ]
    if str(venue).strip().lower() == "bybit":
        references.extend(
            [
                {
                    "name": "Bybit V5 kline",
                    "url": "https://bybit-exchange.github.io/docs/v5/market/kline",
                    "intended_usage": "Bybit public candle endpoint parity reference",
                },
                {
                    "name": "Bybit V5 funding history",
                    "url": "https://bybit-exchange.github.io/docs/v5/market/history-fund-rate",
                    "intended_usage": "Bybit funding-rate history parity reference",
                },
                {
                    "name": "Bybit V5 instruments info",
                    "url": "https://bybit-exchange.github.io/docs/v5/market/instrument",
                    "intended_usage": "Bybit contract metadata and funding interval provenance",
                },
                {
                    "name": "Bybit V5 open interest",
                    "url": "https://bybit-exchange.github.io/docs/v5/market/open-interest",
                    "intended_usage": "Bybit open-interest history parity reference",
                },
            ]
        )
    return references


def _venue_profile_from_manifest(payload: dict[str, object]) -> VenueProfile:
    def _float_list(name: str) -> list[dict[str, float]]:
        raw_items = payload.get(name)
        if not isinstance(raw_items, list):
            return []
        items: list[dict[str, float]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item: dict[str, float] = {}
            for key, value in raw.items():
                try:
                    item[str(key)] = float(value)
                except (TypeError, ValueError):
                    pass
            if item:
                items.append(item)
        return items

    return VenueProfile(
        venue=str(payload.get("venue", "")),
        contract_type=str(payload.get("contract_type", "perpetual")),
        quote_currency=payload.get("quote_currency") if payload.get("quote_currency") is not None else None,
        settlement_currency=payload.get("settlement_currency") if payload.get("settlement_currency") is not None else None,
        funding_interval_h=int(payload["funding_interval_h"]) if payload.get("funding_interval_h") is not None else None,
        mark_price_source=str(payload.get("mark_price_source", "exchange_mark")),
        leverage_tiers=_float_list("leverage_tiers"),
        maintenance_margin_schedule=_float_list("maintenance_margin_schedule"),
        liquidation_fee_schedule=_float_list("liquidation_fee_schedule"),
        liquidation_style=str(payload.get("liquidation_style", "full")),
        partial_liquidation_ratio=float(payload.get("partial_liquidation_ratio", 1.0)),
        liquidation_cooldown_bars=int(payload.get("liquidation_cooldown_bars", 0)),
        liquidation_mark_price_weight=float(payload.get("liquidation_mark_price_weight", 0.0)),
        liquidation_mark_premium_bps=float(payload.get("liquidation_mark_premium_bps", 0.0)),
        notes=[str(item) for item in payload.get("notes", [])] if isinstance(payload.get("notes"), list) else [],
    )


def _normalize_dt(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        return value.to_pydatetime().astimezone(timezone.utc)  # type: ignore[union-attr]
    except AttributeError:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


def _normalize_binance_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if "/" in normalized:
        base = normalized.split("/", 1)[0]
        return f"{base}USDT"
    if ":" in normalized and "/" in normalized:
        base = normalized.split("/", 1)[0]
        return f"{base}USDT"
    return normalized


def _parse_archive_date(value: str | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _iter_archive_days(start_day: date, end_day: date):
    current = start_day
    while current <= end_day:
        yield current
        current += timedelta(days=1)


def _iter_archive_periods(start_day: date, end_day: date):
    current = start_day
    while current <= end_day:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(days=1)
        if current.day == 1 and month_end <= end_day:
            yield "monthly", current, month_end
            current = month_end + timedelta(days=1)
            continue
        yield "daily", current, current
        current += timedelta(days=1)


def _archive_period_label(period_type: str, period_start: date) -> str:
    if period_type == "monthly":
        return period_start.strftime("%Y-%m")
    return period_start.isoformat()


def _binance_archive_url(
    *,
    data_type: str,
    symbol: str,
    interval: str | None,
    day: date,
    period_type: str = "daily",
) -> str:
    if period_type not in {"daily", "monthly"}:
        raise ValueError(f"unsupported Binance archive period_type: {period_type!r}")
    period_text = _archive_period_label(period_type, day)
    if data_type == "klines":
        if interval is None:
            raise ValueError("klines archive URL requires interval")
        filename = f"{symbol}-{interval}-{period_text}.zip"
        return (
            f"{BINANCE_PUBLIC_DATA_BASE}/data/futures/{BINANCE_ARCHIVE_MARKET}/{period_type}/"
            f"klines/{symbol}/{interval}/{filename}"
        )
    if data_type in {"aggTrades", "trades"}:
        filename = f"{symbol}-{data_type}-{period_text}.zip"
        return (
            f"{BINANCE_PUBLIC_DATA_BASE}/data/futures/{BINANCE_ARCHIVE_MARKET}/{period_type}/"
            f"{data_type}/{symbol}/{filename}"
        )
    raise ValueError(f"unsupported Binance archive data_type: {data_type!r}")


def _binance_archive_raw_path(
    *,
    output_dir: Path,
    data_type: str,
    symbol: str,
    interval: str | None,
    day: date,
    period_type: str = "daily",
) -> Path:
    url = _binance_archive_url(
        data_type=data_type,
        symbol=symbol,
        interval=interval,
        day=day,
        period_type=period_type,
    )
    filename = url.rsplit("/", 1)[-1]
    parts = ["raw", "binance_archive", "futures", BINANCE_ARCHIVE_MARKET, period_type, data_type, symbol]
    if interval is not None:
        parts.append(interval)
    path = output_dir.joinpath(*parts, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _binance_rest_fallback_raw_path(
    *,
    output_dir: Path,
    symbol: str,
    interval: str,
    period_type: str,
    period_start: date,
) -> Path:
    label = _archive_period_label(period_type, period_start)
    path = output_dir.joinpath(
        "raw",
        "binance_rest_fallback",
        "futures",
        BINANCE_ARCHIVE_MARKET,
        period_type,
        "klines",
        symbol,
        interval,
        f"{symbol}-{interval}-{label}.json",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _download_archive_bytes(
    url: str,
    raw_path: Path,
    *,
    archive_getter: ArchiveGetter | None,
    retry_events: list[dict[str, object]] | None = None,
) -> bytes:
    raw = _request_bytes(url, archive_getter=archive_getter, retry_events=retry_events)
    raw_path.write_bytes(raw)
    return raw


def _download_and_validate_archive_checksum(
    *,
    url: str,
    raw_path: Path,
    archive_getter: ArchiveGetter | None,
    retry_events: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    checksum_url = f"{url}.CHECKSUM"
    checksum_path = raw_path.with_name(f"{raw_path.name}.CHECKSUM")
    try:
        checksum_raw = _request_bytes(
            checksum_url,
            archive_getter=archive_getter,
            retry_events=retry_events,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, RuntimeError, FileNotFoundError):
        return {"url": checksum_url, "path": str(checksum_path), "status": "unavailable"}

    checksum_path.write_bytes(checksum_raw)
    expected = _parse_checksum_text(checksum_raw.decode("utf-8", errors="replace"))
    actual = _sha256_file(raw_path)
    if expected and expected.lower() != actual.lower():
        raise RuntimeError(f"checksum mismatch for {raw_path}: expected {expected}, got {actual}")
    return {
        "url": checksum_url,
        "path": str(checksum_path),
        "status": "validated" if expected else "present_unparsed",
        "sha256": actual,
    }


def _request_bytes(
    url: str,
    *,
    archive_getter: ArchiveGetter | None = None,
    retry_events: list[dict[str, object]] | None = None,
) -> bytes:
    if archive_getter is not None:
        return archive_getter(url)
    return _http_read_with_retry(url, timeout=30, retry_events=retry_events)


def _parse_checksum_text(text: str) -> str | None:
    for token in text.replace("*", " ").split():
        cleaned = token.strip()
        if len(cleaned) == 64 and all(char in "0123456789abcdefABCDEF" for char in cleaned):
            return cleaned
    return None


def _parse_binance_archive_kline_zip(raw_bytes: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(raw_bytes)) as archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            with archive.open(name) as handle:
                text = handle.read().decode("utf-8")
            reader = csv.reader(text.splitlines())
            for item in reader:
                if not item or item[0].strip().lower() in {"open_time", "timestamp"}:
                    continue
                if len(item) < 6:
                    continue
                try:
                    open_time_ms = int(float(item[0]))
                    rows.append(
                        {
                            "timestamp": datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc).isoformat(),
                            "open": float(item[1]),
                            "high": float(item[2]),
                            "low": float(item[3]),
                            "close": float(item[4]),
                            "volume": float(item[5]),
                            "trade_count": int(float(item[8])) if len(item) > 8 and item[8] else 0,
                        }
                    )
                except (TypeError, ValueError):
                    continue
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compute_paths_content_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda value: str(value)):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        if path.exists():
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _dataset_version(
    *,
    raw_source_id: str,
    raw_source_hash: str,
    parser_version: str,
    normalization_version: str,
) -> str:
    payload = {
        "raw_source_id": raw_source_id,
        "raw_source_hash": raw_source_hash,
        "parser_version": parser_version,
        "normalization_version": normalization_version,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _coerce_list(payload: object) -> list:
    return payload if isinstance(payload, list) else []


def _open_interest_window_ms(interval: str) -> int:
    interval_minutes = _OPEN_INTEREST_INTERVAL_MINUTES.get(interval, 60)
    return interval_minutes * 60 * 1000 * (_BINANCE_MAX_OPEN_INTEREST - 1)


def _attach_fetch_metadata(snapshot, *, manifest_path: Path):
    manifest = _load_fetch_manifest(manifest_path)
    provider_name = str(manifest.get("provider", "binance_perps"))
    build_mode = str(manifest.get("build_mode", "fetched_bundle"))
    exchange_id = manifest.get("exchange_id")
    provenance_updates = {
        "provider": provider_name,
        "build_mode": build_mode,
        "fetch_manifest": str(manifest_path),
        "fetch_request": {
            "venue": manifest.get("venue"),
            "exchange_id": exchange_id,
            "symbol": manifest.get("symbol"),
            "timeframe": manifest.get("timeframe"),
            "lookback_days": manifest.get("lookback_days"),
            "start_date": manifest.get("start_date"),
            "end_date": manifest.get("end_date"),
            "archive_interval": manifest.get("archive_interval"),
        },
    }
    for key in (
        "source_metadata_version",
        "raw_source_id",
        "raw_source_hash",
        "parser_version",
        "normalization_version",
        "exchange_rules_version",
        "feature_version",
        "scenario_pack_version",
        "cost_model_version",
        "dataset_version",
        "field_confidence",
        "archive",
    ):
        if key in manifest:
            provenance_updates[key] = manifest[key]
    quality_report = snapshot.quality_report
    if quality_report is not None:
        source_checks = dict(quality_report.source_checks)
        source_checks.update(
            {
                "fetch_provider": provider_name,
                "fetch_build_mode": build_mode,
                "fetch_manifest": str(manifest_path),
                "fetch_exchange_id": exchange_id,
                "raw_source_id": manifest.get("raw_source_id"),
                "raw_source_hash": manifest.get("raw_source_hash"),
                "dataset_version": manifest.get("dataset_version"),
                "field_confidence": manifest.get("field_confidence"),
            }
        )
        quality_report = replace(quality_report, source_checks=source_checks)
    attached = clone_snapshot(
        snapshot,
        snapshot_id=snapshot.snapshot_id,
        provenance_updates=provenance_updates,
        quality_report=quality_report,
    )
    profile_payload = manifest.get("venue_profile")
    if isinstance(profile_payload, dict):
        venue_profile = _venue_profile_from_manifest(profile_payload)
        attached = replace(attached, venue_profile=venue_profile, contract_type=venue_profile.contract_type)
    return attached


def _load_fetch_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
