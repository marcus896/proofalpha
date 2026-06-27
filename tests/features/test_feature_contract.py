from __future__ import annotations

import unittest

from engine.features.contracts import FeatureContract, validate_feature_contract


class FeatureContractTests(unittest.TestCase):
    def test_feature_contract_records_availability_mode_and_required_symbol_fields(self) -> None:
        contract = FeatureContract(
            name="spread_bps",
            source="bookTicker",
            timestamp_source="exchange_event_time",
            earliest_available_at="bar_close",
            allowed_modes={"research", "validation", "shadow", "paper"},
            max_age_seconds=60,
            leakage_risk="low",
            required_symbol_fields={"tick_size", "step_size"},
        )

        validation = validate_feature_contract(contract)

        self.assertTrue(validation.passed, validation.issues)
        self.assertEqual(contract.to_dict()["timestamp_source"], "exchange_event_time")
        self.assertIn("paper", contract.allowed_modes)

    def test_feature_contract_rejects_non_finite_max_age(self) -> None:
        contract = FeatureContract(
            name="spread_bps",
            source="bookTicker",
            timestamp_source="exchange_event_time",
            earliest_available_at="bar_close",
            allowed_modes={"paper"},
            max_age_seconds=float("inf"),
            leakage_risk="low",
            required_symbol_fields=set(),
        )

        validation = validate_feature_contract(contract)

        self.assertFalse(validation.passed)
        self.assertIn("non_finite_max_age_seconds", validation.issues)


if __name__ == "__main__":
    unittest.main()
