from __future__ import annotations


class ExecutionContractError(ValueError):
    pass


class DuplicateIntentError(ExecutionContractError):
    pass


class InvalidOrderTransitionError(ExecutionContractError):
    pass
