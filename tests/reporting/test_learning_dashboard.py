from __future__ import annotations

import unittest

from engine.reporting.learning_dashboard import build_learning_dashboard


class LearningDashboardTests(unittest.TestCase):
    def test_learning_dashboard_surfaces_model_governance(self) -> None:
        payload = build_learning_dashboard(
            {
                "active_models": {
                    "slippage": "slip-v1",
                    "fill": "fill-v1",
                    "funding": "fund-v1",
                    "capacity": "cap-v1",
                },
                "model_cards": [{"model_id": "slip-v1", "approval_status": "approved"}],
                "training_windows": [{"start": "2026-05-01", "end": "2026-05-07"}],
                "validation_errors": [{"model_id": "fill-v1", "reason": "shadow_fail"}],
                "shadow_results": [{"model_id": "cap-v1", "passed": True}],
                "promotion_history": [{"model_id": "slip-v1"}],
                "rollback_history": [{"model_id": "old-slip"}],
            }
        )

        self.assertEqual(payload["page"], "Learning Models")
        self.assertEqual(payload["active_models"]["slippage"], "slip-v1")
        self.assertEqual(payload["model_cards"][0]["approval_status"], "approved")
        self.assertEqual(payload["rollback_history"][0]["model_id"], "old-slip")


if __name__ == "__main__":
    unittest.main()
