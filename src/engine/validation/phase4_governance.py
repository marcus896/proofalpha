from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from engine.config.models import PromotionDecision, ValidationProtocol, ValidationStageResult


REQUIRED_ABLATION_LAYERS = (
    "backbone",
    "directional_filters",
    "flat_filters",
    "exits",
    "risk_hooks",
    "execution_policy",
)

FAILURE_ROUTE_ACTIONS = {
    "slippage_fragile": "cost_execution_research",
    "regime_specific_only": "regime_scope_research",
    "capacity_fail": "sizing_liquidity_research",
    "feature_leakage": "block_candidate",
}

HARD_GATE_NAMES = (
    "dsr",
    "pbo",
    "spa",
    "cpcv",
    "capacity_5x",
    "no_liquidation",
    "max_drawdown",
    "execution_rules",
)


@dataclass(frozen=True)
class MetricSnapshot:
    net_post_cost_return: float
    cpcv_p10_sharpe: float
    pbo_score: float
    deflated_sharpe_ratio: float
    spa_pvalue: float
    bootstrap_survival: float
    plateau_width: float
    oos_decay: float
    regime_coverage: float
    capacity_5x_edge_erosion: float
    cross_symbol_pass_rate: float
    paper_forward_score: float | None = None


@dataclass(frozen=True)
class AblationResult:
    layer: str
    full_return: float
    ablated_return: float

    @property
    def contribution(self) -> float:
        return float(self.full_return) - float(self.ablated_return)


@dataclass(frozen=True)
class ChampionSnapshot:
    artifact_id: str
    net_post_cost_return: float
    hard_gate_results: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateGovernanceInputs:
    candidate_id: str
    metrics: MetricSnapshot
    ablations: list[AblationResult]
    candidate_gate_results: dict[str, bool] = field(default_factory=dict)
    champion: ChampionSnapshot | None = None
    failure_codes: list[str] = field(default_factory=list)
    robustness_floor: float = 0.70
    paper_forward_floor: float = 0.50


@dataclass(frozen=True)
class CandidateGovernanceReport:
    candidate_id: str
    status: str
    robustness_score: float
    component_scores: dict[str, float]
    ablations: dict[str, dict[str, float]]
    champion_challenger: dict[str, object]
    next_action: dict[str, object]
    paper_forward_score: float | None
    promotion_decision: PromotionDecision

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["promotion_decision"] = asdict(self.promotion_decision)
        return payload


def build_candidate_governance_report(inputs: CandidateGovernanceInputs) -> CandidateGovernanceReport:
    components = _component_scores(inputs.metrics)
    robustness_score = round(sum(components.values()) / len(components), 6)
    ablations = _ablation_payload(inputs.ablations)
    champion_challenger = _champion_challenger(inputs)
    next_action = route_failure_taxonomy(inputs.failure_codes)
    reasons = _rejection_reasons(
        inputs=inputs,
        robustness_score=robustness_score,
        ablations=ablations,
        champion_challenger=champion_challenger,
    )
    status = "passed" if not reasons else "failed"
    return CandidateGovernanceReport(
        candidate_id=inputs.candidate_id,
        status=status,
        robustness_score=robustness_score,
        component_scores=components,
        ablations=ablations,
        champion_challenger=champion_challenger,
        next_action=next_action if reasons else {"action": "promote_to_paper_forward_review", "secondary_actions": []},
        paper_forward_score=inputs.metrics.paper_forward_score,
        promotion_decision=PromotionDecision("accept", []) if not reasons else PromotionDecision("reject", reasons),
    )


def route_failure_taxonomy(failure_codes: list[str]) -> dict[str, object]:
    unique_actions: list[str] = []
    for code in failure_codes:
        action = FAILURE_ROUTE_ACTIONS.get(str(code))
        if action and action not in unique_actions:
            unique_actions.append(action)
    if "block_candidate" in unique_actions:
        return {
            "action": "block_candidate",
            "secondary_actions": [action for action in unique_actions if action != "block_candidate"],
        }
    if not unique_actions:
        return {"action": "promote_to_paper_forward_review", "secondary_actions": []}
    return {"action": unique_actions[0], "secondary_actions": unique_actions[1:]}


def append_phase4_governance_stage(
    validation: ValidationProtocol,
    report: CandidateGovernanceReport,
) -> ValidationProtocol:
    stage = ValidationStageResult(
        stage_name="phase4_candidate_governance",
        passed=report.status == "passed",
        reasons=list(report.promotion_decision.reasons),
        metrics=report.to_dict(),
    )
    gate_results = dict(validation.validation_gate_results)
    gate_results["phase4_candidate_governance"] = report.status == "passed"
    return ValidationProtocol(
        status="passed" if validation.status == "passed" and report.status == "passed" else "failed",
        stage_results=[*validation.stage_results, stage],
        probabilistic_sharpe_ratio=validation.probabilistic_sharpe_ratio,
        deflated_sharpe_ratio=validation.deflated_sharpe_ratio,
        pbo_score=validation.pbo_score,
        spa_pvalue=validation.spa_pvalue,
        in_sample_permutation_pvalue=validation.in_sample_permutation_pvalue,
        walk_forward_permutation_pvalue=validation.walk_forward_permutation_pvalue,
        in_sample_summary=dict(validation.in_sample_summary),
        selection_oos_summary=dict(validation.selection_oos_summary),
        holdout_summary=dict(validation.holdout_summary),
        cpcv_config=dict(validation.cpcv_config),
        purge_bars=validation.purge_bars,
        embargo_bars=validation.embargo_bars,
        n_blocks=validation.n_blocks,
        n_test_blocks=validation.n_test_blocks,
        min_backtest_length=validation.min_backtest_length,
        min_trade_count=validation.min_trade_count,
        validation_trial_count=validation.validation_trial_count,
        validation_gate_results=gate_results,
        validation_gate_details=list(validation.validation_gate_details),
        promotion_decision=report.promotion_decision if report.status != "passed" else validation.promotion_decision,
    )


