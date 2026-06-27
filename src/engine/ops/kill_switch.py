from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KillSwitchResult:
    allowed: bool
    cancel_or_block_new_orders: bool
    force_reduce_only: bool
    halt_agent_tools: bool
    audit_event: dict[str, object]


@dataclass(frozen=True)
class KillSwitch:
    engaged: bool
    force_reduce_only_if_configured: bool = False

    def evaluate(self, action: str) -> KillSwitchResult:
        blocked = self.engaged
        return KillSwitchResult(
            allowed=not blocked,
            cancel_or_block_new_orders=blocked,
            force_reduce_only=blocked and self.force_reduce_only_if_configured,
            halt_agent_tools=blocked,
            audit_event={"action": action, "kill_switch_engaged": self.engaged},
        )
