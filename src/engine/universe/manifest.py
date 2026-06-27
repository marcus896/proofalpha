from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
import hashlib
import json


class SymbolState(StrEnum):
    EXCLUDED = "EXCLUDED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    SHADOW = "SHADOW"
    PAPER_ALLOWED = "PAPER_ALLOWED"
    PAPER_ACTIVE = "PAPER_ACTIVE"
    REDUCE_ONLY = "REDUCE_ONLY"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


PAPER_STATES = {SymbolState.PAPER_ALLOWED, SymbolState.PAPER_ACTIVE, SymbolState.REDUCE_ONLY}


@dataclass(frozen=True)
class UniverseSymbol:
    symbol: str
    state: SymbolState
    ring: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["state"] = self.state.value
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class UniverseManifest:
    universe_id: str
    approved_by: str
    symbols: dict[str, UniverseSymbol]
    manifest_hash: str

    @classmethod
    def create(cls, *, universe_id: str, approved_by: str) -> "UniverseManifest":
        return cls(universe_id=universe_id, approved_by=approved_by, symbols={}, manifest_hash=_stable_hash({}))

    def add_symbol(self, symbol: str, *, ring: str = "RING_3_RESEARCH") -> "UniverseManifest":
        symbols = dict(self.symbols)
        symbols[symbol] = UniverseSymbol(symbol=symbol, state=SymbolState.RESEARCH_ONLY, ring=ring, reasons=("new_symbol",))
        return _with_hash(replace(self, symbols=symbols))

    def with_state(self, symbol: str, state: SymbolState, *, reason: str) -> "UniverseManifest":
        if symbol not in self.symbols:
            raise KeyError(f"symbol_not_in_manifest:{symbol}")
        symbols = dict(self.symbols)
        current = symbols[symbol]
        symbols[symbol] = replace(current, state=state, reasons=(*current.reasons, reason))
        return _with_hash(replace(self, symbols=symbols))

    def paper_allowed(self, symbol: str) -> bool:
        item = self.symbols.get(symbol)
        return item is not None and item.state in PAPER_STATES

    def to_dict(self) -> dict[str, object]:
        return {
            "universe_id": self.universe_id,
            "approved_by": self.approved_by,
            "manifest_hash": self.manifest_hash,
            "symbols": {key: value.to_dict() for key, value in sorted(self.symbols.items())},
        }


def _with_hash(manifest: UniverseManifest) -> UniverseManifest:
    payload = {
        "universe_id": manifest.universe_id,
        "approved_by": manifest.approved_by,
        "symbols": {key: value.to_dict() for key, value in sorted(manifest.symbols.items())},
    }
    return replace(manifest, manifest_hash=_stable_hash(payload))


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
