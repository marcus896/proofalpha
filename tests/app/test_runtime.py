import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from engine.app.config import load_study_config
from engine.app.runtime import (
    _apply_layer_adjustments,
    _derive_stress_metrics,
    _apply_scenario_execution_overlay,
    _bootstrap_strategy_with_settings,
    _compute_calibration_from_snapshot,
    _build_signals,
    _run_grid_with_batch_sim,
    _run_fast_screen_gates,
    _snapshot_supports_realistic_batch_sim,
    _resolve_scenario_runtime_inputs,
    _apply_scenario_stress,
    _summarize_bootstrap_regimes,
    build_runtime_functions,
)
from engine.backtest.simulator_numba import BatchSimResult
from engine.backtest.simulator import simulate_strategy
from engine.config.models import BacktestResult, DataSnapshot, LayerFamily, LayerSpec, PhaseRecord, StrategyGraph
from engine.data.schema import Candle
from engine.strategy.catalog import catalog_by_family, get_layer_by_name
from engine.validation.bootstrap import multivariate_block_bootstrap_indices
from engine.validation.scenarios import StressScenario, resolve_scenario_profile
from engine.validation.regimes import analyze_regimes


class RuntimeSettingsTests(unittest.TestCase):
    def test_snapshot_supports_realistic_batch_sim_with_thin_depth_microstructure(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        snapshot = DataSnapshot(
            snapshot_id="thin-depth-batch-capability",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(
                    timestamp=start + timedelta(hours=index),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1_000.0,
                )
                for index in range(8)
            ],
            funding_rates=[0.0] * 8,
            open_interest=[100.0] * 8,
            liquidation_notional=[500_000.0] * 8,
            spread_bps=[3.0] * 8,
            depth_bid_1bp_usd=[120.0] * 8,
            depth_ask_1bp_usd=[120.0] * 8,
            latency_proxy_ms=[220.0] * 8,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )

        self.assertTrue(_snapshot_supports_realistic_batch_sim(snapshot))

    def test_catalog_only_exposes_supported_time_stop_exit_layer(self) -> None:
        self.assertEqual(catalog_by_family()["exit_layers"], ["time_stop"])
        time_stop = get_layer_by_name("time_stop")
        self.assertEqual(time_stop.family, LayerFamily.EXIT)
        self.assertEqual(time_stop.parameters["hold_bars"].minimum, 1)
        with self.assertRaises(KeyError):
            get_layer_by_name("dema_exit")

    def test_kama_hma_time_stop_exit_layer_overrides_hold_length(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(
                timestamp=start + timedelta(hours=index),
                open=100.0 + index - 0.5,
                high=101.0 + index,
                low=99.0 + index,
                close=100.0 + index,
                volume=1_000.0,
            )
            for index in range(60)
        ]
        snapshot = DataSnapshot(
            snapshot_id="kama-time-stop",
            symbol="SOLUSDT",
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

        _, default_exit_signals = _build_signals(
            snapshot,
            StrategyGraph(backbone="kama_hma"),
            {},
            "long",
        )
        _, time_stop_exit_signals = _build_signals(
            snapshot,
            StrategyGraph(
                backbone="kama_hma",
                layers=[LayerSpec(name="time_stop", family=LayerFamily.EXIT)],
            ),
            {"time_stop": {"hold_bars": 3}},
            "long",
        )

        default_exits = [index for index, value in enumerate(default_exit_signals) if value]
        time_stop_exits = [index for index, value in enumerate(time_stop_exit_signals) if value]
        self.assertEqual(default_exits[:2], [34, 59])
        self.assertEqual(time_stop_exits[0], 13)
        self.assertLess(time_stop_exits[0], default_exits[0])

    def test_load_study_config_parses_runtime_settings(self) -> None:
        config_path = Path("test-runtime-settings.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-settings",
                    "seed": 12,
                    "runtime": {
                        "mode": "builtin",
                        "slippage_bps": 25.0,
                        "latency_bars": 1,
                        "position_side": "short",
                        "min_oos_trades": 7,
                        "search_summary_limit": 2,
                        "bootstrap_samples": 5,
                        "bootstrap_block_size": 4,
                        "bootstrap_method": "stationary_block",
                        "bootstrap_spread_multiplier": 2.0,
                        "bootstrap_depth_multiplier": 0.4,
                        "bootstrap_latency_multiplier": 3.0,
                        "gate_min_backtest_length": True,
                        "holdout_sharpe_floor": 0.08,
                        "holdout_drawdown_cap": -0.2,
                        "scenario_severity_multiplier": 1.3,
                        "position_leverage": 4.0,
                        "maintenance_margin_ratio": 0.02,
                        "liquidation_fee_bps": 75.0,
                        "liquidation_mark_price_weight": 0.6,
                        "partial_liquidation_ratio": 0.5,
                        "liquidation_cooldown_bars": 2,
                        "liquidation_step_schedule": [0.25, 0.5, 1.0],
                        "liquidation_mark_premium_bps": 50.0,
                        "maintenance_margin_schedule": [
                            {"max_leverage": 3.0, "maintenance_margin_ratio": 0.01},
                            {"max_leverage": 10.0, "maintenance_margin_ratio": 0.03},
                        ],
                        "liquidation_fee_schedule": [
                            {"max_leverage": 3.0, "liquidation_fee_bps": 0.0},
                            {"max_leverage": 10.0, "liquidation_fee_bps": 100.0},
                        ],
                    },
                    "layer_parameters": {
                        "mom_squeeze": {"entry_stride": 4},
                        "kama": {"mean_threshold_offset": 0.05},
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        self.assertEqual(study.runtime_settings.slippage_bps, 25.0)
        self.assertEqual(study.runtime_settings.latency_bars, 1)
        self.assertEqual(study.runtime_settings.position_side, "short")
        self.assertEqual(study.runtime_settings.min_oos_trades, 7)
        self.assertEqual(study.runtime_settings.search_summary_limit, 2)
        self.assertEqual(study.runtime_settings.bootstrap_samples, 5)
        self.assertEqual(study.runtime_settings.bootstrap_block_size, 4)
        self.assertEqual(study.runtime_settings.bootstrap_method, "stationary_block")
        self.assertEqual(study.runtime_settings.bootstrap_spread_multiplier, 2.0)
        self.assertEqual(study.runtime_settings.bootstrap_depth_multiplier, 0.4)
        self.assertEqual(study.runtime_settings.bootstrap_latency_multiplier, 3.0)
        self.assertTrue(study.runtime_settings.gate_min_backtest_length)
        self.assertEqual(study.runtime_settings.holdout_sharpe_floor, 0.08)
        self.assertEqual(study.runtime_settings.holdout_drawdown_cap, -0.2)
        self.assertEqual(study.runtime_settings.scenario_severity_multiplier, 1.3)
        self.assertEqual(study.runtime_settings.position_leverage, 4.0)
        self.assertEqual(study.runtime_settings.maintenance_margin_ratio, 0.02)
        self.assertEqual(study.runtime_settings.liquidation_fee_bps, 75.0)
        self.assertEqual(study.runtime_settings.liquidation_mark_price_weight, 0.6)
        self.assertEqual(study.runtime_settings.partial_liquidation_ratio, 0.5)
        self.assertEqual(study.runtime_settings.liquidation_cooldown_bars, 2)
        self.assertEqual(study.runtime_settings.liquidation_step_schedule, [0.25, 0.5, 1.0])
        self.assertEqual(study.runtime_settings.liquidation_mark_premium_bps, 50.0)
        self.assertEqual(
            study.runtime_settings.maintenance_margin_schedule,
            [
                {"max_leverage": 3.0, "maintenance_margin_ratio": 0.01},
                {"max_leverage": 10.0, "maintenance_margin_ratio": 0.03},
            ],
        )
        self.assertEqual(
            study.runtime_settings.liquidation_fee_schedule,
            [
                {"max_leverage": 3.0, "liquidation_fee_bps": 0.0},
                {"max_leverage": 10.0, "liquidation_fee_bps": 100.0},
            ],
        )
        self.assertEqual(study.layer_parameters["mom_squeeze"]["entry_stride"], 4)
        self.assertEqual(study.layer_parameters["kama"]["mean_threshold_offset"], 0.05)

    def test_fast_screen_gates_make_minbtl_and_catastrophe_filters_explicit(self) -> None:
        train = BacktestResult(
            trade_count=4,
            win_rate=0.5,
            gross_pnl=10.0,
            net_pnl=8.0,
            fee_spend=1.0,
            funding_spend=1.0,
            sharpe=1.0,
            sortino=1.0,
            max_drawdown=-0.1,
            equity_curve=[1.0, 1.02, 1.01, 1.03],
            liquidation_events=["liq"],
        )
        oos = BacktestResult(
            trade_count=1,
            win_rate=0.5,
            gross_pnl=1.0,
            net_pnl=-9.0,
            fee_spend=1.0,
            funding_spend=2.0,
            sharpe=0.1,
            sortino=0.1,
            max_drawdown=-0.2,
            equity_curve=[1.0, 1.0, 0.99, 0.99, 0.98],
            liquidation_events=[],
        )

        screen = _run_fast_screen_gates(
            candidate_train=train,
            candidate_oos=oos,
            min_oos_trades=3,
            gate_min_backtest_length=True,
        )

        self.assertFalse(screen["passed"])
        self.assertEqual(screen["stage"], "fast_screen")
        self.assertIn("fast_screen_min_oos_trades", screen["reasons"])
        self.assertIn("fast_screen_liquidation_events", screen["reasons"])
        self.assertIn("fast_screen_excessive_funding_drag", screen["reasons"])
        self.assertTrue(screen["metrics"]["minimum_backtest_length_enforced"])

    def test_load_study_config_parses_optuna_runtime_settings(self) -> None:
        config_path = Path("test-runtime-optuna-settings.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-optuna-settings",
                    "seed": 12,
                    "runtime": {
                        "mode": "builtin",
                        "parameter_search_mode": "optuna",
                        "optuna_trial_budget": 6,
                        "optuna_warm_start_trials": 3,
                        "optuna_sampler": "random",
                        "optuna_pruner_enabled": False,
                        "optuna_startup_trials": 5,
                    },
                    "parameter_grids": {
                        "kama": {
                            "aggressiveness": {"minimum": 1.0, "maximum": 3.0, "step": 1.0},
                        }
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        self.assertEqual(study.runtime_settings.parameter_search_mode, "optuna")
        self.assertEqual(study.runtime_settings.optuna_trials, 6)
        self.assertEqual(study.runtime_settings.optuna_seed_warm_start_limit, 3)
        self.assertEqual(study.runtime_settings.optuna_trial_budget, 6)
        self.assertEqual(study.runtime_settings.optuna_warm_start_trials, 3)
        self.assertEqual(study.runtime_settings.optuna_sampler, "random")
        self.assertFalse(study.runtime_settings.optuna_pruner_enabled)
        self.assertEqual(study.runtime_settings.optuna_startup_trials, 5)

    def test_summarize_bootstrap_regimes_aggregates_average_coverage(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        snapshots: list[DataSnapshot] = []
        for closes in (
            [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 109.0, 108.0, 107.0, 106.0],
            [100.0, 99.0, 98.0, 90.0, 82.0, 78.0, 80.0, 84.0, 90.0, 97.0],
        ):
            candles = [
                Candle(
                    timestamp=start + timedelta(hours=index),
                    open=close - 1.0,
                    high=close + 1.0,
                    low=close - 1.0,
                    close=close,
                    volume=1000.0,
                )
                for index, close in enumerate(closes)
            ]
            snapshots.append(
                DataSnapshot(
                    snapshot_id=f"bootstrap-{len(snapshots)}",
                    symbol="SOLUSDT",
                    venue="binance",
                    timeframe="1h",
                    candles=candles,
                    funding_rates=[0.0] * len(candles),
                    open_interest=[100.0] * len(candles),
                    liquidation_notional=[5.0] * len(candles),
                    maker_fee_bps=2.0,
                    taker_fee_bps=5.0,
                    quality_flags=[],
                )
            )

        summary = _summarize_bootstrap_regimes([analyze_regimes(snapshot) for snapshot in snapshots])

        self.assertEqual(summary["sample_count"], 2)
        self.assertIn("average_regime_coverage", summary)
        self.assertIn("dominant_regimes", summary)
        self.assertLessEqual(summary["average_regime_coverage"]["bull"], 1.0)

    def test_load_study_config_applies_venue_runtime_presets_when_not_explicit(self) -> None:
        config_path = Path("test-runtime-venue-presets.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-venue-presets",
                    "seed": 12,
                    "runtime": {"mode": "builtin"},
                    "snapshot": {
                        "snapshot_id": "runtime-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        self.assertGreater(study.runtime_settings.liquidation_mark_price_weight, 0.0)
        self.assertGreater(study.runtime_settings.liquidation_mark_premium_bps, 0.0)
        self.assertTrue(study.runtime_settings.maintenance_margin_schedule)
        self.assertTrue(study.runtime_settings.liquidation_fee_schedule)

    def test_load_study_config_keeps_explicit_runtime_values_over_venue_presets(self) -> None:
        config_path = Path("test-runtime-venue-presets-explicit.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-venue-presets-explicit",
                    "seed": 12,
                    "runtime": {
                        "mode": "builtin",
                        "liquidation_mark_price_weight": 0.0,
                        "liquidation_mark_premium_bps": 0.0,
                        "maintenance_margin_schedule": [],
                        "liquidation_fee_schedule": [],
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        self.assertEqual(study.runtime_settings.liquidation_mark_price_weight, 0.0)
        self.assertEqual(study.runtime_settings.liquidation_mark_premium_bps, 0.0)
        self.assertEqual(study.runtime_settings.maintenance_margin_schedule, [])
        self.assertEqual(study.runtime_settings.liquidation_fee_schedule, [])

    def test_load_study_config_parses_parameter_grids(self) -> None:
        config_path = Path("test-parameter-grid-settings.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "parameter-grid-settings",
                    "seed": 13,
                    "runtime": {"mode": "builtin"},
                    "parameter_grids": {
                        "kama": {
                            "aggressiveness": {"minimum": 1.0, "maximum": 2.0, "step": 1.0},
                            "mean_threshold_offset": {"minimum": 0.0, "maximum": 0.08, "step": 0.08},
                        }
                    },
                    "snapshot": {
                        "snapshot_id": "parameter-grid-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        self.assertEqual(study.parameter_grids["kama"]["aggressiveness"].values(), [1, 2])
        self.assertEqual(study.parameter_grids["kama"]["mean_threshold_offset"].values(), [0.0, 0.08])

    def test_builtin_runtime_settings_change_evaluator_outcomes(self) -> None:
        low_path = Path("test-runtime-low.json")
        high_path = Path("test-runtime-high.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        base_payload = {
            "run_id": "runtime-compare",
            "seed": 3,
            "runtime": {"mode": "builtin"},
            "snapshot": {
                "snapshot_id": "runtime-compare-snap",
                "symbol": "SOLUSDT",
                "venue": "binance",
                "timeframe": "1h",
                "candles": [
                    {
                        "timestamp": (start + timedelta(hours=hour)).isoformat(),
                        "open": 100 + hour,
                        "high": 101 + hour,
                        "low": 99 + hour,
                        "close": 100 + hour,
                        "volume": 1000.0,
                    }
                    for hour in range(120)
                ],
                "funding_rates": [0.0] * 120,
                "open_interest": [100.0] * 120,
                "liquidation_notional": [0.0] * 120,
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 5.0,
                "quality_flags": [],
            },
            "incumbent": {"backbone": "mom_squeeze"},
            "directional_layers": ["kama"],
            "known_good_filters": [],
            "custom_filters": [],
            "exit_layers": [],
            "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
        }
        low_payload = dict(base_payload)
        low_payload["runtime"] = {"mode": "builtin", "slippage_bps": 5.0, "min_oos_trades": 3}
        high_payload = dict(base_payload)
        high_payload["runtime"] = {"mode": "builtin", "slippage_bps": 50.0, "min_oos_trades": 10}
        low_path.write_text(json.dumps(low_payload), encoding="utf-8")
        high_path.write_text(json.dumps(high_payload), encoding="utf-8")
        try:
            low_study = load_study_config(low_path)
            high_study = load_study_config(high_path)
        finally:
            low_path.unlink()
            high_path.unlink()

        low_evaluator, _, _ = build_runtime_functions(low_study)
        high_evaluator, _, _ = build_runtime_functions(high_study)
        layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)

        low_eval = low_evaluator(low_study.incumbent, layer)
        high_eval = high_evaluator(high_study.incumbent, layer)

        self.assertGreater(low_eval.oos_result.net_pnl, high_eval.oos_result.net_pnl)
        self.assertEqual(high_eval.decision.decision, "reject")
        self.assertNotIn("min_oos_trades", low_eval.decision.reasons)
        self.assertIn("min_oos_trades", high_eval.decision.reasons)

    def test_runtime_uses_optuna_when_enabled(self) -> None:
        config_path = Path("test-runtime-optuna-mode.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-optuna-mode",
                    "seed": 7,
                    "runtime": {
                        "mode": "builtin",
                        "parameter_search_mode": "optuna",
                        "optuna_trial_budget": 4,
                        "optuna_warm_start_trials": 2,
                        "optuna_sampler": "random",
                        "optuna_pruner_enabled": False,
                        "optuna_startup_trials": 3,
                    },
                    "parameter_grids": {
                        "kama": {
                            "aggressiveness": {"minimum": 1.0, "maximum": 3.0, "step": 1.0},
                        }
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-optuna-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)
        with patch("engine.app.runtime.build_optuna_plan") as mock_build_optuna_plan:
            with patch("engine.app.runtime.query_bayesian_seed_trials", return_value=[{"parameters": {"aggressiveness": 1.0}}]):
                mock_build_optuna_plan.return_value = {
                    "planner_mode": "optuna",
                    "best_parameters": {"aggressiveness": 2.0},
                    "best_score": 1.0,
                    "search_summary": [{"decision": "accept", "score": 1.0, "parameters": {"aggressiveness": 2.0}}],
                }
                evaluator, _, _ = build_runtime_functions(study)
                evaluation = evaluator(study.incumbent, layer)

        self.assertTrue(mock_build_optuna_plan.called)
        self.assertEqual(evaluation.selected_parameters["aggressiveness"], 2.0)
        self.assertEqual(evaluation.search_summary[0]["parameters"]["aggressiveness"], 2.0)
        self.assertGreaterEqual(len(evaluation.candidate_trials), 2)
        self.assertEqual(evaluation.candidate_trials[0]["search_source"], "optuna")
        self.assertEqual(evaluation.candidate_trials[0]["seed_evidence"]["source"], "bayesian_memory_unavailable")
        self.assertEqual(evaluation.candidate_trials[-1]["search_source"], "optuna_final")
        _, kwargs = mock_build_optuna_plan.call_args
        self.assertEqual(kwargs["sampler_name"], "random")
        self.assertFalse(kwargs["pruner_enabled"])
        self.assertEqual(kwargs["startup_trials"], 3)
        self.assertEqual(kwargs["n_trials"], 4)

    def test_runtime_uses_batch_sweep_when_dynamic_slippage_is_enabled(self) -> None:
        config_path = Path("test-runtime-dynamic-slippage-grid.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-dynamic-slippage-grid",
                    "seed": 7,
                    "runtime": {
                        "mode": "builtin",
                        "slippage_model": "dynamic",
                    },
                    "parameter_grids": {
                        "kama": {
                            "aggressiveness": {"minimum": 1.0, "maximum": 2.0, "step": 1.0},
                        }
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-dynamic-slippage-grid-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0 + hour for hour in range(120)],
                        "liquidation_notional": [5.0 if hour % 7 == 0 else 0.0 for hour in range(120)],
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
            layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)
            with patch("engine.app.runtime.is_numba_available", return_value=True), patch(
                "engine.app.runtime._run_grid_with_batch_sim", return_value=({}, {})
            ) as mock_batch:
                evaluator, _, _ = build_runtime_functions(study)
                evaluation = evaluator(study.incumbent, layer)
        finally:
            config_path.unlink()

        self.assertTrue(mock_batch.called)
        self.assertEqual(mock_batch.call_args.kwargs["slippage_model"], "dynamic")
        self.assertGreaterEqual(len(evaluation.search_summary), 2)

    def test_runtime_search_summary_records_batch_fallback_telemetry(self) -> None:
        config_path = Path("test-runtime-batch-fallback-telemetry.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-batch-fallback-telemetry",
                    "seed": 7,
                    "runtime": {
                        "mode": "builtin",
                        "slippage_model": "dynamic",
                    },
                    "parameter_grids": {
                        "kama": {
                            "aggressiveness": {"minimum": 1.0, "maximum": 2.0, "step": 1.0},
                        }
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-batch-fallback-telemetry-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0 + hour for hour in range(120)],
                        "liquidation_notional": [5.0 if hour % 7 == 0 else 0.0 for hour in range(120)],
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
            layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)
            with patch("engine.app.runtime.is_numba_available", return_value=True), patch(
                "engine.app.runtime.simulate_strategy_batch", side_effect=RuntimeError("forced batch failure")
            ):
                evaluator, _, _ = build_runtime_functions(study)
                evaluation = evaluator(study.incumbent, layer)
        finally:
            config_path.unlink()

        self.assertGreaterEqual(len(evaluation.search_summary), 2)
        metadata = evaluation.search_summary[0]["batch_simulator"]
        self.assertTrue(metadata["attempted"])
        self.assertFalse(metadata["numba_used"])
        self.assertEqual(metadata["fallback_count"], 1)
        self.assertIn("forced batch failure", metadata["fallback_reason"])

    def test_validation_executor_forwards_gate_min_backtest_length(self) -> None:
        config_path = Path("test-runtime-minbtl.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-minbtl",
                    "seed": 5,
                    "runtime": {
                        "mode": "builtin",
                        "gate_min_backtest_length": True,
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-minbtl-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        _, _, validation_executor = build_runtime_functions(study)

        with patch("engine.app.runtime.run_validation_protocol", return_value=object()) as mock_run_validation_protocol:
            validation_executor(study.incumbent, [])

        self.assertTrue(mock_run_validation_protocol.called)
        self.assertTrue(mock_run_validation_protocol.call_args.kwargs["gate_min_backtest_length"])

    def test_realistic_slippage_grid_uses_batch_sim_when_typed_microstructure_present(self) -> None:
        config_path = Path("test-runtime-realistic-batch-grid.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-realistic-batch-grid",
                    "seed": 5,
                    "runtime": {
                        "mode": "builtin",
                        "slippage_model": "realistic",
                    },
                    "parameter_grids": {
                        "kama": {
                            "aggressiveness": {"minimum": 1.0, "maximum": 2.0, "step": 1.0},
                        }
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-realistic-batch-grid-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0 + hour for hour in range(120)],
                        "liquidation_notional": [5.0 if hour % 7 == 0 else 0.0 for hour in range(120)],
                        "spread_bps": [3.0] * 120,
                        "depth_bid_1bp_usd": [2_500_000.0] * 120,
                        "depth_ask_1bp_usd": [2_500_000.0] * 120,
                        "latency_proxy_ms": [25.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
            layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)
            with patch("engine.app.runtime.is_numba_available", return_value=True), patch(
                "engine.app.runtime._run_grid_with_batch_sim", return_value=({}, {})
            ) as mock_batch:
                evaluator, _, _ = build_runtime_functions(study)
                evaluator(study.incumbent, layer)
        finally:
            config_path.unlink()

        self.assertTrue(mock_batch.called)

    def test_realistic_slippage_grid_uses_batch_sim_when_thin_depth_implies_partial_fill(self) -> None:
        config_path = Path("test-runtime-realistic-batch-grid-thin-depth.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-realistic-batch-grid-thin-depth",
                    "seed": 5,
                    "runtime": {
                        "mode": "builtin",
                        "slippage_model": "realistic",
                    },
                    "parameter_grids": {
                        "kama": {
                            "aggressiveness": {"minimum": 1.0, "maximum": 2.0, "step": 1.0},
                        }
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-realistic-batch-grid-thin-depth-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [1_000_000.0] * 120,
                        "liquidation_notional": [500_000.0] * 120,
                        "spread_bps": [3.0] * 120,
                        "depth_bid_1bp_usd": [120.0] * 120,
                        "depth_ask_1bp_usd": [120.0] * 120,
                        "latency_proxy_ms": [220.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
            layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)
            with patch("engine.app.runtime.is_numba_available", return_value=True), patch(
                "engine.app.runtime._run_grid_with_batch_sim", return_value=({}, {})
            ) as mock_batch:
                evaluator, _, _ = build_runtime_functions(study)
                evaluator(study.incumbent, layer)
        finally:
            config_path.unlink()

        self.assertTrue(mock_batch.called)

    def test_runtime_search_summary_includes_execution_pressure_from_batch_results(self) -> None:
        config_path = Path("test-runtime-batch-search-summary-execution-pressure.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-batch-search-summary-execution-pressure",
                    "seed": 5,
                    "runtime": {
                        "mode": "builtin",
                        "slippage_model": "realistic",
                    },
                    "parameter_grids": {
                        "kama": {
                            "aggressiveness": {"minimum": 1.0, "maximum": 2.0, "step": 1.0},
                        }
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-batch-search-summary-execution-pressure-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100 + hour,
                                "high": 101 + hour,
                                "low": 99 + hour,
                                "close": 100 + hour,
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [1_000_000.0] * 120,
                        "liquidation_notional": [500_000.0] * 120,
                        "spread_bps": [3.0] * 120,
                        "depth_bid_1bp_usd": [120.0] * 120,
                        "depth_ask_1bp_usd": [120.0] * 120,
                        "latency_proxy_ms": [220.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
            layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)
            batch_result_a = BacktestResult(
                trade_count=3,
                win_rate=0.0,
                gross_pnl=12.0,
                net_pnl=9.0,
                fee_spend=1.0,
                funding_spend=2.0,
                sharpe=0.9,
                sortino=1.0,
                max_drawdown=-0.1,
                equity_curve=[0.0, 4.0, 9.0],
                liquidation_events=[],
                execution_pressure_summary={
                    "fill_event_count": 2,
                    "partial_fill_event_count": 1,
                    "average_fill_ratio": 0.72,
                    "min_fill_ratio": 0.44,
                },
            )
            batch_result_b = BacktestResult(
                trade_count=3,
                win_rate=0.0,
                gross_pnl=10.0,
                net_pnl=7.0,
                fee_spend=1.0,
                funding_spend=2.0,
                sharpe=0.6,
                sortino=0.7,
                max_drawdown=-0.12,
                equity_curve=[0.0, 3.0, 7.0],
                liquidation_events=[],
                execution_pressure_summary={
                    "fill_event_count": 2,
                    "partial_fill_event_count": 2,
                    "average_fill_ratio": 0.51,
                    "min_fill_ratio": 0.29,
                },
            )
            with patch("engine.app.runtime.is_numba_available", return_value=True), patch(
                "engine.app.runtime._run_grid_with_batch_sim",
                return_value=(
                    {0: batch_result_a, 1: batch_result_b},
                    {0: batch_result_a, 1: batch_result_b},
                ),
            ):
                evaluator, _, _ = build_runtime_functions(study)
                evaluation = evaluator(study.incumbent, layer)
        finally:
            config_path.unlink()

        self.assertEqual(
            evaluation.search_summary[0]["execution_pressure_summary"]["partial_fill_event_count"],
            1,
        )
        self.assertEqual(
            evaluation.search_summary[1]["execution_pressure_summary"]["min_fill_ratio"],
            0.29,
        )

    def test_batch_grid_passes_dislocation_pressure_from_snapshot_provenance(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(
                timestamp=start + timedelta(hours=index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.0 + index,
                volume=1_000.0,
            )
            for index in range(8)
        ]
        summary = {
            "mark_premium_bps": 100.0,
            "index_basis_bps": 50.0,
            "premium_spike_bars": 2,
        }
        snapshot = DataSnapshot(
            snapshot_id="runtime-batch-dislocation",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * len(candles),
            open_interest=[100.0] * len(candles),
            liquidation_notional=[0.0] * len(candles),
            spread_bps=[3.0] * len(candles),
            depth_bid_1bp_usd=[2_500_000.0] * len(candles),
            depth_ask_1bp_usd=[2_500_000.0] * len(candles),
            latency_proxy_ms=[25.0] * len(candles),
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
            provenance={"dislocation_summary": summary},
        )

        with patch("engine.app.runtime._build_signals", return_value=([False] * len(candles), [False] * len(candles))), patch(
            "engine.validation.regimes.label_snapshot_regimes", return_value=[""] * len(candles)
        ), patch(
            "engine.app.runtime.simulate_strategy_batch",
            return_value=[BatchSimResult(0, 0.0, 0.0, 0.0, 0.0, [0.0] * len(candles))],
        ) as mock_batch:
            _run_grid_with_batch_sim(
                in_sample_snapshot=snapshot,
                oos_snapshot=snapshot,
                candidate_strategy=StrategyGraph(backbone="mom_squeeze"),
                parameter_sets=[{}],
                layer_name="kama",
                base_layer_parameters={},
                position_side="long",
                position_leverage=2.0,
                maintenance_margin_ratio=0.01,
                liquidation_fee_bps=0.0,
                liquidation_mark_price_weight=0.6,
                liquidation_mark_premium_bps=0.0,
                maintenance_margin_schedule=[],
                liquidation_fee_schedule=[],
                taker_fee_bps=5.0,
                slippage_bps=7.0,
                latency_bars=0,
                slippage_model="realistic",
            )

        first_call = mock_batch.call_args_list[0].kwargs
        self.assertEqual(first_call["param_slippage_bps"], [16.0])
        self.assertEqual(first_call["liquidation_mark_premium_bps"], 170.0)
        self.assertEqual(first_call["liquidation_mark_price_weight"], 0.6)

    def test_batch_grid_passes_scenario_overlay_penalties_from_snapshot_provenance(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(
                timestamp=start + timedelta(hours=index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.0 + index,
                volume=1_000.0,
            )
            for index in range(8)
        ]
        snapshot = DataSnapshot(
            snapshot_id="runtime-batch-overlay",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * len(candles),
            open_interest=[100.0] * len(candles),
            liquidation_notional=[0.0] * len(candles),
            spread_bps=[3.0] * len(candles),
            depth_bid_1bp_usd=[2_500_000.0] * len(candles),
            depth_ask_1bp_usd=[2_500_000.0] * len(candles),
            latency_proxy_ms=[25.0] * len(candles),
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
            provenance={
                "scenario_execution_overlay": {
                    "scenario_name": "venue_outage",
                    "liquidity_penalty_bps": 20.0,
                    "latency_delta_bars": 2,
                }
            },
        )

        with patch("engine.app.runtime._build_signals", return_value=([False] * len(candles), [False] * len(candles))), patch(
            "engine.validation.regimes.label_snapshot_regimes", return_value=[""] * len(candles)
        ), patch(
            "engine.app.runtime.simulate_strategy_batch",
            return_value=[BatchSimResult(0, 0.0, 0.0, 0.0, 0.0, [0.0] * len(candles))],
        ) as mock_batch:
            _run_grid_with_batch_sim(
                in_sample_snapshot=snapshot,
                oos_snapshot=snapshot,
                candidate_strategy=StrategyGraph(backbone="mom_squeeze"),
                parameter_sets=[{}],
                layer_name="kama",
                base_layer_parameters={},
                position_side="long",
                position_leverage=2.0,
                maintenance_margin_ratio=0.01,
                liquidation_fee_bps=0.0,
                liquidation_mark_price_weight=0.0,
                liquidation_mark_premium_bps=0.0,
                maintenance_margin_schedule=[],
                liquidation_fee_schedule=[],
                taker_fee_bps=5.0,
                slippage_bps=7.0,
                latency_bars=1,
                slippage_model="realistic",
            )

        first_call = mock_batch.call_args_list[0].kwargs
        self.assertEqual(first_call["param_slippage_bps"], [27.0])
        self.assertEqual(first_call["param_latency_bars"], [3])

    def test_batch_grid_converts_execution_pressure_summary_into_backtest_result(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            Candle(
                timestamp=start + timedelta(hours=index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.0 + index,
                volume=1_000.0,
            )
            for index in range(8)
        ]
        snapshot = DataSnapshot(
            snapshot_id="runtime-batch-execution-pressure",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * len(candles),
            open_interest=[1_000_000.0] * len(candles),
            liquidation_notional=[500_000.0] * len(candles),
            spread_bps=[3.0] * len(candles),
            depth_bid_1bp_usd=[120.0] * len(candles),
            depth_ask_1bp_usd=[120.0] * len(candles),
            latency_proxy_ms=[220.0] * len(candles),
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        batch_result = BatchSimResult(
            1,
            5.0,
            0.5,
            0.0,
            4.5,
            [0.0] * len(candles),
            {
                "fill_event_count": 2,
                "partial_fill_event_count": 2,
                "average_fill_ratio": 0.52,
                "min_fill_ratio": 0.31,
            },
        )

        with patch("engine.app.runtime._build_signals", return_value=([False] * len(candles), [False] * len(candles))), patch(
            "engine.validation.regimes.label_snapshot_regimes", return_value=[""] * len(candles)
        ), patch(
            "engine.app.runtime.simulate_strategy_batch",
            return_value=[batch_result],
        ):
            train_results, oos_results = _run_grid_with_batch_sim(
                in_sample_snapshot=snapshot,
                oos_snapshot=snapshot,
                candidate_strategy=StrategyGraph(backbone="mom_squeeze"),
                parameter_sets=[{}],
                layer_name="kama",
                base_layer_parameters={},
                position_side="long",
                position_leverage=2.0,
                maintenance_margin_ratio=0.01,
                liquidation_fee_bps=0.0,
                liquidation_mark_price_weight=0.0,
                liquidation_mark_premium_bps=0.0,
                maintenance_margin_schedule=[],
                liquidation_fee_schedule=[],
                taker_fee_bps=5.0,
                slippage_bps=7.0,
                latency_bars=0,
                slippage_model="realistic",
            )

        self.assertEqual(train_results[0].execution_pressure_summary["partial_fill_event_count"], 2)
        self.assertEqual(oos_results[0].execution_pressure_summary["min_fill_ratio"], 0.31)

    def test_batch_grid_backtest_result_uses_batch_win_rate(self) -> None:
        candles = [
            Candle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index),
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.0 + index,
                volume=1_000.0,
            )
            for index in range(8)
        ]
        snapshot = DataSnapshot(
            snapshot_id="runtime-batch-win-rate",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=candles,
            funding_rates=[0.0] * len(candles),
            open_interest=[1_000_000.0] * len(candles),
            liquidation_notional=[0.0] * len(candles),
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        batch_result = BatchSimResult(
            2,
            5.0,
            0.5,
            0.0,
            4.5,
            [0.0] * len(candles),
            winning_trades=1,
        )

        with patch("engine.app.runtime._build_signals", return_value=([False] * len(candles), [False] * len(candles))), patch(
            "engine.validation.regimes.label_snapshot_regimes", return_value=[""] * len(candles)
        ), patch(
            "engine.app.runtime.simulate_strategy_batch",
            return_value=[batch_result],
        ):
            train_results, oos_results = _run_grid_with_batch_sim(
                in_sample_snapshot=snapshot,
                oos_snapshot=snapshot,
                candidate_strategy=StrategyGraph(backbone="mom_squeeze"),
                parameter_sets=[{}],
                layer_name="kama",
                base_layer_parameters={},
                position_side="long",
                position_leverage=2.0,
                maintenance_margin_ratio=0.01,
                liquidation_fee_bps=0.0,
                liquidation_mark_price_weight=0.0,
                liquidation_mark_premium_bps=0.0,
                maintenance_margin_schedule=[],
                liquidation_fee_schedule=[],
                taker_fee_bps=5.0,
                slippage_bps=7.0,
                latency_bars=0,
                slippage_model="flat",
            )

        self.assertAlmostEqual(train_results[0].win_rate, 0.5)
        self.assertAlmostEqual(oos_results[0].win_rate, 0.5)

    def test_validation_executor_records_pbo_gate_and_spa_skip(self) -> None:
        config_path = Path("test-runtime-pbo-spa.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-pbo-spa",
                    "seed": 7,
                    "runtime": {
                        "mode": "builtin",
                        "gate_min_backtest_length": True,
                        "permutation_count": 8,
                    },
                    "snapshot": {
                        "snapshot_id": "runtime-pbo-spa-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100.0 + (hour * 0.4),
                                "high": 100.5 + (hour * 0.4),
                                "low": 99.5 + (hour * 0.4),
                                "close": 100.0 + (hour * 0.4) + (0.15 if hour % 2 == 0 else -0.05),
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": [],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "scenarios": [],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        _, _, validation_executor = build_runtime_functions(study)
        validation = validation_executor(
            study.incumbent,
            [PhaseRecord(phase_name="phase-11", layer_name="mom_squeeze", decision="accept", accepted=True, permutation_count=8)],
        )

        self.assertIn("pbo", validation.validation_gate_results)
        self.assertIn("spa", validation.validation_gate_results)
        self.assertIsNone(validation.pbo_score)

    def test_validation_executor_uses_candidate_trials_for_pbo(self) -> None:
        config_path = Path("test-runtime-pbo-candidates.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        config_path.write_text(
            json.dumps(
                {
                    "run_id": "runtime-pbo-candidates",
                    "seed": 7,
                    "runtime": {"mode": "builtin", "gate_min_backtest_length": True, "permutation_count": 8},
                    "snapshot": {
                        "snapshot_id": "runtime-pbo-candidates-snap",
                        "symbol": "SOLUSDT",
                        "venue": "binance",
                        "timeframe": "1h",
                        "candles": [
                            {
                                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                                "open": 100.0 + (hour * 0.4),
                                "high": 100.5 + (hour * 0.4),
                                "low": 99.5 + (hour * 0.4),
                                "close": 100.0 + (hour * 0.4) + (0.15 if hour % 2 == 0 else -0.05),
                                "volume": 1000.0,
                            }
                            for hour in range(120)
                        ],
                        "funding_rates": [0.0] * 120,
                        "open_interest": [100.0] * 120,
                        "liquidation_notional": [0.0] * 120,
                        "maker_fee_bps": 2.0,
                        "taker_fee_bps": 5.0,
                        "quality_flags": [],
                    },
                    "incumbent": {"backbone": "mom_squeeze"},
                    "directional_layers": ["kama"],
                    "known_good_filters": [],
                    "custom_filters": [],
                    "exit_layers": [],
                    "parameter_grids": {
                        "kama": {
                            "aggressiveness": {"minimum": 1.0, "maximum": 2.0, "step": 1.0},
                        }
                    },
                    "scenarios": [],
                }
            ),
            encoding="utf-8",
        )
        try:
            study = load_study_config(config_path)
        finally:
            config_path.unlink()

        evaluator, _, validation_executor = build_runtime_functions(study)
        evaluator(study.incumbent, LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER))
        validation = validation_executor(
            study.incumbent,
            [PhaseRecord(phase_name="phase-11", layer_name="kama", decision="accept", accepted=True, permutation_count=2)],
        )

        self.assertIsNotNone(validation.pbo_score)

    def test_compute_calibration_from_snapshot_skips_missing_liquidation_series(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        snapshot = DataSnapshot(
            snapshot_id="missing-liquidations",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(timestamp=start + timedelta(hours=hour), open=100.0, high=101.0, low=99.0, close=100.0 + hour, volume=1000.0)
                for hour in range(12)
            ],
            funding_rates=[0.0] * 12,
            open_interest=[100.0] * 12,
            liquidation_notional=[0.0] * 12,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=["missing_liquidation_notional_count=12"],
        )

        self.assertIsNone(_compute_calibration_from_snapshot(snapshot))

    def test_layer_parameters_change_trade_frequency_in_builtin_runtime(self) -> None:
        fast_path = Path("test-layer-fast.json")
        slow_path = Path("test-layer-slow.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        base_payload = {
            "run_id": "layer-compare",
            "seed": 4,
            "runtime": {"mode": "builtin", "min_oos_trades": 4},
            "snapshot": {
                "snapshot_id": "layer-compare-snap",
                "symbol": "SOLUSDT",
                "venue": "binance",
                "timeframe": "1h",
                "candles": [
                    {
                        "timestamp": (start + timedelta(hours=hour)).isoformat(),
                        "open": 100 + hour,
                        "high": 101 + hour,
                        "low": 99 + hour,
                        "close": 100 + hour,
                        "volume": 1000.0,
                    }
                    for hour in range(120)
                ],
                "funding_rates": [0.0] * 120,
                "open_interest": [100.0] * 120,
                "liquidation_notional": [0.0] * 120,
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 5.0,
                "quality_flags": [],
            },
            "incumbent": {"backbone": "mom_squeeze"},
            "directional_layers": ["kama"],
            "known_good_filters": [],
            "custom_filters": [],
            "exit_layers": [],
            "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
        }
        # Fast config: small stride -> more trades
        fast_payload = dict(base_payload)
        fast_payload["layer_parameters"] = {
            "mom_squeeze": {"entry_stride": 2},
            "kama": {},
        }
        # Slow config: large stride -> far fewer trades (will fail min_oos_trades gate)
        slow_payload = dict(base_payload)
        slow_payload["layer_parameters"] = {
            "mom_squeeze": {"entry_stride": 60},
            "kama": {},
        }
        fast_path.write_text(json.dumps(fast_payload), encoding="utf-8")
        slow_path.write_text(json.dumps(slow_payload), encoding="utf-8")
        try:
            fast_study = load_study_config(fast_path)
            slow_study = load_study_config(slow_path)
        finally:
            fast_path.unlink()
            slow_path.unlink()

        fast_evaluator, _, _ = build_runtime_functions(fast_study)
        slow_evaluator, _, _ = build_runtime_functions(slow_study)
        layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)

        fast_eval = fast_evaluator(fast_study.incumbent, layer)
        slow_eval = slow_evaluator(slow_study.incumbent, layer)

        self.assertGreater(fast_eval.oos_result.trade_count, slow_eval.oos_result.trade_count)
        self.assertGreater(fast_eval.oos_result.net_pnl, slow_eval.oos_result.net_pnl)
        self.assertNotIn("min_oos_trades", fast_eval.decision.reasons)
        self.assertIn("min_oos_trades", slow_eval.decision.reasons)

    def test_parameter_grids_choose_best_candidate_settings_in_builtin_runtime(self) -> None:
        grid_path = Path("test-runtime-grid.json")
        fixed_path = Path("test-runtime-fixed.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        base_payload = {
            "run_id": "grid-compare",
            "seed": 6,
            "runtime": {"mode": "builtin", "min_oos_trades": 3},
            "snapshot": {
                "snapshot_id": "grid-compare-snap",
                "symbol": "SOLUSDT",
                "venue": "binance",
                "timeframe": "1h",
                "candles": [
                    {
                        "timestamp": (start + timedelta(hours=hour)).isoformat(),
                        "open": 100 + hour,
                        "high": 101 + hour,
                        "low": 99 + hour,
                        "close": 100 + hour,
                        "volume": 1000.0,
                    }
                    for hour in range(120)
                ],
                "funding_rates": [0.0] * 120,
                "open_interest": [100.0] * 120,
                "liquidation_notional": [0.0] * 120,
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 5.0,
                "quality_flags": [],
            },
            "incumbent": {"backbone": "mom_squeeze"},
            "directional_layers": ["kama"],
            "known_good_filters": [],
            "custom_filters": [],
            "exit_layers": [],
            "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
        }
        grid_payload = dict(base_payload)
        grid_payload["parameter_grids"] = {
            "kama": {
                "aggressiveness": {"minimum": 1.0, "maximum": 2.0, "step": 1.0},
                "mean_threshold_offset": {"minimum": 0.0, "maximum": 0.08, "step": 0.08},
            }
        }
        fixed_payload = dict(base_payload)
        fixed_payload["layer_parameters"] = {
            "kama": {"aggressiveness": 1.0, "mean_threshold_offset": 0.08},
        }
        grid_path.write_text(json.dumps(grid_payload), encoding="utf-8")
        fixed_path.write_text(json.dumps(fixed_payload), encoding="utf-8")
        try:
            grid_study = load_study_config(grid_path)
            fixed_study = load_study_config(fixed_path)
        finally:
            grid_path.unlink()
            fixed_path.unlink()

        grid_evaluator, _, _ = build_runtime_functions(grid_study)
        fixed_evaluator, _, _ = build_runtime_functions(fixed_study)
        layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)

        grid_eval = grid_evaluator(grid_study.incumbent, layer)
        fixed_eval = fixed_evaluator(fixed_study.incumbent, layer)

        # Grid search should find aggressiveness=2 (or 1) but either way selects best
        self.assertIn(grid_eval.selected_parameters["aggressiveness"], [1, 2])
        self.assertGreaterEqual(grid_eval.oos_result.net_pnl, fixed_eval.oos_result.net_pnl)
        self.assertGreaterEqual(len(grid_eval.search_summary), 2)
        self.assertGreaterEqual(grid_eval.search_summary[0]["oos_sharpe"], grid_eval.search_summary[-1]["oos_sharpe"])

    def test_builtin_runtime_generates_short_biased_entries_on_downtrends(self) -> None:
        long_path = Path("test-runtime-long-downtrend.json")
        short_path = Path("test-runtime-short-downtrend.json")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            {
                "timestamp": (start + timedelta(hours=hour)).isoformat(),
                "open": 200 - hour,
                "high": 201 - hour,
                "low": 199 - hour,
                "close": 200 - hour,
                "volume": 1000.0,
            }
            for hour in range(120)
        ]
        base_payload = {
            "run_id": "short-downtrend",
            "seed": 9,
            "runtime": {"mode": "builtin", "min_oos_trades": 3},
            "snapshot": {
                "snapshot_id": "short-downtrend-snap",
                "symbol": "SOLUSDT",
                "venue": "binance",
                "timeframe": "1h",
                "candles": candles,
                "funding_rates": [0.0] * len(candles),
                "open_interest": [100.0] * len(candles),
                "liquidation_notional": [0.0] * len(candles),
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 5.0,
                "quality_flags": [],
            },
            "incumbent": {"backbone": "mom_squeeze"},
            "directional_layers": ["kama"],
            "known_good_filters": [],
            "custom_filters": [],
            "exit_layers": [],
            "scenarios": [{"name": "attention-burst", "severity": 0.6, "description": "Attention shock"}],
        }
        long_payload = dict(base_payload)
        short_payload = dict(base_payload)
        long_payload["runtime"] = {"mode": "builtin", "min_oos_trades": 3, "position_side": "long"}
        short_payload["runtime"] = {"mode": "builtin", "min_oos_trades": 3, "position_side": "short"}
        long_path.write_text(json.dumps(long_payload), encoding="utf-8")
        short_path.write_text(json.dumps(short_payload), encoding="utf-8")
        try:
            long_study = load_study_config(long_path)
            short_study = load_study_config(short_path)
        finally:
            long_path.unlink()
            short_path.unlink()

        long_evaluator, _, _ = build_runtime_functions(long_study)
        short_evaluator, _, _ = build_runtime_functions(short_study)
        layer = LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)

        long_eval = long_evaluator(long_study.incumbent, layer)
        short_eval = short_evaluator(short_study.incumbent, layer)

        self.assertEqual(long_eval.oos_result.trade_count, 0)
        self.assertGreater(short_eval.oos_result.trade_count, 0)
        self.assertGreater(short_eval.oos_result.net_pnl, long_eval.oos_result.net_pnl)

    def test_apply_layer_adjustments_is_a_pass_through(self) -> None:
        """After removing synthetic inflation, _apply_layer_adjustments returns the
        result unchanged regardless of layers or position side."""
        base_result = BacktestResult(
            trade_count=10,
            win_rate=0.5,
            gross_pnl=12.0,
            net_pnl=10.0,
            fee_spend=0.5,
            funding_spend=0.1,
            sharpe=1.0,
            sortino=1.1,
            max_drawdown=-0.2,
            equity_curve=[1.0, 1.1, 1.2],
            liquidation_events=[],
        )
        strategy = StrategyGraph(
            backbone="mom_squeeze",
            layers=[LayerSpec(name="kama", family=LayerFamily.DIRECTIONAL_FILTER)],
        )
        layer_parameters = {"kama": {"aggressiveness": 2.0}}

        long_adjusted = _apply_layer_adjustments(base_result, strategy, layer_parameters, "long")
        short_adjusted = _apply_layer_adjustments(base_result, strategy, layer_parameters, "short")

        # Pass-through: both sides return the original result unchanged
        self.assertEqual(long_adjusted.sharpe, base_result.sharpe)
        self.assertEqual(short_adjusted.sharpe, base_result.sharpe)
        self.assertEqual(long_adjusted.net_pnl, base_result.net_pnl)
        self.assertEqual(short_adjusted.net_pnl, base_result.net_pnl)

    def test_apply_scenario_stress_penalizes_short_side_under_squeeze_conditions(self) -> None:
        baseline = BacktestResult(
            trade_count=8,
            win_rate=0.5,
            gross_pnl=15.0,
            net_pnl=12.0,
            fee_spend=0.4,
            funding_spend=0.2,
            sharpe=1.2,
            sortino=1.3,
            max_drawdown=-0.18,
            equity_curve=[1.0, 1.08, 1.12],
            liquidation_events=[],
        )
        snapshot = DataSnapshot(
            snapshot_id="scenario-short-pressure",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(
                    timestamp=start,
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1000.0,
                )
                for start in [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=hour) for hour in range(6)]
            ],
            funding_rates=[0.01] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[40.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        scenario = StressScenario(name="short-squeeze", severity=0.8, description="short squeeze")

        long_stressed = _apply_scenario_stress(baseline, scenario, 0.8, "long", snapshot)
        short_stressed = _apply_scenario_stress(baseline, scenario, 0.8, "short", snapshot)

        self.assertLess(short_stressed.net_pnl, long_stressed.net_pnl)
        self.assertGreater(short_stressed.funding_spend, long_stressed.funding_spend)
        self.assertLess(short_stressed.max_drawdown, long_stressed.max_drawdown)

    def test_apply_scenario_stress_respects_scenario_specific_knobs(self) -> None:
        baseline = BacktestResult(
            trade_count=8,
            win_rate=0.5,
            gross_pnl=20.0,
            net_pnl=16.0,
            fee_spend=0.4,
            funding_spend=0.2,
            sharpe=1.2,
            sortino=1.3,
            max_drawdown=-0.18,
            equity_curve=[1.0, 1.08, 1.16],
            liquidation_events=[],
        )
        snapshot = DataSnapshot(
            snapshot_id="scenario-knobs",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=hour),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1000.0,
                )
                for hour in range(6)
            ],
            funding_rates=[0.01] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[20.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        generic = StressScenario(name="liquidity-withdrawal", severity=0.7, description="generic stress")
        stressed = StressScenario(
            name="liquidity-withdrawal",
            severity=0.7,
            description="stress with explicit knobs",
            funding_multiplier=2.5,
            liquidity_penalty_bps=75.0,
            drawdown_multiplier=1.4,
            mark_premium_bps=120.0,
        )

        generic_result = _apply_scenario_stress(baseline, generic, 0.7, "long", snapshot)
        stressed_result = _apply_scenario_stress(baseline, stressed, 0.7, "long", snapshot)

        self.assertGreater(stressed_result.funding_spend, generic_result.funding_spend)
        self.assertGreater(stressed_result.fee_spend, generic_result.fee_spend)
        self.assertLess(stressed_result.net_pnl, generic_result.net_pnl)
        self.assertLess(stressed_result.max_drawdown, generic_result.max_drawdown)

    def test_apply_scenario_stress_keeps_net_pnl_consistent_with_components(self) -> None:
        baseline = BacktestResult(
            trade_count=8,
            win_rate=0.5,
            gross_pnl=20.0,
            net_pnl=16.0,
            fee_spend=0.4,
            funding_spend=0.2,
            sharpe=1.2,
            sortino=1.3,
            max_drawdown=-0.18,
            equity_curve=[1.0, 1.08, 1.16],
            liquidation_events=[],
        )
        snapshot = DataSnapshot(
            snapshot_id="scenario-consistency",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=hour),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1000.0,
                )
                for hour in range(6)
            ],
            funding_rates=[0.01] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[20.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        stressed = _apply_scenario_stress(
            baseline,
            StressScenario(
                name="liquidity-withdrawal",
                severity=0.7,
                description="stress with explicit knobs",
                funding_multiplier=2.5,
                liquidity_penalty_bps=75.0,
                drawdown_multiplier=1.4,
            ),
            0.7,
            "long",
            snapshot,
        )

        self.assertAlmostEqual(stressed.net_pnl, stressed.gross_pnl - stressed.fee_spend - stressed.funding_spend, places=8)

    def test_apply_scenario_stress_does_not_amplify_negative_funding_benefit(self) -> None:
        baseline = BacktestResult(
            trade_count=8,
            win_rate=0.5,
            gross_pnl=20.0,
            net_pnl=20.2,
            fee_spend=0.0,
            funding_spend=-0.2,
            sharpe=1.2,
            sortino=1.3,
            max_drawdown=-0.18,
            equity_curve=[1.0, 1.08, 1.16],
            liquidation_events=[],
        )
        snapshot = DataSnapshot(
            snapshot_id="scenario-signed-funding",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=hour),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1000.0,
                )
                for hour in range(6)
            ],
            funding_rates=[-0.01] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[20.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        stressed = _apply_scenario_stress(
            baseline,
            StressScenario(
                name="short-squeeze",
                severity=0.8,
                description="short squeeze",
                funding_multiplier=2.0,
            ),
            0.8,
            "short",
            snapshot,
        )

        self.assertGreater(stressed.funding_spend, baseline.funding_spend)
        self.assertGreaterEqual(stressed.funding_spend, -0.2)
        self.assertLess(stressed.net_pnl, baseline.net_pnl)

    def test_resolve_scenario_runtime_inputs_keeps_static_snapshot_unchanged(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        scenario = StressScenario(name="liquidation_cascade", severity=0.9, description="cascade")

        active_snapshot, active_scenario = _resolve_scenario_runtime_inputs(snapshot, scenario, seed=7)
        resolved = resolve_scenario_profile(scenario, venue=snapshot.venue)

        self.assertEqual(
            [candle.close for candle in active_snapshot.candles],
            [candle.close for candle in snapshot.candles],
        )
        self.assertEqual(active_scenario.liquidation_multiplier, resolved.liquidation_multiplier)
        self.assertEqual(active_scenario.calibration_mode, "static")

    def test_resolve_scenario_runtime_inputs_applies_calibrated_profile_and_stressed_path(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        scenario = StressScenario(
            name="liquidation_cascade",
            severity=0.9,
            description="cascade",
            calibration_mode="calibrated",
        )

        active_snapshot, active_scenario = _resolve_scenario_runtime_inputs(snapshot, scenario, seed=7)
        resolved = resolve_scenario_profile(scenario, venue=snapshot.venue)

        self.assertEqual(len(active_snapshot.candles), len(snapshot.candles))
        self.assertNotEqual(
            [candle.close for candle in active_snapshot.candles],
            [candle.close for candle in snapshot.candles],
        )
        self.assertGreater(active_scenario.liquidation_multiplier, resolved.liquidation_multiplier)
        self.assertGreater(active_scenario.hawkes_cascade_multiplier, 1.0)
        self.assertGreater(active_scenario.jump_severity_factor, 1.0)

    def test_resolve_scenario_runtime_inputs_applies_joint_crypto_dislocation_calibration(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        scenario = StressScenario(
            name="joint_crypto_dislocation",
            severity=0.92,
            description="joint crypto dislocation",
            calibration_mode="calibrated",
        )

        active_snapshot, active_scenario = _resolve_scenario_runtime_inputs(snapshot, scenario, seed=7)
        resolved = resolve_scenario_profile(scenario, venue=snapshot.venue)

        self.assertNotEqual(
            [candle.close for candle in active_snapshot.candles],
            [candle.close for candle in snapshot.candles],
        )
        self.assertGreater(active_scenario.funding_multiplier, resolved.funding_multiplier)
        self.assertGreater(active_scenario.liquidation_multiplier, resolved.liquidation_multiplier)
        self.assertGreater(active_scenario.spread_multiplier, resolved.spread_multiplier)
        self.assertLess(active_scenario.depth_multiplier, resolved.depth_multiplier)
        self.assertGreater(active_scenario.latency_multiplier, resolved.latency_multiplier)
        self.assertGreater(active_scenario.mark_premium_bps, resolved.mark_premium_bps)
        self.assertGreater(active_scenario.index_basis_bps, resolved.index_basis_bps)
        self.assertEqual(active_snapshot.provenance["scenario_name"], "joint_crypto_dislocation")
        self.assertIn("dislocation_summary", active_snapshot.provenance)

    def test_joint_crypto_dislocation_worsens_realistic_execution_and_liquidation_pressure(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        strategy = StrategyGraph(backbone="mom_squeeze")
        neutral = StressScenario(name="neutral", severity=0.92, description="neutral")
        dislocation = StressScenario(
            name="joint_crypto_dislocation",
            severity=0.92,
            description="joint crypto dislocation",
            calibration_mode="calibrated",
        )

        baseline = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=neutral,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
            slippage_model="realistic",
        )
        stressed_snapshot, stressed_scenario = _resolve_scenario_runtime_inputs(snapshot, dislocation, seed=7)
        stressed = _apply_scenario_execution_overlay(
            snapshot=stressed_snapshot,
            strategy=strategy,
            scenario=stressed_scenario,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
            slippage_model="realistic",
        )

        self.assertGreater(stressed.fee_spend, baseline.fee_spend)
        self.assertLess(stressed.net_pnl, baseline.net_pnl)
        self.assertGreaterEqual(len(stressed.liquidation_events), len(baseline.liquidation_events))

    def test_resolve_scenario_runtime_inputs_applies_microstructure_stress_when_typed_fields_present(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        scenario = StressScenario(
            name="microstructure-stress",
            severity=0.8,
            description="microstructure stress",
            spread_multiplier=2.0,
            depth_multiplier=0.25,
            latency_multiplier=3.0,
        )

        active_snapshot, active_scenario = _resolve_scenario_runtime_inputs(snapshot, scenario, seed=7)

        self.assertEqual(active_scenario.spread_multiplier, 2.0)
        self.assertEqual(active_scenario.depth_multiplier, 0.25)
        self.assertEqual(active_scenario.latency_multiplier, 3.0)
        self.assertEqual(active_snapshot.spread_bps[0], snapshot.spread_bps[0] * 2.0)
        self.assertEqual(active_snapshot.depth_bid_1bp_usd[0], snapshot.depth_bid_1bp_usd[0] * 0.25)
        self.assertEqual(active_snapshot.depth_ask_1bp_usd[0], snapshot.depth_ask_1bp_usd[0] * 0.25)
        self.assertEqual(active_snapshot.latency_proxy_ms[0], snapshot.latency_proxy_ms[0] * 3.0)
        self.assertEqual(active_snapshot.provenance["transformation"], "scenario_microstructure_stress")
        self.assertEqual(active_snapshot.provenance["scenario_name"], "microstructure-stress")

    def test_resolve_scenario_runtime_inputs_stamps_mark_index_dislocation_summary(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        scenario = StressScenario(
            name="mark_index_dislocation",
            severity=0.75,
            description="mark/index dislocation",
            mark_premium_bps=140.0,
            index_basis_bps=85.0,
            premium_spike_bars=3,
        )

        active_snapshot, active_scenario = _resolve_scenario_runtime_inputs(snapshot, scenario, seed=7)

        self.assertEqual(active_scenario.mark_premium_bps, 140.0)
        self.assertEqual(active_scenario.index_basis_bps, 85.0)
        self.assertEqual(active_scenario.premium_spike_bars, 3)
        self.assertEqual(active_snapshot.provenance["transformation"], "scenario_mark_index_dislocation")
        self.assertEqual(active_snapshot.provenance["scenario_name"], "mark_index_dislocation")
        self.assertEqual(
            active_snapshot.provenance["dislocation_summary"],
            {
                "mark_premium_bps": 140.0,
                "index_basis_bps": 85.0,
                "premium_spike_bars": 3,
            },
        )

    def test_resolve_scenario_runtime_inputs_stamps_execution_overlay_summary(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        scenario = StressScenario(
            name="venue_outage",
            severity=0.9,
            description="Venue disruption",
            liquidity_penalty_bps=55.0,
            latency_delta_bars=2,
        )

        active_snapshot, _active_scenario = _resolve_scenario_runtime_inputs(snapshot, scenario, seed=7)

        self.assertEqual(
            active_snapshot.provenance["scenario_execution_overlay"],
            {
                "scenario_name": "venue_outage",
                "liquidity_penalty_bps": 55.0,
                "latency_delta_bars": 2,
            },
        )

    def test_scenario_microstructure_stress_worsens_realistic_slippage(self) -> None:
        snapshot = DataSnapshot(
            snapshot_id="scenario-realistic-microstructure",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=0), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=1), open=100.0, high=102.0, low=100.0, close=101.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=2), open=101.0, high=104.0, low=96.0, close=103.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=3), open=103.0, high=105.0, low=102.0, close=104.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4), open=104.0, high=106.0, low=103.0, close=105.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=5), open=105.0, high=107.0, low=104.0, close=106.0, volume=1000.0),
            ],
            funding_rates=[0.0] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[0.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            spread_bps=[2.0] * 6,
            depth_bid_1bp_usd=[4_000_000.0] * 6,
            depth_ask_1bp_usd=[4_000_000.0] * 6,
            latency_proxy_ms=[12.0] * 6,
            quality_flags=[],
        )
        strategy = StrategyGraph(backbone="mom_squeeze")
        neutral = StressScenario(name="neutral", severity=0.8, description="neutral")
        microstructure_stress = StressScenario(
            name="microstructure-stress",
            severity=0.8,
            description="microstructure stress",
            spread_multiplier=4.0,
            depth_multiplier=0.1,
            latency_multiplier=5.0,
        )

        baseline = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=neutral,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
            slippage_model="realistic",
        )
        stressed_snapshot, stressed_scenario = _resolve_scenario_runtime_inputs(snapshot, microstructure_stress, seed=7)
        stressed = _apply_scenario_execution_overlay(
            snapshot=stressed_snapshot,
            strategy=strategy,
            scenario=stressed_scenario,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
            slippage_model="realistic",
        )

        self.assertGreater(stressed.fee_spend, baseline.fee_spend)
        self.assertLess(stressed.net_pnl, baseline.net_pnl)

    def test_mark_index_dislocation_can_trigger_liquidation_when_mark_proxy_alone_would_not(self) -> None:
        snapshot = DataSnapshot(
            snapshot_id="scenario-mark-dislocation",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=0), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=1), open=100.0, high=102.0, low=100.0, close=101.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=2), open=102.0, high=103.0, low=82.5, close=82.5, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=3), open=103.0, high=104.0, low=102.0, close=103.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4), open=104.0, high=110.0, low=103.0, close=109.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=5), open=109.0, high=110.0, low=108.0, close=109.0, volume=1000.0),
            ],
            funding_rates=[0.0] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[0.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        strategy = StrategyGraph(backbone="mom_squeeze")
        neutral = StressScenario(name="neutral", severity=0.75, description="neutral")
        dislocation = StressScenario(
            name="mark_index_dislocation",
            severity=0.75,
            description="mark/index dislocation",
            mark_premium_bps=110.0,
            index_basis_bps=65.0,
            premium_spike_bars=2,
        )

        baseline = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=neutral,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
            slippage_model="flat",
        )
        stressed = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=dislocation,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
            slippage_model="flat",
        )

        self.assertEqual(baseline.liquidation_events, [])
        self.assertEqual(len(stressed.liquidation_events), 1)

    def test_index_basis_dislocation_worsens_outcome_relative_to_mark_only(self) -> None:
        snapshot = DataSnapshot(
            snapshot_id="scenario-index-basis",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=0), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=1), open=100.0, high=102.0, low=100.0, close=101.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=2), open=102.0, high=103.0, low=82.5, close=82.5, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=3), open=103.0, high=104.0, low=102.0, close=103.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4), open=104.0, high=110.0, low=103.0, close=109.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=5), open=109.0, high=110.0, low=108.0, close=109.0, volume=1000.0),
            ],
            funding_rates=[0.0] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[0.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        strategy = StrategyGraph(backbone="mom_squeeze")
        mark_only = StressScenario(
            name="custom_mark_only_dislocation",
            severity=0.75,
            description="mark-only dislocation",
            mark_premium_bps=110.0,
            index_basis_bps=0.0,
            premium_spike_bars=0,
        )
        mark_plus_basis = StressScenario(
            name="custom_mark_plus_basis_dislocation",
            severity=0.75,
            description="mark+basis dislocation",
            mark_premium_bps=110.0,
            index_basis_bps=65.0,
            premium_spike_bars=2,
        )

        mark_only_result = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=mark_only,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
            slippage_model="flat",
        )
        mark_plus_basis_result = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=mark_plus_basis,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=5.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
            slippage_model="flat",
        )

        self.assertLess(mark_plus_basis_result.net_pnl, mark_only_result.net_pnl)

    def test_bootstrap_strategy_with_settings_resamples_typed_microstructure_for_multivariate_method(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        strategy = StrategyGraph(backbone="mom_squeeze")
        captured_snapshots: list[DataSnapshot] = []

        def _fake_evaluate(resampled_snapshot: DataSnapshot, *_args, **_kwargs) -> BacktestResult:
            captured_snapshots.append(resampled_snapshot)
            return BacktestResult(
                trade_count=4,
                win_rate=0.5,
                gross_pnl=10.0,
                net_pnl=8.0,
                fee_spend=1.0,
                funding_spend=1.0,
                sharpe=1.0,
                sortino=1.0,
                max_drawdown=-0.1,
                equity_curve=[1.0, 1.02, 1.01],
                liquidation_events=[],
            )

        with patch("engine.app.runtime._evaluate_strategy_with_settings", side_effect=_fake_evaluate):
            _bootstrap_strategy_with_settings(
                snapshot,
                strategy,
                layer_parameters={},
                slippage_bps=0.0,
                latency_bars=0,
                position_side="long",
                position_leverage=1.0,
                maintenance_margin_ratio=0.01,
                liquidation_fee_bps=0.0,
                liquidation_mark_price_weight=0.0,
                partial_liquidation_ratio=1.0,
                liquidation_cooldown_bars=0,
                liquidation_step_schedule=[],
                liquidation_mark_premium_bps=0.0,
                maintenance_margin_schedule=[],
                liquidation_fee_schedule=[],
                slippage_model="realistic",
                bootstrap_samples=1,
                bootstrap_block_size=4,
                bootstrap_method="multivariate_block",
            )

        self.assertEqual(len(captured_snapshots), 1)
        bootstrap_indices = multivariate_block_bootstrap_indices(
            sample_count=len(snapshot.candles),
            block_size=4,
            seed=0,
        )
        resampled_snapshot = captured_snapshots[0]
        self.assertEqual(
            resampled_snapshot.spread_bps,
            [snapshot.spread_bps[index] for index in bootstrap_indices],
        )
        self.assertEqual(
            resampled_snapshot.depth_bid_1bp_usd,
            [snapshot.depth_bid_1bp_usd[index] for index in bootstrap_indices],
        )
        self.assertEqual(
            resampled_snapshot.depth_ask_1bp_usd,
            [snapshot.depth_ask_1bp_usd[index] for index in bootstrap_indices],
        )
        self.assertEqual(
            resampled_snapshot.latency_proxy_ms,
            [snapshot.latency_proxy_ms[index] for index in bootstrap_indices],
        )

    def test_bootstrap_strategy_with_settings_applies_microstructure_overlay_and_provenance(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        strategy = StrategyGraph(backbone="mom_squeeze")
        captured_snapshots: list[DataSnapshot] = []

        def _fake_evaluate(resampled_snapshot: DataSnapshot, *_args, **_kwargs) -> BacktestResult:
            captured_snapshots.append(resampled_snapshot)
            return BacktestResult(
                trade_count=4,
                win_rate=0.5,
                gross_pnl=10.0,
                net_pnl=8.0,
                fee_spend=1.0,
                funding_spend=1.0,
                sharpe=1.0,
                sortino=1.0,
                max_drawdown=-0.1,
                equity_curve=[1.0, 1.02, 1.01],
                liquidation_events=[],
            )

        with patch("engine.app.runtime._evaluate_strategy_with_settings", side_effect=_fake_evaluate):
            _bootstrap_strategy_with_settings(
                snapshot,
                strategy,
                layer_parameters={},
                slippage_bps=0.0,
                latency_bars=0,
                position_side="long",
                position_leverage=1.0,
                maintenance_margin_ratio=0.01,
                liquidation_fee_bps=0.0,
                liquidation_mark_price_weight=0.0,
                partial_liquidation_ratio=1.0,
                liquidation_cooldown_bars=0,
                liquidation_step_schedule=[],
                liquidation_mark_premium_bps=0.0,
                maintenance_margin_schedule=[],
                liquidation_fee_schedule=[],
                slippage_model="realistic",
                bootstrap_samples=1,
                bootstrap_block_size=4,
                bootstrap_method="multivariate_block",
                bootstrap_spread_multiplier=4.0,
                bootstrap_depth_multiplier=0.1,
                bootstrap_latency_multiplier=5.0,
            )

        self.assertEqual(len(captured_snapshots), 1)
        bootstrap_indices = multivariate_block_bootstrap_indices(
            sample_count=len(snapshot.candles),
            block_size=4,
            seed=0,
        )
        resampled_snapshot = captured_snapshots[0]
        self.assertEqual(
            resampled_snapshot.spread_bps,
            [snapshot.spread_bps[index] * 4.0 for index in bootstrap_indices],
        )
        self.assertEqual(
            resampled_snapshot.depth_bid_1bp_usd,
            [snapshot.depth_bid_1bp_usd[index] * 0.1 for index in bootstrap_indices],
        )
        self.assertEqual(
            resampled_snapshot.depth_ask_1bp_usd,
            [snapshot.depth_ask_1bp_usd[index] * 0.1 for index in bootstrap_indices],
        )
        self.assertEqual(
            resampled_snapshot.latency_proxy_ms,
            [snapshot.latency_proxy_ms[index] * 5.0 for index in bootstrap_indices],
        )
        self.assertTrue(resampled_snapshot.provenance["bootstrap_microstructure_overlay_applied"])
        self.assertEqual(resampled_snapshot.provenance["bootstrap_spread_multiplier"], 4.0)
        self.assertEqual(resampled_snapshot.provenance["bootstrap_depth_multiplier"], 0.1)
        self.assertEqual(resampled_snapshot.provenance["bootstrap_latency_multiplier"], 5.0)

    def test_bootstrap_strategy_with_settings_accepts_dependent_wild_method(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        strategy = StrategyGraph(backbone="mom_squeeze")
        captured_snapshots: list[DataSnapshot] = []

        def _fake_evaluate(resampled_snapshot: DataSnapshot, *_args, **_kwargs) -> BacktestResult:
            captured_snapshots.append(resampled_snapshot)
            return BacktestResult(
                trade_count=4,
                win_rate=0.5,
                gross_pnl=10.0,
                net_pnl=8.0,
                fee_spend=1.0,
                funding_spend=1.0,
                sharpe=1.0,
                sortino=1.0,
                max_drawdown=-0.1,
                equity_curve=[1.0, 1.02, 1.01],
                liquidation_events=[],
            )

        with patch("engine.app.runtime._evaluate_strategy_with_settings", side_effect=_fake_evaluate):
            report = _bootstrap_strategy_with_settings(
                snapshot,
                strategy,
                layer_parameters={},
                slippage_bps=0.0,
                latency_bars=0,
                position_side="long",
                position_leverage=1.0,
                maintenance_margin_ratio=0.01,
                liquidation_fee_bps=0.0,
                liquidation_mark_price_weight=0.0,
                partial_liquidation_ratio=1.0,
                liquidation_cooldown_bars=0,
                liquidation_step_schedule=[],
                liquidation_mark_premium_bps=0.0,
                maintenance_margin_schedule=[],
                liquidation_fee_schedule=[],
                slippage_model="realistic",
                bootstrap_samples=1,
                bootstrap_block_size=4,
                bootstrap_method="dependent_wild",
            )

        self.assertEqual(report.bootstrap_method, "dependent_wild")
        self.assertEqual(len(captured_snapshots), 1)
        self.assertEqual(captured_snapshots[0].provenance["transformation"], "dependent_wild_bootstrap")

    def test_bootstrap_microstructure_overlay_worsens_realistic_slippage(self) -> None:
        snapshot = _phase14_snapshot(clustered=True)
        strategy = StrategyGraph(backbone="mom_squeeze")

        def _simulate_from_snapshot(resampled_snapshot: DataSnapshot, *_args, **_kwargs) -> BacktestResult:
            entry = [False] * len(resampled_snapshot.candles)
            exit_ = [False] * len(resampled_snapshot.candles)
            entry[min(2, len(entry) - 3)] = True
            exit_[len(exit_) - 2] = True
            return simulate_strategy(
                resampled_snapshot,
                entry,
                exit_,
                slippage_bps=0.0,
                slippage_model="realistic",
            )

        with patch("engine.app.runtime._evaluate_strategy_with_settings", side_effect=_simulate_from_snapshot):
            baseline = _bootstrap_strategy_with_settings(
                snapshot,
                strategy,
                layer_parameters={},
                slippage_bps=0.0,
                latency_bars=0,
                position_side="long",
                position_leverage=1.0,
                maintenance_margin_ratio=0.01,
                liquidation_fee_bps=0.0,
                liquidation_mark_price_weight=0.0,
                partial_liquidation_ratio=1.0,
                liquidation_cooldown_bars=0,
                liquidation_step_schedule=[],
                liquidation_mark_premium_bps=0.0,
                maintenance_margin_schedule=[],
                liquidation_fee_schedule=[],
                slippage_model="realistic",
                bootstrap_samples=1,
                bootstrap_block_size=4,
                bootstrap_method="multivariate_block",
                bootstrap_spread_multiplier=1.0,
                bootstrap_depth_multiplier=1.0,
                bootstrap_latency_multiplier=1.0,
            )
            stressed = _bootstrap_strategy_with_settings(
                snapshot,
                strategy,
                layer_parameters={},
                slippage_bps=0.0,
                latency_bars=0,
                position_side="long",
                position_leverage=1.0,
                maintenance_margin_ratio=0.01,
                liquidation_fee_bps=0.0,
                liquidation_mark_price_weight=0.0,
                partial_liquidation_ratio=1.0,
                liquidation_cooldown_bars=0,
                liquidation_step_schedule=[],
                liquidation_mark_premium_bps=0.0,
                maintenance_margin_schedule=[],
                liquidation_fee_schedule=[],
                slippage_model="realistic",
                bootstrap_samples=1,
                bootstrap_block_size=4,
                bootstrap_method="multivariate_block",
                bootstrap_spread_multiplier=4.0,
                bootstrap_depth_multiplier=0.1,
                bootstrap_latency_multiplier=5.0,
            )

        self.assertLess(stressed.median_net_profit, baseline.median_net_profit)
        self.assertLess(stressed.worst_case_net_profit, baseline.worst_case_net_profit)

    def test_scenario_execution_overlay_changes_simulated_path(self) -> None:
        snapshot = DataSnapshot(
            snapshot_id="scenario-execution-overlay",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=0), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=1), open=100.0, high=102.0, low=100.0, close=101.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=2), open=101.0, high=104.0, low=96.0, close=103.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=3), open=103.0, high=105.0, low=102.0, close=104.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4), open=104.0, high=106.0, low=103.0, close=105.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=5), open=105.0, high=107.0, low=104.0, close=106.0, volume=1000.0),
            ],
            funding_rates=[0.0] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[0.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        strategy = StrategyGraph(backbone="mom_squeeze")
        scenario = StressScenario(
            name="outage-shock",
            severity=0.8,
            description="execution overlay stress",
            liquidity_penalty_bps=40.0,
            latency_delta_bars=1,
            mark_premium_bps=600.0,
        )

        baseline = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=StressScenario(name="baseline", severity=0.8, description="baseline"),
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
        )
        stressed = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=scenario,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
        )

        self.assertGreater(stressed.fee_spend, baseline.fee_spend)
        self.assertLess(stressed.net_pnl, baseline.net_pnl)
        self.assertGreater(len(stressed.liquidation_events), len(baseline.liquidation_events))

    def test_named_scenario_preset_reaches_execution_overlay(self) -> None:
        snapshot = DataSnapshot(
            snapshot_id="scenario-preset-overlay",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=0), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=1), open=100.0, high=102.0, low=100.0, close=101.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=2), open=101.0, high=104.0, low=96.0, close=103.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=3), open=103.0, high=105.0, low=102.0, close=104.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4), open=104.0, high=106.0, low=103.0, close=105.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=5), open=105.0, high=107.0, low=104.0, close=106.0, volume=1000.0),
            ],
            funding_rates=[0.0] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[0.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        strategy = StrategyGraph(backbone="mom_squeeze")

        neutral = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=StressScenario(name="custom-neutral", severity=0.8, description="neutral"),
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
        )
        preset = _apply_scenario_execution_overlay(
            snapshot=snapshot,
            strategy=strategy,
            scenario=StressScenario(name="outage-shock", severity=0.8, description="preset"),
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
        )

        self.assertGreater(preset.fee_spend, neutral.fee_spend)
        self.assertLess(preset.net_pnl, neutral.net_pnl)

    def test_venue_specific_named_scenario_preset_changes_execution_overlay(self) -> None:
        base_snapshot = DataSnapshot(
            snapshot_id="scenario-venue-preset-overlay",
            symbol="SOLUSDT",
            venue="generic",
            timeframe="1h",
            candles=[
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=0), open=100.0, high=101.0, low=99.0, close=100.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=1), open=100.0, high=102.0, low=100.0, close=101.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=2), open=101.0, high=104.0, low=96.0, close=103.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=3), open=103.0, high=105.0, low=102.0, close=104.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=4), open=104.0, high=106.0, low=103.0, close=105.0, volume=1000.0),
                Candle(timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=5), open=105.0, high=107.0, low=104.0, close=106.0, volume=1000.0),
            ],
            funding_rates=[0.0] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[0.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        binance_snapshot = DataSnapshot(
            snapshot_id=base_snapshot.snapshot_id,
            symbol=base_snapshot.symbol,
            venue="binance",
            timeframe=base_snapshot.timeframe,
            candles=list(base_snapshot.candles),
            funding_rates=list(base_snapshot.funding_rates),
            open_interest=list(base_snapshot.open_interest),
            liquidation_notional=list(base_snapshot.liquidation_notional),
            maker_fee_bps=base_snapshot.maker_fee_bps,
            taker_fee_bps=base_snapshot.taker_fee_bps,
            quality_flags=list(base_snapshot.quality_flags),
        )
        strategy = StrategyGraph(backbone="mom_squeeze")
        scenario = StressScenario(name="outage-shock", severity=0.8, description="preset")

        generic_result = _apply_scenario_execution_overlay(
            snapshot=base_snapshot,
            strategy=strategy,
            scenario=scenario,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
        )
        binance_result = _apply_scenario_execution_overlay(
            snapshot=binance_snapshot,
            strategy=strategy,
            scenario=scenario,
            layer_parameters={},
            slippage_bps=0.0,
            latency_bars=0,
            position_side="long",
            position_leverage=20.0,
            maintenance_margin_ratio=0.01,
            liquidation_fee_bps=0.0,
            liquidation_mark_price_weight=1.0,
            partial_liquidation_ratio=1.0,
            liquidation_cooldown_bars=0,
            liquidation_step_schedule=[],
            liquidation_mark_premium_bps=0.0,
            maintenance_margin_schedule=[],
            liquidation_fee_schedule=[],
        )

        self.assertGreaterEqual(binance_result.fee_spend, generic_result.fee_spend)
        self.assertLessEqual(binance_result.net_pnl, generic_result.net_pnl)

    def test_derive_stress_metrics_emphasizes_basis_and_cascade_pressure(self) -> None:
        snapshot = DataSnapshot(
            snapshot_id="stress-metrics",
            symbol="SOLUSDT",
            venue="binance",
            timeframe="1h",
            candles=[
                Candle(
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=hour),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=1000.0,
                )
                for hour in range(6)
            ],
            funding_rates=[0.015] * 6,
            open_interest=[100.0] * 6,
            liquidation_notional=[45.0] * 6,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            quality_flags=[],
        )
        baseline = BacktestResult(
            trade_count=8,
            win_rate=0.5,
            gross_pnl=20.0,
            net_pnl=16.0,
            fee_spend=0.4,
            funding_spend=0.2,
            sharpe=1.2,
            sortino=1.3,
            max_drawdown=-0.18,
            equity_curve=[1.0, 1.08, 1.16],
            liquidation_events=[],
        )
        stressed = BacktestResult(
            trade_count=8,
            win_rate=0.4,
            gross_pnl=14.0,
            net_pnl=8.0,
            fee_spend=1.2,
            funding_spend=0.9,
            sharpe=0.7,
            sortino=0.8,
            max_drawdown=-0.32,
            equity_curve=[1.0, 1.01, 0.92],
            liquidation_events=["synthetic-liquidation", "follow-on-liquidation"],
        )

        funding_basis = _derive_stress_metrics(
            baseline=baseline,
            stressed=stressed,
            scenario=StressScenario("funding_basis_shock", 0.8, "Basis stress"),
            snapshot=snapshot,
        )
        cascade = _derive_stress_metrics(
            baseline=baseline,
            stressed=stressed,
            scenario=StressScenario("liquidation_cascade", 0.9, "Cascade stress"),
            snapshot=snapshot,
        )

        self.assertGreater(funding_basis.basis_stress_score, 0.0)
        self.assertGreater(cascade.cascade_liquidation_count, 0)
        self.assertGreater(cascade.stress_tail_slippage, 0.0)


