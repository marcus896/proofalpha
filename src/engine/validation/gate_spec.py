from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from engine.config.models import BacktestResult


@dataclass(frozen=True)
class ValidationGateResult:
    name: str
    passed: bool
    actual: float | int | bool | None
    threshold: float | int | bool | None
    severity: str
    reason: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True)
class ValidationGateSpec:
    holdout_sharpe_floor: float = 1.0
    final_holdout_calmar_floor: float = 0.75
    holdout_drawdown_cap: float = -0.20
    capacity_5x_max_edge_degradation: float = 0.25
    capacity_5x_min_fill_completion: float = 0.95
    turnover_budget_required: bool = True
    min_oos_trades_required: bool = True
    min_oos_trades: int = 120
    scenario_pass_matrix_required: bool = True
    regime_pass_matrix_required: bool = True

    @classmethod
    def prd_safe(cls) -> "ValidationGateSpec":
        return cls()


PRD_SAFE_VALIDATION_GATE_SPEC = ValidationGateSpec.prd_safe()


def compute_final_holdout_calmar(result: BacktestResult) -> float:
    drawdown = abs(float(result.max_drawdown))
    if drawdown <= 1e-12:
        return 999.0 if float(result.net_pnl) > 0.0 else 0.0
    return round(float(result.net_pnl) / drawdown, 12)


def evaluate_validation_gate_spec(
    *,
    final_holdout_result: BacktestResult,
    selection_oos_result: BacktestResult | None = None,
    capacity_report: dict[str, Any] | object | None = None,
    scenario_report: dict[str, Any] | object | None = None,
    regime_report: dict[str, Any] | object | None = None,
    spec: ValidationGateSpec | None = None,
) -> list[ValidationGateResult]:
    gate_spec = spec or PRD_SAFE_VALIDATION_GATE_SPEC
    calmar = compute_final_holdout_calmar(final_holdout_result)
    min_oos_actual = int(
        selection_oos_result.trade_count
        if selection_oos_result is not None
        else final_holdout_result.trade_count
    )
    capacity_edge = _capacity_5x_edge_degradation(capacity_report)
    capacity_fill = _capacity_5x_fill_completion(capacity_report)
    turnover_within_budget = _bool_field(capacity_report, "turnover_within_budget")
    scenario_matrix_passed = _scenario_matrix_passed(scenario_report)
    regime_passed = _report_passed(regime_report)

    results = [
        _gate(
            "final_holdout_sharpe",
            actual=float(final_holdout_result.sharpe),
            threshold=gate_spec.holdout_sharpe_floor,
            passed=float(final_holdout_result.sharpe) >= gate_spec.holdout_sharpe_floor,
            reason="final_holdout_sharpe_below_floor",
            evidence_refs=("holdout_summary",),
        ),
        _gate(
            "final_holdout_calmar",
            actual=calmar,
            threshold=gate_spec.final_holdout_calmar_floor,
            passed=calmar >= gate_spec.final_holdout_calmar_floor,
            reason="final_holdout_calmar_below_floor",
            evidence_refs=("holdout_summary",),
        ),
        _gate(
            "final_holdout_drawdown",
            actual=float(final_holdout_result.max_drawdown),
            threshold=gate_spec.holdout_drawdown_cap,
            passed=float(final_holdout_result.max_drawdown) >= gate_spec.holdout_drawdown_cap,
            reason="final_holdout_drawdown_breached_cap",
            evidence_refs=("holdout_summary",),
        ),
        _gate(
            "capacity_5x",
            actual=capacity_edge,
            threshold=gate_spec.capacity_5x_max_edge_degradation,
            passed=(
                capacity_edge is not None
                and capacity_edge < gate_spec.capacity_5x_max_edge_degradation
                and capacity_fill is not None
                and capacity_fill >= gate_spec.capacity_5x_min_fill_completion
            ),
            reason="capacity_5x_degradation_or_fill_failed",
            evidence_refs=("capacity_report",),
        ),
    ]
    if gate_spec.turnover_budget_required:
        results.append(
            _gate(
                "turnover_budget",
                actual=turnover_within_budget,
                threshold=True,
                passed=turnover_within_budget is True,
                reason="turnover_budget_exceeded" if turnover_within_budget is False else "turnover_budget_missing",
                evidence_refs=("capacity_report",),
            )
        )
    if gate_spec.min_oos_trades_required:
        results.append(
            _gate(
                "min_oos_trades",
                actual=min_oos_actual,
                threshold=gate_spec.min_oos_trades,
                passed=min_oos_actual >= gate_spec.min_oos_trades,
                reason="min_oos_trades_below_floor",
                evidence_refs=("selection_oos_summary", "holdout_summary"),
            )
        )
    if gate_spec.scenario_pass_matrix_required:
        results.append(
            _gate(
                "scenario_pass_matrix",
                actual=scenario_matrix_passed,
                threshold=True,
                passed=scenario_matrix_passed is True,
                reason="scenario_pass_matrix_failed",
                evidence_refs=("scenario_report", "regime_scenario_pass_matrix"),
            )
        )
    if gate_spec.regime_pass_matrix_required:
        results.append(
            _gate(
                "regime_pass_matrix",
                actual=regime_passed,
                threshold=True,
                passed=regime_passed is True,
                reason="regime_pass_matrix_failed",
                evidence_refs=("regime_report",),
            )
        )
    return results


