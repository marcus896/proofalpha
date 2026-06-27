import unittest

from engine.config.models import BacktestResult, BootstrapReport
from engine.optimizer.promotion import evaluate_candidate


def _result(sharpe: float, drawdown: float, trades: int) -> BacktestResult:
    return BacktestResult(
        trade_count=trades,
        win_rate=0.45,
        gross_pnl=120.0,
        net_pnl=100.0,
        fee_spend=5.0,
        funding_spend=1.0,
        sharpe=sharpe,
        sortino=sharpe + 0.1,
        max_drawdown=drawdown,
        equity_curve=[0.0, 10.0, -5.0, 20.0],
        liquidation_events=[],
    )


def _bootstrap(median_profit: float, worst_dd: float) -> BootstrapReport:
    return BootstrapReport(
        sample_count=64,
        median_net_profit=median_profit,
        median_max_drawdown=-0.09,
        worst_case_net_profit=-30.0,
        worst_case_drawdown=worst_dd,
        pass_rate=0.75,
    )


class PromotionRuleTests(unittest.TestCase):
    def test_rejects_candidate_that_fails_hard_gate(self) -> None:
        decision = evaluate_candidate(
            incumbent_train=_result(0.80, -0.10, 180),
            incumbent_oos=_result(0.80, -0.12, 180),
            candidate_train=_result(0.82, -0.20, 180),
            candidate_oos=_result(0.82, -0.11, 180),
            bootstrap_report=_bootstrap(120.0, -0.15),
        )

        self.assertEqual(decision.decision, "reject")
        self.assertIn("train_drawdown_cap", decision.reasons)

    def test_marks_candidate_as_wash_when_improvements_are_too_small(self) -> None:
        decision = evaluate_candidate(
            incumbent_train=_result(0.80, -0.10, 180),
            incumbent_oos=_result(0.80, -0.10, 180),
            candidate_train=_result(0.81, -0.095, 180),
            candidate_oos=_result(0.81, -0.09, 180),
            bootstrap_report=_bootstrap(102.0, -0.099),
        )

        self.assertEqual(decision.decision, "wash")
        self.assertIn("insufficient_improvement", decision.reasons)

    def test_accepts_candidate_with_clear_improvement(self) -> None:
        decision = evaluate_candidate(
            incumbent_train=_result(0.80, -0.10, 180),
            incumbent_oos=_result(0.80, -0.10, 180),
            candidate_train=_result(0.90, -0.09, 190),
            candidate_oos=_result(0.90, -0.09, 190),
            bootstrap_report=_bootstrap(130.0, -0.06),
        )

        self.assertEqual(decision.decision, "accept")
        self.assertEqual(decision.reasons, [])


if __name__ == "__main__":
    unittest.main()
