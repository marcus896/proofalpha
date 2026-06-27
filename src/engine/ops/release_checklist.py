from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseChecklistResult:
    passed: bool
    reasons: list[str]


@dataclass(frozen=True)
class ReleaseChecklist:
    local_smoke_passed: bool
    local_soak_passed: bool
    no_live_keys: bool
    live_disabled: bool
    kill_switch_tested: bool
    profile_permissions_loaded: bool

    def evaluate(self) -> ReleaseChecklistResult:
        checks = {
            "local_smoke_not_passed": self.local_smoke_passed,
            "local_soak_not_passed": self.local_soak_passed,
            "live_keys_present": self.no_live_keys,
            "live_not_disabled": self.live_disabled,
            "kill_switch_not_tested": self.kill_switch_tested,
            "profile_permissions_not_loaded": self.profile_permissions_loaded,
        }
        reasons = [reason for reason, passed in checks.items() if not passed]
        return ReleaseChecklistResult(not reasons, reasons)