def gate_results_to_dict(results: list[ValidationGateResult]) -> dict[str, bool]:
    return {result.name: result.passed for result in results}


def gate_details_to_dicts(results: list[ValidationGateResult]) -> list[dict[str, object]]:
    return [result.to_dict() for result in results]


def _gate(
    name: str,
    *,
    actual: float | int | bool | None,
    threshold: float | int | bool | None,
    passed: bool,
    reason: str,
    evidence_refs: tuple[str, ...],
) -> ValidationGateResult:
    return ValidationGateResult(
        name=name,
        passed=bool(passed),
        actual=actual,
        threshold=threshold,
        severity="hard",
        reason="" if passed else reason,
        evidence_refs=evidence_refs,
    )


def _capacity_5x_edge_degradation(report: dict[str, Any] | object | None) -> float | None:
    direct = _float_field(report, "capacity_5x_edge_erosion")
    if direct is not None:
        return direct
    direct = _float_field(report, "capacity_5x_edge_degradation")
    if direct is not None:
        return direct
    rows = _field(report, "rows")
    if isinstance(rows, list):
        for row in rows:
            if int(_float_field(row, "multiplier") or 0) == 5:
                return _float_field(row, "edge_erosion_ratio")
    return None


def _capacity_5x_fill_completion(report: dict[str, Any] | object | None) -> float | None:
    direct = _float_field(report, "capacity_5x_fill_completion")
    if direct is not None:
        return direct
    rows = _field(report, "rows")
    if isinstance(rows, list):
        for row in rows:
            if int(_float_field(row, "multiplier") or 0) == 5:
                return _float_field(row, "modeled_fill_completion_rate")
    return None


def _scenario_matrix_passed(report: dict[str, Any] | object | None) -> bool | None:
    explicit = _bool_field(report, "passed")
    if explicit is False:
        return False
    matrix = _field(report, "regime_scenario_pass_matrix")
    if not isinstance(matrix, dict) or not matrix:
        return explicit if explicit is not None else None
    for scenario_values in matrix.values():
        if isinstance(scenario_values, dict):
            if any(value is not True for value in scenario_values.values()):
                return False
        elif scenario_values is not True:
            return False
    return True


def _report_passed(report: dict[str, Any] | object | None) -> bool | None:
    explicit = _bool_field(report, "passed")
    if explicit is not None:
        return explicit
    matrix = _field(report, "regime_pass_matrix")
    if isinstance(matrix, dict) and matrix:
        return all(value is True for value in matrix.values())
    return None


def _bool_field(report: dict[str, Any] | object | None, name: str) -> bool | None:
    value = _field(report, name)
    return value if isinstance(value, bool) else None


def _float_field(report: dict[str, Any] | object | None, name: str) -> float | None:
    value = _field(report, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _field(report: dict[str, Any] | object | None, name: str) -> Any:
    if isinstance(report, dict):
        return report.get(name)
    if report is not None and hasattr(report, name):
        return getattr(report, name)
    if hasattr(report, "to_dict"):
        payload = report.to_dict()
        if isinstance(payload, dict):
            return payload.get(name)
    return None
