from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from engine.portfolio.symbol_target import SymbolTarget


@dataclass(frozen=True)
class PortfolioRiskBudget:
    max_symbol_weight: float
    max_cluster_weight: float
    max_btc_beta: float
    max_eth_beta: float
    max_funding_cost_bps: float
    max_turnover_weight: float
    cluster_by_symbol: dict[str, str]
    beta_by_symbol: dict[str, dict[str, float]]
    turnover_weight: float = 0.0


@dataclass(frozen=True)
class PortfolioRiskBudgetResult:
    passed: bool
    rejections: list[str]
    metrics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_portfolio_risk_budget(
    targets: list[SymbolTarget] | tuple[SymbolTarget, ...],
    budget: PortfolioRiskBudget,
) -> PortfolioRiskBudgetResult:
    rejections: list[str] = []
    for field_name in (
        "max_symbol_weight",
        "max_cluster_weight",
        "max_btc_beta",
        "max_eth_beta",
        "max_funding_cost_bps",
        "max_turnover_weight",
        "turnover_weight",
    ):
        if not _is_finite(getattr(budget, field_name)):
            rejections.append(f"budget_non_finite:{field_name}")
    cluster_weight: dict[str, float] = {}
    btc_beta = 0.0
    eth_beta = 0.0
    for target in targets:
        invalid_fields = _target_non_finite_fields(target)
        rejections.extend(f"target_non_finite:{target.symbol}:{field_name}" for field_name in invalid_fields)
        if invalid_fields:
            continue
        target_weight = float(target.target_weight)
        gross_weight = abs(target_weight)
        if gross_weight > budget.max_symbol_weight:
            rejections.append(f"symbol_cap:{target.symbol}")
        if target.max_funding_cost_bps > budget.max_funding_cost_bps:
            rejections.append(f"funding_budget:{target.symbol}")
        cluster = budget.cluster_by_symbol.get(target.symbol, "unclustered")
        cluster_weight[cluster] = cluster_weight.get(cluster, 0.0) + gross_weight
        betas = budget.beta_by_symbol.get(target.symbol, {})
        btc_beta += abs(target_weight * float(betas.get("BTC", 0.0)))
        eth_beta += abs(target_weight * float(betas.get("ETH", 0.0)))
    for cluster, weight in sorted(cluster_weight.items()):
        if weight > budget.max_cluster_weight:
            rejections.append(f"cluster_cap:{cluster}")
    if btc_beta > budget.max_btc_beta:
        rejections.append("btc_beta_cap")
    if eth_beta > budget.max_eth_beta:
        rejections.append("eth_beta_cap")
    if budget.turnover_weight > budget.max_turnover_weight:
        rejections.append("turnover_budget")
    return PortfolioRiskBudgetResult(
        passed=not rejections,
        rejections=rejections,
        metrics={
            "cluster_weight": dict(sorted(cluster_weight.items())),
            "btc_beta": round(btc_beta, 12),
            "eth_beta": round(eth_beta, 12),
            "turnover_weight": budget.turnover_weight,
        },
    )


def _target_non_finite_fields(target: SymbolTarget) -> list[str]:
    fields = (
        "target_weight",
        "target_notional",
        "max_loss_budget",
        "max_slippage_bps",
        "max_funding_cost_bps",
    )
    return [field_name for field_name in fields if not _is_finite(getattr(target, field_name))]


def _is_finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
