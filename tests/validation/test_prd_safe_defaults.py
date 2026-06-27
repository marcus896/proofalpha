from __future__ import annotations

import unittest
from inspect import signature

from engine.app.config import RuntimeSettings
from engine.validation.protocol import run_validation_protocol


class PrdSafeDefaultsTests(unittest.TestCase):
    def test_runtime_settings_default_to_prd_safe_holdout_gates(self) -> None:
        settings = RuntimeSettings()

        self.assertEqual(settings.holdout_sharpe_floor, 1.0)
        self.assertEqual(settings.holdout_drawdown_cap, -0.20)

    def test_run_validation_protocol_defaults_are_prd_safe(self) -> None:
        defaults = signature(run_validation_protocol).parameters

        self.assertEqual(defaults["holdout_sharpe_floor"].default, 1.0)
        self.assertEqual(defaults["holdout_drawdown_cap"].default, -0.20)
        self.assertEqual(defaults["holdout_calmar_floor"].default, 0.75)


if __name__ == "__main__":
    unittest.main()
