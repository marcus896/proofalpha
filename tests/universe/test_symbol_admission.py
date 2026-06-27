from __future__ import annotations

import unittest

from engine.universe.admission import AdmissionGateInputs, evaluate_symbol_admission


class SymbolAdmissionTests(unittest.TestCase):
    def test_paper_eligibility_requires_all_admission_gates(self) -> None:
        result = evaluate_symbol_admission(
            AdmissionGateInputs(
                exchange_status_trading=True,
                usdm_linear_perp=True,
                history_1h=True,
                history_15m=True,
                funding_history=True,
                mark_price_history=True,
                open_interest=True,
                book_depth=True,
                spread=True,
                volume=True,
                capacity=True,
                slippage_model_confidence=True,
                funding_stability=True,
                correlation_cluster=True,
                scenario_robustness=True,
                paper_dry_run=True,
            )
        )

        self.assertTrue(result.paper_eligible)
        self.assertEqual(result.rejections, [])


if __name__ == "__main__":
    unittest.main()
