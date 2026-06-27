from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.config.models import DataSnapshot, SnapshotQualityReport, VenueProfile
from engine.data.schema import Candle
from engine.data.validate import validate_snapshot_bundle


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    read_only: bool = True
    supports_funding: bool = False
    supports_open_interest: bool = False
    supports_liquidations: bool = False


DEFAULT_PROVIDER_CONFIGS = {
    "openbb": ProviderConfig(
        name="openbb",
        read_only=True,
        supports_funding=True,
        supports_open_interest=True,
        supports_liquidations=False,
    ),
    "ccxt-reference": ProviderConfig(
        name="ccxt-reference",
        read_only=True,
        supports_funding=True,
        supports_open_interest=True,
        supports_liquidations=False,
    ),
    "ccxt": ProviderConfig(
        name="ccxt",
        read_only=True,
        supports_funding=True,
        supports_open_interest=True,
        supports_liquidations=False,
    ),
    "bybit": ProviderConfig(
        name="bybit",
        read_only=True,
        supports_funding=True,
        supports_open_interest=True,
        supports_liquidations=False,
    ),
}

TIMESTAMP_COLUMN_ALIASES = ("timestamp", "time", "datetime", "date", "open_time")
CANDLE_COLUMN_ALIASES = {
    "timestamp": TIMESTAMP_COLUMN_ALIASES,
    "open": ("open", "Open", "o", "O"),
    "high": ("high", "High", "h", "H"),
    "low": ("low", "Low", "l", "L"),
    "close": ("close", "Close", "c", "C"),
    "volume": ("volume", "Volume", "v", "V"),
}
SERIES_VALUE_COLUMN_ALIASES = {
    "funding_rate": ("funding_rate", "fundingRate", "funding", "rate"),
    "open_interest": ("open_interest", "openInterest", "oi"),
    "liquidation_notional": ("liquidation_notional", "liquidationNotional", "liquidation", "liquidations"),
}
CANDLE_OPTIONAL_NUMERIC_COLUMN_ALIASES = {
    "trade_count": ("trade_count", "tradeCount", "trades"),
    "mark_price": ("mark_price", "markPrice", "mark"),
    "index_price": ("index_price", "indexPrice", "index"),
    "open_interest_usd": ("open_interest_usd", "openInterestUsd", "oi_usd"),
    "basis_bps": ("basis_bps", "basisBps"),
    "liq_long_usd": ("liq_long_usd", "liqLongUsd", "liquidation_long_usd"),
    "liq_short_usd": ("liq_short_usd", "liqShortUsd", "liquidation_short_usd"),
    "spread_bps": ("spread_bps", "spreadBps", "spread"),
    "depth_bid_1bp_usd": ("depth_bid_1bp_usd", "depthBid1bpUsd"),
    "depth_ask_1bp_usd": ("depth_ask_1bp_usd", "depthAsk1bpUsd"),
    "latency_proxy_ms": ("latency_proxy_ms", "latencyProxyMs"),
}
CANDLE_OPTIONAL_TEXT_COLUMN_ALIASES = {
    "next_funding_ts": ("next_funding_ts", "nextFundingTs"),
    "vol_regime": ("vol_regime", "volRegime"),
    "regime_id": ("regime_id", "regimeId"),
}
NULL_NUMERIC_MARKERS = {"na", "n/a", "null", "none", "-", "--"}
SNAPSHOT_BUILD_VERSION = "phase1_snapshot_builder_v1"
SOURCE_METADATA_VERSION = "v3_phase1_source_metadata_v1"
DEFAULT_PARSER_VERSION = "csv_snapshot_parser_v1"
DEFAULT_NORMALIZATION_VERSION = "v3_phase1_snapshot_normalization_v1"
DEFAULT_EXCHANGE_RULES_VERSION = "runtime_venue_preset_v1"
DEFAULT_FEATURE_VERSION = "phase1_snapshot_features_v1"
DEFAULT_SCENARIO_PACK_VERSION = "not_applied"
DEFAULT_COST_MODEL_VERSION = "not_applied"


def load_snapshot_from_csv(
    path: Path,
    snapshot_id: str,
    symbol: str,
    venue: str,
    timeframe: str,
    maker_fee_bps: float,
    taker_fee_bps: float,
) -> DataSnapshot:
    return build_snapshot_from_csv(
        path=path,
        snapshot_id=snapshot_id,
        symbol=symbol,
        venue=venue,
        timeframe=timeframe,
        maker_fee_bps=maker_fee_bps,
        taker_fee_bps=taker_fee_bps,
    )


