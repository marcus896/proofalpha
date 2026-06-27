from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from engine.backtest.binance_usdm import BINANCE_USDM_V3_EXECUTION_MODEL_ID
from engine.config.models import BacktestResult, DataSnapshot, PromotionDecision, ValidationProtocol, ValidationStageResult


V3_FAILURE_CODES = {
    "format_error",
    "contract_error",
    "data_gap",
    "feature_leakage",
    "insufficient_trades",
    "negative_post_cost",
    "dd_fail",
    "liquidation_fail",
    "capacity_fail",
    "slippage_fragile",
    "pbo_fail",
    "dsr_fail",
    "cpcv_fail",
    "spa_fail",
    "holdout_fail",
    "duplicate_candidate",
    "symbol_specific_only",
    "regime_specific_only",
    "execution_rule_fail",
    "venue_model_mismatch",
}

V3_BASELINE_SET = (
    "no_trade",
    "always_long",
    "always_short",
    "simple_1h_momentum",
    "simple_1h_breakout",
    "simple_carry_funding",
)


@dataclass(frozen=True)
class V3PromotionInputs:
    snapshot: DataSnapshot
    validation_protocol: ValidationProtocol
    holdout_result: BacktestResult
    execution_model_id: str
    signal_timeframe: str = "1h"
    execution_timeframe: str = "15m"
    walk_forward_fold_count: int = 0
    position_episode_count: int = 0
    months_of_data: float = 0.0
    cpcv_metrics: dict[str, Any] = field(default_factory=dict)
    baseline_results: dict[str, BacktestResult] = field(default_factory=dict)
    capacity_report: dict[str, Any] = field(default_factory=dict)
    parameter_surface: dict[str, Any] = field(default_factory=dict)
    bootstrap_report: dict[str, Any] = field(default_factory=dict)
    regime_report: dict[str, Any] = field(default_factory=dict)
    reproducible: bool = True
    execution_rule_failures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class V3PromotionGateBundle:
    status: str
    decision: PromotionDecision
    primary_failure_code: str | None
    secondary_failure_codes: list[str]
    gate_results: dict[str, bool]
    metrics: dict[str, Any]
    baseline_set: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_v3_promotion_gates(inputs: V3PromotionInputs) -> V3PromotionGateBundle:
    validation = inputs.validation_protocol
    cpcv_median = _float_or_none(inputs.cpcv_metrics.get("median_sharpe"))
    cpcv_p10 = _float_or_none(inputs.cpcv_metrics.get("p10_sharpe"))
    capacity_5x_edge_erosion = _float_or_none(inputs.capacity_report.get("capacity_5x_edge_erosion"))
    capacity_5x_fill_completion = _float_or_none(inputs.capacity_report.get("capacity_5x_fill_completion"))
    plateau_ok = bool(inputs.parameter_surface.get("plateau_ok", False))
    bootstrap_ok = bool(inputs.bootstrap_report.get("passed", False))
    regime_ok = bool(inputs.regime_report.get("passed", False))
    baselines_ok = _baseline_set_present(inputs.baseline_results)

    gate_results = {
        "venue_model": (
            str(inputs.snapshot.venue).lower() == "binance"
            and inputs.execution_model_id == BINANCE_USDM_V3_EXECUTION_MODEL_ID
            and inputs.signal_timeframe == "1h"
            and inputs.execution_timeframe == "15m"
        ),
        "validation_method": (
            validation.cpcv_config.get("method") == "combinatorial_purged_cv"
            and int(validation.cpcv_config.get("n_blocks", 0)) in range(8, 17)
            and int(validation.cpcv_config.get("n_test_blocks", 0)) in {2, 3}
            and int(validation.cpcv_config.get("purge_bars", 0)) >= 0
            and int(validation.cpcv_config.get("embargo_bars", 0)) >= 0
        ),
        "data_length": inputs.months_of_data >= 18.0 or bool(inputs.snapshot.provenance.get("all_data_since_listing")),
        "walk_forward_folds": inputs.walk_forward_fold_count >= 8,
        "trade_or_episode_count": inputs.holdout_result.trade_count >= 120 or inputs.position_episode_count >= 30,
        "positive_post_cost": inputs.holdout_result.net_pnl > 0.0,
        "sharpe": inputs.holdout_result.sharpe >= 1.0,
        "calmar": _calmar(inputs.holdout_result) >= 0.75,
        "max_drawdown": inputs.holdout_result.max_drawdown >= -0.20,
        "turnover_budget": bool(inputs.capacity_report.get("turnover_within_budget", False)),
        "capacity_5x": (
            capacity_5x_edge_erosion is not None
            and capacity_5x_edge_erosion < 0.25
            and capacity_5x_fill_completion is not None
            and capacity_5x_fill_completion >= 0.95
        ),
        "dsr": validation.deflated_sharpe_ratio is not None and validation.deflated_sharpe_ratio >= 0.95,
        "pbo": validation.pbo_score is not None and validation.pbo_score < 0.20,
        "spa": validation.spa_pvalue is not None and validation.spa_pvalue < 0.05,
        "cpcv": cpcv_median is not None and cpcv_median > 0.75 and cpcv_p10 is not None and cpcv_p10 > 0.0,
        "no_liquidation": not inputs.holdout_result.liquidation_events,
        "execution_rules": not inputs.execution_rule_failures,
        "baseline_set": baselines_ok,
        "parameter_plateau": plateau_ok,
        "bootstrap_monte_carlo": bootstrap_ok,
        "regime_conditional": regime_ok,
        "reproducibility": inputs.reproducible,
    }
    failed_codes = _failure_codes(gate_results)
    status = "passed" if not failed_codes else "failed"
    return V3PromotionGateBundle(
        status=status,
        decision=PromotionDecision("accept", []) if status == "passed" else PromotionDecision("reject", failed_codes),
        primary_failure_code=failed_codes[0] if failed_codes else None,
        secondary_failure_codes=failed_codes[1:],
        gate_results=gate_results,
        metrics={
            "net_pnl": inputs.holdout_result.net_pnl,
            "sharpe": inputs.holdout_result.sharpe,
            "calmar": _calmar(inputs.holdout_result),
            "max_drawdown": inputs.holdout_result.max_drawdown,
            "dsr": validation.deflated_sharpe_ratio,
            "pbo": validation.pbo_score,
            "spa_pvalue": validation.spa_pvalue,
            "cpcv_median_sharpe": cpcv_median,
            "cpcv_p10_sharpe": cpcv_p10,
            "capacity_5x_edge_erosion": capacity_5x_edge_erosion,
            "capacity_5x_fill_completion": capacity_5x_fill_completion,
        },
        baseline_set=list(V3_BASELINE_SET),
    )


