from __future__ import annotations

from enum import StrEnum


class ExecutionTactic(StrEnum):
    PASSIVE_LIMIT = "PASSIVE_LIMIT"
    POST_ONLY_GTX = "POST_ONLY_GTX"
    AGGRESSIVE_LIMIT = "AGGRESSIVE_LIMIT"
    IOC = "IOC"
    SPLIT_PASSIVE = "SPLIT_PASSIVE"
    SPLIT_AGGRESSIVE = "SPLIT_AGGRESSIVE"
    DELAY = "DELAY"
    SKIP = "SKIP"
    REDUCE_ONLY = "REDUCE_ONLY"
    CLOSE = "CLOSE"