def build_snapshot_from_csv(
    *,
    path: Path,
    snapshot_id: str,
    symbol: str,
    venue: str,
    timeframe: str,
    maker_fee_bps: float,
    taker_fee_bps: float,
) -> DataSnapshot:
    candles: list[Candle] = []
    funding_rates: list[float] = []
    open_interest: list[float] = []
    liquidation_notional: list[float] = []
    optional_numeric_values = {key: [] for key in CANDLE_OPTIONAL_NUMERIC_COLUMN_ALIASES}
    optional_text_values = {key: [] for key in CANDLE_OPTIONAL_TEXT_COLUMN_ALIASES}
    invalid_market_counts = {
        "funding_rate": 0,
        "open_interest": 0,
        "liquidation_notional": 0,
    }
    present_market_counts = {
        "funding_rate": 0,
        "open_interest": 0,
        "liquidation_notional": 0,
    }

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        resolved_columns = _resolve_required_columns(reader.fieldnames or [], CANDLE_COLUMN_ALIASES)
        optional_market_columns = _resolve_optional_market_columns(reader.fieldnames or [])
        optional_numeric_columns = _resolve_optional_snapshot_columns(
            reader.fieldnames or [],
            CANDLE_OPTIONAL_NUMERIC_COLUMN_ALIASES,
        )
        optional_text_columns = _resolve_optional_snapshot_columns(
            reader.fieldnames or [],
            CANDLE_OPTIONAL_TEXT_COLUMN_ALIASES,
        )
        for row_index, row in enumerate(reader, start=2):
            trade_count = _read_optional_int(row, optional_numeric_columns["trade_count"])
            candles.append(
                Candle(
                    timestamp=_read_required_timestamp(row, resolved_columns["timestamp"], row_index),
                    open=_read_required_numeric(row, resolved_columns["open"], row_index),
                    high=_read_required_numeric(row, resolved_columns["high"], row_index),
                    low=_read_required_numeric(row, resolved_columns["low"], row_index),
                    close=_read_required_numeric(row, resolved_columns["close"], row_index),
                    volume=_read_required_numeric(row, resolved_columns["volume"], row_index),
                    trade_count=trade_count,
                )
            )
            funding_value, funding_invalid = _read_optional_float(row, optional_market_columns["funding_rate"])
            open_interest_value, open_interest_invalid = _read_optional_float(row, optional_market_columns["open_interest"])
            liquidation_value, liquidation_invalid = _read_optional_float(row, optional_market_columns["liquidation_notional"])
            funding_rates.append(funding_value)
            open_interest.append(open_interest_value)
            liquidation_notional.append(liquidation_value)
            present_market_counts["funding_rate"] += int(
                _has_present_optional_numeric_value(row, optional_market_columns["funding_rate"])
            )
            present_market_counts["open_interest"] += int(
                _has_present_optional_numeric_value(row, optional_market_columns["open_interest"])
            )
            present_market_counts["liquidation_notional"] += int(
                _has_present_optional_numeric_value(row, optional_market_columns["liquidation_notional"])
            )
            invalid_market_counts["funding_rate"] += int(funding_invalid)
            invalid_market_counts["open_interest"] += int(open_interest_invalid)
            invalid_market_counts["liquidation_notional"] += int(liquidation_invalid)
            for key, column_name in optional_numeric_columns.items():
                if key == "trade_count":
                    continue
                optional_numeric_values[key].append(_read_optional_float(row, column_name)[0])
            for key, column_name in optional_text_columns.items():
                optional_text_values[key].append(_read_optional_text(row, column_name))

    quality_flags = _build_invalid_quality_flags(invalid_market_counts)
    provenance = _build_snapshot_provenance(
        provider="csv",
        build_mode="single_csv",
        candles_path=path,
    )
    venue_profile = _build_venue_profile(venue=venue, symbol=symbol)
    phase1_fields = _derive_phase1_snapshot_contract(
        candles=candles,
        funding_rates=funding_rates,
        open_interest=open_interest,
        liquidation_notional=liquidation_notional,
        venue_profile=venue_profile,
        observed_numeric_values=optional_numeric_values,
        observed_numeric_columns=optional_numeric_columns,
        observed_text_values=optional_text_values,
        observed_text_columns=optional_text_columns,
    )
    provenance["phase1_field_population"] = dict(phase1_fields["field_population"])
    return DataSnapshot(
        snapshot_id=snapshot_id,
        symbol=symbol,
        venue=venue,
        timeframe=timeframe,
        candles=candles,
        funding_rates=funding_rates,
        open_interest=open_interest,
        liquidation_notional=liquidation_notional,
        maker_fee_bps=maker_fee_bps,
        taker_fee_bps=taker_fee_bps,
        contract_type=venue_profile.contract_type,
        mark_price=phase1_fields["mark_price"],
        index_price=phase1_fields["index_price"],
        next_funding_ts=phase1_fields["next_funding_ts"],
        open_interest_usd=phase1_fields["open_interest_usd"],
        basis_bps=phase1_fields["basis_bps"],
        liq_long_usd=phase1_fields["liq_long_usd"],
        liq_short_usd=phase1_fields["liq_short_usd"],
        spread_bps=phase1_fields["spread_bps"],
        depth_bid_1bp_usd=phase1_fields["depth_bid_1bp_usd"],
        depth_ask_1bp_usd=phase1_fields["depth_ask_1bp_usd"],
        latency_proxy_ms=phase1_fields["latency_proxy_ms"],
        ret_1=phase1_fields["ret_1"],
        ret_24=phase1_fields["ret_24"],
        rv_24h=phase1_fields["rv_24h"],
        funding_z=phase1_fields["funding_z"],
        d_oi=phase1_fields["d_oi"],
        d_oi_z=phase1_fields["d_oi_z"],
        liq_intensity_z=phase1_fields["liq_intensity_z"],
        vol_regime=phase1_fields["vol_regime"],
        regime_id=phase1_fields["regime_id"],
        regime_probabilities=phase1_fields["regime_probabilities"],
        quality_flags=quality_flags,
        venue_profile=venue_profile,
        quality_report=_build_quality_report(
            snapshot_id=snapshot_id,
            timeframe=timeframe,
            candles=candles,
            funding_rates=funding_rates,
            open_interest=open_interest,
            liquidation_notional=liquidation_notional,
            quality_flags=quality_flags,
            present_market_counts=present_market_counts,
            source_checks={
                "provider": "csv",
                "build_mode": "single_csv",
                "build_version": provenance["build_version"],
                "source_hash": provenance["source_hash"],
                "source_paths": dict(provenance["source_paths"]),
                "phase1_field_population": dict(phase1_fields["field_population"]),
            },
        ),
        provenance=provenance,
    )


