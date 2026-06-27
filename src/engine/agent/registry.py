from __future__ import annotations

from dataclasses import dataclass


AGENT_LOOP_EVENTS = [
    "planning_started",
    "study_proposed",
    "study_materialized",
    "validation_started",
    "validation_completed",
    "memory_updated",
    "batch_refined",
    "loop_stopped",
]


@dataclass(frozen=True)
class LoopRole:
    name: str
    responsibility: str
    read_only: bool


LOOP_ROLE_REGISTRY = {
    "ResearchPlanner": LoopRole(
        name="ResearchPlanner",
        responsibility="Propose the next bounded study or batch from memory and schema evidence.",
        read_only=True,
    ),
    "StudyMaterializer": LoopRole(
        name="StudyMaterializer",
        responsibility="Write executable study payloads for the proposed plan.",
        read_only=False,
    ),
    "ValidationExecutor": LoopRole(
        name="ValidationExecutor",
        responsibility="Run the authoritative validation path and collect study artifacts.",
        read_only=False,
    ),
    "MemoryUpdater": LoopRole(
        name="MemoryUpdater",
        responsibility="Summarize the evidence that should feed the next iteration.",
        read_only=True,
    ),
    "RefinementPlanner": LoopRole(
        name="RefinementPlanner",
        responsibility="Choose whether to continue and which follow-up payload to try next.",
        read_only=True,
    ),
}
