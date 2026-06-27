from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path

from engine.forecasting.artifacts import build_forecast_artifact
from engine.forecasting.cache import (
    ForecastArtifactMetadata,
    build_forecast_cache_key,
    get_or_create_forecast_artifact,
    load_cached_forecast_artifact,
    write_forecast_artifact,
)
from engine.forecasting.timesfm_adapter import ForecastRequest, TimesFmAdapter, TimesFmAdapterConfig


class ForecastCacheTests(unittest.TestCase):
    def test_cache_key_is_stable_and_invalidates_on_model_or_config_change(self) -> None:
        base = {
            "source_snapshot_id": "snapshot-btc-1h",
            "symbol": "BTCUSDT",
            "context_end_ts": "2026-05-01T00:00:00Z",
            "context_length": 512,
            "horizon": 3,
            "model_id": "google/timesfm-2.5-200m-pytorch",
            "model_sha256": "sha256:model-a",
            "config_checksum": "sha256:config-a",
        }

        first = build_forecast_cache_key(**base)
        second = build_forecast_cache_key(**dict(base, context_end_ts="2026-05-01T00:00:00+00:00"))
        changed_model = build_forecast_cache_key(**dict(base, model_sha256="sha256:model-b"))
        changed_config = build_forecast_cache_key(**dict(base, config_checksum="sha256:config-b"))

        self.assertEqual(first.key, second.key)
        self.assertEqual(first.parts["context_end_ts"], "2026-05-01T00:00:00+00:00")
        self.assertNotEqual(first.key, changed_model.key)
        self.assertNotEqual(first.key, changed_config.key)

    def test_writer_persists_validated_research_only_artifact_and_cache_hit_metrics(self) -> None:
        artifact = _artifact()
        cache_key = build_forecast_cache_key(
            source_snapshot_id=artifact.source_snapshot_id,
            symbol="BTCUSDT",
            context_end_ts=artifact.context_end_ts,
            context_length=artifact.context_length,
            horizon=artifact.horizon,
            model_id=artifact.model_id,
            model_sha256="2F776EFE6245E42B24BC4153FFDF61810140210E4BD3B01FB21F7AA779AB6CE8",
            config_checksum=artifact.config_checksum,
        )

        output_root = Path("outputs") / "test_forecast_cache"
        record = write_forecast_artifact(
            output_root,
            artifact,
            cache_key,
            ForecastArtifactMetadata(
                model_path="models/timesfm-2.5-200m-pytorch",
                model_sha256="2F776EFE6245E42B24BC4153FFDF61810140210E4BD3B01FB21F7AA779AB6CE8",
                runtime_profile="python3.11-cpu-sidecar",
                sidecar_version="timesfm-sidecar-v1",
                quantile_schema=["q10", "q50", "q90"],
            ),
        )
        loaded = load_cached_forecast_artifact(output_root, cache_key)
        missed = load_cached_forecast_artifact(
            output_root,
            build_forecast_cache_key(
                source_snapshot_id=artifact.source_snapshot_id,
                symbol="BTCUSDT",
                context_end_ts=artifact.context_end_ts,
                context_length=artifact.context_length,
                horizon=artifact.horizon,
                model_id=artifact.model_id,
                model_sha256="sha256:different-model",
                config_checksum=artifact.config_checksum,
            ),
        )
        payload = json.loads(record.path.read_text(encoding="utf-8"))

        self.assertEqual(record.cache_status, "miss_written")
        self.assertEqual(record.metrics, {"cache_hits": 0, "cache_misses": 1})
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.cache_status, "hit")
        self.assertEqual(loaded.metrics, {"cache_hits": 1, "cache_misses": 0})
        self.assertIsNone(missed)

        self.assertTrue(payload["research_only"])
        self.assertEqual(payload["cache_key"], cache_key.key)
        self.assertEqual(payload["cache_key_parts"]["symbol"], "BTCUSDT")
        self.assertEqual(payload["metadata"]["model_path"], "models/timesfm-2.5-200m-pytorch")
        self.assertEqual(payload["metadata"]["model_sha256"], "2F776EFE6245E42B24BC4153FFDF61810140210E4BD3B01FB21F7AA779AB6CE8")
        self.assertEqual(payload["metadata"]["runtime_profile"], "python3.11-cpu-sidecar")
        self.assertEqual(payload["metadata"]["sidecar_version"], "timesfm-sidecar-v1")
        self.assertEqual(payload["metadata"]["quantile_schema"], ["q10", "q50", "q90"])
        self.assertNotIn("order", payload)
        self.assertNotIn("trade_action", payload)
        self.assertNotIn("position_size", payload)

    def test_writer_rejects_invalid_artifact_and_malformed_metadata(self) -> None:
        invalid_artifact = _artifact(fixture={"point": [103.0, 104.0], "q10": [102.0, 103.0]})
        cache_key = build_forecast_cache_key(
            source_snapshot_id=invalid_artifact.source_snapshot_id,
            symbol="BTCUSDT",
            context_end_ts=invalid_artifact.context_end_ts,
            context_length=invalid_artifact.context_length,
            horizon=invalid_artifact.horizon,
            model_id=invalid_artifact.model_id,
            model_sha256="sha256:model",
            config_checksum=invalid_artifact.config_checksum,
        )

        output_root = Path("outputs") / "test_forecast_cache_invalid"
        with self.assertRaisesRegex(ValueError, "invalid_forecast_artifact:missing_quantile:q50"):
            write_forecast_artifact(output_root, invalid_artifact, cache_key, _metadata())

        with self.assertRaisesRegex(ValueError, "missing_forecast_artifact_metadata:model_sha256"):
            write_forecast_artifact(
                output_root,
                _artifact(),
                cache_key,
                ForecastArtifactMetadata(
                    model_path="models/timesfm-2.5-200m-pytorch",
                    model_sha256="",
                    runtime_profile="python3.11-cpu-sidecar",
                    sidecar_version="timesfm-sidecar-v1",
                    quantile_schema=["q10", "q50", "q90"],
                ),
            )

    def test_get_or_create_skips_factory_on_cache_hit(self) -> None:
        artifact = _artifact()
        cache_key = build_forecast_cache_key(
            source_snapshot_id=artifact.source_snapshot_id,
            symbol="BTCUSDT",
            context_end_ts=artifact.context_end_ts,
            context_length=artifact.context_length,
            horizon=artifact.horizon,
            model_id=artifact.model_id,
            model_sha256="sha256:model",
            config_checksum=artifact.config_checksum,
        )
        output_root = Path("outputs") / "test_forecast_cache_get_or_create" / uuid.uuid4().hex
        calls = 0

        def factory():
            nonlocal calls
            calls += 1
            return artifact

        first = get_or_create_forecast_artifact(output_root, cache_key, _metadata(), factory)
        second = get_or_create_forecast_artifact(output_root, cache_key, _metadata(), factory)

        self.assertEqual(calls, 1)
        self.assertEqual(first.cache_status, "miss_written")
        self.assertEqual(second.cache_status, "hit")


