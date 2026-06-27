from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
import site
import sys

from engine.config.models import (
    BacktestResult,
    DataSnapshot,
    PermutationTestResult,
    PhaseRecord,
    PromotionDecision,
    SharpeEvidence,
    SplitPack,
    StrategyGraph,
    ValidationProtocol,
    ValidationStageResult,
)
from engine.validation.cpcv import resolve_cpcv_config
from engine.validation.gate_spec import (
    ValidationGateSpec,
    evaluate_validation_gate_spec,
    gate_details_to_dicts,
    gate_results_to_dict,
)
from engine.validation.permutation import run_in_sample_permutation_test, run_walk_forward_permutation_test
from engine.validation.statistics import (
    compute_deflated_sharpe_ratio,
    compute_minimum_backtest_length,
    compute_observed_sharpe_ratio,
    compute_probabilistic_sharpe_ratio,
    compute_sample_kurtosis,
    compute_sample_skewness,
    estimate_deflated_sharpe_benchmark,
    estimate_sharpe_ratio_standard_error,
)


StrategyEvaluator = Callable[[DataSnapshot, StrategyGraph], BacktestResult]


def legacy_validation_protocol(decision: PromotionDecision | None = None) -> ValidationProtocol:
    final_decision = decision or PromotionDecision("accept", [])
    return ValidationProtocol(
        status="legacy_validation_missing",
        stage_results=[],
        validation_trial_count=1,
        validation_gate_results={},
        promotion_decision=final_decision,
    )


def serialize_validation_protocol(validation_protocol: ValidationProtocol) -> dict[str, object]:
    return asdict(validation_protocol)


