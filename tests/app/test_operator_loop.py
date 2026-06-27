import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from engine.app.cli import main
from engine.app.operator_loop import record_candidate_queue_entry


def _clean_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _study_payload(*, run_id: str = "candidate-a") -> dict[str, object]:
    return {
        "run_id": run_id,
        "seed": 7,
        "runtime": {"mode": "builtin"},
        "snapshot": {
            "snapshot_id": "strict-v3-snapshot",
            "symbol": "BTCUSDT",
            "venue": "binance",
            "timeframe": "1Hour",
            "candles": [],
            "funding_rates": [],
            "open_interest": [],
            "liquidation_notional": [],
            "maker_fee_bps": 2.0,
            "taker_fee_bps": 5.0,
        },
        "incumbent": {"backbone": "mom_squeeze"},
        "directional_layers": ["kama"],
        "known_good_filters": ["flat9"],
        "custom_filters": [],
        "exit_layers": [],
    }


class CandidateQueueTests(unittest.TestCase):
    def test_candidate_queue_dedupes_canonical_payload_and_tracks_seen_count(self) -> None:
        root = Path("test-operator-loop-candidate-dedupe")
        queue_path = root / "candidate-queue.json"
        try:
            first = record_candidate_queue_entry(
                queue_path,
                study_payload=_study_payload(run_id="first-run"),
                config_path=root / "first.next-study.json",
                run_id="first-run",
                readiness={
                    "run_ready": True,
                    "research_ready": True,
                    "improvement_ready": False,
                    "blockers": ["missing_paper_executor_feedback"],
                },
            )
            second = record_candidate_queue_entry(
                queue_path,
                study_payload=_study_payload(run_id="second-run"),
                config_path=root / "second.next-study.json",
                run_id="second-run",
                readiness={
                    "run_ready": True,
                    "research_ready": True,
                    "improvement_ready": False,
                    "blockers": ["missing_paper_executor_feedback"],
                },
            )

            self.assertEqual(first["candidates"][0]["candidate_id"], second["candidates"][0]["candidate_id"])
            self.assertEqual(second["candidates"][0]["seen_count"], 2)
            self.assertEqual(second["candidates"][0]["first_seen_run_id"], "first-run")
            self.assertEqual(second["candidates"][0]["last_seen_run_id"], "second-run")
            self.assertEqual(len(second["candidates"]), 1)
        finally:
            _clean_tree(root)


