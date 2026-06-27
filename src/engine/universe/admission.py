from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AdmissionGateInputs:
    exchange_status_trading: bool
    usdm_linear_perp: bool
    history_1h: bool
    history_15m: bool
    funding_history: bool
    mark_price_history: bool
    open_interest: bool
    book_depth: bool
    spread: bool
    volume: bool
    capacity: bool
    slippage_model_confidence: bool
    funding_stability: bool
    correlation_cluster: bool
    scenario_robustness: bool
    paper_dry_run: bool


@dataclass(frozen=True)
class AdmissionDecision:
    paper_eligible: bool
    rejections: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_symbol_admission(inputs: AdmissionGateInputs) -> AdmissionDecision:
    rejections = [
        field
        for field, passed in inputs.__dict__.items()
        if not bool(passed)
    ]
    return AdmissionDecision(paper_eligible=not rejections, rejections=rejections)
