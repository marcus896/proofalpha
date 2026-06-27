from __future__ import annotations

import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.backtest.binance_usdm import (
    MaintenanceMarginTier,
    liquidation_price_with_maintenance_tiers,
    select_maintenance_margin_tier,
)
from engine.calibration.cost_capacity import (
    CalibrationModel,
    build_capacity_report,
    build_cost_capacity_calibration_artifact,
    evaluate_calibration_update,
    fit_impact_calibration,
    load_order_telemetry_measurements,
)
from engine.memory.store import initialize_memory_db


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _insert_telemetry(
    db_path: Path,
    *,
    telemetry_id: str,
    symbol: str = "BTCUSDT",
    regime: str = "trend",
    qty_submitted: float = 1.0,
    qty_filled: float = 1.0,
    expected_price: float = 100.0,
    live_vwap_price: float = 100.08,
    slip_bps: float = 8.0,
    spread_bps: float = 2.0,
    topn_depth: float = 20.0,
    vol_15m: float = 0.02,
    latency_ms: float = 25.0,
    adv_notional: float = 10_000.0,
    maker_ratio: float = 0.0,
) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO order_telemetry (
                telemetry_id, symbol, side, qty_submitted, qty_filled, qty_canceled,
                expected_price, live_vwap_price, slip_bps, spread_bps, topn_depth,
                vol_15m, latency_rtt_ms, maker_ratio, was_rejected, risk_blocked,
                metadata_json
            ) VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            """,
            (
                telemetry_id,
                symbol,
                qty_submitted,
                qty_filled,
                max(0.0, qty_submitted - qty_filled),
                expected_price,
                live_vwap_price,
                slip_bps,
                spread_bps,
                topn_depth,
                vol_15m,
                latency_ms,
                maker_ratio,
                json.dumps(
                    {
                        "adv_notional": adv_notional,
                        "regime": regime,
                        "funding_window": False,
                        "modeled_fill_price": expected_price,
                        "opportunity_loss_bps": 1.5,
                    },
                    sort_keys=True,
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()


class Phase7CostCapacityCalibrationTests(unittest.TestCase):
    def test_loads_paper_live_measurements_with_sqrt_participation_and_fill_diagnostics(self) -> None:
        root = Path("test-phase7-measurements")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            _insert_telemetry(db_path, telemetry_id="t1", qty_submitted=2.0, qty_filled=1.5, adv_notional=20_000.0)

            measurements = load_order_telemetry_measurements(db_path)

            self.assertEqual(len(measurements), 1)
            row = measurements[0]
            self.assertEqual(row.symbol, "BTCUSDT")
            self.assertEqual(row.regime, "trend")
            self.assertAlmostEqual(row.submitted_notional, 200.0)
            self.assertAlmostEqual(row.participation_rate, 0.01)
            self.assertAlmostEqual(row.sqrt_q_over_adv, 0.1)
            self.assertAlmostEqual(row.fill_completion_rate, 0.75)
            self.assertAlmostEqual(row.realized_vs_modeled_fill_bps, 8.0)
            self.assertAlmostEqual(row.opportunity_loss_bps, 1.5)
        finally:
            _clean_tree(root)

    def test_fits_impact_model_and_blocks_capacity_when_5x_edge_or_completion_fails(self) -> None:
        measurements = []
        root = Path("test-phase7-capacity")
        db_path = root / "memory.sqlite"
        try:
            initialize_memory_db(db_path)
            for index in range(20):
                _insert_telemetry(
                    db_path,
                    telemetry_id=f"t{index}",
                    qty_submitted=2.0,
                    qty_filled=2.0 if index < 18 else 1.7,
                    slip_bps=10.0 + (index % 4),
                    spread_bps=2.0,
                    topn_depth=10.0,
                    adv_notional=2_000.0,
                    vol_15m=0.03,
                    latency_ms=30.0,
                )
            measurements = load_order_telemetry_measurements(db_path)
        finally:
            _clean_tree(root)

        model = fit_impact_calibration(
            measurements,
            source_model_version="cost-v1",
            minimum_orders_per_bucket=20,
        )
        report = build_capacity_report(
            measurements,
            model=model,
            baseline_edge_bps=20.0,
            max_participation_rate=0.08,
        )

        self.assertEqual(model.status, "usable")
        self.assertGreater(model.square_root_impact_bps, 0.0)
        self.assertEqual([row.multiplier for row in report.rows], [1, 2, 5, 10])
        self.assertFalse(report.passed)
        self.assertIn("capacity_fail_5x_edge_erosion", report.failure_reasons)
        self.assertIn("capacity_fail_5x_fill_completion", report.failure_reasons)

    def test_calibration_update_requires_large_bucket_samples_and_confidence_before_lowering_costs(self) -> None:
        incumbent = CalibrationModel(
            model_version="cost-calibration-old",
            source_model_version="cost-v1",
            status="usable",
            sample_count=500,
            bucket_counts={"BTCUSDT|trend": 500},
            square_root_impact_bps=100.0,
            spread_coefficient=0.5,
            volatility_coefficient=10.0,
            latency_coefficient=0.01,
            funding_window_bps=0.0,
            queue_fill_coefficient=1.0,
            max_participation_rate=0.05,
            notes=[],
        )
        cheaper = CalibrationModel(
            model_version="cost-calibration-new",
            source_model_version="cost-v1",
            status="usable",
            sample_count=150,
            bucket_counts={"BTCUSDT|trend": 150},
            square_root_impact_bps=50.0,
            spread_coefficient=0.4,
            volatility_coefficient=8.0,
            latency_coefficient=0.01,
            funding_window_bps=0.0,
            queue_fill_coefficient=1.3,
            max_participation_rate=0.08,
            notes=[],
        )

        blocked = evaluate_calibration_update(
            incumbent,
            cheaper,
            oos_passed=True,
            bootstrap_passed=True,
            minimum_orders_per_bucket=200,
        )
        allowed = evaluate_calibration_update(
            incumbent,
            cheaper,
            oos_passed=True,
            bootstrap_passed=True,
            minimum_orders_per_bucket=100,
        )

        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.selected_model.model_version, incumbent.model_version)
        self.assertIn("insufficient_bucket_sample:BTCUSDT|trend", blocked.reasons)
        self.assertTrue(allowed.allowed)
        self.assertGreater(allowed.selected_model.square_root_impact_bps, cheaper.square_root_impact_bps)
        self.assertLess(allowed.selected_model.square_root_impact_bps, incumbent.square_root_impact_bps)

    def test_tiered_binance_liquidation_helpers_select_notional_bucket(self) -> None:
        tiers = [
            MaintenanceMarginTier(notional_floor=0.0, notional_cap=50_000.0, maintenance_margin_ratio=0.004),
            MaintenanceMarginTier(notional_floor=50_000.0, notional_cap=250_000.0, maintenance_margin_ratio=0.005),
        ]

        selected = select_maintenance_margin_tier(100_000.0, tiers)
        long_liq = liquidation_price_with_maintenance_tiers(
            entry_price=100.0,
            side="long",
            leverage=10.0,
            quantity=1_000.0,
            tiers=tiers,
        )

        self.assertEqual(selected.maintenance_margin_ratio, 0.005)
        self.assertAlmostEqual(long_liq, 90.5)

    def test_cli_writes_capacity_calibration_artifact(self) -> None:
        root = Path("test-phase7-cli")
        db_path = root / "memory.sqlite"
        artifact_path = root / "capacity-artifact.json"
        try:
            initialize_memory_db(db_path)
            for index in range(12):
                _insert_telemetry(db_path, telemetry_id=f"t{index}", adv_notional=50_000.0, qty_submitted=1.0)

            with mock.patch("builtins.print"):
                exit_code = main(
                    [
                        "calibrate-cost-capacity",
                        "--db",
                        str(db_path),
                        "--output",
                        str(artifact_path),
                        "--baseline-edge-bps",
                        "100",
                        "--minimum-orders-per-bucket",
                        "10",
                    ]
                )
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["artifact_type"], "cost_capacity_calibration")
            self.assertEqual(payload["capacity_report"]["multipliers"], [1, 2, 5, 10])
            self.assertIn("cost_model_version", payload)
            self.assertIn("artifact_sha256", payload)
        finally:
            _clean_tree(root)


class Phase7ArtifactTests(unittest.TestCase):
    def test_calibration_artifact_has_stable_cost_model_version_and_checksum(self) -> None:
        model = CalibrationModel(
            model_version="cost-calibration-abc",
            source_model_version="cost-v1",
            status="usable",
            sample_count=250,
            bucket_counts={"BTCUSDT|trend": 250},
            square_root_impact_bps=40.0,
            spread_coefficient=0.5,
            volatility_coefficient=10.0,
            latency_coefficient=0.01,
            funding_window_bps=0.0,
            queue_fill_coefficient=1.0,
            max_participation_rate=0.05,
            notes=[],
        )
        report = build_capacity_report([], model=model, baseline_edge_bps=100.0)

        artifact = build_cost_capacity_calibration_artifact(
            model=model,
            capacity_report=report,
            source="unit-test",
        )

        self.assertEqual(artifact["cost_model_version"], model.model_version)
        self.assertEqual(artifact["source_model_version"], "cost-v1")
        self.assertIn("artifact_sha256", artifact)


if __name__ == "__main__":
    unittest.main()
