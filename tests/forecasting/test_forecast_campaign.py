from __future__ import annotations

import json
import unittest

from engine.config.models import PromotionDecision, ValidationProtocol, ValidationStageResult
from engine.forecasting.baseline_gate import ForecastComparisonResult
from engine.forecasting.campaign import (
    PRIMARY_FORECAST_SYMBOLS,
    append_forecast_campaign_stage,
    build_forecast_validation_campaign,
    run_forecast_validation_campaign,
)


def _baselines() -> dict[str, ForecastComparisonResult]:
    return {
        "no_forecast": ForecastComparisonResult("no_forecast", 0.02),
        "momentum": ForecastComparisonResult("momentum", 0.06),
        "breakout": ForecastComparisonResult("breakout", 0.04),
        "carry_funding": ForecastComparisonResult("carry_funding", 0.07),
    }


class ForecastCampaignTests(unittest.TestCase):
    def test_campaign_helper_builds_primary_symbol_forecast_feature_contracts(self) -> None:
        campaign = build_forecast_validation_campaign(
            model_id="timesfm-2.0-500m-pytorch",
            config_checksum="sha256:abc123",
        )

        payload = campaign.to_dict()
        self.assertEqual(tuple(payload["symbols"]), PRIMARY_FORECAST_SYMBOLS)
        self.assertTrue(payload["research_only"])
        self.assertEqual(
            tuple(payload["required_baselines"]),
            ("no_forecast", "momentum", "breakout", "carry_funding"),
        )
        self.assertEqual(len(payload["forecast_variants"]), 3)
        for variant in payload["forecast_variants"]:
            self.assertIn(variant["symbol"], PRIMARY_FORECAST_SYMBOLS)
            self.assertIn("forecast_feature", variant["feature_contracts"])
            self.assertEqual(variant["forecast_feature_config"]["model_id"], "timesfm-2.0-500m-pytorch")
            self.assertEqual(variant["forecast_feature_config"]["config_checksum"], "sha256:abc123")

        serialized = json.dumps(payload)
        self.assertNotIn("trade_action", serialized)
        self.assertNotIn("position_size", serialized)
        self.assertNotIn("order", serialized)

    def test_campaign_passes_only_when_every_symbol_beats_required_baselines(self) -> None:
        campaign = build_forecast_validation_campaign()
        report = run_forecast_validation_campaign(
            campaign,
            {
                symbol: {
                    "forecast": ForecastComparisonResult(
                        f"{symbol.lower()}-timesfm-forecast-feature",
                        0.11,
                        hard_gate_results={"dsr": True, "pbo": True, "spa": True, "cpcv": True},
                    ),
                    "baselines": _baselines(),
                }
                for symbol in PRIMARY_FORECAST_SYMBOLS
            },
        )

        self.assertEqual(report.status, "passed")
        self.assertTrue(report.research_only)
        self.assertFalse(report.promotion_blocked)
        self.assertEqual(report.promotion_decision.decision, "accept")
        self.assertEqual(set(report.post_cost_improvements), set(PRIMARY_FORECAST_SYMBOLS))
        self.assertAlmostEqual(report.post_cost_improvements["BTCUSDT"], 0.04)
        self.assertEqual(report.failed_reasons, [])
        self.assertNotIn("executor_action", json.dumps(report.to_dict()))

    def test_campaign_records_forecast_unavailable_skip(self) -> None:
        campaign = build_forecast_validation_campaign()
        results = {
            symbol: {
                "forecast": ForecastComparisonResult(f"{symbol.lower()}-timesfm-forecast-feature", 0.11),
                "baselines": _baselines(),
            }
            for symbol in PRIMARY_FORECAST_SYMBOLS
        }
        results["ETHUSDT"] = {"baselines": _baselines()}

        report = run_forecast_validation_campaign(campaign, results)

        self.assertEqual(report.status, "skipped")
        self.assertTrue(report.promotion_blocked)
        self.assertEqual(report.symbol_reports["ETHUSDT"].status, "skipped")
        self.assertIn("forecast_unavailable:ETHUSDT", report.failed_reasons)
        self.assertEqual(report.promotion_decision.decision, "reject")

    def test_campaign_prefixes_baseline_and_hard_gate_failure_reasons_by_symbol(self) -> None:
        campaign = build_forecast_validation_campaign(symbols=("BTCUSDT",))

        report = run_forecast_validation_campaign(
            campaign,
            {
                "BTCUSDT": {
                    "forecast": ForecastComparisonResult(
                        "btcusdt-timesfm-forecast-feature",
                        0.05,
                        hard_gate_results={"dsr": False, "pbo": True},
                    ),
                    "baselines": _baselines(),
                }
            },
            reference_hard_gate_results={"dsr": True, "pbo": True},
        )

        self.assertEqual(report.status, "failed")
        self.assertIn("BTCUSDT:forecast_does_not_beat_baselines", report.failed_reasons)
        self.assertIn("BTCUSDT:baseline_loss:momentum", report.failed_reasons)
        self.assertIn("BTCUSDT:forecast_hard_gate_weakened:dsr", report.failed_reasons)

    def test_campaign_report_appends_research_only_stage_to_validation_protocol(self) -> None:
        campaign = build_forecast_validation_campaign(symbols=("BTCUSDT",))
        report = run_forecast_validation_campaign(
            campaign,
            {
                "BTCUSDT": {
                    "forecast": ForecastComparisonResult("btcusdt-timesfm-forecast-feature", 0.11),
                    "baselines": _baselines(),
                }
            },
        )
        protocol = ValidationProtocol(
            status="passed",
            stage_results=[ValidationStageResult("phase4_candidate_governance", True)],
            validation_gate_results={"phase4_candidate_governance": True},
            promotion_decision=PromotionDecision("accept", []),
        )

        updated = append_forecast_campaign_stage(protocol, report)

        self.assertEqual(updated.status, "passed")
        self.assertTrue(updated.validation_gate_results["phase5_forecast_validation_campaign"])
        self.assertEqual(updated.stage_results[-1].stage_name, "phase5_forecast_validation_campaign")
        self.assertTrue(updated.stage_results[-1].metrics["research_only"])
        self.assertFalse(updated.stage_results[-1].metrics["promotion_blocked"])
        self.assertEqual(updated.promotion_decision.decision, "accept")


if __name__ == "__main__":
    unittest.main()
