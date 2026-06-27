import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.execution.paper import (
    PaperMarketSnapshot,
    PaperOrderIntent,
    approximate_queue_fill,
    calculate_side_aware_slippage,
    record_paper_execution_result,
    run_paper_executor_fixture,
)
from engine.strategy.artifacts import (
    build_strategy_artifact,
    evaluate_rollout_transition,
    load_strategy_artifact,
    validate_strategy_artifact,
    write_strategy_artifact,
)


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _valid_artifact_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "strategy_id": "strategy-phase6",
        "family": "momentum",
        "variant_id": "variant-phase6",
        "venue": "binance_usdm",
        "signal_timeframe": "1h",
        "execution_timeframe": "15m",
        "symbol_scope": ["BTCUSDT"],
        "regime_scope": ["trend", "neutral"],
        "feature_version": "feature-v1",
        "data_snapshot_ids": ["snapshot-v1"],
        "execution_model": "binance_usdm_v3",
        "cost_model": "cost-v1",
        "scenario_pack": "scenario-v1",
        "parameters": {"lookback": 48},
        "risk_limits": {"max_notional": 1000.0, "max_drawdown": 0.2},
        "order_policy": {"order_type": "limit", "time_in_force": "GTX", "post_only": True},
        "validation_report_id": "validation-v1",
        "code_sha": "code-sha",
        "rollout_stage": "backtest",
        "promotion_approved": True,
        "validation_status": "passed",
        "created_at_utc": "2026-04-26T00:00:00Z",
    }
    payload.update(overrides)
    return payload


class Phase6ArtifactContractTests(unittest.TestCase):
    def test_immutable_artifact_checksum_detects_mutation_and_blocks_research_config(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload())
        valid = validate_strategy_artifact(artifact)

        mutated = dict(artifact)
        mutated["parameters"] = {"lookback": 96}
        mutated_validation = validate_strategy_artifact(mutated)

        research_config = {
            "run_id": "mutable-research-config",
            "snapshot": {"symbol": "BTCUSDT", "venue": "binance", "timeframe": "1h"},
            "incumbent": {"backbone": "mom_squeeze"},
        }
        research_validation = validate_strategy_artifact(research_config)

        self.assertTrue(valid.passed)
        self.assertEqual(valid.artifact_sha256, artifact["artifact_sha256"])
        self.assertFalse(mutated_validation.passed)
        self.assertIn("artifact_checksum_mismatch", mutated_validation.reasons)
        self.assertFalse(research_validation.passed)
        self.assertIn("not_strategy_artifact", research_validation.reasons)

    def test_artifact_metadata_preserves_validation_gate_details(self) -> None:
        artifact = build_strategy_artifact(
            _valid_artifact_payload(
                validation_gate_details=[
                    {
                        "name": "final_holdout_calmar",
                        "passed": True,
                        "actual": 1.2,
                        "threshold": 0.75,
                    }
                ]
            )
        )

        self.assertEqual(artifact["validation_gate_details"][0]["name"], "final_holdout_calmar")
        self.assertTrue(validate_strategy_artifact(artifact).passed)

    def test_artifact_validation_rejects_unapproved_wrong_venue_wrong_timeframe_and_stale_validation(self) -> None:
        rejected = build_strategy_artifact(
            _valid_artifact_payload(
                promotion_approved=False,
                venue="bybit",
                signal_timeframe="5m",
                execution_timeframe="1m",
                validation_status="stale",
            )
        )

        validation = validate_strategy_artifact(rejected)

        self.assertFalse(validation.passed)
        self.assertIn("artifact_not_approved", validation.reasons)
        self.assertIn("venue_not_allowed", validation.reasons)
        self.assertIn("signal_timeframe_not_allowed", validation.reasons)
        self.assertIn("execution_timeframe_not_allowed", validation.reasons)
        self.assertIn("validation_not_current", validation.reasons)

    def test_rollout_ladder_blocks_stage_skips_and_reports_missing_gate_evidence(self) -> None:
        blocked_skip = evaluate_rollout_transition(
            from_stage="backtest",
            to_stage="shadow_live",
            gate_evidence={"full_validation_pass": True},
        )
        paper_ok = evaluate_rollout_transition(
            from_stage="backtest",
            to_stage="paper",
            gate_evidence={"full_validation_pass": True},
        )
        shadow_blocked = evaluate_rollout_transition(
            from_stage="paper",
            to_stage="shadow_live",
            gate_evidence={"paper_stability_pass": True},
        )

        self.assertFalse(blocked_skip.allowed)
        self.assertIn("rollout_stage_skip_not_allowed", blocked_skip.reasons)
        self.assertTrue(paper_ok.allowed)
        self.assertFalse(shadow_blocked.allowed)
        self.assertIn("missing_gate_evidence:telemetry_complete", shadow_blocked.reasons)