def run_validation_protocol(
    split_pack: SplitPack,
    strategy: StrategyGraph,
    evaluate_strategy: StrategyEvaluator,
    trial_count: int,
    candidate_return_series: list[list[float]] | None = None,
    permutation_count: int = 1000,
    permutation_pvalue_threshold: float = 0.01,
    walk_forward_relaxed_pvalue_threshold: float = 0.05,
    walk_forward_relaxed_candle_limit: int = 30,
    deflated_sharpe_ratio_threshold: float = 0.95,
    gate_probabilistic_sharpe_ratio: bool = False,
    gate_min_backtest_length: bool = False,
    probabilistic_sharpe_ratio_threshold: float = 0.95,
    holdout_sharpe_floor: float = 1.0,
    holdout_drawdown_cap: float = -0.20,
    holdout_calmar_floor: float = 0.75,
    capacity_report: dict[str, object] | object | None = None,
    scenario_report: dict[str, object] | object | None = None,
    regime_report: dict[str, object] | object | None = None,
    validation_gate_spec: ValidationGateSpec | None = None,
    n_blocks: int = 10,
    n_test_blocks: int = 2,
    purge_bars: int | None = None,
    embargo_bars: int = 0,
    feature_lookback_bars: int = 0,
    barrier_horizon_bars: int = 0,
    holding_horizon_bars: int = 0,
    seed: int = 0,
) -> ValidationProtocol:
    effective_trial_count = max(1, int(trial_count))
    in_sample_result = evaluate_strategy(split_pack.in_sample.snapshot, strategy)
    walk_forward_result = evaluate_strategy(split_pack.selection_oos.snapshot, strategy)
    final_holdout_result = evaluate_strategy(split_pack.final_holdout.snapshot, strategy)
    model_return_series = [list(series) for series in (candidate_return_series or []) if len(series) >= 2]
    perf_matrix = _build_partitioned_performance_matrix(model_return_series, max_partitions=16)
    pbo_report = _compute_pbo_report(perf_matrix)
    spa_report = _compute_spa_report(model_return_series)

    sharpe_evidence = _build_sharpe_evidence(walk_forward_result, effective_trial_count)
    cpcv_config = resolve_cpcv_config(
        n_blocks=n_blocks,
        n_test_blocks=n_test_blocks,
        purge_bars=purge_bars,
        embargo_bars=embargo_bars,
        feature_lookback_bars=feature_lookback_bars,
        barrier_horizon_bars=barrier_horizon_bars,
        holding_horizon_bars=holding_horizon_bars,
    )
    in_sample_permutation = run_in_sample_permutation_test(
        snapshot=split_pack.in_sample.snapshot,
        strategy=strategy,
        evaluate_strategy=evaluate_strategy,
        permutation_count=permutation_count,
        seed=seed + 101,
    )
    walk_forward_permutation = run_walk_forward_permutation_test(
        snapshot=split_pack.selection_oos.snapshot,
        strategy=strategy,
        evaluate_strategy=evaluate_strategy,
        permutation_count=permutation_count,
        seed=seed + 202,
    )
    prd_gate_spec = validation_gate_spec or ValidationGateSpec(
        holdout_sharpe_floor=holdout_sharpe_floor,
        final_holdout_calmar_floor=holdout_calmar_floor,
        holdout_drawdown_cap=holdout_drawdown_cap,
    )
    prd_gate_results = evaluate_validation_gate_spec(
        final_holdout_result=final_holdout_result,
        selection_oos_result=walk_forward_result,
        capacity_report=capacity_report,
        scenario_report=scenario_report,
        regime_report=regime_report,
        spec=prd_gate_spec,
    )
    prd_gate_booleans = gate_results_to_dict(prd_gate_results)
    prd_gate_details = gate_details_to_dicts(prd_gate_results)

    relaxed_threshold_applied = len(split_pack.selection_oos.candles) < walk_forward_relaxed_candle_limit
    walk_forward_permutation_threshold = (
        walk_forward_relaxed_pvalue_threshold if relaxed_threshold_applied else permutation_pvalue_threshold
    )

    gate_results = {
        "minimum_backtest_length": (
            sharpe_evidence.sample_count >= sharpe_evidence.minimum_backtest_length
        ) if gate_min_backtest_length else True,
        "in_sample_excellence": in_sample_result.sharpe > 0.0,
        "in_sample_permutation": in_sample_permutation.pvalue <= permutation_pvalue_threshold,
        "deflated_sharpe_ratio": sharpe_evidence.deflated_sharpe_ratio >= deflated_sharpe_ratio_threshold,
        "pbo": True if not pbo_report["available"] else float(pbo_report["pbo"]) <= 0.20,
        "probabilistic_sharpe_ratio": (
            sharpe_evidence.probabilistic_sharpe_ratio >= probabilistic_sharpe_ratio_threshold
        ) if gate_probabilistic_sharpe_ratio else True,
        "spa": True if not spa_report["available"] else all(bool(value) for value in spa_report["rejections"]),
        "walk_forward_permutation": walk_forward_permutation.pvalue <= walk_forward_permutation_threshold,
        "final_holdout_excellence": prd_gate_booleans["final_holdout_sharpe"],
        "final_holdout_calmar": prd_gate_booleans["final_holdout_calmar"],
        "final_holdout_drawdown": prd_gate_booleans["final_holdout_drawdown"],
        "capacity_5x": prd_gate_booleans["capacity_5x"],
        "turnover_budget": prd_gate_booleans.get("turnover_budget", True),
        "min_oos_trades": prd_gate_booleans.get("min_oos_trades", True),
        "scenario_pass_matrix": prd_gate_booleans.get("scenario_pass_matrix", True),
        "regime_pass_matrix": prd_gate_booleans.get("regime_pass_matrix", True),
    }
    gate_enforcement = {
        "minimum_backtest_length": gate_min_backtest_length,
        "in_sample_excellence": True,
        "in_sample_permutation": not relaxed_threshold_applied,
        "deflated_sharpe_ratio": not relaxed_threshold_applied,
        "pbo": bool(pbo_report["enforced"]),
        "probabilistic_sharpe_ratio": gate_probabilistic_sharpe_ratio and not relaxed_threshold_applied,
        "spa": bool(spa_report["enforced"]),
        "walk_forward_permutation": not relaxed_threshold_applied,
        "final_holdout_excellence": True,
        "final_holdout_calmar": True,
        "final_holdout_drawdown": True,
        "capacity_5x": True,
        "turnover_budget": True,
        "min_oos_trades": True,
        "scenario_pass_matrix": True,
        "regime_pass_matrix": True,
    }

    required_gate_names = [
        "minimum_backtest_length",
        "in_sample_excellence",
        "in_sample_permutation",
        "deflated_sharpe_ratio",
        "pbo",
        "spa",
        "walk_forward_permutation",
        "final_holdout_excellence",
        "final_holdout_calmar",
        "final_holdout_drawdown",
        "capacity_5x",
        "turnover_budget",
        "min_oos_trades",
        "scenario_pass_matrix",
        "regime_pass_matrix",
    ]
    if not gate_min_backtest_length:
        required_gate_names.remove("minimum_backtest_length")
    if gate_probabilistic_sharpe_ratio:
        required_gate_names.append("probabilistic_sharpe_ratio")

    failed_gates = [
        gate_name
        for gate_name in required_gate_names
        if gate_enforcement.get(gate_name, False) and not gate_results.get(gate_name, False)
    ]
    soft_failed_gates = [
        gate_name
        for gate_name in required_gate_names
        if not gate_enforcement.get(gate_name, False) and not gate_results.get(gate_name, False)
    ]
    promotion_decision = PromotionDecision("reject", failed_gates) if failed_gates else PromotionDecision("accept", [])

    stage_results = [
        ValidationStageResult(
            stage_name="minimum_backtest_length",
            passed=gate_results["minimum_backtest_length"],
            reasons=[] if gate_results["minimum_backtest_length"] else ["minimum_backtest_length"],
            metrics={
                "sample_count": sharpe_evidence.sample_count,
                "minimum_backtest_length": sharpe_evidence.minimum_backtest_length,
                "enforced": gate_enforcement["minimum_backtest_length"],
            },
        ),
        ValidationStageResult(
            stage_name="in_sample_excellence",
            passed=gate_results["in_sample_excellence"],
            reasons=[] if gate_results["in_sample_excellence"] else ["in_sample_excellence"],
            metrics={
                "sharpe": in_sample_result.sharpe,
                "trade_count": in_sample_result.trade_count,
                "enforced": gate_enforcement["in_sample_excellence"],
            },
        ),
        _permutation_stage_result(
            in_sample_permutation,
            threshold=permutation_pvalue_threshold,
            extra_metrics={"enforced": gate_enforcement["in_sample_permutation"]},
        ),
        ValidationStageResult(
            stage_name="walk_forward",
            passed=_walk_forward_stage_passed(gate_results, gate_probabilistic_sharpe_ratio),
            reasons=_walk_forward_stage_reasons(gate_results, gate_probabilistic_sharpe_ratio),
            metrics={
                "sharpe": walk_forward_result.sharpe,
                "trade_count": walk_forward_result.trade_count,
                "probabilistic_sharpe_ratio": sharpe_evidence.probabilistic_sharpe_ratio,
                "deflated_sharpe_ratio": sharpe_evidence.deflated_sharpe_ratio,
                "benchmark_sharpe": sharpe_evidence.benchmark_sharpe,
                "enforced": gate_enforcement["deflated_sharpe_ratio"],
            },
        ),
        ValidationStageResult(
            stage_name="pbo",
            passed=gate_results["pbo"],
            reasons=[] if gate_results["pbo"] else ["pbo"],
            metrics={
                "pbo": pbo_report["pbo"],
                "available": pbo_report["available"],
                "enforced": gate_enforcement["pbo"],
                "partitions": pbo_report["partitions"],
                "model_count": pbo_report["model_count"],
            },
        ),
        ValidationStageResult(
            stage_name="spa",
            passed=gate_results["spa"],
            reasons=[] if gate_results["spa"] else ["spa"],
            metrics={
                "status": spa_report["status"],
                "available": spa_report["available"],
                "enforced": gate_enforcement["spa"],
                "pvalues": spa_report["pvalues"],
                "rejections": spa_report["rejections"],
                "block_size": spa_report["block_size"],
                "reps": spa_report["reps"],
            },
        ),
        _permutation_stage_result(
            walk_forward_permutation,
            threshold=walk_forward_permutation_threshold,
            extra_metrics={
                "relaxed_threshold_applied": relaxed_threshold_applied,
                "enforced": gate_enforcement["walk_forward_permutation"],
            },
        ),
        ValidationStageResult(
            stage_name="final_holdout",
            passed=(
                gate_results["final_holdout_excellence"]
                and gate_results["final_holdout_calmar"]
                and gate_results["final_holdout_drawdown"]
            ),
            reasons=[
                gate_name
                for gate_name in ["final_holdout_excellence", "final_holdout_calmar", "final_holdout_drawdown"]
                if not gate_results[gate_name]
            ],
            metrics={
                "sharpe": final_holdout_result.sharpe,
                "calmar": _gate_actual(prd_gate_details, "final_holdout_calmar"),
                "max_drawdown": final_holdout_result.max_drawdown,
                "sharpe_floor": holdout_sharpe_floor,
                "calmar_floor": holdout_calmar_floor,
                "drawdown_cap": holdout_drawdown_cap,
                "enforced": True,
            },
        ),
        ValidationStageResult(
            stage_name="prd_validation_gate_spec",
            passed=all(result["passed"] for result in prd_gate_details),
            reasons=[str(result["name"]) for result in prd_gate_details if not result["passed"]],
            metrics={
                "spec": {
                    "holdout_sharpe_floor": prd_gate_spec.holdout_sharpe_floor,
                    "final_holdout_calmar_floor": prd_gate_spec.final_holdout_calmar_floor,
                    "holdout_drawdown_cap": prd_gate_spec.holdout_drawdown_cap,
                    "capacity_5x_max_edge_degradation": prd_gate_spec.capacity_5x_max_edge_degradation,
                    "capacity_5x_min_fill_completion": prd_gate_spec.capacity_5x_min_fill_completion,
                    "turnover_budget_required": prd_gate_spec.turnover_budget_required,
                    "min_oos_trades_required": prd_gate_spec.min_oos_trades_required,
                    "min_oos_trades": prd_gate_spec.min_oos_trades,
                    "scenario_pass_matrix_required": prd_gate_spec.scenario_pass_matrix_required,
                    "regime_pass_matrix_required": prd_gate_spec.regime_pass_matrix_required,
                },
                "gate_results": prd_gate_details,
            },
        ),
    ]

    return ValidationProtocol(
        status="failed" if failed_gates else ("warning" if soft_failed_gates else "passed"),
        stage_results=stage_results,
        probabilistic_sharpe_ratio=sharpe_evidence.probabilistic_sharpe_ratio,
        deflated_sharpe_ratio=sharpe_evidence.deflated_sharpe_ratio,
        pbo_score=pbo_report["pbo"],
        spa_pvalue=max(spa_report["pvalues"], default=None),
        in_sample_permutation_pvalue=in_sample_permutation.pvalue,
        walk_forward_permutation_pvalue=walk_forward_permutation.pvalue,
        in_sample_summary=_build_split_summary(in_sample_result),
        selection_oos_summary=_build_split_summary(walk_forward_result),
        holdout_summary=_build_split_summary(final_holdout_result),
        cpcv_config=cpcv_config,
        purge_bars=int(cpcv_config["purge_bars"]),
        embargo_bars=int(cpcv_config["embargo_bars"]),
        n_blocks=int(cpcv_config["n_blocks"]),
        n_test_blocks=int(cpcv_config["n_test_blocks"]),
        min_backtest_length=sharpe_evidence.minimum_backtest_length,
        min_trade_count=min(
            in_sample_result.trade_count,
            walk_forward_result.trade_count,
            final_holdout_result.trade_count,
        ),
        validation_trial_count=effective_trial_count,
        validation_gate_results=gate_results,
        validation_gate_details=prd_gate_details,
        promotion_decision=promotion_decision,
    )


