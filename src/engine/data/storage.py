from __future__ import annotations

import json
from pathlib import Path
import sys

from engine.config.models import DataSnapshot, SnapshotQualityReport, VenueProfile
from engine.data.schema import Candle


def store_snapshot(snapshot: DataSnapshot, root: Path) -> dict[str, Path]:
    duckdb = _load_duckdb()
    root.mkdir(parents=True, exist_ok=True)
    parquet_path = root / f"{snapshot.snapshot_id}.parquet"
    db_path = root / "snapshot_store.duckdb"

    rows = _snapshot_rows(snapshot)
    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            """
            create table if not exists snapshot_catalog (
                snapshot_id varchar primary key,
                symbol varchar not null,
                venue varchar not null,
                timeframe varchar not null,
                contract_type varchar not null,
                parquet_path varchar not null,
                maker_fee_bps double not null,
                taker_fee_bps double not null,
                quality_flags_json varchar not null,
                venue_profile_json varchar,
                quality_report_json varchar,
                provenance_json varchar not null,
                row_count bigint not null,
                first_ts varchar,
                last_ts varchar
            )
            """
        )
        connection.execute("drop table if exists snapshot_rows_stage")
        connection.execute(
            """
            create table snapshot_rows_stage (
                snapshot_id varchar,
                symbol varchar,
                venue varchar,
                timeframe varchar,
                contract_type varchar,
                ts varchar,
                open double,
                high double,
                low double,
                close double,
                volume double,
                trade_count bigint,
                funding_rate double,
                open_interest double,
                liquidation_notional double,
                mark_price double,
                index_price double,
                next_funding_ts varchar,
                open_interest_usd double,
                basis_bps double,
                liq_long_usd double,
                liq_short_usd double,
                spread_bps double,
                depth_bid_1bp_usd double,
                depth_ask_1bp_usd double,
                latency_proxy_ms double,
                ret_1 double,
                ret_24 double,
                rv_24h double,
                funding_z double,
                d_oi double,
                d_oi_z double,
                liq_intensity_z double,
                vol_regime varchar,
                regime_id varchar,
                regime_probabilities_json varchar
            )
            """
        )
        connection.executemany(
            """
            insert into snapshot_rows_stage values (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            rows,
        )
        connection.execute(
            f"copy snapshot_rows_stage to '{parquet_path.as_posix()}' (format parquet)"
        )
        connection.execute("delete from snapshot_catalog where snapshot_id = ?", [snapshot.snapshot_id])
        connection.execute(
            """
            insert into snapshot_catalog (
                snapshot_id,
                symbol,
                venue,
                timeframe,
                contract_type,
                parquet_path,
                maker_fee_bps,
                taker_fee_bps,
                quality_flags_json,
                venue_profile_json,
                quality_report_json,
                provenance_json,
                row_count,
                first_ts,
                last_ts
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                snapshot.snapshot_id,
                snapshot.symbol,
                snapshot.venue,
                snapshot.timeframe,
                snapshot.contract_type,
                str(parquet_path),
                snapshot.maker_fee_bps,
                snapshot.taker_fee_bps,
                json.dumps(snapshot.quality_flags, sort_keys=True),
                json.dumps(_serialize_venue_profile(snapshot.venue_profile), sort_keys=True)
                if snapshot.venue_profile is not None
                else None,
                json.dumps(_serialize_quality_report(snapshot.quality_report), sort_keys=True)
                if snapshot.quality_report is not None
                else None,
                json.dumps(snapshot.provenance, sort_keys=True),
                len(snapshot.candles),
                snapshot.candles[0].timestamp.isoformat() if snapshot.candles else None,
                snapshot.candles[-1].timestamp.isoformat() if snapshot.candles else None,
            ],
        )
        connection.execute("drop table snapshot_rows_stage")

    return {
        "duckdb_path": db_path,
        "parquet_path": parquet_path,
    }