def _metadata() -> ForecastArtifactMetadata:
    return ForecastArtifactMetadata(
        model_path="models/timesfm-2.5-200m-pytorch",
        model_sha256="sha256:model",
        runtime_profile="python3.11-cpu-sidecar",
        sidecar_version="timesfm-sidecar-v1",
        quantile_schema=["q10", "q50", "q90"],
    )


def _artifact(
    fixture: dict[str, list[float]] | None = None,
):
    adapter = TimesFmAdapter(
        TimesFmAdapterConfig(model_id="google/timesfm-2.5-200m-pytorch"),
        fixture_forecast=fixture
        or {
            "point": [103.0, 104.0],
            "q10": [102.0, 103.0],
            "q50": [103.0, 104.0],
            "q90": [104.0, 105.0],
        },
    )
    result = adapter.forecast(
        ForecastRequest(
            values=[100.0, 101.0, 102.0],
            horizon=2,
            source_snapshot_id="snapshot-btc-1h",
            context_end_ts="2026-05-01T00:00:00Z",
        )
    )
    return build_forecast_artifact(
        result,
        feature_timestamp="2026-05-01T00:15:00Z",
        created_at="2026-05-01T00:16:00Z",
        config_checksum="sha256:config-a",
    )


if __name__ == "__main__":
    unittest.main()