def load_snapshot_bundle_from_csv(
    candles_path: Path,
    snapshot_id: str,
    symbol: str,
    venue: str,
    timeframe: str,
    maker_fee_bps: float,
    taker_fee_bps: float,
    funding_path: Path | None = None,
    open_interest_path: Path | None = None,
    liquidation_notional_path: Path | None = None,
) -> DataSnapshot:
    return build_snapshot_from_bundle(
        candles_path=candles_path,
        snapshot_id=snapshot_id,
        symbol=symbol,
        venue=venue,
        timeframe=timeframe,
        maker_fee_bps=maker_fee_bps,
        taker_fee_bps=taker_fee_bps,
        funding_path=funding_path,
        open_interest_path=open_interest_path,
        liquidation_notional_path=liquidation_notional_path,
    )


def build_snapshot_from_bundle(
    *,
    candles_path: Path,
    snapshot_id: str,
    symbol: str,
    venue: str,
    timeframe: str,
    maker_fee_bps: float,
    taker_fee_bps: float,
    funding_path: Path | None = None,
    open_interest_path: Path | None = None,
    liquidation_notional_path: Path | None = None,
) -> DataSnapshot:
    candles: list[Candle] = []
    optional_numeric_values = {key: [] for key in CANDLE_OPTIONAL_NUMERIC_COLUMN_ALIASES}
    optional_text_values = {key: [] for key in CANDLE_OPTIONAL_TEXT_COLUMN_ALIASES}
    with candles_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        resolved_columns = _resolve_required_columns(reader.fieldnames or [], CANDLE_COLUMN_ALIASES)
        optional_numeric_columns = _resolve_optional_snapshot_columns(
            reader.fieldnames or [],
            CANDLE_OPTIONAL_NUMERIC_COLUMN_ALIASES,
        )
        optional_text_columns = _resolve_optional_snapshot_columns(
            reader.fieldnames or [],
            CANDLE_OPTIONAL_TEXT_COLUMN_ALIASES,
        )
        for row_index, row in enumerate(reader, start=2):
            trade_count = _read_optional_int(row, optional_numeric_columns["trade_count"])
            candles.append(
                Candle(
                    timestamp=_read_required_timestamp(row, resolved_columns["timestamp"], row_index),
                    open=_read_required_numeric(row, resolved_columns["open"], row_index),
                    high=_read_required_numeric(row, resolved_columns["high"], row_index),
                    low=_read_required_numeric(row, resolved_columns["low"], row_index),
                    close=_read_required_numeric(row, resolved_columns["close"], row_index),
                    volume=_read_required_numeric(row, resolved_columns["volume"], row_index),
                    trade_count=trade_count,
                )
            )
            for key, column_name in optional_numeric_columns.items():
                if key == "trade_count":
                    continue
                optional_numeric_values[key].append(_read_optional_float(row, column_name)[0])
            for key, column_name in optional_text_columns.items():
                optional_text_values[key].append(_read_optional_text(row, column_name))

    funding_by_timestamp, funding_invalid_count, funding_invalid_timestamp_count = _load_timestamp_series(funding_path, "funding_rate")
    open_interest_by_timestamp, open_interest_invalid_count, open_interest_invalid_timestamp_count = _load_timestamp_series(open_interest_path, "open_interest")
    liquidation_by_timestamp, liquidation_invalid_count, liquidation_invalid_timestamp_count = _load_timestamp_series(liquidation_notional_path, "liquidation_notional")

    timestamps = [candle.timestamp.isoformat() for candle in candles]
    quality_flags = _build_bundle_quality_flags(
        timestamps=timestamps,
        funding_by_timestamp=funding_by_timestamp,
        open_interest_by_timestamp=open_interest_by_timestamp,
        liquidation_by_timestamp=liquidation_by_timestamp,
        funding_path=funding_path,
        open_interest_path=open_interest_path,
        liquidation_notional_path=liquidation_notional_path,
        funding_invalid_count=funding_invalid_count,
        open_interest_invalid_count=open_interest_invalid_count,
        liquidation_invalid_count=liquidation_invalid_count,
        funding_invalid_timestamp_count=funding_invalid_timestamp_count,
        open_interest_invalid_timestamp_count=open_interest_invalid_timestamp_count,
        liquidation_invalid_timestamp_count=liquidation_invalid_timestamp_count,
    )
    provenance = _build_snapshot_provenance(
        provider="csv",
        build_mode="bundle_csv",
        candles_path=candles_path,
        funding_path=funding_path,
        open_interest_path=open_interest_path,
        liquidation_notional_path=liquidation_notional_path,
    )
    funding_rates = [funding_by_timestamp.get(timestamp, 0.0) for timestamp in timestamps]
    open_interest = [open_interest_by_timestamp.get(timestamp, 0.0) for timestamp in timestamps]
    liquidation_notional = [liquidation_by_timestamp.get(timestamp, 0.0) for timestamp in timestamps]
    venue_profile = _build_venue_profile(venue=venue, symbol=symbol)
    phase1_fields = _derive_phase1_snapshot_contract(
        candles=candles,
        funding_rates=funding_rates,
        open_interest=open_interest,
        liquidation_notional=liquidation_notional,
        venue_profile=venue_profile,
        observed_numeric_values=optional_numeric_values,
        observed_numeric_columns=optional_numeric_columns,
        observed_text_values=optional_text_values,
        observed_text_columns=optional_text_columns,
    )
    provenance["phase1_field_population"] = dict(phase1_fields["field_population"])
    present_market_counts = {
        "funding_rate": sum(1 for timestamp in timestamps if timestamp in funding_by_timestamp),
        "open_interest": sum(1 for timestamp in timestamps if timestamp in open_interest_by_timestamp),
        "liquidation_notional": sum(1 for timestamp in timestamps if timestamp in liquidation_by_timestamp),
    }
    return DataSnapshot(
        snapshot_id=snapshot_id,
        symbol=symbol,
        venue=venue,
        timeframe=timeframe,
        candles=candles,
        funding_rates=funding_rates,
        open_interest=open_interest,
        liquidation_notional=liquidation_notional,
        maker_fee_bps=maker_fee_bps,
        taker_fee_bps=taker_fee_bps,
        contract_type=venue_profile.contract_type,
        mark_price=phase1_fields["mark_price"],
        index_price=phase1_fields["index_price"],
        next_funding_ts=phase1_fields["next_funding_ts"],
        open_interest_usd=phase1_fields["open_interest_usd"],
        basis_bps=phase1_fields["basis_bps"],
        liq_long_usd=phase1_fields["liq_long_usd"],
        liq_short_usd=phase1_fields["liq_short_usd"],
        spread_bps=phase1_fields["spread_bps"],
        depth_bid_1bp_usd=phase1_fields["depth_bid_1bp_usd"],
        depth_ask_1bp_usd=phase1_fields["depth_ask_1bp_usd"],
        latency_proxy_ms=phase1_fields["latency_proxy_ms"],
        ret_1=phase1_fields["ret_1"],
        ret_24=phase1_fields["ret_24"],
        rv_24h=phase1_fields["rv_24h"],
        funding_z=phase1_fields["funding_z"],
        d_oi=phase1_fields["d_oi"],
        d_oi_z=phase1_fields["d_oi_z"],
        liq_intensity_z=phase1_fields["liq_intensity_z"],
        vol_regime=phase1_fields["vol_regime"],
        regime_id=phase1_fields["regime_id"],
        regime_probabilities=phase1_fields["regime_probabilities"],
        quality_flags=quality_flags,
        venue_profile=venue_profile,
        quality_report=_build_quality_report(
            snapshot_id=snapshot_id,
            timeframe=timeframe,
            candles=candles,
            funding_rates=funding_rates,
            open_interest=open_interest,
            liquidation_notional=liquidation_notional,
            quality_flags=quality_flags,
            present_market_counts=present_market_counts,
            source_checks={
                "provider": "csv",
                "build_mode": "bundle_csv",
                "build_version": provenance["build_version"],
                "source_hash": provenance["source_hash"],
                "source_paths": dict(provenance["source_paths"]),
                "phase1_field_population": dict(phase1_fields["field_population"]),
            },
        ),
        provenance=provenance,
    )


