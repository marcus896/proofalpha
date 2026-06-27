from __future__ import annotations

from enum import StrEnum


class StrategyLifecycleState(StrEnum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    PROMOTED = "PROMOTED"
    SHADOW = "SHADOW"
    PAPER_ACTIVE = "PAPER_ACTIVE"
    WATCH = "WATCH"
    DEGRADED = "DEGRADED"
    REDUCE_ONLY = "REDUCE_ONLY"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


ALLOWED_TRANSITIONS = {
    StrategyLifecycleState.CANDIDATE: {StrategyLifecycleState.VALIDATED, StrategyLifecycleState.RETIRED},
    StrategyLifecycleState.VALIDATED: {StrategyLifecycleState.PROMOTED, StrategyLifecycleState.RETIRED},
    StrategyLifecycleState.PROMOTED: {StrategyLifecycleState.SHADOW, StrategyLifecycleState.RETIRED},
    StrategyLifecycleState.SHADOW: {StrategyLifecycleState.PAPER_ACTIVE, StrategyLifecycleState.WATCH, StrategyLifecycleState.RETIRED},
    StrategyLifecycleState.PAPER_ACTIVE: {StrategyLifecycleState.WATCH, StrategyLifecycleState.DEGRADED, StrategyLifecycleState.REDUCE_ONLY, StrategyLifecycleState.RETIRED},
    StrategyLifecycleState.WATCH: {StrategyLifecycleState.PAPER_ACTIVE, StrategyLifecycleState.DEGRADED, StrategyLifecycleState.RETIRED},
    StrategyLifecycleState.DEGRADED: {StrategyLifecycleState.REDUCE_ONLY, StrategyLifecycleState.QUARANTINED, StrategyLifecycleState.RETIRED},
    StrategyLifecycleState.REDUCE_ONLY: {StrategyLifecycleState.QUARANTINED, StrategyLifecycleState.RETIRED},
    StrategyLifecycleState.QUARANTINED: {StrategyLifecycleState.RETIRED},
    StrategyLifecycleState.RETIRED: set(),
}


def transition_allowed(current: StrategyLifecycleState, target: StrategyLifecycleState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
