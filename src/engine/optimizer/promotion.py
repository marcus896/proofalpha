from __future__ import annotations

from engine.config.models import BacktestResult, BootstrapReport, PromotionDecision


def _abs_drawdown(drawdown: float) -> float:
    return abs(drawdown)


def evaluate_candidate(
    incumbent_train: BacktestResult,
    incumbent_oos: BacktestResult,
    candidate_train: BacktestResult,
    candidate_oos: BacktestResult,
    bootstrap_report: BootstrapReport,
    min_oos_trades: int = 100,
    position_leverage: float = 1.0,
) -> PromotionDecision:
    reasons: list[str] = []

    if candidate_oos.trade_count < min_oos_trades:
        reasons.append("min_oos_trades")
    if _abs_drawdown(candidate_train.max_drawdown) > _abs_drawdown(incumbent_train.max_drawdown) * 1.05:
        reasons.append("train_drawdown_cap")
    if candidate_oos.sharpe < incumbent_oos.sharpe * 0.95:
        reasons.append("oos_sharpe_floor")
    # Scale drawdown kill-switch by leverage: a 10x strategy tolerates
    # up to -2.5 (= -0.25 * 10) before rejection, matching the
    # simulator's leverage-aware equity dynamics.
    effective_leverage = max(1.0, float(position_leverage))
    drawdown_kill_threshold = -0.25 * effective_leverage
    if bootstrap_report.worst_case_drawdown <= drawdown_kill_threshold:
        reasons.append("bootstrap_kill_switch")
    if candidate_train.liquidation_events or candidate_oos.liquidation_events:
        reasons.append("liquidation_events")

    if reasons:
        return PromotionDecision(decision="reject", reasons=reasons)

    incumbent_abs_dd = max(_abs_drawdown(incumbent_oos.max_drawdown), 1e-9)
    candidate_floor_abs_dd = _abs_drawdown(bootstrap_report.worst_case_drawdown)
    sharpe_gain = (candidate_oos.sharpe - incumbent_oos.sharpe) / max(abs(incumbent_oos.sharpe), 1e-9)
    floor_dd_improvement = (incumbent_abs_dd - candidate_floor_abs_dd) / incumbent_abs_dd
    median_profit_gain = (bootstrap_report.median_net_profit - incumbent_oos.net_pnl) / max(abs(incumbent_oos.net_pnl), 1e-9)

    if sharpe_gain < 0.02 and floor_dd_improvement < 0.10 and median_profit_gain < 0.05:
        return PromotionDecision(decision="wash", reasons=["insufficient_improvement"])

    return PromotionDecision(decision="accept", reasons=[])

