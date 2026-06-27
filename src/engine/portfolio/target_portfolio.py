from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable

from engine.portfolio.allocator import PortfolioAllocation
from engine.portfolio.symbol_target import SymbolTarget


@dataclass(frozen=True)
class TargetPortfolio:
    target_portfolio_id: str
    universe_id: str
    artifact_set_id: str
    capital_base: float
    gross_exposure_target: float
    net_exposure_target: float
    btc_beta_target: float
    eth_beta_target: float
    max_symbol_weight: float
    max_cluster_weight: float
    symbol_targets: tuple[SymbolTarget, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["symbol_targets"] = [target.to_dict() for target in self.symbol_targets]
        return payload


def build_target_portfolio(
    *,
    universe_id: str,
    artifact_set_id: str,
    capital_base: float,
    allocations: Iterable[PortfolioAllocation],
    btc_beta_target: float = 0.0,
    eth_beta_target: float = 0.0,
    max_symbol_weight: float = 1.0,
    max_cluster_weight: float = 1.0,
    max_slippage_bps: float = 25.0,
    max_funding_cost_bps: float = 10.0,
    rebalance_reason: str = "scheduled",
) -> TargetPortfolio:
    if not math.isfinite(float(capital_base)):
        raise ValueError("capital_base_must_be_finite")
    if capital_base <= 0:
        raise ValueError("capital_base_must_be_positive")
    for field_name, value in (
        ("btc_beta_target", btc_beta_target),
        ("eth_beta_target", eth_beta_target),
        ("max_symbol_weight", max_symbol_weight),
        ("max_cluster_weight", max_cluster_weight),
        ("max_slippage_bps", max_slippage_bps),
        ("max_funding_cost_bps", max_funding_cost_bps),
    ):
        if not math.isfinite(float(value)):
            raise ValueError(f"{field_name}_must_be_finite")
    targets: list[SymbolTarget] = []
    for allocation in allocations:
        if not math.isfinite(float(allocation.notional)):
            raise ValueError("allocation_notional_must_be_finite")
        if allocation.notional < 0:
            raise ValueError("allocation_notional_must_be_non_negative")
        if not math.isfinite(float(allocation.max_drawdown)):
            raise ValueError("allocation_max_drawdown_must_be_finite")
        if allocation.max_drawdown < 0:
            raise ValueError("allocation_max_drawdown_must_be_non_negative")
        symbols = tuple(allocation.symbols)
        per_symbol_notional = float(allocation.notional) / max(1, len(symbols))
        for symbol in symbols:
            targets.append(
                SymbolTarget(
                    symbol=symbol,
                    artifact_id=allocation.artifact_id,
                    role=allocation.portfolio_role,
                    target_weight=round(per_symbol_notional / capital_base, 12),
                    target_notional=round(per_symbol_notional, 8),
                    max_loss_budget=round(per_symbol_notional * float(allocation.max_drawdown), 8),
                    max_slippage_bps=max_slippage_bps,
                    max_funding_cost_bps=max_funding_cost_bps,
                    rebalance_reason=rebalance_reason,
                )
            )
    gross = round(sum(abs(target.target_weight) for target in targets), 12)
    net = round(sum(target.target_weight for target in targets), 12)
    payload = {
        "universe_id": universe_id,
        "artifact_set_id": artifact_set_id,
        "capital_base": capital_base,
        "gross_exposure_target": gross,
        "net_exposure_target": net,
        "btc_beta_target": btc_beta_target,
        "eth_beta_target": eth_beta_target,
        "max_symbol_weight": max_symbol_weight,
        "max_cluster_weight": max_cluster_weight,
        "symbol_targets": [target.to_dict() for target in targets],
    }
    return TargetPortfolio(
        target_portfolio_id="target-portfolio-" + _stable_hash(payload)[:16],
        universe_id=universe_id,
        artifact_set_id=artifact_set_id,
        capital_base=float(capital_base),
        gross_exposure_target=gross,
        net_exposure_target=net,
        btc_beta_target=float(btc_beta_target),
        eth_beta_target=float(eth_beta_target),
        max_symbol_weight=float(max_symbol_weight),
        max_cluster_weight=float(max_cluster_weight),
        symbol_targets=tuple(targets),
    )


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
