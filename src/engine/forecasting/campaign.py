from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping

from engine.config.models import PromotionDecision, ValidationProtocol, ValidationStageResult
from engine.forecasting.baseline_gate import (
    REQUIRED_FORECAST_BASELINES,
    ForecastBaselineGateReport,
    ForecastComparisonResult,
    compare_forecast_to_baselines,
)
from engine.forecasting.runtime_profile import DEFAULT_TIMESFM_MODEL_ID


PRIMARY_FORECAST_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_FORECAST_FEATURE_FIELDS = (
    "timesfm_q10_return",
    "timesfm_q50_return",
    "timesfm_q90_return",
    "timesfm_uncertainty_ratio",
    "timesfm_confidence_bucket",
)


@dataclass(frozen=True)
class ForecastCampaignVariant:
    symbol: str
    variant_id: str
    feature_contracts: tuple[str, ...]
    forecast_feature_config: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "variant_id": self.variant_id,
            "feature_contracts": list(self.feature_contracts),
            "forecast_feature_config": dict(self.forecast_feature_config),
        }


@dataclass(frozen=True)
class ForecastValidationCampaign:
    campaign_id: str
    symbols: tuple[str, ...]
    required_baselines: tuple[str, ...]
    forecast_variants: tuple[ForecastCampaignVariant, ...]
    research_only: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "symbols": list(self.symbols),
            "required_baselines": list(self.required_baselines),
            "forecast_variants": [variant.to_dict() for variant in self.forecast_variants],
            "research_only": self.research_only,
        }


@dataclass(frozen=True)
class ForecastSymbolCampaignReport:
    symbol: str
    status: str
    forecast_variant_id: str
    baseline_gate_report: ForecastBaselineGateReport | None = None
    skip_reason: str | None = None
    failed_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "forecast_variant_id": self.forecast_variant_id,
            "baseline_gate_report": (
                self.baseline_gate_report.to_dict() if self.baseline_gate_report is not None else None
            ),
            "skip_reason": self.skip_reason,
            "failed_reasons": list(self.failed_reasons),
        }


@dataclass(frozen=True)
class ForecastValidationCampaignReport:
    campaign_id: str
    status: str
    symbol_reports: dict[str, ForecastSymbolCampaignReport]
    failed_reasons: list[str]
    post_cost_improvements: dict[str, float]
    promotion_blocked: bool
    promotion_decision: PromotionDecision
    research_only: bool = True

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["symbol_reports"] = {
            symbol: symbol_report.to_dict()
            for symbol, symbol_report in self.symbol_reports.items()
        }
        payload["promotion_decision"] = asdict(self.promotion_decision)
        return payload


def build_forecast_validation_campaign(
    *,
    symbols: tuple[str, ...] = PRIMARY_FORECAST_SYMBOLS,
    model_id: str = DEFAULT_TIMESFM_MODEL_ID,
    config_checksum: str | None = None,
    horizon: int = 2,
    context_length: int = 512,
    feature_fields: tuple[str, ...] = DEFAULT_FORECAST_FEATURE_FIELDS,
) -> ForecastValidationCampaign:
    variants = tuple(
        ForecastCampaignVariant(
            symbol=symbol,
            variant_id=_forecast_variant_id(symbol),
            feature_contracts=("ohlcv", "forecast_feature"),
            forecast_feature_config={
                "model_id": model_id,
                "config_checksum": config_checksum,
                "horizon": horizon,
                "context_length": context_length,
                "fields": list(feature_fields),
            },
        )
        for symbol in symbols
    )
    return ForecastValidationCampaign(
        campaign_id="phase5-timesfm-primary-symbol-validation",
        symbols=tuple(symbols),
        required_baselines=REQUIRED_FORECAST_BASELINES,
        forecast_variants=variants,
    )


