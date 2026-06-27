from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutedFailure:
    failed_gate: str
    repeated_count: int
    failure_family: str
    recommended_action: str
    memory_reason: str


@dataclass(frozen=True)
class FailureRouter:
    failed_gate: str
    repeated_count: int

    def route(self) -> RoutedFailure:
        family = _family_for_gate(self.failed_gate)
        if self.repeated_count >= 3:
            action = "stop"
        elif self.failed_gate in {"stress", "scenario"}:
            action = "stress"
        elif self.failed_gate in {"calibration", "slippage", "funding"}:
            action = "calibrate"
        else:
            action = "narrow"
        return RoutedFailure(
            failed_gate=self.failed_gate,
            repeated_count=self.repeated_count,
            failure_family=family,
            recommended_action=action,
            memory_reason=f"{family}:{self.failed_gate}:repeated={self.repeated_count}:action={action}",
        )


def _family_for_gate(gate: str) -> str:
    if any(token in gate for token in ("holdout", "sample", "pbo", "sharpe", "calmar")):
        return "validation_failures"
    if any(token in gate for token in ("fill", "order", "reconcile")):
        return "execution_failures"
    if any(token in gate for token in ("data", "stale", "missing")):
        return "data_failures"
    return "agent_policy_failures"
