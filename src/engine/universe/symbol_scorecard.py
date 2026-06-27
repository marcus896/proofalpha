from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SymbolScorecard:
    symbol: str
    data_quality: float
    liquidity: float
    capacity: float
    funding_behavior: float
    correlation: float
    validation: float
    paper_health: float

    @property
    def total_score(self) -> float:
        values = (
            self.data_quality,
            self.liquidity,
            self.capacity,
            self.funding_behavior,
            self.correlation,
            self.validation,
            self.paper_health,
        )
        return round(sum(values) / len(values), 12)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["total_score"] = self.total_score
        return payload
