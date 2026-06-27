from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ShadowValidationReport:
    candidate_model_id: str
    incumbent_model_id: str
    passed: bool
    improvement_ratio: float
    promotes_model: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_shadow_validation(
    *,
    candidate_model_id: str,
    incumbent_model_id: str,
    candidate_errors: list[float],
    incumbent_errors: list[float],
    min_improvement_ratio: float,
) -> ShadowValidationReport:
    candidate = _mean_abs(candidate_errors)
    incumbent = _mean_abs(incumbent_errors)
    improvement = 0.0 if incumbent <= 0 else (incumbent - candidate) / incumbent
    return ShadowValidationReport(
        candidate_model_id=candidate_model_id,
        incumbent_model_id=incumbent_model_id,
        passed=improvement >= min_improvement_ratio,
        improvement_ratio=round(improvement, 12),
        promotes_model=False,
    )


def _mean_abs(values: list[float]) -> float:
    return sum(abs(float(value)) for value in values) / len(values) if values else 0.0
