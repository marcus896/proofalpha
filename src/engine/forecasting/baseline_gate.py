from __future__ import annotations

from dataclasses import asdict, dataclass, field

from engine.config.models import PromotionDecision, ValidationProtocol, ValidationStageResult


REQUIRED_FORECAST_BASELINES = ("no_forecast", "momentum", "breakout", "carry_funding")


@dataclass(frozen=True)
class ForecastComparisonResult:
    variant_id: str
    net_post_cost_return: float
    hard_gate_results: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ForecastBaselineGateReport:
    forecast_variant_id: str
    status: str
    best_baseline_id: str | None
    best_baseline_return: float | None
    forecast_return: float
    net_post_cost_improvement: float | None
    baseline_returns: dict[str, float]
    hard_gate_regressions: list[str]
    research_only: bool
    promotion_decision: PromotionDecision

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["promotion_decision"] = asdict(self.promotion_decision)
        return payload


def compare_forecast_to_baselines(
    *,
    forecast: ForecastComparisonResult,
    baselines: dict[str, ForecastComparisonResult],
    reference_hard_gate_results: dict[str, bool] | None = None,
) -> ForecastBaselineGateReport:
    reasons: list[str] = []
    baseline_returns = {
        baseline_id: float(result.net_post_cost_return)
        for baseline_id, result in baselines.items()
        if baseline_id in REQUIRED_FORECAST_BASELINES
    }
    for baseline_id in REQUIRED_FORECAST_BASELINES:
        if baseline_id not in baselines:
            reasons.append(f"missing_required_baseline:{baseline_id}")

    forecast_return = float(forecast.net_post_cost_return)
    best_baseline_id = None
    best_baseline_return = None
    if baseline_returns:
        best_baseline_id, best_baseline_return = max(baseline_returns.items(), key=lambda item: item[1])
        losing_baselines = [
            baseline_id
            for baseline_id, baseline_return in baseline_returns.items()
            if forecast_return <= baseline_return
        ]
        if losing_baselines:
            reasons.append("forecast_does_not_beat_baselines")
            reasons.extend(f"baseline_loss:{baseline_id}" for baseline_id in sorted(losing_baselines))

    hard_gate_regressions = _hard_gate_regressions(
        forecast.hard_gate_results,
        reference_hard_gate_results or _baseline_hard_gate_reference(baselines),
    )
    reasons.extend(f"forecast_hard_gate_weakened:{gate}" for gate in hard_gate_regressions)
    reasons = _unique(reasons)
    status = "passed" if not reasons else "failed"
    improvement = None
    if best_baseline_return is not None:
        improvement = round(forecast_return - best_baseline_return, 12)
    return ForecastBaselineGateReport(
        forecast_variant_id=forecast.variant_id,
        status=status,
        best_baseline_id=best_baseline_id,
        best_baseline_return=best_baseline_return,
        forecast_return=forecast_return,
        net_post_cost_improvement=improvement,
        baseline_returns=baseline_returns,
        hard_gate_regressions=hard_gate_regressions,
        research_only=True,
        promotion_decision=PromotionDecision("accept", []) if status == "passed" else PromotionDecision("reject", reasons),
    )


def append_forecast_baseline_stage(
    validation: ValidationProtocol,
    report: ForecastBaselineGateReport,
) -> ValidationProtocol:
    stage = ValidationStageResult(
        stage_name="phase5_forecast_baseline_gate",
        passed=report.status == "passed",
        reasons=list(report.promotion_decision.reasons),
        metrics=report.to_dict(),
    )
    gate_results = dict(validation.validation_gate_results)
    gate_results["phase5_forecast_baseline_gate"] = report.status == "passed"
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


def _baseline_hard_gate_reference(
    baselines: dict[str, ForecastComparisonResult],
) -> dict[str, bool]:
    reference: dict[str, bool] = {}
    for result in baselines.values():
        for gate_name, passed in result.hard_gate_results.items():
            reference[gate_name] = reference.get(gate_name, False) or bool(passed)
    return reference


def _hard_gate_regressions(
    candidate_gates: dict[str, bool],
    reference_gates: dict[str, bool],
) -> list[str]:
    return sorted(
        gate_name
        for gate_name, reference_passed in reference_gates.items()
        if reference_passed is True and candidate_gates.get(gate_name) is False
    )


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
