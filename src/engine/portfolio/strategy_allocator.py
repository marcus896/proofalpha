from __future__ import annotations

from engine.portfolio.allocator import PortfolioArtifactCandidate


def constrained_score_tilt(
    candidates: list[PortfolioArtifactCandidate],
    *,
    max_weight: float,
) -> dict[str, float]:
    positive = [candidate for candidate in candidates if candidate.expected_return_bps > 0 and candidate.approved]
    total_score = sum(float(candidate.expected_return_bps) for candidate in positive)
    if total_score <= 0:
        return {}
    weights = {
        candidate.artifact_id: min(max_weight, float(candidate.expected_return_bps) / total_score)
        for candidate in positive
    }
    normalizer = sum(weights.values())
    if normalizer <= 0:
        return {}
    return {key: round(value / normalizer, 12) for key, value in sorted(weights.items())}
