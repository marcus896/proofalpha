import unittest
from types import SimpleNamespace

from engine.config.models import LayerFamily, LayerSpec
from engine.app.data_sufficiency import (
    PUBLIC_ONLY_ALLOWED_PROVIDERS,
    STRICT_V3_MIN_BARS,
    STRICT_V3_SYMBOLS,
    build_data_sufficiency_report,
)


def _study(
    *,
    candle_count: int,
    symbol: str = "BTCUSDT",
    timeframe: str = "1Hour",
    provider: str | None = "binance_public_archive",
    field_confidence: str = "unavailable_archive_sidecar_empty_do_not_treat_zero_as_truth",
    source_hash: str | None = "sha256:test-source",
    fetch_manifest: str | None = "outputs/data/fetch_manifest.json",
    quality_flags: list[str] | None = None,
    layers: list[LayerSpec] | None = None,
    runtime_mode: str = "builtin",
    run_id: str = "strict-v3-study",
    paper_evidence_present: bool = False,
) -> SimpleNamespace:
    provenance: dict[str, object] = {
        "provider": provider,
        "source_hash": source_hash,
        "fetch_manifest": fetch_manifest,
        "field_confidence": {"liquidation_notional": field_confidence},
    }
    if paper_evidence_present:
        provenance["paper_evidence"] = {"completed": True, "order_count": 25}
    snapshot = SimpleNamespace(
        snapshot_id="strict-v3-snapshot",
        symbol=symbol,
        venue="binance",
        timeframe=timeframe,
        candles=[object()] * candle_count,
        liquidation_notional=[0.0] * candle_count,
        quality_flags=quality_flags or [],
        quality_report=None,
        provenance=provenance,
    )
    return SimpleNamespace(
        run_id=run_id,
        runtime_mode=runtime_mode,
        snapshot=snapshot,
        incumbent=SimpleNamespace(backbone="mom_squeeze", layers=[]),
        directional_layers=layers or [],
        known_good_filters=[],
        custom_filters=[],
        exit_layers=[],
    )


class DataSufficiencyTests(unittest.TestCase):
    def test_strict_constants_match_plan(self) -> None:
        self.assertEqual(STRICT_V3_MIN_BARS, {"1Hour": 13_140, "15Min": 52_560})
        self.assertEqual(STRICT_V3_SYMBOLS, {"BTCUSDT", "ETHUSDT"})
        self.assertEqual(
            PUBLIC_ONLY_ALLOWED_PROVIDERS,
            {"binance_perps", "binance_public_archive", "binance_public_ws_rest_bundle"},
        )

    def test_weak_five_candle_study_is_smoke_ready_not_improvement_ready(self) -> None:
        report = build_data_sufficiency_report(
            _study(
                candle_count=5,
                provider=None,
                source_hash=None,
                fetch_manifest=None,
                runtime_mode="fixture",
                run_id="example-study",
            )
        )

        self.assertEqual(report["artifact_type"], "data_sufficiency_report")
        self.assertTrue(report["run_ready"])
        self.assertFalse(report["research_ready"])
        self.assertFalse(report["improvement_ready"])
        self.assertFalse(report["can_claim_strategy_improvement"])
        self.assertEqual(report["minimum_candle_count"], 13_140)
        self.assertIn("example_or_fixture_study", report["blockers"])
        self.assertIn("missing_real_source_provenance", report["blockers"])

    def test_public_archive_history_is_research_ready_without_fake_liquidations(self) -> None:
        report = build_data_sufficiency_report(_study(candle_count=13_140))

        self.assertTrue(report["run_ready"])
        self.assertTrue(report["research_ready"])
        self.assertFalse(report["improvement_ready"])
        self.assertFalse(report["can_claim_strategy_improvement"])
        self.assertEqual(report["provider"], "binance_public_archive")
        self.assertTrue(report["source_hash_present"])
        self.assertTrue(report["fetch_manifest_present"])
        self.assertEqual(report["feature_availability"]["liquidation_notional"], "unavailable")
        self.assertFalse(report["feature_availability"]["liquidation_dependent_features_allowed"])
        self.assertIn("observed_liquidation_sidecar", report["missing_data_requirements"])

    def test_liquidation_dependent_layer_blocks_research_without_observed_sidecar(self) -> None:
        liquidation_layer = LayerSpec(
            "liq_intensity_filter",
            LayerFamily.DIRECTIONAL_FILTER,
            eligibility_rules={"requires": "liquidation_notional"},
        )

        report = build_data_sufficiency_report(_study(candle_count=13_140, layers=[liquidation_layer]))

        self.assertFalse(report["research_ready"])
        self.assertFalse(report["improvement_ready"])
        self.assertIn("liquidation_feature_missing_observed_sidecar", report["blockers"])

    def test_observed_liquidation_sidecar_and_paper_evidence_can_be_improvement_ready(self) -> None:
        report = build_data_sufficiency_report(
            _study(
                candle_count=52_560,
                timeframe="15Min",
                provider="binance_public_ws_rest_bundle",
                field_confidence="observed_public_forceorder_with_zero_buckets",
                paper_evidence_present=True,
            )
        )

        self.assertTrue(report["run_ready"])
        self.assertTrue(report["research_ready"])
        self.assertTrue(report["improvement_ready"])
        self.assertFalse(report["can_claim_strategy_improvement"])
        self.assertEqual(report["feature_availability"]["liquidation_notional"], "observed")
        self.assertTrue(report["feature_availability"]["liquidation_dependent_features_allowed"])
        self.assertEqual(report["missing_data_requirements"], [])


if __name__ == "__main__":
    unittest.main()
