from __future__ import annotations

import unittest

from engine.config.models import PromotionDecision, ValidationProtocol, ValidationStageResult
from engine.forecasting.baseline_gate import (
    ForecastComparisonResult,
    append_forecast_baseline_stage,
    compare_forecast_to_baselines,
)


class ForecastBaselineGateTests(unittest.TestCase):
    def test_forecast_variant_must_beat_all_required_post_cost_baselines(self) -> None:
        report = compare_forecast_to_baselines(
            forecast=ForecastComparisonResult(
                variant_id="timesfm-q50-direction",
                net_post_cost_return=0.16,
                hard_gate_results={"dsr": True, "pbo": True, "spa": True, "cpcv": True},
            ),
            baselines={
                "no_forecast": ForecastComparisonResult("no_forecast", 0.04),
                "momentum": ForecastComparisonResult("momentum", 0.10),
                "breakout": ForecastComparisonResult("breakout", 0.08),
                "carry_funding": ForecastComparisonResult("carry_funding", 0.12),
            },
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.best_baseline_id, "carry_funding")
        self.assertAlmostEqual(report.net_post_cost_improvement, 0.04)
        self.assertEqual(report.promotion_decision.decision, "accept")
        self.assertTrue(report.research_only)

    def test_forecast_variant_rejected_when_it_loses_to_any_required_baseline(self) -> None:
        report = compare_forecast_to_baselines(
            forecast=ForecastComparisonResult("timesfm-weak", 0.09),
            baselines={
                "no_forecast": ForecastComparisonResult("no_forecast", 0.04),
                "momentum": ForecastComparisonResult("momentum", 0.11),
                "breakout": ForecastComparisonResult("breakout", 0.08),
                "carry_funding": ForecastComparisonResult("carry_funding", 0.12),
            },
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.promotion_decision.decision, "reject")
        self.assertIn("forecast_does_not_beat_baselines", report.promotion_decision.reasons)
        self.assertIn("baseline_loss:momentum", report.promotion_decision.reasons)
        self.assertIn("baseline_loss:carry_funding", report.promotion_decision.reasons)

    def test_forecast_variant_rejected_when_hard_gates_weaken(self) -> None:
        report = compare_forecast_to_baselines(
            forecast=ForecastComparisonResult(
                "timesfm-regression",
                0.20,
                hard_gate_results={"dsr": False, "pbo": True, "spa": True, "cpcv": True},
            ),
            baselines={
                "no_forecast": ForecastComparisonResult("no_forecast", 0.04),
                "momentum": ForecastComparisonResult("momentum", 0.10),
                "breakout": ForecastComparisonResult("breakout", 0.08),
                "carry_funding": ForecastComparisonResult("carry_funding", 0.12),
            },
            reference_hard_gate_results={"dsr": True, "pbo": True, "spa": True, "cpcv": True},
        )

        self.assertEqual(report.status, "failed")
        self.assertIn("forecast_hard_gate_weakened:dsr", report.promotion_decision.reasons)

    def test_missing_required_baseline_blocks_promotion(self) -> None:
        report = compare_forecast_to_baselines(
            forecast=ForecastComparisonResult("timesfm", 0.20),
            baselines={
                "no_forecast": ForecastComparisonResult("no_forecast", 0.04),
                "momentum": ForecastComparisonResult("momentum", 0.10),
            },
        )

        self.assertEqual(report.status, "failed")
        self.assertIn("missing_required_baseline:breakout", report.promotion_decision.reasons)
        self.assertIn("missing_required_baseline:carry_funding", report.promotion_decision.reasons)

    def test_baseline_report_appends_research_only_stage_to_validation_protocol(self) -> None:
        report = compare_forecast_to_baselines(
            forecast=ForecastComparisonResult("timesfm", 0.16),
            baselines={
                "no_forecast": ForecastComparisonResult("no_forecast", 0.04),
                "momentum": ForecastComparisonResult("momentum", 0.10),
                "breakout": ForecastComparisonResult("breakout", 0.08),
                "carry_funding": ForecastComparisonResult("carry_funding", 0.12),
            },
        )
        protocol = ValidationProtocol(
            status="passed",
            stage_results=[ValidationStageResult("phase4_candidate_governance", True)],
            validation_gate_results={"phase4_candidate_governance": True},
            promotion_decision=PromotionDecision("accept", []),
        )

        updated = append_forecast_baseline_stage(protocol, report)

        self.assertEqual(updated.status, "passed")
        self.assertTrue(updated.validation_gate_results["phase5_forecast_baseline_gate"])
        self.assertEqual(updated.stage_results[-1].stage_name, "phase5_forecast_baseline_gate")
        self.assertTrue(updated.stage_results[-1].metrics["research_only"])
        self.assertEqual(updated.stage_results[-1].metrics["promotion_decision"]["decision"], "accept")


if __name__ == "__main__":
    unittest.main()
