import unittest
from unittest.mock import patch

from engine.agent import controller


class AgentValidatorModuleTests(unittest.TestCase):
    def test_controller_default_validator_delegates_to_validator_module(self) -> None:
        expected = {"status": "evaluated", "run_ids": ["delegated"]}
        with patch("engine.agent.controller._agent_validator.default_validator", return_value=expected) as mocked:
            result = controller._default_validator({"payload": {}}, {"config_paths": ["study.json"]})

        self.assertEqual(result, expected)
        mocked.assert_called_once()

    def test_validator_returns_karpathy_direct_eval_without_autoresearch(self) -> None:
        from engine.agent import validator

        expected = {"status": "evaluated", "run_ids": ["direct"]}
        with patch(
            "engine.agent.validator.try_read_karpathy_python_target_direct_eval",
            return_value=expected,
        ) as direct_eval:
            with patch("engine.agent.validator.execute_autoresearch") as execute_autoresearch:
                result = validator.default_validator({"payload": {}}, {"config_paths": ["study.json"]})

        self.assertEqual(result, expected)
        direct_eval.assert_called_once()
        execute_autoresearch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
