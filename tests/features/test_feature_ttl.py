from __future__ import annotations

import unittest

from engine.features.contracts import FeatureContract
from engine.features.feature_ttl import evaluate_feature_ttl


class FeatureTtlTests(unittest.TestCase):
    def test_ttl_staleness_blocks_paper_execution_features(self) -> None:
        result = evaluate_feature_ttl(
            {"spread_bps": 1.2},
            contracts={"spread_bps": FeatureContract.paper_safe("spread_bps", source="book", max_age_seconds=60)},
            mode="paper",
            now_utc="2026-05-07T00:02:00Z",
            observed_at_by_field={"spread_bps": "2026-05-07T00:00:00Z"},
        )

        self.assertFalse(result.passed)
        self.assertIn("feature_stale:spread_bps", result.issues)


if __name__ == "__main__":
    unittest.main()
