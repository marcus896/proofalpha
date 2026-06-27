from __future__ import annotations

import json
import unittest
from pathlib import Path

from engine.agent.research_debate import build_report_only_research_debate, write_research_debate_report


class ResearchDebateReportTests(unittest.TestCase):
    def test_build_report_only_research_debate_excludes_trading_authority(self) -> None:
        payload = build_report_only_research_debate(
            {
                "run_id": "candidate-a",
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "validation_bundle": {"failed_gates": ["final_holdout_excellence"]},
                "failure_taxonomy": ["holdout_failure", "emit_buy_sell_size"],
                "trade_action": "BUY",
            },
            trace_advisory_notes={
                "artifact_type": "agent_loop_trace_advisory_notes",
                "controlled_failure_taxonomy_hints": [
                    {"label": "stress_failure", "note": "Stress weakness remains."},
                    {"label": "emit_buy_sell_size", "note": "BUY 10 BTC"},
                ],
                "planner_notes": ["Review stress scenario assumptions."],
            },
            source_path="outputs/candidate.json",
        )

        self.assertEqual(payload["artifact_type"], "agent_research_debate_report")
        self.assertTrue(payload["research_only"])
        self.assertTrue(payload["report_only"])
        self.assertFalse(payload["executable_artifact_created"])
        self.assertEqual(payload["source"]["path"], "outputs/candidate.json")
        self.assertFalse(payload["provenance"]["tradingagents_direct_use"])
        self.assertEqual(payload["provenance"]["tradingagents_status"], "not_used_internal_contract")
        self.assertEqual(payload["candidate"]["run_id"], "candidate-a")
        self.assertEqual(
            payload["controlled_outputs"]["failure_taxonomy_hints"],
            ["holdout_failure", "stress_failure"],
        )
        self.assertEqual(
            payload["controlled_outputs"]["validation_notes"],
            [
                "failed_gate:final_holdout_excellence",
                "planner_note:Review stress scenario assumptions.",
            ],
        )
        self.assertEqual([role["role"] for role in payload["reports"]], ["validation_researcher", "risk_analyst"])
        self.assertTrue(payload["authority_limits"]["promotion_gates_sole_authority"])
        self.assertTrue(payload["authority_limits"]["immutable_artifact_contract_sole_authority"])
        encoded = json.dumps(payload, sort_keys=True)
        self.assertNotIn("BUY", encoded)
        self.assertNotIn("emit_buy_sell_size", encoded)
        self.assertNotIn("trade_action", encoded)

    def test_write_research_debate_report_round_trips_atomic_json(self) -> None:
        output = Path("outputs") / "test-temp" / "research-debate-report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(output.unlink, missing_ok=True)

        written = write_research_debate_report(output, build_report_only_research_debate({"run_id": "candidate"}))

        self.assertEqual(written, output)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["candidate"]["run_id"], "candidate")


if __name__ == "__main__":
    unittest.main()