def validation_trial_count(phase_records: list[PhaseRecord]) -> int:
    return max(1, sum(max(1, int(record.permutation_count)) for record in phase_records))


def _gate_actual(gate_details: list[dict[str, object]], name: str) -> object:
    for detail in gate_details:
        if detail.get("name") == name:
            return detail.get("actual")
    return None


def _build_sharpe_evidence(result: BacktestResult, trial_count: int) -> SharpeEvidence:
    returns = _equity_return_series(result)
    observed_sharpe = compute_observed_sharpe_ratio(returns)
    standard_error = estimate_sharpe_ratio_standard_error(returns, observed_sharpe=observed_sharpe)
    benchmark_sharpe = estimate_deflated_sharpe_benchmark(standard_error, trial_count)
    return SharpeEvidence(
        observed_sharpe=observed_sharpe,
        benchmark_sharpe=benchmark_sharpe,
        probabilistic_sharpe_ratio=compute_probabilistic_sharpe_ratio(returns, benchmark_sharpe=0.0),
        deflated_sharpe_ratio=compute_deflated_sharpe_ratio(returns, trial_count=trial_count),
        skewness=compute_sample_skewness(returns),
        kurtosis=compute_sample_kurtosis(returns),
        sample_count=len(returns),
        trial_count=trial_count,
        minimum_backtest_length=compute_minimum_backtest_length(returns, target_psr=0.95),
    )


