import unittest
from datetime import UTC, datetime, timedelta

from engine.config.models import (
    BacktestResult,
    BootstrapReport,
    DataSnapshot,
    CrisisWindow,
    PhaseRecord,
    PromotionDecision,
    RunCard,
    SnapshotWindow,
    SplitPack,
    StrategyGraph,
)
from engine.data.schema import Candle
from engine.reporting.dashboard import build_dashboard_payload


class DashboardPayloadTests(unittest.TestCase):
    def test_build_dashboard_payload_tolerates_malformed_artifact_fields(self) -> None:
        runcard = RunCard(
            run_id="run-malformed",
            strategy_hash="hash-malformed",
            phase="phase-5",
            split_id="split-x",
            seed=17,
            decision=PromotionDecision(decision="blocked", reasons=["artifact_corruption"]),
            metrics={},
            artifacts={
                "snapshot_quality_status": "dirty",
                "snapshot_quality_flag_count": "NaN",
                "snapshot_quality_flags_json": "{broken",
                "snapshot_quality_report_json": "{broken",
                "snapshot_provenance_json": "{broken",
                "runtime_settings_json": "{broken",
                "scenario_profiles_json": "{broken",
                "stress_liquidity_metrics_json": "{broken",
                "regime_scenario_pass_matrix_json": "{broken",
                "regime_summary_json": "{broken",
                "bootstrap_summary_json": "{broken",
                "validation_protocol_json": "{broken",
                "validation_gate_details_json": "{broken",
            },
        )

        payload = build_dashboard_payload(runcard=runcard)

        self.assertEqual(payload["snapshot_quality"]["status"], "dirty")
        self.assertEqual(payload["snapshot_quality"]["flag_count"], 0)
        self.assertEqual(payload["snapshot_quality"]["flags"], [])
        self.assertEqual(payload["snapshot_quality"]["report"], {})
        self.assertEqual(payload["snapshot_provenance"], {})
        self.assertEqual(payload["runtime_settings"], {})
        self.assertEqual(payload["scenario_profiles"], {})
        self.assertEqual(payload["stress_liquidity_metrics"], {})
        self.assertEqual(payload["regime_scenario_pass_matrix"], {})
        self.assertEqual(payload["regimes"], {})
        self.assertEqual(payload["bootstrap"], {})
        self.assertEqual(payload["validation_protocol"]["status"], "legacy_validation_missing")
        self.assertEqual(payload["validation_gate_details"], [])

    def test_build_dashboard_payload_includes_forecast_governance_fields(self) -> None:
        runcard = RunCard(
            run_id="run-forecast",
            strategy_hash="hash-forecast",
            phase="phase-13",
            split_id="split-forecast",
            seed=13,
            decision=PromotionDecision(decision="blocked", reasons=[]),
            metrics={},
            artifacts={
                "forecast_model_id": "timesfm-btc-v1",
                "forecast_ttl_status": "FRESH",
                "forecast_baseline_comparison_json": '{"edge": 0.03}',
                "forecast_decay_status": "FEATURE_ALLOWED",
                "forecast_forbidden_use_status": "blocked",
            },
        )

        payload = build_dashboard_payload(runcard=runcard)

        self.assertEqual(payload["forecast_governance"]["forecast_model_id"], "timesfm-btc-v1")
        self.assertEqual(payload["forecast_governance"]["ttl_status"], "FRESH")
        self.assertEqual(payload["forecast_governance"]["baseline_comparison"]["edge"], 0.03)
        self.assertEqual(payload["forecast_governance"]["decay_status"], "FEATURE_ALLOWED")
        self.assertEqual(payload["forecast_governance"]["forbidden_use_status"], "blocked")

    def test_build_dashboard_payload_includes_holdout_and_phase_summary(self) -> None:
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
            for index in range(8)
        ]
        snapshot = DataSnapshot(
            snapshot_id="snap-2",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * 8,
            open_interest=[100.0] * 8,
            liquidation_notional=[0.0] * 8,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
        )
        split_pack = SplitPack(
            in_sample=SnapshotWindow(snapshot=snapshot, start_index=0, end_index=4),
            selection_oos=SnapshotWindow(snapshot=snapshot, start_index=4, end_index=6),
            final_holdout=SnapshotWindow(snapshot=snapshot, start_index=6, end_index=8),
            bootstrap_source=SnapshotWindow(snapshot=snapshot, start_index=0, end_index=6),
            crisis_windows=[
                CrisisWindow(
                    name="crash-1",
                    snapshot_window=SnapshotWindow(snapshot=snapshot, start_index=5, end_index=7),
                    regime_label="crash",
                )
            ],
            regime_labels=["bull", "bull", "sideways", "bear", "crash", "crash", "liquidity_stress", "short_squeeze"],
            regime_coverage={"bull": 0.25, "sideways": 0.125, "bear": 0.125, "crash": 0.25, "liquidity_stress": 0.125, "short_squeeze": 0.125},
            crisis_window_coverage={"crash": 0.25},
        )
        runcard = RunCard(
            run_id="run-2",
            strategy_hash="hash-2",
            phase="phase-5",
            split_id="split-b",
            seed=99,
            decision=PromotionDecision(decision="blocked", reasons=["final_holdout_sharpe"]),
            metrics={"oos_sharpe": 0.93},
            artifacts={
                "dashboard": "dash.html",
                "snapshot_quality_status": "dirty",
                "snapshot_quality_flag_count": "2",
                "snapshot_quality_flags_json": '["missing_funding_rate_count=4", "orphan_open_interest_count=1"]',
                "snapshot_quality_report_json": '{"generated_at": "2024-01-05T00:00:00+00:00", "issues": ["missing_funding_rate_count=4"], "passed": false, "quality_score": 0.75, "report_id": "snap-2:quality", "snapshot_id": "snap-2", "metrics": {"funding_coverage_ratio": 0.96}}',
                "snapshot_provenance_json": '{"build_mode": "bundle_csv", "build_version": "phase1_snapshot_builder_v1", "provider": "csv", "source_hash": "abc123", "source_paths": {"candles": "candles.csv"}}',
                "snapshot_build_version": "phase1_snapshot_builder_v1",
                "snapshot_source_hash": "abc123",
                "scenario_profiles_json": '{"outage-shock": {"latency_delta_bars": 3, "mark_premium_bps": 210.0, "name": "outage-shock"}}',
                "stress_liquidity_metrics_json": '{"basis_stress_score": 0.34, "cascade_liquidation_count": 3, "liquidity_stress_score": 0.71, "stress_slippage_quantile": 0.22, "stress_tail_slippage": 0.31}',
                "regime_scenario_pass_matrix_json": '{"crash": {"venue_outage": false}, "sideways": {"attention_burst": true}}',
                "runtime_settings_json": '{"liquidation_mark_price_weight": 0.35, "position_side": "short"}',
                "validation_gate_details_json": '[{"name": "final_holdout_calmar", "passed": false, "actual": 0.5, "threshold": 0.75, "severity": "hard", "reason": "final_holdout_calmar_below_floor", "evidence_refs": ["holdout_summary"]}]',
            },
        )
        phase_records = [
            PhaseRecord(
                phase_name="phase-2",
                layer_name="kama",
                decision="accept",
                accepted=True,
                oos_sharpe=0.31,
                selected_parameters={"aggressiveness": 2},
                permutation_count=4,
                search_summary=[
                    {
                        "parameters": {"aggressiveness": 2},
                        "oos_sharpe": 0.31,
                        "decision": "accept",
                        "execution_pressure_summary": {
                            "fill_event_count": 2,
                            "partial_fill_event_count": 1,
                            "average_fill_ratio": 0.72,
                            "min_fill_ratio": 0.44,
                        },
                    },
                    {"parameters": {"aggressiveness": 1}, "oos_sharpe": 0.28, "decision": "wash"},
                ],
            ),
            PhaseRecord(phase_name="phase-5", layer_name="time_stop", decision="accept", accepted=True, oos_sharpe=0.40),
        ]

        payload = build_dashboard_payload(
            runcard=runcard,
            split_pack=split_pack,
            selection_oos_result=BacktestResult(
                trade_count=12,
                win_rate=0.5,
                gross_pnl=18.0,
                net_pnl=14.0,
                fee_spend=1.0,
                funding_spend=0.2,
                sharpe=0.9,
                sortino=1.1,
                max_drawdown=-0.15,
                equity_curve=[0.0, 6.0, 4.0, 9.0, 7.0, 14.0],
                execution_pressure_summary={
                    "fill_event_count": 2,
                    "partial_fill_event_count": 1,
                    "average_fill_ratio": 0.72,
                    "min_fill_ratio": 0.44,
                },
            ),
            bootstrap_report=BootstrapReport(
                sample_count=8,
                median_net_profit=10.0,
                median_max_drawdown=-0.12,
                worst_case_net_profit=-4.0,
                worst_case_drawdown=-0.18,
                pass_rate=0.75,
                bootstrap_method="stationary_block",
                block_size=3,
                bootstrap_microstructure_overlay={
                    "spread_multiplier": 4.0,
                    "depth_multiplier": 0.1,
                    "latency_multiplier": 5.0,
                },
                bootstrap_regime_summary={
                    "average_regime_coverage": {"bull": 0.4, "crash": 0.1},
                    "crisis_sample_frequency": {"crash": 0.5},
                    "dominant_regimes": ["bull", "sideways"],
                    "sample_count": 8,
                },
            ),
            strategy=StrategyGraph(backbone="mom_squeeze"),
            phase_records=phase_records,
            holdout_decision=PromotionDecision(decision="reject", reasons=["final_holdout_sharpe"]),
        )

        self.assertEqual(payload["run_id"], "run-2")
        self.assertEqual(payload["strategy"]["backbone"], "mom_squeeze")
        self.assertEqual(payload["holdout"]["decision"], "reject")
        self.assertEqual(payload["phases"][0]["layer_name"], "kama")
        self.assertEqual(payload["phases"][1]["decision"], "accept")
        self.assertEqual(payload["phases"][0]["selected_parameters"]["aggressiveness"], 2)
        self.assertEqual(payload["phases"][0]["permutation_count"], 4)
        self.assertEqual(payload["phases"][0]["search_summary"][0]["decision"], "accept")
        self.assertEqual(
            payload["phases"][0]["search_summary"][0]["execution_pressure_summary"]["partial_fill_event_count"],
            1,
        )
        self.assertEqual(payload["snapshot_quality"]["status"], "dirty")
        self.assertEqual(payload["snapshot_quality"]["flag_count"], 2)
        self.assertIn("missing_funding_rate_count=4", payload["snapshot_quality"]["flags"])
        self.assertEqual(payload["snapshot_quality"]["report"]["quality_score"], 0.75)
        self.assertEqual(payload["snapshot_provenance"]["build_version"], "phase1_snapshot_builder_v1")
        self.assertEqual(payload["snapshot_provenance"]["source_hash"], "abc123")
        self.assertEqual(payload["scenario_profiles"]["outage-shock"]["latency_delta_bars"], 3)
        self.assertEqual(payload["runtime_settings"]["position_side"], "short")
        self.assertEqual(payload["runtime_settings"]["liquidation_mark_price_weight"], 0.35)
        self.assertEqual(payload["selection_oos_execution_pressure"]["partial_fill_event_count"], 1)
        self.assertEqual(payload["selection_oos_execution_pressure"]["min_fill_ratio"], 0.44)
        self.assertEqual(payload["bootstrap"]["bootstrap_method"], "stationary_block")
        self.assertEqual(payload["bootstrap"]["block_size"], 3)
        self.assertEqual(payload["bootstrap"]["bootstrap_microstructure_overlay"]["spread_multiplier"], 4.0)
        self.assertEqual(payload["bootstrap"]["bootstrap_regime_summary"]["sample_count"], 8)
        self.assertEqual(payload["bootstrap"]["bootstrap_regime_summary"]["dominant_regimes"][0], "bull")
        self.assertEqual(payload["stress_liquidity_metrics"]["cascade_liquidation_count"], 3)
        self.assertEqual(payload["regime_scenario_pass_matrix"]["crash"]["venue_outage"], False)
        self.assertEqual(payload["regimes"]["crisis_windows"][0]["name"], "crash-1")
        self.assertEqual(payload["regimes"]["regime_coverage"]["bull"], 0.25)
        self.assertEqual(len(payload["timeseries"]), 6)
        self.assertEqual(payload["timeseries"][0]["equity"], 0.0)
        self.assertEqual(payload["timeseries"][0]["drawdown"], 0.0)
        self.assertAlmostEqual(payload["timeseries"][2]["drawdown"], -2.0 / 7.0)
        self.assertAlmostEqual(payload["timeseries"][4]["drawdown"], -2.0 / 10.0)
        self.assertIn("T", payload["timeseries"][0]["timestamp"])
        self.assertEqual(payload["validation_protocol"]["status"], "legacy_validation_missing")
        self.assertEqual(payload["validation_gate_details"][0]["name"], "final_holdout_calmar")
        self.assertFalse(payload["validation_gate_details"][0]["passed"])


if __name__ == "__main__":
    unittest.main()
