from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RollbackValidation:
    passed: bool
    reasons: list[str]


@dataclass(frozen=True)
class ArtifactRollbackManifest:
    artifact_id: str
    rollback_artifact_id: str
    reason: str

    def validate(self) -> RollbackValidation:
        reasons: list[str] = []
        if not self.rollback_artifact_id:
            reasons.append("missing_rollback_artifact_id")
        if self.rollback_artifact_id == self.artifact_id:
            reasons.append("rollback_target_same_as_artifact")
        return RollbackValidation(not reasons, reasons)
