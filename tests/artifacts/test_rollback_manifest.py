from __future__ import annotations

import unittest

from engine.strategy.artifacts import RollbackManifest, build_rollback_manifest, validate_rollback_manifest


class RollbackManifestTests(unittest.TestCase):
    def test_rollback_manifest_records_parent_reason_compatibility_and_fallback_stage(self) -> None:
        manifest = build_rollback_manifest(
            artifact_id="artifact-new",
            parent_artifact_id="artifact-old",
            rollback_reason="capacity_drift_breached",
            rollback_compatible=True,
            fallback_stage="paper",
        )

        parsed = RollbackManifest.from_dict(manifest.to_dict())

        self.assertEqual(parsed.parent_artifact_id, "artifact-old")
        self.assertEqual(parsed.rollback_reason, "capacity_drift_breached")
        self.assertTrue(parsed.rollback_compatible)
        self.assertEqual(parsed.fallback_stage, "paper")
        self.assertTrue(validate_rollback_manifest(parsed.to_dict()).passed)


if __name__ == "__main__":
    unittest.main()
