from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any

from engine.data.schema import Candle


@dataclass(frozen=True)
class ParameterRange:
    minimum: float
    maximum: float
    step: float
    excluded_values: list[float | int] = field(default_factory=list)

    def values(self) -> list[float | int]:
        if self.step <= 0:
            raise ValueError("step must be positive")
        excluded = {float(value) for value in self.excluded_values if isinstance(value, (int, float))}
        values: list[float | int] = []
        current = self.minimum
        guard = 0
        while current <= self.maximum + (self.step / 1_000_000):
            rounded = round(current, 10)
            if float(rounded) in excluded:
                current += self.step
                guard += 1
                if guard > 100_000:
                    raise ValueError("parameter range produced too many values")
                continue
            if float(rounded).is_integer():
                values.append(int(rounded))
            else:
                values.append(rounded)
            current += self.step
            guard += 1
            if guard > 100_000:
                raise ValueError("parameter range produced too many values")
        return values


@dataclass(frozen=True)
class DataSnapshot:
    snapshot_id: str
    symbol: str
    venue: str
    timeframe: str
    candles: list[Candle]
    funding_rates: list[float]
    open_interest: list[float]
    liquidation_notional: list[float]
    maker_fee_bps: float
    taker_fee_bps: float
    contract_type: str = "perpetual"
    mark_price: list[float] = field(default_factory=list)
    index_price: list[float] = field(default_factory=list)
    next_funding_ts: list[str] = field(default_factory=list)
    open_interest_usd: list[float] = field(default_factory=list)
    basis_bps: list[float] = field(default_factory=list)
    liq_long_usd: list[float] = field(default_factory=list)
    liq_short_usd: list[float] = field(default_factory=list)
    spread_bps: list[float] = field(default_factory=list)
    depth_bid_1bp_usd: list[float] = field(default_factory=list)
    depth_ask_1bp_usd: list[float] = field(default_factory=list)
    latency_proxy_ms: list[float] = field(default_factory=list)
    ret_1: list[float] = field(default_factory=list)
    ret_24: list[float] = field(default_factory=list)
    rv_24h: list[float] = field(default_factory=list)
    funding_z: list[float] = field(default_factory=list)
    d_oi: list[float] = field(default_factory=list)
    d_oi_z: list[float] = field(default_factory=list)
    liq_intensity_z: list[float] = field(default_factory=list)
    vol_regime: list[str] = field(default_factory=list)
    regime_id: list[str] = field(default_factory=list)
    regime_probabilities: list[dict[str, float]] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    venue_profile: "VenueProfile | None" = None
    quality_report: "SnapshotQualityReport | None" = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VenueProfile:
    venue: str
    contract_type: str = "perpetual"
    quote_currency: str | None = None
    settlement_currency: str | None = None
    funding_interval_h: int | None = None
    maker_fee_bps: float | None = None
    taker_fee_bps: float | None = None
    fee_schedule_source: str | None = None
    mark_price_source: str = "exchange_mark"
    leverage_tiers: list[dict[str, float]] = field(default_factory=list)
    maintenance_margin_schedule: list[dict[str, float]] = field(default_factory=list)
    liquidation_fee_schedule: list[dict[str, float]] = field(default_factory=list)
    liquidation_style: str = "full"
    partial_liquidation_ratio: float = 1.0
    liquidation_cooldown_bars: int = 0
    liquidation_mark_price_weight: float = 0.0
    liquidation_mark_premium_bps: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SnapshotQualityReport:
    report_id: str
    snapshot_id: str
    quality_score: float = 1.0
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    source_checks: dict[str, Any] = field(default_factory=dict)
    generated_at: str | None = None


@dataclass(frozen=True)
class SnapshotWindow:
    snapshot: DataSnapshot
    start_index: int
    end_index: int

    @property
    def candles(self) -> list[Candle]:
        """Return candles from the (already-sliced) snapshot.

        Note: ``start_index`` and ``end_index`` record the position within the
        *original* parent snapshot for provenance.  The ``snapshot`` stored here
        is already sliced to this window by :func:`slice_snapshot`, so returning
        ``self.snapshot.candles`` directly is correct.
        """
        return self.snapshot.candles


@dataclass(frozen=True)
class CrisisWindow:
    name: str
    snapshot_window: SnapshotWindow
    regime_label: str

    @property
    def candles(self) -> list[Candle]:
        return self.snapshot_window.candles


@dataclass(frozen=True)
class SplitPack:
    in_sample: SnapshotWindow
    selection_oos: SnapshotWindow
    final_holdout: SnapshotWindow
    bootstrap_source: SnapshotWindow
    crisis_windows: list[CrisisWindow] = field(default_factory=list)
    regime_labels: list[str] = field(default_factory=list)
    regime_coverage: dict[str, float] = field(default_factory=dict)
    crisis_window_coverage: dict[str, float] = field(default_factory=dict)
    regime_model: str = "deterministic"
    regime_metadata: dict[str, Any] = field(default_factory=dict)


class LayerFamily(str, Enum):
    BACKBONE = "backbone"
    DIRECTIONAL_FILTER = "directional_filter"
    KNOWN_GOOD_FLAT_FILTER = "known_good_flat_filter"
    CUSTOM_FLAT_FILTER = "custom_flat_filter"
    EXIT = "exit"
    RISK_GUARD = "risk_guard"