class Phase6PaperExecutorTests(unittest.TestCase):
    def test_slippage_formula_is_side_aware(self) -> None:
        buy = calculate_side_aware_slippage(side="BUY", expected_price=100.0, live_vwap_price=101.0)
        sell = calculate_side_aware_slippage(side="SELL", expected_price=100.0, live_vwap_price=99.0)
        favorable_sell = calculate_side_aware_slippage(side="SELL", expected_price=100.0, live_vwap_price=101.0)

        self.assertEqual(buy["slip_px"], 1.0)
        self.assertEqual(buy["slip_bps"], 100.0)
        self.assertEqual(sell["slip_px"], 1.0)
        self.assertEqual(sell["slip_bps"], 100.0)
        self.assertEqual(favorable_sell["slip_px"], -1.0)

    def test_queue_approximation_uses_depth_ahead_traded_volume_and_cancellations(self) -> None:
        summary = approximate_queue_fill(
            order_qty=3.0,
            depth_ahead_qty=5.0,
            traded_qty_at_price=7.0,
            canceled_ahead_qty=1.0,
        )

        self.assertEqual(summary["filled_qty"], 3.0)
        self.assertEqual(summary["fill_ratio"], 1.0)
        self.assertEqual(summary["depth_ahead_qty"], 5.0)

    def test_paper_executor_runs_only_approved_artifact_and_records_telemetries_and_divergence(self) -> None:
        artifact = build_strategy_artifact(_valid_artifact_payload(rollout_stage="paper"))
        intent = PaperOrderIntent(
            symbol="BTCUSDT",
            side="BUY",
            qty=2.0,
            expected_price=100.0,
            limit_price=100.5,
            order_type="limit",
            post_only=True,
        )
        snapshots = [
            PaperMarketSnapshot(
                ts="2026-04-26T00:00:00Z",
                symbol="BTCUSDT",
                bid=99.9,
                ask=100.1,
                last_trade_price=100.0,
                traded_qty_at_price=2.0,
                canceled_ahead_qty=0.0,
                depth_ahead_qty=1.0,
                visible_depth_qty=5.0,
                topn_depth_qty=10.0,
                volatility_1m=0.01,
                volatility_15m=0.03,
                funding_rate=0.0001,
            )
        ]

        result = run_paper_executor_fixture(
            artifact,
            order_intents=[intent],
            market_snapshots=snapshots,
            latency_ms=25.0,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0005,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["artifact_id"], artifact["artifact_id"])
        self.assertEqual(len(result["order_telemetry"]), 1)
        telemetry = result["order_telemetry"][0]
        self.assertEqual(telemetry["qty_submitted"], 2.0)
        self.assertEqual(telemetry["qty_filled"], 1.0)
        self.assertEqual(telemetry["maker_ratio"], 1.0)
        self.assertIn("paper_live_divergence", result)
        self.assertEqual(result["paper_live_divergence"]["recorded_for_calibration"], True)

        research_config = {"run_id": "not-artifact"}
        with self.assertRaisesRegex(ValueError, "not_strategy_artifact"):
            run_paper_executor_fixture(research_config, order_intents=[intent], market_snapshots=snapshots)

    def test_paper_executor_uses_artifact_cost_model_config_for_effective_fees(self) -> None:
        artifact = build_strategy_artifact(
            _valid_artifact_payload(
                rollout_stage="paper",
                cost_model_config={
                    "source": "venue_profile:test-tier",
                    "maker_fee_bps": 1.5,
                    "taker_fee_bps": 4.5,
                    "slippage_model": "quoted_depth_v1",
                    "slippage_bps": 6.0,
                },
            )
        )

        result = run_paper_executor_fixture(
            artifact,
            order_intents=[
                PaperOrderIntent(
                    symbol="BTCUSDT",
                    side="BUY",
                    qty=2.0,
                    expected_price=100.0,
                    limit_price=100.5,
                    order_type="limit",
                    post_only=True,
                )
            ],
            market_snapshots=[
                PaperMarketSnapshot(
                    ts="2026-04-26T00:00:00Z",
                    symbol="BTCUSDT",
                    bid=99.9,
                    ask=100.1,
                    last_trade_price=100.0,
                    traded_qty_at_price=3.0,
                    depth_ahead_qty=1.0,
                    visible_depth_qty=5.0,
                    topn_depth_qty=10.0,
                )
            ],
        )

        effective = result["effective_cost_model"]
        telemetry = result["order_telemetry"][0]

        self.assertEqual(effective["cost_model"], "cost-v1")
        self.assertEqual(effective["source"], "artifact_cost_model_config")
        self.assertEqual(effective["venue_source"], "venue_profile:test-tier")
        self.assertEqual(effective["maker_fee_bps"], 1.5)
        self.assertEqual(effective["taker_fee_bps"], 4.5)
        self.assertEqual(effective["slippage_model"], "quoted_depth_v1")
        self.assertEqual(effective["slippage_bps"], 6.0)
        self.assertEqual(telemetry["fee_rate"], 0.00015)
        self.assertEqual(telemetry["fee_quote"], 0.03015)

    def test_paper_executor_persists_order_telemetry_for_later_calibration(self) -> None:
        root = Path("test-phase6-paper-telemetry")
        db_path = root / "memory.sqlite"
        try:
            artifact = build_strategy_artifact(_valid_artifact_payload(rollout_stage="paper"))
            result = run_paper_executor_fixture(
                artifact,
                order_intents=[
                    PaperOrderIntent(
                        symbol="BTCUSDT",
                        side="BUY",
                        qty=1.0,
                        expected_price=100.0,
                        limit_price=100.5,
                        order_type="market",
                    )
                ],
                market_snapshots=[
                    PaperMarketSnapshot(
                        ts="2026-04-26T00:00:00Z",
                        symbol="BTCUSDT",
                        bid=99.9,
                        ask=100.1,
                        last_trade_price=100.2,
                        visible_depth_qty=5.0,
                        topn_depth_qty=10.0,
                        funding_rate=0.0001,
                    )
                ],
            )

            summary = record_paper_execution_result(db_path, result)
            connection = sqlite3.connect(db_path)
            try:
                telemetry = connection.execute(
                    "SELECT symbol, side, qty_submitted, qty_filled, expected_price, live_vwap_price, slip_bps, maker_ratio FROM order_telemetry"
                ).fetchone()
                funding = connection.execute(
                    "SELECT symbol, position_notional, funding_rate, funding_fee FROM funding_events"
                ).fetchone()
                divergence = connection.execute(
                    "SELECT metric_name, metric_value FROM live_metrics WHERE artifact_id = ?",
                    (artifact["artifact_id"],),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(summary["order_telemetry_rows"], 1)
            self.assertEqual(telemetry, ("BTCUSDT", "BUY", 1.0, 1.0, 100.0, 100.2, 20.0, 0.0))
            self.assertEqual(funding, ("BTCUSDT", 100.2, 0.0001, 0.01002))
            self.assertIn(("paper_live_average_slip_bps", 20.0), divergence)
        finally:
            _clean_tree(root)


class Phase6CliTests(unittest.TestCase):
    def test_cli_validates_lists_and_paper_runs_artifacts(self) -> None:
        root = Path("test-phase6-cli")
        try:
            artifact = build_strategy_artifact(_valid_artifact_payload(rollout_stage="paper"))
            artifact_path = write_strategy_artifact(root / "artifact.strategy-artifact.json", artifact)
            fixture_path = root / "market-fixture.json"
            fixture_path.write_text(
                json.dumps(
                    {
                        "order_intents": [
                            {
                                "symbol": "BTCUSDT",
                                "side": "BUY",
                                "qty": 1.0,
                                "expected_price": 100.0,
                                "limit_price": 100.5,
                                "order_type": "limit",
                                "post_only": True,
                            }
                        ],
                        "market_snapshots": [
                            {
                                "ts": "2026-04-26T00:00:00Z",
                                "symbol": "BTCUSDT",
                                "bid": 99.9,
                                "ask": 100.1,
                                "last_trade_price": 100.0,
                                "traded_qty_at_price": 2.0,
                                "canceled_ahead_qty": 0.0,
                                "depth_ahead_qty": 0.0,
                                "visible_depth_qty": 5.0,
                                "topn_depth_qty": 10.0,
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            with mock.patch("builtins.print") as print_mock:
                self.assertEqual(main(["validate-artifact", "--artifact", str(artifact_path)]), 0)
            validate_payload = json.loads(print_mock.call_args.args[0])
            self.assertTrue(validate_payload["passed"])

            with mock.patch("builtins.print") as print_mock:
                self.assertEqual(main(["list-artifacts", "--dir", str(root)]), 0)
            list_payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(list_payload["artifacts"][0]["artifact_id"], artifact["artifact_id"])

            with mock.patch("builtins.print") as print_mock:
                self.assertEqual(
                    main(
                        [
                            "paper-run-artifact",
                            "--artifact",
                            str(artifact_path),
                            "--market-fixture",
                            str(fixture_path),
                        ]
                    ),
                    0,
                )
            run_payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(run_payload["status"], "completed")
            self.assertEqual(run_payload["artifact_id"], artifact["artifact_id"])
        finally:
            _clean_tree(root)
