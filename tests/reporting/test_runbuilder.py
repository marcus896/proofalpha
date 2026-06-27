import json
import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import (
    BacktestResult,
    BootstrapReport,
    CandidateEvaluation,
    DataSnapshot,
    OvernightRunReport,
    PhaseRecord,
    PromotionDecision,
    SnapshotQualityReport,
    StressMetrics,
    StrategyGraph,
    ValidationProtocol,
    VenueProfile,
)
from engine.data.schema import Candle
from engine.reporting.runcards import build_runcard
from engine.validation.scenarios import ScenarioEvaluationReport, ScenarioResult
from engine.validation.splits import build_split_pack


def _snapshot() -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0 + index,
            volume=1_000.0,
        )
        for index in range(100)
    ]
    return DataSnapshot(
        snapshot_id="snap-1",
        symbol="SOLUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=[0.0] * 100,
        open_interest=[100.0] * 100,
        liquidation_notional=[0.0] * 100,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        venue_profile=VenueProfile(
            venue="binance_usdm",
            maker_fee_bps=1.5,
            taker_fee_bps=4.5,
            fee_schedule_source="fixture-tier-vip0",
        ),
        quality_flags=[],
        quality_report=SnapshotQualityReport(
            report_id="snap-1:quality",
            snapshot_id="snap-1",
            quality_score=0.75,
            passed=False,
            issues=["missing_funding_rate_count=4"],
            metrics={
                "candle_count": 100,
                "funding_coverage_ratio": 0.96,
                "first_candle_ts": candles[0].timestamp.isoformat(),
                "last_candle_ts": candles[-1].timestamp.isoformat(),
            },
            source_checks={
                "build_version": "phase1_snapshot_builder_v1",
                "source_hash": "abc123",
            },
            generated_at="2024-01-05T00:00:00+00:00",
        ),
        provenance={
            "provider": "csv",
            "build_mode": "bundle_csv",
            "build_version": "phase1_snapshot_builder_v1",
            "source_hash": "abc123",
            "source_paths": {"candles": "candles.csv"},
        },
    )


def _result(sharpe: float, drawdown: float, net_pnl: float = 100.0) -> BacktestResult:
    return BacktestResult(
        trade_count=160,
        win_rate=0.47,
        gross_pnl=120.0,
        net_pnl=net_pnl,
        fee_spend=5.0,
        funding_spend=1.0,
        sharpe=sharpe,
        sortino=sharpe + 0.1,
        max_drawdown=drawdown,
        equity_curve=[0.0, 10.0, -5.0, 15.0],
        liquidation_events=[],
    )


