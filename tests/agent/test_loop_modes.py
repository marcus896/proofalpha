from __future__ import annotations

import unittest

from engine.agent.loop_modes import AgentLoopMode, allowed_actions_for_mode


class LoopModesTests(unittest.TestCase):
    def test_loop_modes_allow_study_actions_not_trade_actions(self) -> None:
        self.assertIn("RequestCalibrationStudy", allowed_actions_for_mode(AgentLoopMode.CALIBRATE))
        self.assertNotIn("PlaceOrder", allowed_actions_for_mode(AgentLoopMode.EXECUTOR))


if __name__ == "__main__":
    unittest.main()
