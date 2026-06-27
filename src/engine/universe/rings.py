from __future__ import annotations

from enum import StrEnum


class Ring(StrEnum):
    RING_0_CORE = "RING_0_CORE"
    RING_1_LIQUID_MAJORS = "RING_1_LIQUID_MAJORS"
    RING_2_LARGE_CAP_ALTS = "RING_2_LARGE_CAP_ALTS"
    RING_3_RESEARCH = "RING_3_RESEARCH"
    RING_4_EXCLUDED = "RING_4_EXCLUDED"


RING_CAPS = {
    Ring.RING_0_CORE: 0.50,
    Ring.RING_1_LIQUID_MAJORS: 0.30,
    Ring.RING_2_LARGE_CAP_ALTS: 0.15,
    Ring.RING_3_RESEARCH: 0.0,
    Ring.RING_4_EXCLUDED: 0.0,
}


def ring_for_symbol(symbol: str) -> Ring:
    if symbol in {"BTCUSDT", "ETHUSDT"}:
        return Ring.RING_0_CORE
    if symbol in {"SOLUSDT", "BNBUSDT", "XRPUSDT"}:
        return Ring.RING_1_LIQUID_MAJORS
    if symbol.endswith("USDT"):
        return Ring.RING_3_RESEARCH
    return Ring.RING_4_EXCLUDED


def ring_weight_cap(ring: Ring) -> float:
    return RING_CAPS[ring]