class RunCardBuilderTests(unittest.TestCase):
    def test_build_runcard_includes_split_and_scenario_metrics(self) -> None:
        snapshot = _snapshot()
        snapshot = DataSnapshot(
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            venue=snapshot.venue,
            timeframe=snapshot.timeframe,
            candles=snapshot.candles,
            funding_rates=snapshot.funding_rates,
            open_interest=snapshot.open_interest,
            liquidation_notional=snapshot.liquidation_notional,
            maker_fee_bps=snapshot.maker_fee_bps,
            taker_fee_bps=snapshot.taker_fee_bps,
            venue_profile=snapshot.venue_profile,
            quality_flags=["missing_funding_rate_count=4", "orphan_open_interest_count=1"],
            quality_report=snapshot.quality_report,
            provenance=snapshot.provenance,
        )
        split_pack = build_split_pack(snapshot)
        report = OvernightRunReport(
            status="promoted",
            final_strategy=StrategyGraph(backbone="mom_squeeze"),
            phase_records=[
                PhaseRecord(
                    "phase-2",
                    "kama",
                    "accept",
                    True,
                    0.31,
                    {"aggressiveness": 2},
                    4,
                    [
                        {"parameters": {"aggressiveness": 2}, "oos_sharpe": 0.31, "decision": "accept"},
                        {"parameters": {"aggressiveness": 1}, "oos_sharpe": 0.28, "decision": "wash"},
                    ],
                ),
                PhaseRecord("phase-5", "time_stop", "accept", True, 0.40),
            ],
            holdout_decision=PromotionDecision("accept", []),
            final_evaluation=CandidateEvaluation(
                layer_name="time_stop",
                decision=PromotionDecision("accept", []),
                train_result=_result(0.85, -0.11, net_pnl=130.0),
                oos_result=_result(0.91, -0.12, net_pnl=145.0),
                bootstrap_report=BootstrapReport(
                    sample_count=8,
                    median_net_profit=100.0,
                    median_max_drawdown=-0.1,
                    worst_case_net_profit=-10.0,
                    worst_case_drawdown=-0.2,
                    pass_rate=0.75,
                    bootstrap_method="moving_block",
                    block_size=4,
                    bootstrap_microstructure_overlay={
                        "spread_multiplier": 4.0,
                        "depth_multiplier": 0.1,
                        "latency_multiplier": 5.0,
                    },
                    bootstrap_regime_summary={"sample_count": 8},
                ),
            ),
        )
        scenario_report = ScenarioEvaluationReport(
            total_scenarios=2,
            passed_scenarios=1,
            pass_rate=0.5,
            stress_liquidity_metrics={
                "stress_slippage_quantile": 0.22,
                "stress_tail_slippage": 0.31,
                "liquidity_stress_score": 0.71,
                "basis_stress_score": 0.34,
                "cascade_liquidation_count": 3,
            },
            regime_scenario_pass_matrix={
                "crash": {"venue_outage": False},
                "sideways": {"attention_burst": True},
            },
            results=[
                ScenarioResult(
                    "attention_burst",
                    0.6,
                    True,
                    [],
                    _result(0.7, -0.18),
                    {"name": "attention-burst", "liquidity_penalty_bps": 15.0},
                    StressMetrics(0.12, 0.18, 0.42, 0.25, 0),
                ),
                ScenarioResult(
                    "venue_outage",
                    0.9,
                    False,
                    ["drawdown_kill_switch"],
                    _result(0.3, -0.35),
                    {"name": "outage-shock", "latency_delta_bars": 3, "mark_premium_bps": 210.0},
                    StressMetrics(0.22, 0.31, 0.71, 0.34, 3),
                ),
            ],
        )

        runcard = build_runcard(
            run_id="run-3",
            snapshot=snapshot,
            split_pack=split_pack,
            report=report,
            selection_oos_result=_result(0.91, -0.12, net_pnl=145.0),
            scenario_report=scenario_report,
            seed=123,
            runtime_settings={
                "position_side": "short",
                "liquidation_mark_price_weight": 0.35,
                "slippage_model": "quoted_depth_v1",
                "slippage_bps": 6.0,
            },
            validation_protocol=ValidationProtocol(
                status="failed",
                validation_gate_results={"final_holdout_calmar": False},
                validation_gate_details=[
                    {
                        "name": "final_holdout_calmar",
                        "passed": False,
                        "actual": 0.5,
                        "threshold": 0.75,
                        "severity": "hard",
                        "reason": "final_holdout_calmar_below_floor",
                        "evidence_refs": ["holdout_summary"],
                    }
                ],
            ),
        )

        self.assertEqual(runcard.run_id, "run-3")
        self.assertEqual(runcard.split_id, "snap-1:60-20-20")
        self.assertEqual(runcard.decision.decision, "promoted")
        self.assertEqual(runcard.metrics["selection_oos_sharpe"], 0.91)
        self.assertEqual(runcard.metrics["sortino_ratio"], 1.01)
        self.assertEqual(runcard.metrics["total_trades"], 160)
        self.assertEqual(runcard.metrics["win_rate"], 0.47)
        self.assertGreaterEqual(runcard.metrics["selection_oos_drawdown_amount"], 0.0)
        self.assertEqual(runcard.metrics["scenario_pass_rate"], 0.5)
        self.assertEqual(runcard.metrics["stress_slippage_quantile"], 0.22)
        self.assertEqual(runcard.metrics["cascade_liquidation_count"], 3)
        self.assertEqual(runcard.metrics["accepted_layers"], 2)
        self.assertEqual(runcard.artifacts["selected_parameters_json"], '{"kama": {"aggressiveness": 2}}')
        self.assertEqual(
            runcard.artifacts["parameter_search_json"],
            '{"kama": {"permutation_count": 4, "search_summary": [{"decision": "accept", "oos_sharpe": 0.31, "parameters": {"aggressiveness": 2}}, {"decision": "wash", "oos_sharpe": 0.28, "parameters": {"aggressiveness": 1}}]}}',
        )
        self.assertEqual(runcard.artifacts["final_status"], "promoted")
        self.assertEqual(runcard.artifacts["snapshot_quality_status"], "dirty")
        self.assertEqual(runcard.artifacts["snapshot_quality_flag_count"], "2")
        self.assertEqual(
            runcard.artifacts["snapshot_quality_flags_json"],
            '["missing_funding_rate_count=4", "orphan_open_interest_count=1"]',
        )
        self.assertEqual(runcard.artifacts["snapshot_build_version"], "phase1_snapshot_builder_v1")
        self.assertEqual(runcard.artifacts["snapshot_source_hash"], "abc123")
        self.assertIn('"quality_score": 0.75', runcard.artifacts["snapshot_quality_report_json"])
        self.assertIn('"build_mode": "bundle_csv"', runcard.artifacts["snapshot_provenance_json"])
        self.assertEqual(
            runcard.artifacts["scenario_profiles_json"],
            '{"attention_burst": {"liquidity_penalty_bps": 15.0, "name": "attention-burst"}, "venue_outage": {"latency_delta_bars": 3, "mark_premium_bps": 210.0, "name": "outage-shock"}}',
        )
        self.assertEqual(
            runcard.artifacts["runtime_settings_json"],
            '{"liquidation_mark_price_weight": 0.35, "position_side": "short", "slippage_bps": 6.0, "slippage_model": "quoted_depth_v1"}',
        )
        effective_cost_model = json.loads(runcard.artifacts["effective_cost_model_json"])
        self.assertEqual(effective_cost_model["source"], "venue_profile")
        self.assertEqual(effective_cost_model["venue_source"], "fixture-tier-vip0")
        self.assertEqual(effective_cost_model["maker_fee_bps"], 1.5)
        self.assertEqual(effective_cost_model["taker_fee_bps"], 4.5)
        self.assertEqual(effective_cost_model["slippage_model"], "quoted_depth_v1")
        self.assertEqual(effective_cost_model["slippage_bps"], 6.0)
        self.assertIn('"regime_coverage"', runcard.artifacts["regime_summary_json"])
        self.assertIn('"regime_model"', runcard.artifacts["regime_summary_json"])
        self.assertIn('"regime_metadata"', runcard.artifacts["regime_summary_json"])
        self.assertIn('"bootstrap_regime_summary"', runcard.artifacts["bootstrap_summary_json"])
        self.assertIn('"bootstrap_microstructure_overlay"', runcard.artifacts["bootstrap_summary_json"])
        self.assertIn('"stress_tail_slippage"', runcard.artifacts["stress_liquidity_metrics_json"])
        self.assertIn('"venue_outage"', runcard.artifacts["regime_scenario_pass_matrix_json"])
        self.assertIn('"final_holdout_calmar"', runcard.artifacts["validation_gate_details_json"])
        self.assertIn('"final_holdout_calmar": false', runcard.artifacts["validation_gate_results_json"])


if __name__ == "__main__":
    unittest.main()
