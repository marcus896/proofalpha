from __future__ import annotations

from engine.execution.execution_tactics import ExecutionTactic


class ExecutionPolicyRegistry:
    def __init__(self) -> None:
        self.journal: list[dict[str, object]] = []

    def log_risk_decision(self, *, order_id: str, decision: str, reasons: list[str]) -> None:
        self.journal.append(
            {
                "decision_type": "risk",
                "order_id": order_id,
                "decision": decision,
                "reasons": list(reasons),
            }
        )

    def log_tactic_decision(self, *, order_id: str, tactic: ExecutionTactic, reasons: list[str]) -> None:
        self.journal.append(
            {
                "decision_type": "tactic",
                "order_id": order_id,
                "tactic": tactic.value,
                "reasons": list(reasons),
            }
        )