class OperateLoopTests(unittest.TestCase):
    def test_operate_loop_blocks_weak_data_and_writes_operator_artifacts(self) -> None:
        root = Path("test-operator-loop-blocked")
        output_dir = root / "operate"
        queue_path = root / "queue.json"
        config_path = root / "study.json"
        try:
            root.mkdir(parents=True, exist_ok=True)
            payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
            payload["run_id"] = "strict-v3-weak"
            payload["snapshot"]["symbol"] = "BTCUSDT"
            payload["snapshot"]["venue"] = "binance"
            payload["snapshot"]["timeframe"] = "1Hour"
            payload["snapshot"]["provenance"] = {
                "provider": "binance_public_archive",
                "source_hash": "sha256:weak",
                "fetch_manifest": "outputs/data/fetch_manifest.json",
                "field_confidence": {
                    "liquidation_notional": "unavailable_archive_sidecar_empty_do_not_treat_zero_as_truth"
                },
            }
            config_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

            with mock.patch("builtins.print") as print_mock:
                exit_code = main(
                    [
                        "operate-loop",
                        "--config",
                        str(config_path),
                        "--output-dir",
                        str(output_dir),
                        "--db",
                        str(root / "memory.sqlite"),
                        "--candidate-queue",
                        str(queue_path),
                        "--require-improvement-ready",
                    ]
                )

            printed = json.loads(print_mock.call_args.args[0])
            report = json.loads((output_dir / "operator-loop-report.json").read_text(encoding="utf-8"))
            data_sufficiency = json.loads((output_dir / "data-sufficiency.json").read_text(encoding="utf-8"))
            queue = json.loads(queue_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "blocked_data_sufficiency")
            self.assertEqual(report["data_sufficiency_path"], str(output_dir / "data-sufficiency.json"))
            self.assertEqual(report["candidate_queue_path"], str(queue_path))
            self.assertFalse(data_sufficiency["improvement_ready"])
            self.assertEqual(queue["candidates"][0]["status"], "blocked_data")
            self.assertIn("collect_strict_v3_data", [action["id"] for action in report["next_actions"]])
        finally:
            _clean_tree(root)

    def test_candidate_queue_marks_blocked_data_when_strict_data_fails(self) -> None:
        root = Path("test-operator-loop-candidate-blocked")
        queue_path = root / "candidate-queue.json"
        try:
            queue = record_candidate_queue_entry(
                queue_path,
                study_payload=_study_payload(),
                config_path=root / "blocked.next-study.json",
                run_id="blocked-run",
                readiness={
                    "run_ready": True,
                    "research_ready": False,
                    "improvement_ready": False,
                    "blockers": ["liquidation_feature_missing_observed_sidecar"],
                },
                next_action_ids=["collect_strict_v3_data"],
            )

            candidate = queue["candidates"][0]
            self.assertEqual(candidate["status"], "blocked_data")
            self.assertEqual(candidate["readiness"]["blockers"], ["liquidation_feature_missing_observed_sidecar"])
            self.assertEqual(candidate["next_action_ids"], ["collect_strict_v3_data"])
        finally:
            _clean_tree(root)

    def test_operate_loop_reads_strategy_evidence_card_before_guarded_rerun(self) -> None:
        root = Path("test-operator-loop-evidence-card-block")
        output_dir = root / "operate"
        config_path = root / "study.json"
        card_path = root / "strategy-evidence-card.json"
        try:
            root.mkdir(parents=True, exist_ok=True)
            payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
            payload["run_id"] = "strict-v3-evidence-card"
            payload["snapshot"]["provenance"] = {
                "provider": "binance_public_archive",
                "source_hash": "sha256:strict",
                "field_confidence": {"liquidation_notional": "observed_public_force_order_sidecar"},
            }
            config_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            card_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "strategy_evidence_card",
                        "candidate_id": "candidate",
                        "status": "blocked",
                        "can_claim_strategy_improvement": False,
                        "blockers": ["paper_forward_score_not_ready"],
                        "next_allowed_action": "collect_paper_forward_score",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            with mock.patch("engine.app.operator_loop.run_guarded_loop_repeat") as repeat_mock:
                with mock.patch("builtins.print") as print_mock:
                    exit_code = main(
                        [
                            "operate-loop",
                            "--config",
                            str(config_path),
                            "--output-dir",
                            str(output_dir),
                            "--db",
                            str(root / "memory.sqlite"),
                            "--allow-smoke",
                            "--strategy-evidence-card",
                            str(card_path),
                        ]
                    )

            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(exit_code, 2)
            self.assertEqual(printed["status"], "blocked_strategy_evidence_card")
            self.assertFalse(repeat_mock.called)
            self.assertEqual(printed["strategy_evidence_card_summary"]["next_allowed_action"], "collect_paper_forward_score")
        finally:
            _clean_tree(root)

    def test_candidate_queue_records_tested_and_promoted_states(self) -> None:
        root = Path("test-operator-loop-candidate-promoted")
        queue_path = root / "candidate-queue.json"
        try:
            tested = record_candidate_queue_entry(
                queue_path,
                study_payload=_study_payload(),
                config_path=root / "candidate.next-study.json",
                run_id="tested-run",
                readiness={"run_ready": True, "research_ready": True, "improvement_ready": True, "blockers": []},
                failed_gates=["capacity_5x"],
                failure_taxonomy=["stress_failure"],
                paper_hypotheses=["paper_experiment:collect_more_paper_samples"],
                tested=True,
            )
            promoted = record_candidate_queue_entry(
                queue_path,
                study_payload=_study_payload(),
                config_path=root / "candidate.next-study.json",
                run_id="promoted-run",
                readiness={"run_ready": True, "research_ready": True, "improvement_ready": True, "blockers": []},
                promoted=True,
            )

            self.assertEqual(tested["candidates"][0]["status"], "tested")
            candidate = promoted["candidates"][0]
            self.assertEqual(candidate["status"], "promoted")
            self.assertEqual(candidate["seen_count"], 2)
            self.assertEqual(candidate["failed_gates"], [])
            self.assertEqual(candidate["failure_taxonomy"], [])
            self.assertEqual(json.loads(queue_path.read_text(encoding="utf-8"))["candidates"][0]["status"], "promoted")
        finally:
            _clean_tree(root)


if __name__ == "__main__":
    unittest.main()
