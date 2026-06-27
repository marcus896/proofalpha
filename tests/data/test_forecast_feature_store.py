from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import DataSnapshot
from engine.data.feature_store import (
    build_normalized_feature_rows,
    derive_forecast_feature_fields,
    join_forecast_features,
    validate_feature_store,
)
from engine.data.schema import Candle
from engine.forecasting.artifacts import ForecastCovariate, build_forecast_artifact
from engine.forecasting.timesfm_adapter import ForecastRequest, TimesFmAdapter, TimesFmAdapterConfig


class ForecastFeatureStoreJoinTests(unittest.TestCase):
    def test_derives_bounded_forecast_features_without_raw_quantiles(self) -> None:
        artifact = _artifact("BTCUSDT", q50=[103.0, 106.0], q10=[101.0, 103.0], q90=[105.0, 109.0])

        fields = derive_forecast_feature_fields(artifact, symbol="BTCUSDT", last_observed_value=100.0)

        self.assertAlmostEqual(fields["timesfm_q50_return"], 0.06)
        self.assertEqual(fields["timesfm_direction"], 1)
        self.assertEqual(fields["timesfm_interval_width"], 6.0)
        self.assertAlmostEqual(fields["timesfm_uncertainty_ratio"], 0.06)
        self.assertAlmostEqual(fields["timesfm_skew"], 0.0)
        self.assertEqual(fields["timesfm_confidence_bucket"], "low")
        self.assertEqual(fields["timesfm_horizon"], 2)
        self.assertEqual(fields["timesfm_symbol"], "BTCUSDT")
        self.assertNotIn("q10", fields)
        self.assertNotIn("q50", fields)
        self.assertNotIn("q90", fields)
        self.assertNotIn("point_forecast", fields)
        self.assertNotIn("order", fields)
        self.assertNotIn("trade_action", fields)
        self.assertNotIn("position_size", fields)

    def test_join_forecast_features_for_primary_symbols_and_metadata(self) -> None:
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            with self.subTest(symbol=symbol):
                rows = build_normalized_feature_rows(_snapshot(symbol))
                artifact = _artifact(symbol, feature_timestamp=rows[0].ts_close, context_end_ts=rows[0].ts_open)

                joined = join_forecast_features(rows, [artifact])
                report = validate_feature_store(joined)

                self.assertTrue(report.passed, report.issues)
                self.assertIn("timesfm_q50_return", joined[0].forecast_features)
                self.assertEqual(joined[0].field_confidence["timesfm_forecast"], "model_derived_research_only")
                self.assertEqual(joined[0].field_confidence["timesfm_q50_return"], "model_derived_research_only")
                self.assertEqual(joined[0].source_ts_by_field["timesfm_forecast_context_end"], rows[0].ts_open)
                self.assertEqual(report.field_confidence["timesfm_forecast"], "model_derived_research_only")
                self.assertEqual(joined[0].contract_payload()["source_snapshot_id"], f"{symbol.lower()}-feature-snap")
                self.assertNotIn("q50", joined[0].forecast_features)

    def test_join_rejects_future_forecast_context_and_unknown_future_covariates(self) -> None:
        rows = build_normalized_feature_rows(_snapshot("BTCUSDT"))
        future_context = _artifact(
            "BTCUSDT",
            feature_timestamp=rows[0].ts_close,
            context_end_ts=rows[0].ts_close + timedelta(minutes=1),
        )
        future_covariate = _artifact(
            "BTCUSDT",
            feature_timestamp=rows[0].ts_close,
            context_end_ts=rows[0].ts_open,
            future_covariates=[
                ForecastCovariate(
                    name="future_funding",
                    value=0.0002,
                    available_at=rows[0].ts_close + timedelta(minutes=1),
                    known_at_decision_time=False,
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "invalid_forecast_artifact:forecast_context_after_feature_timestamp"):
            join_forecast_features(rows, [future_context])
        with self.assertRaisesRegex(ValueError, "invalid_forecast_artifact:future_covariate_not_known:future_funding"):
            join_forecast_features(rows, [future_covariate])

    def test_feature_store_validation_catches_future_forecast_source_timestamp(self) -> None:
        rows = build_normalized_feature_rows(_snapshot("BTCUSDT"))
        bad_row = rows[0].with_forecast_features(
            {"timesfm_q50_return": 0.01},
            field_confidence={"timesfm_forecast": "model_derived_research_only"},
            source_ts_by_field={"timesfm_forecast_context_end": rows[0].ts_close + timedelta(minutes=1)},
        )

        report = validate_feature_store([bad_row] + rows[1:])

        self.assertFalse(report.passed)
        self.assertIn("future_timesfm_forecast_context_end_row=0", report.issues)


def _snapshot(symbol: str) -> DataSnapshot:
    base_time = datetime(2026, 5, 1, tzinfo=UTC)
    candles = [
        Candle(
            timestamp=base_time + timedelta(minutes=15 * index),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.0 + index,
            volume=10.0 + index,
            trade_count=100 + index,
        )
        for index in range(4)
    ]
    return DataSnapshot(
        snapshot_id=f"{symbol.lower()}-feature-snap",
        symbol=symbol,
        venue="binance",
        timeframe="15Min",
        candles=candles,
        funding_rates=[0.0001] * len(candles),
        open_interest=[1_000.0] * len(candles),
        liquidation_notional=[0.0] * len(candles),
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        mark_price=[candle.close for candle in candles],
        index_price=[candle.close for candle in candles],
        provenance={"field_confidence": {"ohlcv": "high", "mark_index": "high"}},
    )


def _artifact(
    symbol: str,
    *,
    feature_timestamp: datetime | None = None,
    context_end_ts: datetime | None = None,
    q50: list[float] | None = None,
    q10: list[float] | None = None,
    q90: list[float] | None = None,
    future_covariates: list[ForecastCovariate] | None = None,
):
    adapter = TimesFmAdapter(
        TimesFmAdapterConfig(model_id="google/timesfm-2.5-200m-pytorch"),
        fixture_forecast={
            "point": q50 or [101.0, 102.0],
            "q10": q10 or [100.0, 101.0],
            "q50": q50 or [101.0, 102.0],
            "q90": q90 or [102.0, 103.0],
        },
    )
    request = ForecastRequest(
        values=[98.0, 99.0, 100.0],
        horizon=2,
        source_snapshot_id=f"{symbol.lower()}-feature-snap",
        context_end_ts=context_end_ts or datetime(2026, 5, 1, tzinfo=UTC),
    )
    return build_forecast_artifact(
        adapter.forecast(request),
        feature_timestamp=feature_timestamp or datetime(2026, 5, 1, 0, 15, tzinfo=UTC),
        created_at=datetime(2026, 5, 1, 0, 16, tzinfo=UTC),
        config_checksum="sha256:feature-config",
        last_observed_value=100.0,
        future_covariates=future_covariates,
    )


if __name__ == "__main__":
    unittest.main()
