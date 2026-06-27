from __future__ import annotations


def assign_symbol_clusters(symbols: list[str] | tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for symbol in symbols:
        if symbol.startswith(("BTC", "ETH")):
            result[symbol] = "majors"
        else:
            result[symbol] = "alts"
    return result
