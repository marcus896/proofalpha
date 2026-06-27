from __future__ import annotations

from engine.universe.rings import ring_for_symbol


def discover_research_symbols(symbols: list[str] | tuple[str, ...]) -> dict[str, str]:
    return {symbol: ring_for_symbol(symbol).value for symbol in symbols if symbol.endswith("USDT")}