def load_snapshot(snapshot_id: str, root: Path) -> DataSnapshot:
    duckdb = _load_duckdb()
    db_path = root / "snapshot_store.duckdb"
    if not db_path.exists():
        raise FileNotFoundError(f"snapshot store not found: {db_path}")

    with duckdb.connect(str(db_path), read_only=True) as connection:
        catalog_row = connection.execute(
            """
            select
                symbol,
                venue,
                timeframe,
                contract_type,
                parquet_path,
                maker_fee_bps,
                taker_fee_bps,
                quality_flags_json,
                venue_profile_json,
                quality_report_json,
                provenance_json
            from snapshot_catalog
            where snapshot_id = ?
            """,
            [snapshot_id],
        ).fetchone()
        if catalog_row is None:
            raise KeyError(f"unknown snapshot_id: {snapshot_id}")
        rows = connection.execute(
            """
            select
                ts,
                open,
                high,
                low,
                close,
                volume,
                trade_count,
                funding_rate,
                open_interest,
                liquidation_notional,
                mark_price,
                index_price,
                next_funding_ts,
                open_interest_usd,
                basis_bps,
                liq_long_usd,
                liq_short_usd,
                spread_bps,
                depth_bid_1bp_usd,
                depth_ask_1bp_usd,
                latency_proxy_ms,
                ret_1,
                ret_24,
                rv_24h,
                funding_z,
                d_oi,
                d_oi_z,
                liq_intensity_z,
                vol_regime,
                regime_id,
                regime_probabilities_json
            from read_parquet(?)
            order by ts
            """,
            [catalog_row[4]],
        ).fetchall()

    candles: list[Candle] = []
    funding_rates: list[float] = []
    open_interest: list[float] = []
    liquidation_notional: list[float] = []
    mark_price: list[float] = []
    index_price: list[float] = []
    next_funding_ts: list[str] = []
    open_interest_usd: list[float] = []
    basis_bps: list[float] = []
    liq_long_usd: list[float] = []
    liq_short_usd: list[float] = []
    spread_bps: list[float] = []
    depth_bid_1bp_usd: list[float] = []
    depth_ask_1bp_usd: list[float] = []
    latency_proxy_ms: list[float] = []
    ret_1: list[float] = []
    ret_24: list[float] = []
    rv_24h: list[float] = []
    funding_z: list[float] = []
    d_oi: list[float] = []
    d_oi_z: list[float] = []
    liq_intensity_z: list[float] = []
    vol_regime: list[str] = []
    regime_id: list[str] = []
    regime_probabilities: list[dict[str, float]] = []

    for row in rows:
        candles.append(
            Candle(
                timestamp=_parse_timestamp(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                trade_count=int(row[6]),
            )
        )
        funding_rates.append(float(row[7]))
        open_interest.append(float(row[8]))
        liquidation_notional.append(float(row[9]))
        mark_price.append(float(row[10]))
        index_price.append(float(row[11]))
        next_funding_ts.append(str(row[12]))
        open_interest_usd.append(float(row[13]))
        basis_bps.append(float(row[14]))
        liq_long_usd.append(float(row[15]))
        liq_short_usd.append(float(row[16]))
        spread_bps.append(float(row[17]))
        depth_bid_1bp_usd.append(float(row[18]))
        depth_ask_1bp_usd.append(float(row[19]))
        latency_proxy_ms.append(float(row[20]))
        ret_1.append(float(row[21]))
        ret_24.append(float(row[22]))
        rv_24h.append(float(row[23]))
        funding_z.append(float(row[24]))
        d_oi.append(float(row[25]))
        d_oi_z.append(float(row[26]))
        liq_intensity_z.append(float(row[27]))
        vol_regime.append(str(row[28]))
        regime_id.append(str(row[29]))
        regime_probabilities.append(dict(json.loads(str(row[30]))))

    return DataSnapshot(
        snapshot_id=snapshot_id,
        symbol=str(catalog_row[0]),
        venue=str(catalog_row[1]),
        timeframe=str(catalog_row[2]),
        contract_type=str(catalog_row[3]),
        candles=candles,
        funding_rates=funding_rates,
        open_interest=open_interest,
        liquidation_notional=liquidation_notional,
        maker_fee_bps=float(catalog_row[5]),
        taker_fee_bps=float(catalog_row[6]),
        mark_price=mark_price,
        index_price=index_price,
        next_funding_ts=next_funding_ts,
        open_interest_usd=open_interest_usd,
        basis_bps=basis_bps,
        liq_long_usd=liq_long_usd,
        liq_short_usd=liq_short_usd,
        spread_bps=spread_bps,
        depth_bid_1bp_usd=depth_bid_1bp_usd,
        depth_ask_1bp_usd=depth_ask_1bp_usd,
        latency_proxy_ms=latency_proxy_ms,
        ret_1=ret_1,
        ret_24=ret_24,
        rv_24h=rv_24h,
        funding_z=funding_z,
        d_oi=d_oi,
        d_oi_z=d_oi_z,
        liq_intensity_z=liq_intensity_z,
        vol_regime=vol_regime,
        regime_id=regime_id,
        regime_probabilities=regime_probabilities,
        quality_flags=list(json.loads(str(catalog_row[7]))),
        venue_profile=_deserialize_venue_profile(catalog_row[8]),
        quality_report=_deserialize_quality_report(catalog_row[9]),
        provenance=dict(json.loads(str(catalog_row[10]))),
    )


def list_stored_snapshots(root: Path) -> list[dict[str, object]]:
    duckdb = _load_duckdb()
    db_path = root / "snapshot_store.duckdb"
    if not db_path.exists():
        return []
    with duckdb.connect(str(db_path), read_only=True) as connection:
        rows = connection.execute(
            """
            select snapshot_id, symbol, venue, timeframe, contract_type, row_count, parquet_path
            from snapshot_catalog
            order by snapshot_id
            """
        ).fetchall()
    return [
        {
            "snapshot_id": str(row[0]),
            "symbol": str(row[1]),
            "venue": str(row[2]),
            "timeframe": str(row[3]),
            "contract_type": str(row[4]),
            "row_count": int(row[5]),
            "parquet_path": str(row[6]),
        }
        for row in rows
    ]


def _snapshot_rows(snapshot: DataSnapshot) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for index, candle in enumerate(snapshot.candles):
        rows.append(
            (
                snapshot.snapshot_id,
                snapshot.symbol,
                snapshot.venue,
                snapshot.timeframe,
                snapshot.contract_type,
                candle.timestamp.isoformat(),
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                candle.trade_count,
                snapshot.funding_rates[index],
                snapshot.open_interest[index],
                snapshot.liquidation_notional[index],
                snapshot.mark_price[index] if snapshot.mark_price else candle.close,
                snapshot.index_price[index] if snapshot.index_price else candle.close,
                snapshot.next_funding_ts[index] if snapshot.next_funding_ts else candle.timestamp.isoformat(),
                snapshot.open_interest_usd[index] if snapshot.open_interest_usd else 0.0,
                snapshot.basis_bps[index] if snapshot.basis_bps else 0.0,
                snapshot.liq_long_usd[index] if snapshot.liq_long_usd else 0.0,
                snapshot.liq_short_usd[index] if snapshot.liq_short_usd else 0.0,
                snapshot.spread_bps[index] if snapshot.spread_bps else 0.0,
                snapshot.depth_bid_1bp_usd[index] if snapshot.depth_bid_1bp_usd else 0.0,
                snapshot.depth_ask_1bp_usd[index] if snapshot.depth_ask_1bp_usd else 0.0,
                snapshot.latency_proxy_ms[index] if snapshot.latency_proxy_ms else 0.0,
                snapshot.ret_1[index] if snapshot.ret_1 else 0.0,
                snapshot.ret_24[index] if snapshot.ret_24 else 0.0,
                snapshot.rv_24h[index] if snapshot.rv_24h else 0.0,
                snapshot.funding_z[index] if snapshot.funding_z else 0.0,
                snapshot.d_oi[index] if snapshot.d_oi else 0.0,
                snapshot.d_oi_z[index] if snapshot.d_oi_z else 0.0,
                snapshot.liq_intensity_z[index] if snapshot.liq_intensity_z else 0.0,
                snapshot.vol_regime[index] if snapshot.vol_regime else "",
                snapshot.regime_id[index] if snapshot.regime_id else "",
                json.dumps(snapshot.regime_probabilities[index] if snapshot.regime_probabilities else {"unassigned": 1.0}, sort_keys=True),
            )
        )
    return rows


def _serialize_venue_profile(profile: VenueProfile | None) -> dict[str, object] | None:
    if profile is None:
        return None
    return {
        "venue": profile.venue,
        "contract_type": profile.contract_type,
        "quote_currency": profile.quote_currency,
        "settlement_currency": profile.settlement_currency,
        "funding_interval_h": profile.funding_interval_h,
        "mark_price_source": profile.mark_price_source,
        "leverage_tiers": [dict(item) for item in profile.leverage_tiers],
        "maintenance_margin_schedule": [dict(item) for item in profile.maintenance_margin_schedule],
        "liquidation_fee_schedule": [dict(item) for item in profile.liquidation_fee_schedule],
        "liquidation_style": profile.liquidation_style,
        "partial_liquidation_ratio": profile.partial_liquidation_ratio,
        "liquidation_cooldown_bars": profile.liquidation_cooldown_bars,
        "liquidation_mark_price_weight": profile.liquidation_mark_price_weight,
        "liquidation_mark_premium_bps": profile.liquidation_mark_premium_bps,
        "notes": list(profile.notes),
    }


def _deserialize_venue_profile(raw: object) -> VenueProfile | None:
    if raw is None:
        return None
    payload = json.loads(str(raw))
    return VenueProfile(
        venue=payload["venue"],
        contract_type=payload.get("contract_type", "perpetual"),
        quote_currency=payload.get("quote_currency"),
        settlement_currency=payload.get("settlement_currency"),
        funding_interval_h=payload.get("funding_interval_h"),
        mark_price_source=payload.get("mark_price_source", "exchange_mark"),
        leverage_tiers=[dict(item) for item in payload.get("leverage_tiers", [])],
        maintenance_margin_schedule=[dict(item) for item in payload.get("maintenance_margin_schedule", [])],
        liquidation_fee_schedule=[dict(item) for item in payload.get("liquidation_fee_schedule", [])],
        liquidation_style=payload.get("liquidation_style", "full"),
        partial_liquidation_ratio=payload.get("partial_liquidation_ratio", 1.0),
        liquidation_cooldown_bars=payload.get("liquidation_cooldown_bars", 0),
        liquidation_mark_price_weight=payload.get("liquidation_mark_price_weight", 0.0),
        liquidation_mark_premium_bps=payload.get("liquidation_mark_premium_bps", 0.0),
        notes=list(payload.get("notes", [])),
    )


def _serialize_quality_report(report: SnapshotQualityReport | None) -> dict[str, object] | None:
    if report is None:
        return None
    return {
        "report_id": report.report_id,
        "snapshot_id": report.snapshot_id,
        "quality_score": report.quality_score,
        "passed": report.passed,
        "issues": list(report.issues),
        "metrics": dict(report.metrics),
        "source_checks": dict(report.source_checks),
        "generated_at": report.generated_at,
    }


def _deserialize_quality_report(raw: object) -> SnapshotQualityReport | None:
    if raw is None:
        return None
    payload = json.loads(str(raw))
    return SnapshotQualityReport(
        report_id=payload["report_id"],
        snapshot_id=payload["snapshot_id"],
        quality_score=payload.get("quality_score", 1.0),
        passed=payload.get("passed", True),
        issues=list(payload.get("issues", [])),
        metrics=dict(payload.get("metrics", {})),
        source_checks=dict(payload.get("source_checks", {})),
        generated_at=payload.get("generated_at"),
    )


def _parse_timestamp(value: object) -> object:
    from datetime import datetime

    return datetime.fromisoformat(str(value))


def _load_duckdb():
    repo_root = Path(__file__).resolve().parents[3]
    vendor_paths = [repo_root / "vendor_duckdb_open", repo_root / "vendor_duckdb", repo_root / ".vendor"]
    vendor_texts = [str(path) for path in vendor_paths if path.exists()]
    sys.path[:] = [entry for entry in sys.path if entry not in vendor_texts]
    for vendor_text in reversed(vendor_texts):
        sys.path.insert(0, vendor_text)
    sys.modules.pop("duckdb", None)
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency failure path
        raise RuntimeError("duckdb is required for snapshot storage") from exc
    return duckdb