def _equity_return_series(result: BacktestResult) -> list[float]:
    """Extract period-over-period return series from the equity curve.

    IMPORTANT: This computes absolute PnL diffs, not percentage returns.
    This is correct *only* because the equity curve is cumulative PnL from 0.0
    with constant position sizing — absolute diffs are therefore proportional
    to percentage returns.  If position sizing ever becomes dynamic (e.g.
    equity-fraction sizing), this must switch to percentage returns:
        return (current - previous) / max(abs(previous), 1e-9)
    """
    if len(result.equity_curve) < 2:
        return [float(result.net_pnl)]
    returns = [
        float(current) - float(previous)
        for previous, current in zip(result.equity_curve, result.equity_curve[1:])
    ]
    return returns or [float(result.net_pnl)]


def _build_split_summary(result: BacktestResult) -> dict[str, float | int]:
    return {
        "trade_count": int(result.trade_count),
        "sharpe": float(result.sharpe),
        "net_pnl": float(result.net_pnl),
        "max_drawdown": float(result.max_drawdown),
    }


def _permutation_stage_result(
    permutation_result: PermutationTestResult,
    threshold: float,
    extra_metrics: dict[str, object] | None = None,
) -> ValidationStageResult:
    passed = permutation_result.pvalue <= threshold
    metrics: dict[str, object] = {
        "metric_name": permutation_result.metric_name,
        "observed_metric": permutation_result.observed_metric,
        "exceedance_count": permutation_result.exceedance_count,
        "permutation_count": permutation_result.permutation_count,
        "pvalue": permutation_result.pvalue,
        "threshold": threshold,
    }
    if extra_metrics:
        metrics.update(extra_metrics)
    return ValidationStageResult(
        stage_name=permutation_result.stage_name,
        passed=passed,
        reasons=[] if passed else [permutation_result.stage_name],
        metrics=metrics,
    )


