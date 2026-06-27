from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PreTradeCheckContext:
    artifact_approved: bool
    artifact_expired: bool
    symbol_allowed: bool
    paper_mode_allowed: bool
    market_fresh: bool
    book_gap_clean: bool
    reconciliation_clean: bool
    duplicate_client_order_id: bool
    rate_limit_ok: bool
    margin_ok: bool
    venue_rules_ok: bool
    spread_depth_ok: bool
    funding_ok: bool
    liquidation_ok: bool
    portfolio_risk_ok: bool


@dataclass(frozen=True)
class PreTradeCheckResult:
    passed: bool
    rejections: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_pretrade_checks(context: PreTradeCheckContext) -> PreTradeCheckResult:
    checks = {
        "artifact_not_approved": context.artifact_approved,
        "artifact_expired": not context.artifact_expired,
        "symbol_not_allowed": context.symbol_allowed,
        "paper_mode_not_allowed": context.paper_mode_allowed,
        "market_data_stale": context.market_fresh,
        "book_gap_detected": context.book_gap_clean,
        "reconciliation_dirty": context.reconciliation_clean,
        "duplicate_client_order_id": not context.duplicate_client_order_id,
        "rate_limit_block": context.rate_limit_ok,
        "margin_leverage_block": context.margin_ok,
        "venue_rule_block": context.venue_rules_ok,
        "spread_depth_block": context.spread_depth_ok,
        "funding_block": context.funding_ok,
        "liquidation_block": context.liquidation_ok,
        "portfolio_risk_block": context.portfolio_risk_ok,
    }
    rejections = [reason for reason, passed in checks.items() if not passed]
    return PreTradeCheckResult(passed=not rejections, rejections=rejections)
