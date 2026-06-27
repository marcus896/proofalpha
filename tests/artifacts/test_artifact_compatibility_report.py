from __future__ import annotations

import unittest

from engine.strategy.artifacts import build_artifact_compatibility_report, build_strategy_artifact

from tests.artifacts.test_promotion_manifest import _valid_artifact_payload


class ArtifactCompatibilityReportTests(unittest.TestCase):
    def test_compatibility_report_checks_venue_timeframes_symbols_features_and_risk(self) -> None:
        artifact = build_strategy_artifact(
            _valid_artifact_payload(
                symbol_scope=["BTCUSDT"],
                feature_contract_hash="feature-contract-v1",
                risk_limits={"max_notional": 1000.0, "max_drawdown": 0.2},
            )
        )

        report = build_artifact_compatibility_report(
            artifact,
            expected_venue="binance_usdm",
            expected_signal_timeframe="1h",
            expected_execution_timeframe="15m",
            expected_execution_model="binance_usdm_v3",
            allowed_symbols={"BTCUSDT", "ETHUSDT"},
            feature_contract_hash="feature-contract-v1",
            max_notional=1000.0,
        )

        self.assertTrue(report.compatible)
        self.assertEqual(report.checks["venue"], True)
        self.assertEqual(report.checks["feature_contract"], True)

    def test_compatibility_report_lists_failed_checks(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload(symbol_scope=["DOGEUSDT"]))

        report = build_artifact_compatibility_report(
            artifact,
            expected_venue="binance_usdm",
            expected_signal_timeframe="1h",
            expected_execution_timeframe="15m",
            expected_execution_model="binance_usdm_v3",
            allowed_symbols={"BTCUSDT", "ETHUSDT"},
            feature_contract_hash="different",
            max_notional=500.0,
        )

        self.assertFalse(report.compatible)
        self.assertIn("symbol_universe", report.reasons)
        self.assertIn("feature_contract", report.reasons)
        self.assertIn("risk_limits", report.reasons)


if __name__ == "__main__":
    unittest.main()