def extract_phase4_governance_report(protocol: ValidationProtocol) -> dict[str, object]:
    for stage in reversed(protocol.stage_results):
        if stage.stage_name == "phase4_candidate_governance" and isinstance(stage.metrics, dict):
            return dict(stage.metrics)
    return {}


def _component_scores(metrics: MetricSnapshot) -> dict[str, float]:
    components = {
        "cpcv_p10": _clamp((float(metrics.cpcv_p10_sharpe) + 0.2) / 0.6),
        "pbo": _clamp((0.20 - float(metrics.pbo_score)) / 0.20),
        "dsr": _clamp((float(metrics.deflated_sharpe_ratio) - 0.50) / 0.50),
        "spa": _clamp((0.10 - float(metrics.spa_pvalue)) / 0.10),
        "bootstrap_survival": _clamp(metrics.bootstrap_survival),
        "plateau_width": _clamp(float(metrics.plateau_width) / 0.25),
        "oos_decay": _clamp(1.0 - (float(metrics.oos_decay) / 0.50)),
        "regime_coverage": _clamp(metrics.regime_coverage),
        "capacity_5x": _clamp(1.0 - (float(metrics.capacity_5x_edge_erosion) / 0.25)),
        "cross_symbol_portability": _clamp(metrics.cross_symbol_pass_rate),
    }
    if metrics.paper_forward_score is not None:
        components["paper_forward"] = _clamp(metrics.paper_forward_score)
    return {key: round(value, 6) for key, value in components.items()}


def _ablation_payload(ablations: list[AblationResult]) -> dict[str, dict[str, float]]:
    payload: dict[str, dict[str, float]] = {}
    for ablation in ablations:
        payload[str(ablation.layer)] = {
            "full_return": float(ablation.full_return),
            "ablated_return": float(ablation.ablated_return),
            "contribution": round(ablation.contribution, 6),
        }
    return payload


def _champion_challenger(inputs: CandidateGovernanceInputs) -> dict[str, object]:
    champion = inputs.champion
    if champion is None:
        return {"status": "no_champion", "required_return_delta": None, "weakened_hard_gates": []}
    weakened = [
        gate_name
        for gate_name in HARD_GATE_NAMES
        if champion.hard_gate_results.get(gate_name) is True and inputs.candidate_gate_results.get(gate_name) is False
    ]
    return_delta = float(inputs.metrics.net_post_cost_return) - float(champion.net_post_cost_return)
    if weakened:
        status = "hard_gate_weakened"
    elif return_delta <= 0.0:
        status = "challenger_loses"
    else:
        status = "challenger_wins"
    return {
        "status": status,
        "champion_artifact_id": champion.artifact_id,
        "champion_net_post_cost_return": float(champion.net_post_cost_return),
        "challenger_net_post_cost_return": float(inputs.metrics.net_post_cost_return),
        "return_delta": round(return_delta, 6),
        "weakened_hard_gates": weakened,
    }


def _rejection_reasons(
    *,
    inputs: CandidateGovernanceInputs,
    robustness_score: float,
    ablations: dict[str, dict[str, float]],
    champion_challenger: dict[str, object],
) -> list[str]:
    reasons: list[str] = []
    metrics = inputs.metrics
    if robustness_score < inputs.robustness_floor:
        reasons.append("robustness_score_below_floor")
    if metrics.cpcv_p10_sharpe <= 0.0:
        reasons.append("cpcv_p10_fail")
    if metrics.pbo_score >= 0.20:
        reasons.append("pbo_fail")
    if metrics.deflated_sharpe_ratio < 0.95:
        reasons.append("dsr_fail")
    if metrics.spa_pvalue >= 0.05:
        reasons.append("spa_fail")
    if metrics.bootstrap_survival < 0.60:
        reasons.append("bootstrap_survival_fail")
    if metrics.plateau_width < 0.10:
        reasons.append("plateau_width_fail")
    if metrics.oos_decay > 0.40:
        reasons.append("oos_decay_fail")
    if metrics.regime_coverage < 0.50:
        reasons.append("regime_specific_only")
    if metrics.capacity_5x_edge_erosion >= 0.25:
        reasons.append("capacity_fail")
    if metrics.cross_symbol_pass_rate < 0.67:
        reasons.append("cross_symbol_portability_fail")
    if metrics.paper_forward_score is not None and metrics.paper_forward_score < inputs.paper_forward_floor:
        reasons.append("paper_forward_fail")
    for layer in REQUIRED_ABLATION_LAYERS:
        if layer not in ablations:
            reasons.append(f"missing_ablation:{layer}")
    if champion_challenger.get("status") == "challenger_loses":
        reasons.append("champion_challenger_return_fail")
    for gate_name in champion_challenger.get("weakened_hard_gates", []):
        reasons.append(f"champion_challenger_hard_gate_weakened:{gate_name}")
    for code in inputs.failure_codes:
        text = str(code)
        if text == "feature_leakage" or text not in reasons and text in FAILURE_ROUTE_ACTIONS:
            reasons.append(text)
    return _unique(reasons)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _clamp(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(value)))
