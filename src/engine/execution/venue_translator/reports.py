from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class TranslationReport:
    passed: bool
    raw_intent: dict[str, object]
    rounded_order: dict[str, object]
    rule_snapshot_hash: str
    rejection_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
