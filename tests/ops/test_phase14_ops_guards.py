from __future__ import annotations

import unittest

from engine.ops.config_diff import diff_config
from engine.ops.kill_switch import KillSwitch
from engine.ops.mode_guard import ModeGuard
from engine.ops.profile_permissions import ProfilePermissions
from engine.ops.release_checklist import ReleaseChecklist
from engine.ops.secrets_guard import SecretsGuard


class Phase14OpsGuardTests(unittest.TestCase):
    def test_secrets_guard_blocks_key_export(self) -> None:
        result = SecretsGuard().scan({"BINANCE_API_KEY": "abc", "mode": "paper"})

        self.assertFalse(result.passed)
        self.assertIn("private_key_field:BINANCE_API_KEY", result.reasons)

    def test_secrets_guard_blocks_nested_key_export(self) -> None:
        result = SecretsGuard().scan({"venue": {"credentials": {"api_secret": "abc"}}})

        self.assertFalse(result.passed)
        self.assertIn("private_key_field:venue.credentials.api_secret", result.reasons)

    def test_mode_guard_enforces_live_disabled(self) -> None:
        result = ModeGuard(allowed_modes=["research", "paper"], live_disabled_enforced=True).validate_transition(
            "paper",
            "live",
        )

        self.assertFalse(result.passed)
        self.assertIn("mode_not_allowed:live", result.reasons)

    def test_mode_guard_enforces_live_disabled_case_insensitively(self) -> None:
        result = ModeGuard(allowed_modes=["research", "paper", "LIVE"], live_disabled_enforced=True).validate_transition(
            "PAPER",
            "LIVE",
        )

        self.assertFalse(result.passed)
        self.assertIn("live_disabled_enforced", result.reasons)
        self.assertIn("paper_to_live_forbidden", result.reasons)

    def test_kill_switch_blocks_executor_and_agent_tools(self) -> None:
        switch = KillSwitch(engaged=True, force_reduce_only_if_configured=True)

        result = switch.evaluate("place_order")

        self.assertFalse(result.allowed)
        self.assertTrue(result.halt_agent_tools)

    def test_profile_permissions_deny_forbidden_mcp_tools(self) -> None:
        permissions = ProfilePermissions.paper_execute()

        self.assertFalse(permissions.is_tool_allowed("place_order"))
        self.assertTrue(permissions.is_tool_allowed("get_validation_protocol"))

    def test_release_checklist_requires_guards(self) -> None:
        checklist = ReleaseChecklist(
            local_smoke_passed=True,
            local_soak_passed=True,
            no_live_keys=True,
            live_disabled=True,
            kill_switch_tested=False,
            profile_permissions_loaded=True,
        )

        self.assertFalse(checklist.evaluate().passed)
        self.assertIn("kill_switch_not_tested", checklist.evaluate().reasons)
        self.assertEqual(diff_config({"mode": "paper"}, {"mode": "paper"}), {})


if __name__ == "__main__":
    unittest.main()
