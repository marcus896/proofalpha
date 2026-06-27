from __future__ import annotations

import unittest

from engine.execution.pretrade_checks import PreTradeCheckContext, run_pretrade_checks


class PreTradeChecksTests(unittest.TestCase):
    def test_pretrade_checks_emit_explicit_rejections(self) -> None:
        result = run_pretrade_checks(
            PreTradeCheckContext(
                artifact_approved=False,
                artifact_expired=True,
                symbol_allowed=False,
                paper_mode_allowed=True,
                market_fresh=False,
                book_gap_clean=False,
                reconciliation_clean=False,
                duplicate_client_order_id=True,
                rate_limit_ok=False,
                margin_ok=False,
                venue_rules_ok=False,
                spread_depth_ok=False,
                funding_ok=False,
                liquidation_ok=False,
                portfolio_risk_ok=False,
            )
        )

        self.assertFalse(result.passed)
        self.assertIn("artifact_not_approved", result.rejections)
        self.assertIn("duplicate_client_order_id", result.rejections)
        self.assertIn("portfolio_risk_block", result.rejections)


if __name__ == "__main__":
    unittest.main()
