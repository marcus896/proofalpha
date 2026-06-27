from __future__ import annotations

from dataclasses import dataclass

from engine.strategy.lifecycle_state import StrategyLifecycleState, transition_allowed


@dataclass
class StrategyLifecycleManager:
    state: StrategyLifecycleState

    def transition(self, target: StrategyLifecycleState) -> bool:
        if not transition_allowed(self.state, target):
            return False
        self.state = target
        return True