def append_v3_gate_stage(validation: ValidationProtocol, bundle: V3PromotionGateBundle) -> ValidationProtocol:
    stage = ValidationStageResult(
        stage_name="binance_usdm_v3_promotion",
        passed=bundle.status == "passed",
        reasons=[] if bundle.status == "passed" else [code for code in bundle.decision.reasons],
        metrics=bundle.to_dict(),
    )
    gate_results = dict(validation.validation_gate_results)
    gate_results.update({f"v3_{name}": passed for name, passed in bundle.gate_results.items()})
    return ValidationProtocol(
        status="passed" if bundle.status == "passed" and validation.status == "passed" else "failed",
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
        promotion_decision=bundle.decision if bundle.status != "passed" else validation.promotion_decision,
    )


def _failure_codes(gates: dict[str, bool]) -> list[str]:
    mapping = {
        "venue_model": "venue_model_mismatch",
        "validation_method": "cpcv_fail",
        "data_length": "data_gap",
        "walk_forward_folds": "insufficient_trades",
        "trade_or_episode_count": "insufficient_trades",
        "positive_post_cost": "negative_post_cost",
        "sharpe": "holdout_fail",
        "calmar": "holdout_fail",
        "max_drawdown": "dd_fail",
        "turnover_budget": "capacity_fail",
        "capacity_5x": "capacity_fail",
        "dsr": "dsr_fail",
        "pbo": "pbo_fail",
        "spa": "spa_fail",
        "cpcv": "cpcv_fail",
        "no_liquidation": "liquidation_fail",
        "execution_rules": "execution_rule_fail",
        "baseline_set": "holdout_fail",
        "parameter_plateau": "slippage_fragile",
        "bootstrap_monte_carlo": "holdout_fail",
        "regime_conditional": "regime_specific_only",
        "reproducibility": "contract_error",
    }
    codes: list[str] = []
    for gate_name, passed in gates.items():
        if passed:
            continue
        code = mapping[gate_name]
        if code not in codes:
            codes.append(code)
    return codes


def _baseline_set_present(results: dict[str, BacktestResult]) -> bool:
    return all(name in results for name in V3_BASELINE_SET)


def _calmar(result: BacktestResult) -> float:
    drawdown = abs(float(result.max_drawdown))
    if drawdown <= 1e-12:
        return 999.0 if result.net_pnl > 0.0 else 0.0
    return float(result.net_pnl) / drawdown


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
