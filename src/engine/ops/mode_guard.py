from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeGuardResult:
    passed: bool
    reasons: list[str]


@dataclass(frozen=True)
class ModeGuard:
    allowed_modes: list[str]
    live_disabled_enforced: bool = True

    def validate_transition(self, current_mode: str, target_mode: str) -> ModeGuardResult:
        reasons: list[str] = []
        normalized_current_mode = current_mode.strip().lower()
        normalized_target_mode = target_mode.strip().lower()
        normalized_allowed_modes = {mode.strip().lower() for mode in self.allowed_modes}
        if normalized_target_mode not in normalized_allowed_modes:
            reasons.append(f"mode_not_allowed:{normalized_target_mode}")
        if self.live_disabled_enforced and normalized_target_mode == "live":
            reasons.append("live_disabled_enforced")
        if normalized_current_mode == "paper" and normalized_target_mode == "live":
            reasons.append("paper_to_live_forbidden")
        return ModeGuardResult(not reasons, reasons)
