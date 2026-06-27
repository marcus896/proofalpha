from __future__ import annotations

import unittest

from engine.memory.decision_journal import DecisionJournal
from engine.memory.event_sourcing import MemoryEventLog
from engine.memory.failure_taxonomy_v2 import FailureTaxonomyV2
from engine.memory.learning_dataset_builder import LearningDatasetBuilder
from engine.memory.schema_versioning import MemorySchemaVersion


class Phase14MemoryJournalTests(unittest.TestCase):
    def test_decision_journal_records_risk_veto(self) -> None:
        entry = DecisionJournal.record(
            decision_id="decision-1",
            actor="risk_manager",
            decision_type="risk_veto",
            input_payload={"intent": "open"},
            output_payload={"decision": "reject"},
            reason="funding_budget",
        )

        self.assertEqual(entry.reason, "funding_budget")
        self.assertTrue(entry.input_hash)
        self.assertTrue(entry.output_hash)

    def test_event_sourced_memory_builds_learning_rows(self) -> None:
        log = MemoryEventLog()
        log.append("risk_veto", {"symbol": "BTCUSDT", "reason": "funding_budget"})
        rows = LearningDatasetBuilder().from_events(log.events)

        self.assertEqual(rows[0]["event_type"], "risk_veto")
        self.assertEqual(rows[0]["reason"], "funding_budget")

    def test_failure_taxonomy_v2_classifies_execution_failure(self) -> None:
        taxonomy = FailureTaxonomyV2.classify("orphan_order")

        self.assertEqual(taxonomy, "execution_failures")
        self.assertEqual(MemorySchemaVersion.current().version, 1)


if __name__ == "__main__":
    unittest.main()