def _build_snapshot_provenance(
    *,
    provider: str,
    build_mode: str,
    candles_path: Path,
    funding_path: Path | None = None,
    open_interest_path: Path | None = None,
    liquidation_notional_path: Path | None = None,
) -> dict[str, object]:
    source_paths: dict[str, str] = {"candles": str(candles_path)}
    if funding_path is not None:
        source_paths["funding_rate"] = str(funding_path)
    if open_interest_path is not None:
        source_paths["open_interest"] = str(open_interest_path)
    if liquidation_notional_path is not None:
        source_paths["liquidation_notional"] = str(liquidation_notional_path)
    source_hash = _compute_source_hash(source_paths)
    raw_source_id = f"{provider}:{build_mode}:{source_paths['candles']}"
    dataset_version = _compute_dataset_version(
        raw_source_id=raw_source_id,
        raw_source_hash=source_hash,
        parser_version=DEFAULT_PARSER_VERSION,
        normalization_version=DEFAULT_NORMALIZATION_VERSION,
    )
    return {
        "provider": provider,
        "build_mode": build_mode,
        "build_version": SNAPSHOT_BUILD_VERSION,
        "source_metadata_version": SOURCE_METADATA_VERSION,
        "raw_source_id": raw_source_id,
        "raw_source_hash": source_hash,
        "parser_version": DEFAULT_PARSER_VERSION,
        "normalization_version": DEFAULT_NORMALIZATION_VERSION,
        "exchange_rules_version": DEFAULT_EXCHANGE_RULES_VERSION,
        "feature_version": DEFAULT_FEATURE_VERSION,
        "scenario_pack_version": DEFAULT_SCENARIO_PACK_VERSION,
        "cost_model_version": DEFAULT_COST_MODEL_VERSION,
        "dataset_version": dataset_version,
        "source_paths": source_paths,
        "source_hash": source_hash,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _build_quality_report(
    *,
    snapshot_id: str,
    timeframe: str,
    candles: list[Candle],
    funding_rates: list[float],
    open_interest: list[float],
    liquidation_notional: list[float],
    quality_flags: list[str],
    present_market_counts: dict[str, int],
    source_checks: dict[str, object],
) -> SnapshotQualityReport:
    validation = validate_snapshot_bundle(
        candle_timestamps=[candle.timestamp.isoformat() for candle in candles],
        candle_opens=[candle.open for candle in candles],
        candle_highs=[candle.high for candle in candles],
        candle_lows=[candle.low for candle in candles],
        candle_closes=[candle.close for candle in candles],
        candle_volumes=[candle.volume for candle in candles],
        funding_rates=funding_rates,
        open_interest=open_interest,
        liquidation_notional=liquidation_notional,
        timeframe=timeframe,
    )
    issues = list(dict.fromkeys([*validation["warnings"], *quality_flags]))
    row_count = max(1, len(candles))
    quality_score = max(0.0, 1.0 - (len(issues) / row_count))
    return SnapshotQualityReport(
        report_id=f"{snapshot_id}:quality",
        snapshot_id=snapshot_id,
        quality_score=quality_score,
        passed=not issues,
        issues=issues,
        metrics={
            "candle_count": len(candles),
            "quality_flag_count": len(quality_flags),
            "validation_warning_count": len(validation["warnings"]),
            "funding_present_count": present_market_counts["funding_rate"],
            "open_interest_present_count": present_market_counts["open_interest"],
            "liquidation_notional_present_count": present_market_counts["liquidation_notional"],
            "funding_coverage_ratio": _safe_coverage_ratio(present_market_counts["funding_rate"], len(candles)),
            "open_interest_coverage_ratio": _safe_coverage_ratio(present_market_counts["open_interest"], len(candles)),
            "liquidation_notional_coverage_ratio": _safe_coverage_ratio(
                present_market_counts["liquidation_notional"], len(candles)
            ),
            "first_candle_ts": candles[0].timestamp.isoformat() if candles else None,
            "last_candle_ts": candles[-1].timestamp.isoformat() if candles else None,
        },
        source_checks=source_checks,
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
    )


def _compute_source_hash(source_paths: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for source_name in sorted(source_paths):
        source_path = Path(source_paths[source_name])
        digest.update(source_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(source_path).encode("utf-8"))
        digest.update(b"\0")
        if source_path.exists():
            with source_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(8192), b""):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _compute_dataset_version(
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
    encoded = repr(sorted(payload.items())).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_coverage_ratio(present_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return present_count / total_count


def _build_venue_profile(*, venue: str, symbol: str) -> VenueProfile:
    preset = _load_venue_runtime_preset(venue)
    quote_currency = _infer_quote_currency(symbol)
    maintenance_margin_schedule = [dict(item) for item in preset.get("maintenance_margin_schedule", [])]
    liquidation_fee_schedule = [dict(item) for item in preset.get("liquidation_fee_schedule", [])]
    leverage_tiers = [
        {"max_leverage": float(item["max_leverage"])}
        for item in maintenance_margin_schedule
        if "max_leverage" in item
    ]
    return VenueProfile(
        venue=venue,
        contract_type="perpetual",
        quote_currency=quote_currency,
        settlement_currency=quote_currency,
        funding_interval_h=_default_funding_interval_h(venue),
        mark_price_source="exchange_mark",
        leverage_tiers=leverage_tiers,
        maintenance_margin_schedule=maintenance_margin_schedule,
        liquidation_fee_schedule=liquidation_fee_schedule,
        liquidation_style="partial" if maintenance_margin_schedule else "full",
        partial_liquidation_ratio=0.5 if maintenance_margin_schedule else 1.0,
        liquidation_cooldown_bars=int(preset.get("liquidation_cooldown_bars", 0)),
        liquidation_mark_price_weight=float(preset.get("liquidation_mark_price_weight", 0.0)),
        liquidation_mark_premium_bps=float(preset.get("liquidation_mark_premium_bps", 0.0)),
        notes=["phase1_provider_metadata"],
    )


def _load_venue_runtime_preset(venue: str) -> dict[str, object]:
    try:
        from engine.app.config import VENUE_RUNTIME_PRESETS

        return dict(VENUE_RUNTIME_PRESETS.get(str(venue).lower(), {}))
    except Exception:
        return {}


def _default_funding_interval_h(venue: str) -> int | None:
    normalized = str(venue).strip().lower()
    if normalized in {"binance", "bybit"}:
        return 8
    return None


def _infer_quote_currency(symbol: str) -> str | None:
    normalized = str(symbol).strip().upper()
    for suffix in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if normalized.endswith(suffix):
            return suffix
    return None


def _load_timestamp_series(path: Path | None, value_column: str) -> tuple[dict[str, float], int, int]:
    if path is None or not path.exists():
        return {}, 0, 0
    values: dict[str, float] = {}
    invalid_count = 0
    invalid_timestamp_count = 0
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        timestamp_column = _resolve_optional_column(fieldnames, TIMESTAMP_COLUMN_ALIASES)
        value_column_name = _resolve_optional_column(fieldnames, SERIES_VALUE_COLUMN_ALIASES.get(value_column, (value_column,)))
        if timestamp_column is None or value_column_name is None:
            return values, 0, 0
        for row in reader:
            timestamp = row.get(timestamp_column)
            if not timestamp:
                continue
            try:
                normalized_timestamp = _normalize_timestamp_key(timestamp)
            except ValueError:
                invalid_timestamp_count += 1
                continue
            parsed_value, was_invalid = _parse_optional_numeric_value(row.get(value_column_name))
            values[normalized_timestamp] = parsed_value
            invalid_count += int(was_invalid)
    return values, invalid_count, invalid_timestamp_count


def _resolve_required_columns(fieldnames: list[str], aliases_by_field: dict[str, tuple[str, ...]]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for field, aliases in aliases_by_field.items():
        resolved_name = _resolve_optional_column(fieldnames, aliases)
        if resolved_name is None:
            alias_text = ", ".join(aliases)
            raise KeyError(f"missing required column for {field}: expected one of [{alias_text}]")
        resolved[field] = resolved_name
    return resolved


def _resolve_optional_market_columns(fieldnames: list[str]) -> dict[str, str | None]:
    return {
        field: _resolve_optional_column(fieldnames, aliases)
        for field, aliases in SERIES_VALUE_COLUMN_ALIASES.items()
    }


def _resolve_optional_snapshot_columns(
    fieldnames: list[str],
    aliases_by_field: dict[str, tuple[str, ...]],
) -> dict[str, str | None]:
    return {
        field: _resolve_optional_column(fieldnames, aliases)
        for field, aliases in aliases_by_field.items()
    }


def _resolve_optional_column(fieldnames: list[str], aliases: tuple[str, ...]) -> str | None:
    normalized_lookup = {_normalize_header(fieldname): fieldname for fieldname in fieldnames}
    for alias in aliases:
        resolved = normalized_lookup.get(_normalize_header(alias))
        if resolved is not None:
            return resolved
    return None


def _read_optional_float(row: dict[str, str], column_name: str | None) -> tuple[float, bool]:
    if column_name is None:
        return 0.0, False
    return _parse_optional_numeric_value(row.get(column_name))


def _read_optional_int(row: dict[str, str], column_name: str | None) -> int:
    if column_name is None:
        return 0
    parsed_value, _ = _parse_optional_numeric_value(row.get(column_name))
    return int(parsed_value)


def _read_optional_text(row: dict[str, str], column_name: str | None) -> str:
    if column_name is None:
        return ""
    value = row.get(column_name)
    if value is None:
        return ""
    return value.strip()


def _has_present_optional_numeric_value(row: dict[str, str], column_name: str | None) -> bool:
    if column_name is None:
        return False
    value = row.get(column_name)
    if value is None:
        return False
    normalized = value.strip().replace(",", "")
    if not normalized:
        return False
    return normalized.lower() not in NULL_NUMERIC_MARKERS


def _read_required_timestamp(row: dict[str, str], column_name: str, row_index: int) -> datetime:
    raw_value = row.get(column_name)
    try:
        return _parse_timestamp_value(raw_value or "")
    except ValueError as exc:
        raise ValueError(
            f"Invalid required candle field at row {row_index}: {column_name}={raw_value!r}"
        ) from exc


def _read_required_numeric(row: dict[str, str], column_name: str, row_index: int) -> float:
    raw_value = row.get(column_name)
    try:
        return _parse_numeric_value(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid required candle field at row {row_index}: {column_name}={raw_value!r}"
        ) from exc


def _parse_timestamp_value(value: str) -> datetime:
    normalized = value.strip()
    try:
        epoch_value = float(normalized)
    except ValueError:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    if "." in normalized:
        if epoch_value.is_integer():
            epoch_text = normalized.split(".", 1)[0]
            if len(epoch_text) >= 13:
                return datetime.fromtimestamp(epoch_value / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(epoch_value, tz=timezone.utc)

    if normalized.isdigit():
        if len(normalized) >= 13:
            return datetime.fromtimestamp(epoch_value / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(epoch_value, tz=timezone.utc)

    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_timestamp_key(value: str) -> str:
    return _parse_timestamp_value(value).isoformat()


def _normalize_header(value: str) -> str:
    return value.strip().lower()


def _parse_numeric_value(value: str | None, default: float | None = None) -> float:
    if value is None:
        if default is None:
            raise ValueError("numeric value is required")
        return default
    normalized = value.strip().replace(",", "")
    if not normalized:
        if default is None:
            raise ValueError("numeric value is required")
        return default
    if normalized.lower() in NULL_NUMERIC_MARKERS:
        if default is None:
            raise ValueError("numeric value is required")
        return default
    return float(normalized)


def _parse_optional_numeric_value(value: str | None) -> tuple[float, bool]:
    if value is None:
        return 0.0, False
    normalized = value.strip().replace(",", "")
    if not normalized:
        return 0.0, True
    if normalized.lower() in NULL_NUMERIC_MARKERS:
        return 0.0, True
    try:
        return float(normalized), False
    except ValueError:
        return 0.0, True


def _derive_phase1_snapshot_contract(
    *,
    candles: list[Candle],
    funding_rates: list[float],
    open_interest: list[float],
    liquidation_notional: list[float],
    venue_profile: VenueProfile,
    observed_numeric_values: dict[str, list[float]],
    observed_numeric_columns: dict[str, str | None],
    observed_text_values: dict[str, list[str]],
    observed_text_columns: dict[str, str | None],
) -> dict[str, object]:
    closes = [candle.close for candle in candles]
    funding_interval_h = venue_profile.funding_interval_h or 0
    mark_price = _use_observed_or_fallback(
        observed_numeric_values["mark_price"],
        observed_numeric_columns["mark_price"],
        closes,
    )
    index_price = _use_observed_or_fallback(
        observed_numeric_values["index_price"],
        observed_numeric_columns["index_price"],
        closes,
    )
    open_interest_usd = _use_observed_or_fallback(
        observed_numeric_values["open_interest_usd"],
        observed_numeric_columns["open_interest_usd"],
        [oi * close for oi, close in zip(open_interest, closes, strict=False)],
    )
    basis_bps = _use_observed_or_fallback(
        observed_numeric_values["basis_bps"],
        observed_numeric_columns["basis_bps"],
        [(((mark - index) / index) * 10_000.0) if index else 0.0 for mark, index in zip(mark_price, index_price, strict=False)],
    )
    liq_split_fallback = [max(value, 0.0) / 2.0 for value in liquidation_notional]
    liq_long_usd = _use_observed_or_fallback(
        observed_numeric_values["liq_long_usd"],
        observed_numeric_columns["liq_long_usd"],
        liq_split_fallback,
    )
    liq_short_usd = _use_observed_or_fallback(
        observed_numeric_values["liq_short_usd"],
        observed_numeric_columns["liq_short_usd"],
        liq_split_fallback,
    )
    spread_bps = _use_observed_or_fallback(
        observed_numeric_values["spread_bps"],
        observed_numeric_columns["spread_bps"],
        [0.0] * len(candles),
    )
    depth_bid_1bp_usd = _use_observed_or_fallback(
        observed_numeric_values["depth_bid_1bp_usd"],
        observed_numeric_columns["depth_bid_1bp_usd"],
        [0.0] * len(candles),
    )
    depth_ask_1bp_usd = _use_observed_or_fallback(
        observed_numeric_values["depth_ask_1bp_usd"],
        observed_numeric_columns["depth_ask_1bp_usd"],
        [0.0] * len(candles),
    )
    latency_proxy_ms = _use_observed_or_fallback(
        observed_numeric_values["latency_proxy_ms"],
        observed_numeric_columns["latency_proxy_ms"],
        [0.0] * len(candles),
    )
    next_funding_ts = _use_observed_text_or_fallback(
        observed_text_values["next_funding_ts"],
        observed_text_columns["next_funding_ts"],
        [
            (candle.timestamp + timedelta(hours=funding_interval_h)).isoformat() if funding_interval_h else candle.timestamp.isoformat()
            for candle in candles
        ],
    )
    ret_1 = _compute_returns(closes, lag=1)
    ret_24 = _compute_returns(closes, lag=24)
    rv_24h = _compute_realized_volatility(ret_1, window=24)
    funding_z = _zscore_series(funding_rates)
    d_oi = _compute_deltas(open_interest)
    d_oi_z = _zscore_series(d_oi)
    liq_intensity_z = _zscore_series(
        [long_value + short_value for long_value, short_value in zip(liq_long_usd, liq_short_usd, strict=False)]
    )
    vol_regime = _use_observed_text_or_fallback(
        observed_text_values["vol_regime"],
        observed_text_columns["vol_regime"],
        _classify_vol_regime(rv_24h),
    )
    regime_id = _use_observed_text_or_fallback(
        observed_text_values["regime_id"],
        observed_text_columns["regime_id"],
        ["unassigned"] * len(candles),
    )
    regime_probabilities = [{"unassigned": 1.0} for _ in candles]
    field_population = {
        "mark_price": _field_population_label(observed_numeric_columns["mark_price"], "close_fallback"),
        "index_price": _field_population_label(observed_numeric_columns["index_price"], "close_fallback"),
        "next_funding_ts": _field_population_label(observed_text_columns["next_funding_ts"], "funding_interval_derived"),
        "open_interest_usd": _field_population_label(observed_numeric_columns["open_interest_usd"], "oi_close_derived"),
        "basis_bps": _field_population_label(observed_numeric_columns["basis_bps"], "mark_index_derived"),
        "liq_long_usd": _field_population_label(observed_numeric_columns["liq_long_usd"], "equal_split_fallback"),
        "liq_short_usd": _field_population_label(observed_numeric_columns["liq_short_usd"], "equal_split_fallback"),
        "spread_bps": _field_population_label(observed_numeric_columns["spread_bps"], "zero_fallback"),
        "depth_bid_1bp_usd": _field_population_label(observed_numeric_columns["depth_bid_1bp_usd"], "zero_fallback"),
        "depth_ask_1bp_usd": _field_population_label(observed_numeric_columns["depth_ask_1bp_usd"], "zero_fallback"),
        "latency_proxy_ms": _field_population_label(observed_numeric_columns["latency_proxy_ms"], "zero_fallback"),
        "ret_1": "derived",
        "ret_24": "derived",
        "rv_24h": "derived",
        "funding_z": "derived",
        "d_oi": "derived",
        "d_oi_z": "derived",
        "liq_intensity_z": "derived",
        "vol_regime": _field_population_label(observed_text_columns["vol_regime"], "rv_derived"),
        "regime_id": _field_population_label(observed_text_columns["regime_id"], "default_unassigned"),
        "regime_probabilities": "default_unassigned",
    }
    return {
        "mark_price": mark_price,
        "index_price": index_price,
        "next_funding_ts": next_funding_ts,
        "open_interest_usd": open_interest_usd,
        "basis_bps": basis_bps,
        "liq_long_usd": liq_long_usd,
        "liq_short_usd": liq_short_usd,
        "spread_bps": spread_bps,
        "depth_bid_1bp_usd": depth_bid_1bp_usd,
        "depth_ask_1bp_usd": depth_ask_1bp_usd,
        "latency_proxy_ms": latency_proxy_ms,
        "ret_1": ret_1,
        "ret_24": ret_24,
        "rv_24h": rv_24h,
        "funding_z": funding_z,
        "d_oi": d_oi,
        "d_oi_z": d_oi_z,
        "liq_intensity_z": liq_intensity_z,
        "vol_regime": vol_regime,
        "regime_id": regime_id,
        "regime_probabilities": regime_probabilities,
        "field_population": field_population,
    }


def _use_observed_or_fallback(
    observed_values: list[float],
    observed_column: str | None,
    fallback_values: list[float],
) -> list[float]:
    if observed_column is not None:
        return list(observed_values)
    return list(fallback_values)


def _use_observed_text_or_fallback(
    observed_values: list[str],
    observed_column: str | None,
    fallback_values: list[str],
) -> list[str]:
    if observed_column is not None:
        return list(observed_values)
    return list(fallback_values)


def _field_population_label(observed_column: str | None, fallback_label: str) -> str:
    if observed_column is not None:
        return "observed"
    return fallback_label


def _compute_returns(values: list[float], *, lag: int) -> list[float]:
    returns = [0.0] * len(values)
    for index in range(lag, len(values)):
        base = values[index - lag]
        if base:
            returns[index] = (values[index] / base) - 1.0
    return returns


def _compute_deltas(values: list[float]) -> list[float]:
    deltas = [0.0] * len(values)
    for index in range(1, len(values)):
        deltas[index] = values[index] - values[index - 1]
    return deltas


def _compute_realized_volatility(returns: list[float], *, window: int) -> list[float]:
    realized = [0.0] * len(returns)
    for index in range(len(returns)):
        start = max(0, index - window + 1)
        window_values = returns[start : index + 1]
        if window_values:
            realized[index] = math.sqrt(sum(value * value for value in window_values))
    return realized


def _zscore_series(values: list[float]) -> list[float]:
    if not values:
        return []
    mean_value = sum(values) / len(values)
    # Population stddev (/N) is intentional: this normalizes the *entire*
    # snapshot population, not a rolling sample estimate.
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    std_value = math.sqrt(variance)
    if std_value <= 0:
        return [0.0] * len(values)
    return [(value - mean_value) / std_value for value in values]


def _classify_vol_regime(rv_24h: list[float]) -> list[str]:
    if not rv_24h:
        return []
    sorted_values = sorted(rv_24h)
    median_value = sorted_values[len(sorted_values) // 2]
    low_cutoff = median_value * 0.75
    high_cutoff = median_value * 1.25
    labels: list[str] = []
    for value in rv_24h:
        if value <= low_cutoff:
            labels.append("low")
        elif value >= high_cutoff:
            labels.append("high")
        else:
            labels.append("medium")
    return labels


def _build_invalid_quality_flags(invalid_counts: dict[str, int]) -> list[str]:
    flags: list[str] = []
    for field, count in invalid_counts.items():
        if count > 0:
            flags.append(f"invalid_{field}_count={count}")
    return flags


def _build_bundle_quality_flags(
    timestamps: list[str],
    funding_by_timestamp: dict[str, float],
    open_interest_by_timestamp: dict[str, float],
    liquidation_by_timestamp: dict[str, float],
    funding_path: Path | None,
    open_interest_path: Path | None,
    liquidation_notional_path: Path | None,
    funding_invalid_count: int,
    open_interest_invalid_count: int,
    liquidation_invalid_count: int,
    funding_invalid_timestamp_count: int,
    open_interest_invalid_timestamp_count: int,
    liquidation_invalid_timestamp_count: int,
) -> list[str]:
    quality_flags: list[str] = []
    candle_timestamps = set(timestamps)

    quality_flags.extend(
        _series_quality_flags(
            series_name="funding_rate",
            series=funding_by_timestamp,
            candle_timestamps=candle_timestamps,
            enabled=funding_path is not None,
            invalid_count=funding_invalid_count,
            invalid_timestamp_count=funding_invalid_timestamp_count,
        )
    )
    quality_flags.extend(
        _series_quality_flags(
            series_name="open_interest",
            series=open_interest_by_timestamp,
            candle_timestamps=candle_timestamps,
            enabled=open_interest_path is not None,
            invalid_count=open_interest_invalid_count,
            invalid_timestamp_count=open_interest_invalid_timestamp_count,
        )
    )
    quality_flags.extend(
        _series_quality_flags(
            series_name="liquidation_notional",
            series=liquidation_by_timestamp,
            candle_timestamps=candle_timestamps,
            enabled=liquidation_notional_path is not None,
            invalid_count=liquidation_invalid_count,
            invalid_timestamp_count=liquidation_invalid_timestamp_count,
        )
    )
    return quality_flags


def _series_quality_flags(
    series_name: str,
    series: dict[str, float],
    candle_timestamps: set[str],
    enabled: bool,
    invalid_count: int,
    invalid_timestamp_count: int,
) -> list[str]:
    if not enabled:
        return []

    missing_count = sum(1 for timestamp in candle_timestamps if timestamp not in series)
    orphan_count = sum(1 for timestamp in series if timestamp not in candle_timestamps)

    flags: list[str] = []
    if missing_count > 0:
        flags.append(f"missing_{series_name}_count={missing_count}")
    if orphan_count > 0:
        flags.append(f"orphan_{series_name}_count={orphan_count}")
    if invalid_count > 0:
        flags.append(f"invalid_{series_name}_count={invalid_count}")
    if invalid_timestamp_count > 0:
        flags.append(f"invalid_{series_name}_timestamp_count={invalid_timestamp_count}")
    return flags