if __name__ == "__main__":
    unittest.main()


def _phase14_snapshot(clustered: bool) -> DataSnapshot:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    closes = [100.0, 101.0, 102.0, 104.0, 91.0, 89.0, 94.0, 96.0, 95.0, 97.0]
    liquidation_notional = (
        [0.0, 0.0, 35.0, 50.0, 65.0, 45.0, 0.0, 0.0, 0.0, 0.0]
        if clustered
        else [0.0, 10.0, 0.0, 12.0, 0.0, 11.0, 0.0, 9.0, 0.0, 8.0]
    )
    candles = [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=close - 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=1_000.0 + index,
        )
        for index, close in enumerate(closes)
    ]
    return DataSnapshot(
        snapshot_id=f"phase14-runtime-{int(clustered)}",
        symbol="SOLUSDT",
        venue="binance",
        timeframe="1h",
        candles=candles,
        funding_rates=[0.004, 0.003, 0.004, 0.006, 0.011, 0.008, 0.005, 0.004, 0.003, 0.002],
        open_interest=[100.0, 103.0, 108.0, 116.0, 130.0, 136.0, 133.0, 128.0, 126.0, 124.0],
        liquidation_notional=liquidation_notional,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        spread_bps=[2.0, 2.1, 2.0, 2.2, 2.8, 3.0, 2.6, 2.4, 2.3, 2.2],
        depth_bid_1bp_usd=[4_000_000.0, 3_800_000.0, 3_700_000.0, 3_400_000.0, 1_600_000.0, 1_200_000.0, 1_800_000.0, 2_100_000.0, 2_300_000.0, 2_500_000.0],
        depth_ask_1bp_usd=[3_900_000.0, 3_700_000.0, 3_600_000.0, 3_300_000.0, 1_500_000.0, 1_100_000.0, 1_700_000.0, 2_000_000.0, 2_200_000.0, 2_400_000.0],
        latency_proxy_ms=[12.0, 12.0, 13.0, 14.0, 22.0, 28.0, 20.0, 18.0, 16.0, 15.0],
        quality_flags=[],
    )
