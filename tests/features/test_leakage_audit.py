from __future__ import annotations

import unittest

from engine.features.contracts import FeatureContract
from engine.features.leakage_audit import audit_feature_causality_from_signals, audit_feature_leakage


class LeakageAuditTests(unittest.TestCase):
    def test_leakage_audit_reports_future_timestamp_and_research_only_field(self) -> None:
        report = audit_feature_leakage(
            {"close": 100.0, "label_return": 0.02},
            contracts={
                "close": FeatureContract.paper_safe("close", source="kline", max_age_seconds=900),
                "label_return": FeatureContract(
                    name="label_return",
                    source="label",
                    timestamp_source="label_end",
                    earliest_available_at="future",
                    allowed_modes={"research"},
                    max_age_seconds=0,
                    leakage_risk="research_only",
                    required_symbol_fields=set(),
                ),
            },
            as_of_utc="2026-05-07T00:00:00Z",
            observed_at_by_field={
                "close": "2026-05-06T23:59:00Z",
                "label_return": "2026-05-07T01:00:00Z",
            },
            mode="paper",
        )

        self.assertFalse(report.passed)
        self.assertIn("future_timestamp:label_return", report.issues)
        self.assertIn("research_only_field:label_return", report.issues)
        self.assertEqual(report.to_dict()["status"], "failed")

    def test_causality_audit_allows_causal_signal_after_future_spike_is_observable(self) -> None:
        contract = FeatureContract.paper_safe("rolling_close", source="kline", max_age_seconds=900)
        baseline = [100.0, 101.0, 102.0, 103.0, 104.0]
        mutated = [100.0, 101.0, 102.0, 103.0, 999.0]

        report = audit_feature_causality_from_signals(
            {"rolling_close": baseline},
            mutated_signals={"rolling_close": mutated},
            contracts={"rolling_close": contract},
            spike_index=4,
            mode="validation",
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.to_dict()["status"], "passed")

    def test_causality_audit_rejects_non_causal_contract_shape(self) -> None:
        contract = FeatureContract(
            name="centered_super_smoother",
            source="kline",
            timestamp_source="bar_close",
            earliest_available_at="bar_close",
            allowed_modes={"research", "validation"},
            max_age_seconds=900,
            leakage_risk="low",
            required_symbol_fields={"close"},
            input_fields=("close",),
            lookback_bars=10,
            warmup_bars=20,
            uses_centered_window=True,
        )

        report = audit_feature_causality_from_signals(
            {"centered_super_smoother": [1.0, 1.0, 1.0]},
            mutated_signals={"centered_super_smoother": [1.0, 1.0, 2.0]},
            contracts={"centered_super_smoother": contract},
            spike_index=2,
            mode="validation",
        )

        self.assertFalse(report.passed)
        self.assertIn("centered_window:centered_super_smoother", report.issues)

    def test_causality_audit_rejects_future_spike_that_changes_prior_signal(self) -> None:
        contract = FeatureContract.paper_safe("leaky_close", source="kline", max_age_seconds=900)

        report = audit_feature_causality_from_signals(
            {"leaky_close": [104.0, 104.0, 104.0, 104.0, 104.0]},
            mutated_signals={"leaky_close": [999.0, 999.0, 999.0, 999.0, 999.0]},
            contracts={"leaky_close": contract},
            spike_index=4,
            mode="validation",
        )

        self.assertFalse(report.passed)
        self.assertIn("future_spike_changed_pre_observable_signal:leaky_close:0", report.issues)


if __name__ == "__main__":
    unittest.main()
