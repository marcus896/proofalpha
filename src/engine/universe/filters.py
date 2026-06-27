from __future__ import annotations

from dataclasses import asdict, dataclass

from engine.universe.manifest import UniverseManifest


@dataclass(frozen=True)
class SymbolFilterDecision:
    allowed: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def executor_symbol_allowed(manifest: UniverseManifest, symbol: str) -> SymbolFilterDecision:
    if symbol not in manifest.symbols:
        return SymbolFilterDecision(False, ["symbol_not_in_manifest"])
    if not manifest.paper_allowed(symbol):
        return SymbolFilterDecision(False, ["symbol_not_paper_allowed"])
    return SymbolFilterDecision(True, [])