def _walk_forward_stage_passed(gate_results: dict[str, bool], gate_probabilistic_sharpe_ratio: bool) -> bool:
    if gate_probabilistic_sharpe_ratio:
        return gate_results["deflated_sharpe_ratio"] and gate_results["probabilistic_sharpe_ratio"]
    return gate_results["deflated_sharpe_ratio"]


def _walk_forward_stage_reasons(gate_results: dict[str, bool], gate_probabilistic_sharpe_ratio: bool) -> list[str]:
    reasons: list[str] = []
    if not gate_results["deflated_sharpe_ratio"]:
        reasons.append("deflated_sharpe_ratio")
    if gate_probabilistic_sharpe_ratio and not gate_results["probabilistic_sharpe_ratio"]:
        reasons.append("probabilistic_sharpe_ratio")
    return reasons


def _aligned_model_return_series(*series_list: list[float]) -> list[list[float]]:
    non_empty_series = [list(series) for series in series_list if series]
    if len(non_empty_series) < 2:
        return []
    target_length = min(len(series) for series in non_empty_series)
    return [series[-target_length:] for series in non_empty_series]


def _build_partitioned_performance_matrix(
    model_return_series: list[list[float]],
    max_partitions: int,
) -> list[list[float]]:
    if len(model_return_series) < 2:
        return []
    sample_count = min(len(series) for series in model_return_series)
    partitions = min(int(max_partitions), sample_count)
    if partitions % 2 != 0:
        partitions -= 1
    if partitions < 2:
        return []

    matrix: list[list[float]] = []
    for partition_index in range(partitions):
        start = (partition_index * sample_count) // partitions
        end = ((partition_index + 1) * sample_count) // partitions
        if end <= start:
            return []
        matrix.append(
            [
                sum(series[start:end]) / (end - start)
                for series in model_return_series
            ]
        )
    return matrix


def _compute_pbo_report(perf_matrix: list[list[float]]) -> dict[str, object]:
    if not perf_matrix:
        return {
            "pbo": None,
            "available": False,
            "enforced": False,
            "partitions": 0,
            "model_count": 0,
        }
    _ensure_user_site_packages_available()
    from engine.validation.overfitting import compute_cscv_pbo

    report = compute_cscv_pbo(perf_matrix, S=len(perf_matrix))
    return {
        "pbo": report["pbo"],
        "available": True,
        "enforced": True,
        "partitions": len(perf_matrix),
        "model_count": len(perf_matrix[0]) if perf_matrix else 0,
    }


def _compute_spa_report(model_return_series: list[list[float]]) -> dict[str, object]:
    if not model_return_series:
        return {
            "status": "skipped",
            "available": False,
            "enforced": False,
            "pvalues": [],
            "rejections": [],
            "block_size": 0,
            "reps": 0,
        }
    _ensure_user_site_packages_available()
    from engine.validation.spa import run_spa_test

    benchmark_returns = [0.0] * len(model_return_series[0])
    block_size = max(2, len(benchmark_returns) // 4)
    report = run_spa_test(
        benchmark=benchmark_returns,
        models=model_return_series,
        block_size=block_size,
        reps=2000,
    )
    return {
        "status": report["status"],
        "available": report["available"],
        "enforced": report["enforced"],
        "pvalues": list(report["pvalues"]),
        "rejections": list(report["rejections"]),
        "block_size": block_size,
        "reps": 2000,
    }


def _ensure_user_site_packages_available() -> None:
    user_site = site.getusersitepackages()
    if user_site and user_site not in sys.path:
        site.addsitedir(user_site)
