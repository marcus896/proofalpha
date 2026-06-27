from __future__ import annotations

from dataclasses import replace
from typing import Any

from engine.config.models import DataSnapshot, SnapshotQualityReport
from engine.data.schema import Candle


_MISSING = object()


def clone_snapshot(
    snapshot: DataSnapshot,
    *,
    snapshot_id: str,
    candles: list[Candle] | None = None,
    funding_rates: list[float] | None = None,
    open_interest: list[float] | None = None,
    liquidation_notional: list[float] | None = None,
    mark_price: list[float] | None = None,
    index_price: list[float] | None = None,
    next_funding_ts: list[str] | None = None,
    open_interest_usd: list[float] | None = None,
    basis_bps: list[float] | None = None,
    liq_long_usd: list[float] | None = None,
    liq_short_usd: list[float] | None = None,
    spread_bps: list[float] | None = None,
    depth_bid_1bp_usd: list[float] | None = None,
    depth_ask_1bp_usd: list[float] | None = None,
    latency_proxy_ms: list[float] | None = None,
    ret_1: list[float] | None = None,
    ret_24: list[float] | None = None,
    rv_24h: list[float] | None = None,
    funding_z: list[float] | None = None,
    d_oi: list[float] | None = None,
    d_oi_z: list[float] | None = None,
    liq_intensity_z: list[float] | None = None,
    vol_regime: list[str] | None = None,
    regime_id: list[str] | None = None,
    regime_probabilities: list[dict[str, float]] | None = None,
    quality_flags: list[str] | None = None,
    provenance_updates: dict[str, Any] | None = None,
    quality_report: SnapshotQualityReport | None | object = _MISSING,
) -> DataSnapshot:
    provenance = dict(snapshot.provenance)
    if snapshot_id != snapshot.snapshot_id:
        provenance.setdefault("derived_from_snapshot_id", snapshot.snapshot_id)
    if provenance_updates:
        provenance.update(provenance_updates)

    next_quality_report = snapshot.quality_report if quality_report is _MISSING else quality_report
    if next_quality_report is not None and next_quality_report.snapshot_id != snapshot_id:
        source_checks = dict(next_quality_report.source_checks)
        source_checks.setdefault("derived_from_snapshot_id", snapshot.snapshot_id)
        next_quality_report = replace(
            next_quality_report,
            report_id=f"{next_quality_report.report_id}:{snapshot_id}",
            snapshot_id=snapshot_id,
            source_checks=source_checks,
        )

    return DataSnapshot(
        snapshot_id=snapshot_id,
        symbol=snapshot.symbol,
        venue=snapshot.venue,
        timeframe=snapshot.timeframe,
        contract_type=snapshot.contract_type,
        candles=list(snapshot.candles if candles is None else candles),
        funding_rates=list(snapshot.funding_rates if funding_rates is None else funding_rates),
        open_interest=list(snapshot.open_interest if open_interest is None else open_interest),
        liquidation_notional=list(snapshot.liquidation_notional if liquidation_notional is None else liquidation_notional),
        mark_price=list(snapshot.mark_price if mark_price is None else mark_price),
        index_price=list(snapshot.index_price if index_price is None else index_price),
        next_funding_ts=list(snapshot.next_funding_ts if next_funding_ts is None else next_funding_ts),
        open_interest_usd=list(snapshot.open_interest_usd if open_interest_usd is None else open_interest_usd),
        basis_bps=list(snapshot.basis_bps if basis_bps is None else basis_bps),
        liq_long_usd=list(snapshot.liq_long_usd if liq_long_usd is None else liq_long_usd),
        liq_short_usd=list(snapshot.liq_short_usd if liq_short_usd is None else liq_short_usd),
        maker_fee_bps=snapshot.maker_fee_bps,
        taker_fee_bps=snapshot.taker_fee_bps,
        spread_bps=list(snapshot.spread_bps if spread_bps is None else spread_bps),
        depth_bid_1bp_usd=list(snapshot.depth_bid_1bp_usd if depth_bid_1bp_usd is None else depth_bid_1bp_usd),
        depth_ask_1bp_usd=list(snapshot.depth_ask_1bp_usd if depth_ask_1bp_usd is None else depth_ask_1bp_usd),
        latency_proxy_ms=list(snapshot.latency_proxy_ms if latency_proxy_ms is None else latency_proxy_ms),
        ret_1=list(snapshot.ret_1 if ret_1 is None else ret_1),
        ret_24=list(snapshot.ret_24 if ret_24 is None else ret_24),
        rv_24h=list(snapshot.rv_24h if rv_24h is None else rv_24h),
        funding_z=list(snapshot.funding_z if funding_z is None else funding_z),
        d_oi=list(snapshot.d_oi if d_oi is None else d_oi),
        d_oi_z=list(snapshot.d_oi_z if d_oi_z is None else d_oi_z),
        liq_intensity_z=list(snapshot.liq_intensity_z if liq_intensity_z is None else liq_intensity_z),
        vol_regime=list(snapshot.vol_regime if vol_regime is None else vol_regime),
        regime_id=list(snapshot.regime_id if regime_id is None else regime_id),
        regime_probabilities=[
            dict(item) for item in (snapshot.regime_probabilities if regime_probabilities is None else regime_probabilities)
        ],
        quality_flags=list(snapshot.quality_flags if quality_flags is None else quality_flags),
        venue_profile=snapshot.venue_profile,
        quality_report=next_quality_report,
        provenance=provenance,
    )


def slice_snapshot(snapshot: DataSnapshot, start_index: int, end_index: int, snapshot_id_suffix: str) -> DataSnapshot:
    return clone_snapshot(
        snapshot,
        snapshot_id=f"{snapshot.snapshot_id}:{snapshot_id_suffix}",
        candles=snapshot.candles[start_index:end_index],
        funding_rates=snapshot.funding_rates[start_index:end_index],
        open_interest=snapshot.open_interest[start_index:end_index],
        liquidation_notional=snapshot.liquidation_notional[start_index:end_index],
        mark_price=snapshot.mark_price[start_index:end_index],
        index_price=snapshot.index_price[start_index:end_index],
        next_funding_ts=snapshot.next_funding_ts[start_index:end_index],
        open_interest_usd=snapshot.open_interest_usd[start_index:end_index],
        basis_bps=snapshot.basis_bps[start_index:end_index],
        liq_long_usd=snapshot.liq_long_usd[start_index:end_index],
        liq_short_usd=snapshot.liq_short_usd[start_index:end_index],
        spread_bps=snapshot.spread_bps[start_index:end_index],
        depth_bid_1bp_usd=snapshot.depth_bid_1bp_usd[start_index:end_index],
        depth_ask_1bp_usd=snapshot.depth_ask_1bp_usd[start_index:end_index],
        latency_proxy_ms=snapshot.latency_proxy_ms[start_index:end_index],
        ret_1=snapshot.ret_1[start_index:end_index],
        ret_24=snapshot.ret_24[start_index:end_index],
        rv_24h=snapshot.rv_24h[start_index:end_index],
        funding_z=snapshot.funding_z[start_index:end_index],
        d_oi=snapshot.d_oi[start_index:end_index],
        d_oi_z=snapshot.d_oi_z[start_index:end_index],
        liq_intensity_z=snapshot.liq_intensity_z[start_index:end_index],
        vol_regime=snapshot.vol_regime[start_index:end_index],
        regime_id=snapshot.regime_id[start_index:end_index],
        regime_probabilities=snapshot.regime_probabilities[start_index:end_index],
        provenance_updates={
            "transformation": "slice",
            "start_index": start_index,
            "end_index": end_index,
        },
    )