@dataclass(frozen=True)
class LayerSpec:
    name: str
    family: LayerFamily
    parameters: dict[str, ParameterRange] = field(default_factory=dict)
    precedence: int = 0
    eligibility_rules: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyGraph:
    backbone: str
    layers: list[LayerSpec] = field(default_factory=list)
    risk_guards: list[LayerSpec] = field(default_factory=list)

    def with_layer(self, layer: LayerSpec) -> "StrategyGraph":
        return StrategyGraph(
            backbone=self.backbone,
            layers=[*self.layers, layer],
            risk_guards=list(self.risk_guards),
        )

    @property
    def strategy_hash(self) -> str:
        payload = {
            "backbone": self.backbone,
            "layers": [
                {
                    "name": layer.name,
                    "family": layer.family.value,
                    "parameters": {key: asdict(value) for key, value in layer.parameters.items()},
                    "precedence": layer.precedence,
                    "eligibility_rules": layer.eligibility_rules,
                }
                for layer in self.layers
            ],
            "risk_guards": [
                {
                    "name": layer.name,
                    "family": layer.family.value,
                    "parameters": {key: asdict(value) for key, value in layer.parameters.items()},
                    "precedence": layer.precedence,
                    "eligibility_rules": layer.eligibility_rules,
                }
                for layer in self.risk_guards
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BacktestResult:
    trade_count: int
    win_rate: float
    gross_pnl: float
    net_pnl: float
    fee_spend: float
    funding_spend: float
    sharpe: float
    sortino: float
    max_drawdown: float
    equity_curve: list[float]
    liquidation_events: list[str] = field(default_factory=list)
    execution_pressure_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StressMetrics:
    stress_slippage_quantile: float
    stress_tail_slippage: float
    liquidity_stress_score: float
    basis_stress_score: float
    cascade_liquidation_count: int


@dataclass(frozen=True)
class BootstrapReport:
    sample_count: int
    median_net_profit: float
    median_max_drawdown: float
    worst_case_net_profit: float
    worst_case_drawdown: float
    pass_rate: float
    bootstrap_method: str = "moving_block"
    block_size: int | None = None
    bootstrap_microstructure_overlay: dict[str, Any] = field(default_factory=dict)
    bootstrap_regime_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromotionDecision:
    decision: str
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PermutationTestResult:
    stage_name: str
    metric_name: str
    observed_metric: float
    exceedance_count: int
    permutation_count: int
    pvalue: float
    seed: int


@dataclass(frozen=True)
class SharpeEvidence:
    observed_sharpe: float
    benchmark_sharpe: float
    probabilistic_sharpe_ratio: float
    deflated_sharpe_ratio: float
    skewness: float
    kurtosis: float
    sample_count: int
    trial_count: int
    minimum_backtest_length: int = 0


@dataclass(frozen=True)
class ValidationStageResult:
    stage_name: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationProtocol:
    status: str
    stage_results: list[ValidationStageResult] = field(default_factory=list)
    probabilistic_sharpe_ratio: float | None = None
    deflated_sharpe_ratio: float | None = None
    pbo_score: float | None = None
    spa_pvalue: float | None = None
    in_sample_permutation_pvalue: float | None = None
    walk_forward_permutation_pvalue: float | None = None
    in_sample_summary: dict[str, Any] = field(default_factory=dict)
    selection_oos_summary: dict[str, Any] = field(default_factory=dict)
    holdout_summary: dict[str, Any] = field(default_factory=dict)
    cpcv_config: dict[str, Any] = field(default_factory=dict)
    purge_bars: int | None = None
    embargo_bars: int | None = None
    n_blocks: int | None = None
    n_test_blocks: int | None = None
    min_backtest_length: int | None = None
    min_trade_count: int | None = None
    validation_trial_count: int = 1
    validation_gate_results: dict[str, bool] = field(default_factory=dict)
    validation_gate_details: list[dict[str, Any]] = field(default_factory=list)
    promotion_decision: PromotionDecision = field(default_factory=lambda: PromotionDecision("accept", []))


@dataclass(frozen=True)
class CandidateEvaluation:
    layer_name: str
    decision: PromotionDecision
    train_result: BacktestResult
    oos_result: BacktestResult
    bootstrap_report: BootstrapReport
    selected_parameters: dict[str, float | int] = field(default_factory=dict)
    permutation_count: int = 1
    search_summary: list[dict[str, Any]] = field(default_factory=list)
    candidate_trials: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PhaseRecord:
    phase_name: str
    layer_name: str
    decision: str
    accepted: bool
    oos_sharpe: float | None = None
    selected_parameters: dict[str, float | int] = field(default_factory=dict)
    permutation_count: int = 1
    search_summary: list[dict[str, Any]] = field(default_factory=list)
    candidate_trials: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class OvernightRunReport:
    status: str
    final_strategy: StrategyGraph
    phase_records: list[PhaseRecord] = field(default_factory=list)
    holdout_decision: PromotionDecision | None = None
    final_evaluation: CandidateEvaluation | None = None
    validation_protocol: ValidationProtocol | None = None


@dataclass(frozen=True)
class RunCard:
    run_id: str
    strategy_hash: str
    phase: str
    split_id: str
    seed: int
    decision: PromotionDecision
    metrics: dict[str, float]
    artifacts: dict[str, str]


@dataclass(frozen=True)
class AgentPolicy:
    allowed_tools: list[str]
    read_only: bool = True
    forbidden_actions: list[str] = field(default_factory=list)
    evidence_required: bool = True


@dataclass(frozen=True)
class ResearchCycleExecution:
    report: OvernightRunReport
    runcard: RunCard
    dashboard_payload: dict[str, Any]
    runcard_path: str
    dashboard_path: str