def run_forecast_validation_campaign(
    campaign: ForecastValidationCampaign,
    results_by_symbol: Mapping[str, Mapping[str, object]],
    *,
    reference_hard_gate_results: dict[str, bool] | None = None,
) -> ForecastValidationCampaignReport:
    variant_by_symbol = {
        variant.symbol: variant
        for variant in campaign.forecast_variants
    }
    symbol_reports: dict[str, ForecastSymbolCampaignReport] = {}
    failed_reasons: list[str] = []
    post_cost_improvements: dict[str, float] = {}

    for symbol in campaign.symbols:
        variant = variant_by_symbol[symbol]
        symbol_result = dict(results_by_symbol.get(symbol, {}))
        forecast = symbol_result.get("forecast")
        if not isinstance(forecast, ForecastComparisonResult):
            reason = f"forecast_unavailable:{symbol}"
            symbol_reports[symbol] = ForecastSymbolCampaignReport(
                symbol=symbol,
                status="skipped",
                forecast_variant_id=variant.variant_id,
                skip_reason=reason,
                failed_reasons=[reason],
            )
            failed_reasons.append(reason)
            continue

        baselines = _coerce_baselines(symbol_result.get("baselines"))
        baseline_report = compare_forecast_to_baselines(
            forecast=forecast,
            baselines=baselines,
            reference_hard_gate_results=reference_hard_gate_results,
        )
        prefixed_reasons = [
            f"{symbol}:{reason}"
            for reason in baseline_report.promotion_decision.reasons
        ]
        symbol_reports[symbol] = ForecastSymbolCampaignReport(
            symbol=symbol,
            status=baseline_report.status,
            forecast_variant_id=forecast.variant_id,
            baseline_gate_report=baseline_report,
            failed_reasons=prefixed_reasons,
        )
        failed_reasons.extend(prefixed_reasons)
        if baseline_report.net_post_cost_improvement is not None:
            post_cost_improvements[symbol] = baseline_report.net_post_cost_improvement

    status = _campaign_status(symbol_reports)
    promotion_blocked = status != "passed"
    promotion_decision = (
        PromotionDecision("accept", [])
        if status == "passed"
        else PromotionDecision("reject", _unique(failed_reasons))
    )
    return ForecastValidationCampaignReport(
        campaign_id=campaign.campaign_id,
        status=status,
        symbol_reports=symbol_reports,
        failed_reasons=_unique(failed_reasons),
        post_cost_improvements=post_cost_improvements,
        promotion_blocked=promotion_blocked,
        promotion_decision=promotion_decision,
    )


def append_forecast_campaign_stage(
    validation: ValidationProtocol,
    report: ForecastValidationCampaignReport,
) -> ValidationProtocol:
    stage = ValidationStageResult(
        stage_name="phase5_forecast_validation_campaign",
        passed=report.status == "passed",
        reasons=list(report.promotion_decision.reasons),
        metrics=report.to_dict(),
    )
    gate_results = dict(validation.validation_gate_results)
    gate_results["phase5_forecast_validation_campaign"] = report.status == "passed"
    return ValidationProtocol(
        status="passed" if validation.status == "passed" and report.status == "passed" else "failed",
        stage_results=[*validation.stage_results, stage],
        probabilistic_sharpe_ratio=validation.probabilistic_sharpe_ratio,
        deflated_sharpe_ratio=validation.deflated_sharpe_ratio,
        pbo_score=validation.pbo_score,
        spa_pvalue=validation.spa_pvalue,
        in_sample_permutation_pvalue=validation.in_sample_permutation_pvalue,
        walk_forward_permutation_pvalue=validation.walk_forward_permutation_pvalue,
        in_sample_summary=dict(validation.in_sample_summary),
        selection_oos_summary=dict(validation.selection_oos_summary),
        holdout_summary=dict(validation.holdout_summary),
        cpcv_config=dict(validation.cpcv_config),
        purge_bars=validation.purge_bars,
        embargo_bars=validation.embargo_bars,
        n_blocks=validation.n_blocks,
        n_test_blocks=validation.n_test_blocks,
        min_backtest_length=validation.min_backtest_length,
        min_trade_count=validation.min_trade_count,
        validation_trial_count=validation.validation_trial_count,
        validation_gate_results=gate_results,
        validation_gate_details=list(validation.validation_gate_details),
        promotion_decision=report.promotion_decision if report.status != "passed" else validation.promotion_decision,
    )


def _forecast_variant_id(symbol: str) -> str:
    return f"{symbol.lower()}-timesfm-forecast-feature"


def _coerce_baselines(value: object) -> dict[str, ForecastComparisonResult]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(baseline_id): result
        for baseline_id, result in value.items()
        if isinstance(result, ForecastComparisonResult)
    }


def _campaign_status(symbol_reports: dict[str, ForecastSymbolCampaignReport]) -> str:
    if any(report.status == "skipped" for report in symbol_reports.values()):
        return "skipped"
    if any(report.status != "passed" for report in symbol_reports.values()):
        return "failed"
    return "passed"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
