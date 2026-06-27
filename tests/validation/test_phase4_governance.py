from __future__ import annotations

import unittest

from engine.config.models import PromotionDecision, RunCard, ValidationProtocol, ValidationStageResult
from engine.reporting.dashboard import build_dashboard_payload
from engine.validation.phase4_governance import (
    AblationResult,
    CandidateGovernanceInputs,
    ChampionSnapshot,
    MetricSnapshot,
    append_phase4_governance_stage,
    build_candidate_governance_report,
)


class Phase4CandidateGovernanceTests(unittest.TestCase):
    def test_governance_accepts_robust_challenger_and_surfaces_report_in_dashboard(self) -> None:
        report = build_candidate_governance_report(_governance_inputs())

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.promotion_decision.decision, "accept")
        self.assertGreater(report.robustness_score, 0.75)
        self.assertEqual(report.champion_challenger["status"], "challenger_wins")
        self.assertEqual(report.paper_forward_score, 0.82)
        self.assertEqual(report.next_action["action"], "promote_to_paper_forward_review")
        self.assertEqual(set(report.ablations), set(_required_ablation_layers()))

        protocol = append_phase4_governance_stage(_validation(), report)
        dashboard = build_dashboard_payload(
            runcard=RunCard(
                run_id="phase4",
                strategy_hash="abc",
                phase="phase4",
                split_id="split",
                seed=1,
                decision=PromotionDecision("accept", []),
                metrics={},
                artifacts={},
            ),
            validation_protocol=protocol,
        )

        self.assertEqual(dashboard["candidate_governance"]["status"], "passed")
        self.assertIn("robustness_score", dashboard["candidate_governance"])
        self.assertIn("champion_challenger", dashboard["candidate_governance"])

    def test_governance_rejects_fragile_candidate_with_specific_routes(self) -> None:
        inputs = _governance_inputs(
            metrics=MetricSnapshot(
                net_post_cost_return=0.30,
                cpcv_p10_sharpe=-0.10,
                pbo_score=0.35,
                deflated_sharpe_ratio=0.70,
                spa_pvalue=0.20,
                bootstrap_survival=0.40,
                plateau_width=0.05,
                oos_decay=0.55,
                regime_coverage=0.30,
                capacity_5x_edge_erosion=0.48,
                cross_symbol_pass_rate=0.33,
                paper_forward_score=0.20,
            ),
            failure_codes=["slippage_fragile", "regime_specific_only", "capacity_fail"],
        )

        report = build_candidate_governance_report(inputs)

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.promotion_decision.decision, "reject")
        self.assertIn("robustness_score_below_floor", report.promotion_decision.reasons)
        self.assertIn("paper_forward_fail", report.promotion_decision.reasons)
        self.assertIn("cpcv_p10_fail", report.promotion_decision.reasons)
        self.assertIn("pbo_fail", report.promotion_decision.reasons)
        self.assertIn("capacity_fail", report.promotion_decision.reasons)
        self.assertEqual(report.next_action["action"], "cost_execution_research")
        self.assertEqual(report.next_action["secondary_actions"], ["regime_scope_research", "sizing_liquidity_research"])

    def test_governance_blocks_feature_leakage_before_routing_experiments(self) -> None:
        report = build_candidate_governance_report(
            _governance_inputs(failure_codes=["feature_leakage", "slippage_fragile"])
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.next_action["action"], "block_candidate")
        self.assertIn("feature_leakage", report.promotion_decision.reasons)

    def test_governance_rejects_challenger_that_weakens_hard_gates(self) -> None:
        report = build_candidate_governance_report(
            _governance_inputs(
                candidate_gate_results={"dsr": False, "pbo": True, "spa": True, "cpcv": True, "capacity_5x": True},
                champion=ChampionSnapshot(
                    artifact_id="champion",
                    net_post_cost_return=0.18,
                    hard_gate_results={"dsr": True, "pbo": True, "spa": True, "cpcv": True, "capacity_5x": True},
                ),
            )
        )

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.champion_challenger["status"], "hard_gate_weakened")
        self.assertIn("champion_challenger_hard_gate_weakened:dsr", report.promotion_decision.reasons)


def _governance_inputs(**overrides) -> CandidateGovernanceInputs:
    kwargs = {
        "candidate_id": "candidate-a",
        "metrics": MetricSnapshot(
            net_post_cost_return=0.24,
            cpcv_p10_sharpe=0.30,
            pbo_score=0.08,
            deflated_sharpe_ratio=0.97,
            spa_pvalue=0.01,
            bootstrap_survival=0.90,
            plateau_width=0.35,
            oos_decay=0.10,
            regime_coverage=0.80,
            capacity_5x_edge_erosion=0.12,
            cross_symbol_pass_rate=0.90,
            paper_forward_score=0.82,
        ),
        "ablations": [
            AblationResult(layer=layer, full_return=0.24, ablated_return=0.18)
            for layer in _required_ablation_layers()
        ],
        "candidate_gate_results": {"dsr": True, "pbo": True, "spa": True, "cpcv": True, "capacity_5x": True},
        "champion": ChampionSnapshot(
            artifact_id="champion",
            net_post_cost_return=0.15,
            hard_gate_results={"dsr": True, "pbo": True, "spa": True, "cpcv": True, "capacity_5x": True},
        ),
        "failure_codes": [],
    }
    kwargs.update(overrides)
    return CandidateGovernanceInputs(**kwargs)


def _required_ablation_layers() -> list[str]:
    return ["backbone", "directional_filters", "flat_filters", "exits", "risk_hooks", "execution_policy"]


def _validation() -> ValidationProtocol:
    return ValidationProtocol(
        status="passed",
        stage_results=[ValidationStageResult(stage_name="existing", passed=True)],
        validation_gate_results={"dsr": True},
        promotion_decision=PromotionDecision("accept", []),
    )


if __name__ == "__main__":
    unittest.main()
