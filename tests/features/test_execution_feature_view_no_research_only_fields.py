from __future__ import annotations

import unittest

from engine.features.contracts import FeatureContract
from engine.features.execution_feature_view import build_execution_feature_view


class ExecutionFeatureViewTests(unittest.TestCase):
    def test_execution_feature_view_rejects_research_only_fields(self) -> None:
        contracts = {
            "close": FeatureContract.paper_safe("close", source="kline", max_age_seconds=900),
            "future_return": FeatureContract(
                name="future_return",
                source="label",
                timestamp_source="label_interval_end",
                earliest_available_at="future",
                allowed_modes={"research", "validation"},
                max_age_seconds=0,
                leakage_risk="research_only",
                required_symbol_fields=set(),
            ),
        }

        with self.assertRaisesRegex(ValueError, "research_only_field:future_return"):
            build_execution_feature_view(
                {"close": 100.0, "future_return": 0.01},
                contracts=contracts,
                mode="paper",
                now_utc="2026-05-07T00:00:00Z",
                observed_at_by_field={
                    "close": "2026-05-06T23:59:00Z",
                    "future_return": "2026-05-07T01:00:00Z",
                },
            )


if __name__ == "__main__":
    unittest.main()
