import unittest

from engine.agent.registry import AGENT_LOOP_EVENTS, LOOP_ROLE_REGISTRY


class AgentRegistryTests(unittest.TestCase):
    def test_registry_exposes_required_roles_and_events(self) -> None:
        self.assertEqual(
            AGENT_LOOP_EVENTS,
            [
                "planning_started",
                "study_proposed",
                "study_materialized",
                "validation_started",
                "validation_completed",
                "memory_updated",
                "batch_refined",
                "loop_stopped",
            ],
        )
        self.assertEqual(
            set(LOOP_ROLE_REGISTRY),
            {
                "ResearchPlanner",
                "StudyMaterializer",
                "ValidationExecutor",
                "MemoryUpdater",
                "RefinementPlanner",
            },
        )
        self.assertFalse(LOOP_ROLE_REGISTRY["ValidationExecutor"].read_only)
