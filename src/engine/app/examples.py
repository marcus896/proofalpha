from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from engine.app.schema import build_study_schema
from engine.config.models import DataSnapshot
from engine.data.schema import Candle
from engine.io.artifacts import write_json_atomic


def write_example_study_config(
    path: Path,
    snapshot: DataSnapshot,
    run_id: str = "example-study",
    seed: int = 7,
) -> None:
    payload = {
        "run_id": run_id,
        "seed": seed,
        "runtime": {"mode": "builtin"},
        "snapshot": serialize_snapshot(snapshot),
        "incumbent": {"backbone": "mom_squeeze"},
        "directional_layers": ["kama"],
        "known_good_filters": ["flat9"],
        "custom_filters": [],
        "exit_layers": [],
        "scenarios": [
            {"name": "attention-burst", "severity": 0.6, "description": "Attention shock"},
            {"name": "outage-shock", "severity": 0.9, "description": "Outage shock"},
        ],
        "holdout_decision": {"decision": "accept", "reasons": []},
    }
    write_json_atomic(path, payload)


def build_example_snapshot(
    snapshot_id: str = "example-solusdt-1h",
    symbol: str = "SOLUSDT",
    venue: str = "binance",
    timeframe: str = "1h",
    periods: int = 120,
) -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.0 + index,
            volume=1_000.0,
        )
        for index in range(periods)
    ]
    return DataSnapshot(
        snapshot_id=snapshot_id,
        symbol=symbol,
        venue=venue,
        timeframe=timeframe,
        candles=candles,
        funding_rates=[0.0] * periods,
        open_interest=[100.0] * periods,
        liquidation_notional=[0.0] * periods,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        contract_type="perpetual",
        quality_flags=[],
    )


def write_repo_example_artifacts(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = build_example_snapshot()
    write_example_study_config(directory / "minimal_builtin_study.json", snapshot, run_id="example-study", seed=7)
    write_json_atomic(directory / "study.schema.json", build_study_schema())


def serialize_snapshot(snapshot: DataSnapshot) -> dict[str, object]:
    payload: dict[str, object] = {
        "snapshot_id": snapshot.snapshot_id,
        "symbol": snapshot.symbol,
        "venue": snapshot.venue,
        "timeframe": snapshot.timeframe,
        "contract_type": snapshot.contract_type,
        "candles": [
            {
                "timestamp": candle.timestamp.isoformat(),
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "trade_count": candle.trade_count,
            }
            for candle in snapshot.candles
        ],
        "funding_rates": list(snapshot.funding_rates),
        "open_interest": list(snapshot.open_interest),
        "liquidation_notional": list(snapshot.liquidation_notional),
        "maker_fee_bps": snapshot.maker_fee_bps,
        "taker_fee_bps": snapshot.taker_fee_bps,
        "mark_price": list(snapshot.mark_price),
        "index_price": list(snapshot.index_price),
        "next_funding_ts": list(snapshot.next_funding_ts),
        "open_interest_usd": list(snapshot.open_interest_usd),
        "basis_bps": list(snapshot.basis_bps),
        "liq_long_usd": list(snapshot.liq_long_usd),
        "liq_short_usd": list(snapshot.liq_short_usd),
        "spread_bps": list(snapshot.spread_bps),
        "depth_bid_1bp_usd": list(snapshot.depth_bid_1bp_usd),
        "depth_ask_1bp_usd": list(snapshot.depth_ask_1bp_usd),
        "latency_proxy_ms": list(snapshot.latency_proxy_ms),
        "ret_1": list(snapshot.ret_1),
        "ret_24": list(snapshot.ret_24),
        "rv_24h": list(snapshot.rv_24h),
        "funding_z": list(snapshot.funding_z),
        "d_oi": list(snapshot.d_oi),
        "d_oi_z": list(snapshot.d_oi_z),
        "liq_intensity_z": list(snapshot.liq_intensity_z),
        "vol_regime": list(snapshot.vol_regime),
        "regime_id": list(snapshot.regime_id),
        "regime_probabilities": [dict(item) for item in snapshot.regime_probabilities],
        "quality_flags": list(snapshot.quality_flags),
    }
    if snapshot.venue_profile is not None:
        payload["venue_profile"] = {
            "venue": snapshot.venue_profile.venue,
            "contract_type": snapshot.venue_profile.contract_type,
            "quote_currency": snapshot.venue_profile.quote_currency,
            "settlement_currency": snapshot.venue_profile.settlement_currency,
            "funding_interval_h": snapshot.venue_profile.funding_interval_h,
            "mark_price_source": snapshot.venue_profile.mark_price_source,
            "leverage_tiers": [dict(item) for item in snapshot.venue_profile.leverage_tiers],
            "maintenance_margin_schedule": [
                dict(item) for item in snapshot.venue_profile.maintenance_margin_schedule
            ],
            "liquidation_fee_schedule": [dict(item) for item in snapshot.venue_profile.liquidation_fee_schedule],
            "liquidation_style": snapshot.venue_profile.liquidation_style,
            "partial_liquidation_ratio": snapshot.venue_profile.partial_liquidation_ratio,
            "liquidation_cooldown_bars": snapshot.venue_profile.liquidation_cooldown_bars,
            "liquidation_mark_price_weight": snapshot.venue_profile.liquidation_mark_price_weight,
            "liquidation_mark_premium_bps": snapshot.venue_profile.liquidation_mark_premium_bps,
            "notes": list(snapshot.venue_profile.notes),
        }
    if snapshot.quality_report is not None:
        payload["quality_report"] = {
            "report_id": snapshot.quality_report.report_id,
            "snapshot_id": snapshot.quality_report.snapshot_id,
            "quality_score": snapshot.quality_report.quality_score,
            "passed": snapshot.quality_report.passed,
            "issues": list(snapshot.quality_report.issues),
            "metrics": dict(snapshot.quality_report.metrics),
            "source_checks": dict(snapshot.quality_report.source_checks),
            "generated_at": snapshot.quality_report.generated_at,
        }
    if snapshot.provenance:
        payload["provenance"] = dict(snapshot.provenance)
    return payload


def _serialize_snapshot(snapshot: DataSnapshot) -> dict[str, object]:
    return serialize_snapshot(snapshot)
