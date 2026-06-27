from __future__ import annotations

import unittest

from engine.validation.robustness_ladder import (
    build_paper_forward_score,
    build_robust_evaluation_scorecard,
    build_sealed_holdout_check,
    build_strategy_evidence_card,
    build_strategy_tournament_report,
)


class RobustnessLadderTests(unittest.TestCase):
    def test_tournament_ranks_stability_over_single_bucket_profit(self) -> None:
        report = build_strategy_tournament_report(
            [
                {
                    "candidate_id": "rocket",
                    "family": "pivot_atr_breakout",
                    "symbol": "BTCUSDT",
                    "timeframe": "1Hour",
                    "year": 2026,
                    "regime": "trend",
                    "oos_sharpe": 3.0,
                    "net_profit": 1000.0,
                    "max_drawdown": -0.45,
                    "trade_count": 12,
                },
                {
                    "candidate_id": "stable",
                    "family": "causal_kalman_state_filter",
                    "symbol": "BTCUSDT",
                    "timeframe": "1Hour",
                    "year": 2025,
                    "regime": "trend",
                    "oos_sharpe": 1.0,
                    "net_profit": 250.0,
                    "max_drawdown": -0.10,
                    "trade_count": 45,
                },
                {
                    "candidate_id": "stable",
                    "family": "causal_kalman_state_filter",
                    "symbol": "ETHUSDT",
                    "timeframe": "15Min",
                    "year": 2026,
                    "regime": "chop",
                    "oos_sharpe": 0.9,
                    "net_profit": 200.0,
                    "max_drawdown": -0.12,
                    "trade_count": 40,
                },
            ],
            minimum_bucket_count=2,
        )

        self.assertEqual(report["artifact_type"], "strategy_tournament")
        self.assertEqual(report["rank_basis"], "stability_score")
        self.assertEqual(report["ranked_candidates"][0]["candidate_id"], "stable")
        self.assertIn("insufficient_bucket_count:rocket", report["blockers"])

    def test_robust_evaluation_blocks_missing_or_failed_ladder_evidence(self) -> None:
        scorecard = build_robust_evaluation_scorecard(
            {
                "candidate_id": "bad",
                "feature_audit": {"passed": False, "issues": ["future_spike_changed_pre_observable_signal:bad:0"]},
                "tournament_candidate": {"bucket_count": 1, "distinct_symbols": ["BTCUSDT"], "distinct_regimes": ["trend"]},
                "metrics": {
                    "in_sample_sharpe": 2.0,
                    "oos_sharpe": 0.2,
                    "sealed_holdout_sharpe": -0.1,
                    "cpcv_pass": False,
                    "bootstrap_pass_rate": 0.2,
                    "spa_pass": False,
                    "pbo": 0.8,
                    "dsr": 0.4,
                    "regime_pass_rate": 0.5,
                    "scenario_pass_rate": 0.5,
                    "capacity_pass": False,
                    "slippage_bps": 80.0,
                    "trade_count": 8,
                    "max_drawdown": -0.55,
                },
            }
        )

        self.assertEqual(scorecard["artifact_type"], "robust_evaluation_scorecard")
        self.assertFalse(scorecard["robustness_ready"])
        self.assertIn("feature_causality_audit_failed", scorecard["blockers"])
        self.assertIn("cpcv_failed", scorecard["blockers"])
        self.assertGreater(scorecard["is_to_oos_distortion"], 0.0)

    def test_robust_evaluation_passes_multi_axis_post_cost_candidate(self) -> None:
        scorecard = build_robust_evaluation_scorecard(
            {
                "candidate_id": "stable",
                "feature_audit": {"passed": True, "issues": []},
                "tournament_candidate": {
                    "bucket_count": 4,
                    "distinct_symbols": ["BTCUSDT", "ETHUSDT"],
                    "distinct_regimes": ["trend", "chop"],
                },
                "metrics": {
                    "in_sample_sharpe": 1.2,
                    "oos_sharpe": 1.0,
                    "sealed_holdout_sharpe": 0.8,
                    "cpcv_pass": True,
                    "bootstrap_pass_rate": 0.88,
                    "spa_pass": True,
                    "pbo": 0.12,
                    "dsr": 0.97,
                    "regime_pass_rate": 0.82,
                    "scenario_pass_rate": 0.8,
                    "capacity_pass": True,
                    "slippage_bps": 12.0,
                    "trade_count": 80,
                    "max_drawdown": -0.14,
                },
            }
        )

        self.assertTrue(scorecard["robustness_ready"])
        self.assertEqual(scorecard["status"], "passed")

    def test_sealed_holdout_report_hides_tunable_metrics_from_agent_view(self) -> None:
        report = build_sealed_holdout_check(
            {
                "candidate_id": "stable",
                "robust_evaluation": {"robustness_ready": True},
                "sealed_metrics": {
                    "sharpe": 0.9,
                    "max_drawdown": -0.12,
                    "trade_count": 60,
                    "post_cost_return": 0.18,
                },
            }
        )

        self.assertEqual(report["artifact_type"], "sealed_holdout_check")
        self.assertTrue(report["passed"])
        self.assertEqual(report["agent_visible"]["decision"], "pass")
        self.assertNotIn("sharpe", report["agent_visible"])
        self.assertNotIn("max_drawdown", report["agent_visible"])
        self.assertIn("sealed_metric_digest", report)

    def test_paper_forward_score_blocks_weak_or_missing_execution_evidence(self) -> None:
        report = build_paper_forward_score(
            {
                "candidate_id": "stable",
                "data_inventory": {"forward_first_window_ready": False},
                "paper_dashboard": {"orders": {"order_count": 2}, "pnl": {"telemetry_quality_score": 0.2}},
            }
        )

        self.assertEqual(report["artifact_type"], "paper_forward_score")
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(report["advisory_only"])
        self.assertFalse(report["live_policy_mutation_allowed"])
        self.assertIn("public_ws_window_not_ready", report["blockers"])
        self.assertIn("paper_sample_too_small", report["blockers"])
        self.assertIn("liquidation_sidecar_missing", report["blockers"])

    def test_paper_forward_score_ready_remains_advisory(self) -> None:
        report = build_paper_forward_score(
            {
                "candidate_id": "stable",
                "data_inventory": {"forward_first_window_ready": True, "liquidation_sidecar_ready": True},
                "paper_dashboard": {
                    "orders": {
                        "order_count": 20,
                        "filled_count": 20,
                        "rejected_count": 0,
                        "risk_blocked_count": 0,
                        "max_abs_slip_bps": 5.0,
                        "latency_ms_p95": 100.0,
                    },
                    "pnl": {"telemetry_quality_score": 0.9},
                },
                "calibration_feedback": {
                    "sample_count": 20,
                    "telemetry_quality": {"score": 0.9},
                    "priors": {"funding_shock_bps": {"sample_mean": 0.5}},
                    "capacity_questions": {
                        "max_participation_rate_seen": 0.01,
                        "mean_fill_completion_rate": 0.98,
                        "mean_edge_erosion_bps": 2.0,
                    },
                },
            }
        )

        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["advisory_only"])
        self.assertGreater(report["execution_realism_score"], 0.8)
        self.assertEqual(report["blockers"], [])

    def test_strategy_evidence_card_blocks_advisory_paper_without_governance(self) -> None:
        card = build_strategy_evidence_card(
            {
                "candidate_id": "stable",
                "data_matrix": {"artifact_id": "matrix", "status": "ready", "robustness_ready": True},
                "feature_audit": {"artifact_id": "feature", "passed": True},
                "strategy_tournament": {"artifact_id": "tournament", "status": "ready"},
                "robust_evaluation": {"artifact_id": "robust", "robustness_ready": True},
                "sealed_holdout": {
                    "artifact_id": "holdout",
                    "passed": True,
                    "agent_visible": {"decision": "pass"},
                    "sealed_metric_digest": "sha256:hidden",
                    "sealed_metrics": {"sharpe": 9.9},
                },
                "paper_forward_score": {"artifact_id": "paper", "status": "ready", "advisory_only": True},
            }
        )

        self.assertEqual(card["artifact_type"], "strategy_evidence_card")
        self.assertEqual(card["status"], "blocked")
        self.assertFalse(card["can_claim_strategy_improvement"])
        self.assertEqual(card["next_allowed_action"], "request_promotion_governance_review")
        self.assertIn("paper_forward_score_advisory_without_governance_approval", card["blockers"])
        self.assertNotIn("sealed_metrics", card)

    def test_strategy_evidence_card_allows_claim_after_governance_approval(self) -> None:
        card = build_strategy_evidence_card(
            {
                "candidate_id": "stable",
                "promotion_governance_approved": True,
                "data_matrix": {"artifact_id": "matrix", "status": "ready", "robustness_ready": True},
                "feature_audit": {"artifact_id": "feature", "passed": True},
                "strategy_tournament": {"artifact_id": "tournament", "status": "ready"},
                "robust_evaluation": {"artifact_id": "robust", "robustness_ready": True},
                "sealed_holdout": {"artifact_id": "holdout", "passed": True, "agent_visible": {"decision": "pass"}},
                "paper_forward_score": {"artifact_id": "paper", "status": "ready", "advisory_only": True},
            }
        )

        self.assertEqual(card["status"], "ready")
        self.assertTrue(card["can_claim_strategy_improvement"])
        self.assertEqual(card["blockers"], [])


if __name__ == "__main__":
    unittest.main()
