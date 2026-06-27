from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from engine.backtest.binance_usdm import BINANCE_USDM_V3_EXECUTION_MODEL_ID
from engine.config.models import BacktestResult, DataSnapshot, PromotionDecision, ValidationProtocol
from engine.data.schema import Candle
from engine.validation.cpcv import resolve_cpcv_config
from engine.validation.promotion import (
    V3_BASELINE_SET,
    V3PromotionInputs,
    append_v3_gate_stage,
    evaluate_v3_promotion_gates,
)


class Phase3PromotionGateTests(unittest.TestCase):
    def test_v3_promotion_passes_only_with_full_gate_bundle(self) -> None:
        bundle = evaluate_v3_promotion_gates(_promotion_inputs())

        self.assertEqual(bundle.status, "passed")
        self.assertEqual(bundle.decision.decision, "accept")
        self.assertTrue(all(bundle.gate_results.values()))
        self.assertEqual(bundle.baseline_set, list(V3_BASELINE_SET))

    def test_v3_promotion_rejects_5m_execution_and_records_primary_failure(self) -> None:
        inputs = _promotion_inputs(execution_timeframe="5m")

        bundle = evaluate_v3_promotion_gates(inputs)

        self.assertEqual(bundle.status, "failed")
        self.assertEqual(bundle.primary_failure_code, "venue_model_mismatch")
        self.assertIn("venue_model_mismatch", bundle.decision.reasons)

    def test_v3_promotion_rejects_unpurged_or_naive_validation_method(self) -> None:
        protocol = _validation()
        protocol = ValidationProtocol(
            status=protocol.status,
            deflated_sharpe_ratio=protocol.deflated_sharpe_ratio,
            pbo_score=protocol.pbo_score,
            spa_pvalue=protocol.spa_pvalue,
            cpcv_config={"method": "ordinary_kfold", "n_blocks": 5, "n_test_blocks": 1, "purge_bars": 0, "embargo_bars": 0},
            validation_gate_results=protocol.validation_gate_results,
            promotion_decision=protocol.promotion_decision,
        )
        bundle = evaluate_v3_promotion_gates(_promotion_inputs(validation_protocol=protocol))

        self.assertEqual(bundle.status, "failed")
        self.assertIn("cpcv_fail", bundle.decision.reasons)

    def test_v3_promotion_rejects_missing_stats_capacity_plateau_and_liquidation(self) -> None:
        bad_result = _result(liquidation_events=["liq"])
        inputs = _promotion_inputs(
            holdout_result=bad_result,
            cpcv_metrics={"median_sharpe": 0.3, "p10_sharpe": -0.1},
            capacity_report={"turnover_within_budget": True, "capacity_5x_edge_erosion": 0.40, "capacity_5x_fill_completion": 0.90},
            parameter_surface={"plateau_ok": False},
            validation_protocol=_validation(dsr=0.50, pbo=0.30, spa=0.20),
        )

        bundle = evaluate_v3_promotion_gates(inputs)

        self.assertEqual(bundle.status, "failed")
        self.assertIn("liquidation_fail", bundle.decision.reasons)
        self.assertIn("capacity_fail", bundle.decision.reasons)
        self.assertIn("dsr_fail", bundle.decision.reasons)
        self.assertIn("pbo_fail", bundle.decision.reasons)
        self.assertIn("spa_fail", bundle.decision.reasons)
        self.assertIn("cpcv_fail", bundle.decision.reasons)
        self.assertIn("slippage_fragile", bundle.decision.reasons)

    def test_append_v3_gate_stage_blocks_validation_protocol(self) -> None:
        bundle = evaluate_v3_promotion_gates(_promotion_inputs(execution_timeframe="1m"))
        protocol = append_v3_gate_stage(_validation(), bundle)

        self.assertEqual(protocol.status, "failed")
        self.assertEqual(protocol.promotion_decision.decision, "reject")
        self.assertFalse(protocol.validation_gate_results["v3_venue_model"])
        self.assertEqual(protocol.stage_results[-1].stage_name, "binance_usdm_v3_promotion")


def _promotion_inputs(**overrides) -> V3PromotionInputs:
    kwargs = {
        "snapshot": _snapshot(),
        "validation_protocol": _validation(),
        "holdout_result": _result(),
        "execution_model_id": BINANCE_USDM_V3_EXECUTION_MODEL_ID,
        "signal_timeframe": "1h",
        "execution_timeframe": "15m",
        "walk_forward_fold_count": 8,
        "position_episode_count": 30,
        "months_of_data": 18.0,
        "cpcv_metrics": {"median_sharpe": 1.10, "p10_sharpe": 0.20},
        "baseline_results": {name: _result(net_pnl=0.0, sharpe=0.0) for name in V3_BASELINE_SET},
        "capacity_report": {"turnover_within_budget": True, "capacity_5x_edge_erosion": 0.10, "capacity_5x_fill_completion": 0.98},
        "parameter_surface": {"plateau_ok": True},
        "bootstrap_report": {"passed": True},
        "regime_report": {"passed": True},
        "reproducible": True,
        "execution_rule_failures": [],
    }
    kwargs.update(overrides)
    return V3PromotionInputs(**kwargs)


def _validation(*, dsr: float = 0.96, pbo: float = 0.10, spa: float = 0.01) -> ValidationProtocol:
    return ValidationProtocol(
        status="passed",
        deflated_sharpe_ratio=dsr,
        pbo_score=pbo,
        spa_pvalue=spa,
        cpcv_config=resolve_cpcv_config(n_blocks=12, n_test_blocks=2, purge_bars=4, embargo_bars=2),
        validation_gate_results={"deflated_sharpe_ratio": True, "pbo": True, "spa": True},
        promotion_decision=PromotionDecision("accept", []),
    )


def _result(*, net_pnl: float = 1.0, sharpe: float = 1.25, liquidation_events: list[str] | None = None) -> BacktestResult:
    return BacktestResult(
        trade_count=120,
        win_rate=0.55,
        gross_pnl=net_pnl + 0.2,
        net_pnl=net_pnl,
        fee_spend=0.1,
        funding_spend=0.1,
        sharpe=sharpe,
        sortino=sharpe,
        max_drawdown=-0.10,
        equity_curve=[0.0, 0.2, 0.5, net_pnl],
        liquidation_events=list(liquidation_events or []),
    )


def _snapshot() -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(timestamp=start + timedelta(hours=index), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0)
        for index in range(100)
    ]
    return DataSnapshot(
        snapshot_id="phase3-promotion",
        symbol="BTCUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=[0.0] * len(candles),
        open_interest=[100.0] * len(candles),
        liquidation_notional=[0.0] * len(candles),
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        quality_flags=[],
    )


if __name__ == "__main__":
    unittest.main()
