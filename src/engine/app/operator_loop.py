from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.app.config import build_study_signature_from_payload
from engine.app.config import load_study_config
from engine.app.data_sufficiency import build_data_sufficiency_report
from engine.app.guarded_loop import GuardedLoopRepeatSettings, run_guarded_loop_repeat
from engine.app.loop_readiness import build_loop_readiness_report
from engine.io.artifacts import write_json_atomic


CANDIDATE_QUEUE_VERSION = 1


@dataclass(frozen=True)
class OperateLoopSettings:
    output_dir: Path
    db_path: Path
    config_path: Path | None = None
    study_dir: Path | None = None
    profile: str = "strict_v3"
    max_cycles: int = 3
    iterations: int = 3
    run_budget: int = 3
    paper_dashboard_path: Path | None = None
    paper_postrun_summary_path: Path | None = None
    paper_calibration_feedback_path: Path | None = None
    strategy_evidence_card_path: Path | None = None
    require_research_ready: bool = False
    require_improvement_ready: bool = False
    allow_smoke: bool = False
    candidate_queue_path: Path | None = None


def run_operate_loop(settings: OperateLoopSettings) -> dict[str, object]:
    output_dir = settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "operator-loop-report.json"
    data_sufficiency_path = output_dir / "data-sufficiency.json"
    readiness_report_path = output_dir / "loop-readiness.json"
    candidate_queue_path = settings.candidate_queue_path or output_dir / "candidate-queue.json"
    guarded_repeat_report_path = output_dir / "guarded-loop-repeat.json"
    strategy_evidence_card = _load_strategy_evidence_card(settings.strategy_evidence_card_path)

    if settings.config_path is None:
        evidence_blocker = _strategy_evidence_card_blocker(strategy_evidence_card, settings=settings)
        if evidence_blocker:
            return _write_operator_report(
                report_path,
                status="blocked_strategy_evidence_card",
                profile=settings.profile,
                data_sufficiency_path=None,
                readiness_report_path=None,
                guarded_repeat_report_path=None,
                improvement_gate_path=None,
                candidate_queue_path=candidate_queue_path,
                can_claim_strategy_improvement=False,
                strategy_improvement_supported=False,
                next_actions=_strategy_evidence_card_next_actions(strategy_evidence_card, evidence_blocker),
                strategy_evidence_card_path=settings.strategy_evidence_card_path,
                strategy_evidence_card=strategy_evidence_card,
            )
        repeat_report = run_guarded_loop_repeat(
            GuardedLoopRepeatSettings(
                output_dir=output_dir,
                db_path=settings.db_path,
                study_dir=settings.study_dir,
                max_cycles=settings.max_cycles,
                iterations=settings.iterations,
                run_budget=settings.run_budget,
                paper_dashboard_path=settings.paper_dashboard_path,
                paper_postrun_summary_path=settings.paper_postrun_summary_path,
                paper_calibration_feedback_path=settings.paper_calibration_feedback_path,
            )
        )
        return _write_operator_report(
            report_path,
            status=str(repeat_report.get("status") or "blocked_missing_initial_study"),
            profile=settings.profile,
            data_sufficiency_path=None,
            readiness_report_path=None,
            guarded_repeat_report_path=guarded_repeat_report_path,
            improvement_gate_path=None,
            candidate_queue_path=candidate_queue_path,
            can_claim_strategy_improvement=False,
            strategy_improvement_supported=bool(repeat_report.get("strategy_improvement_supported")),
            next_actions=list(repeat_report.get("next_actions", [])) if isinstance(repeat_report.get("next_actions"), list) else [],
            strategy_evidence_card_path=settings.strategy_evidence_card_path,
            strategy_evidence_card=strategy_evidence_card,
        )

    study = load_study_config(settings.config_path)
    study_payload = json.loads(settings.config_path.read_text(encoding="utf-8"))
    data_sufficiency = build_data_sufficiency_report(study, profile=settings.profile)
    write_json_atomic(data_sufficiency_path, data_sufficiency)
    readiness_report = build_loop_readiness_report(study, config_path=settings.config_path)
    write_json_atomic(readiness_report_path, readiness_report)
    next_actions = _data_sufficiency_next_actions(data_sufficiency)
    queue = record_candidate_queue_entry(
        candidate_queue_path,
        study_payload=study_payload,
        config_path=settings.config_path,
        run_id=str(getattr(study, "run_id", "")),
        readiness=data_sufficiency,
        next_action_ids=[str(action["id"]) for action in next_actions if isinstance(action, dict) and action.get("id")],
        profile=settings.profile,
    )

    blocked = _operate_loop_data_blocker(data_sufficiency, settings=settings)
    if blocked:
        return _write_operator_report(
            report_path,
            status="blocked_data_sufficiency",
            profile=settings.profile,
            data_sufficiency_path=data_sufficiency_path,
            readiness_report_path=readiness_report_path,
            guarded_repeat_report_path=None,
            improvement_gate_path=None,
            candidate_queue_path=candidate_queue_path,
            can_claim_strategy_improvement=False,
            strategy_improvement_supported=False,
            next_actions=next_actions or [_next_action("repair_data_sufficiency", 1, blocked, [])],
            candidate_queue=queue,
            strategy_evidence_card_path=settings.strategy_evidence_card_path,
            strategy_evidence_card=strategy_evidence_card,
        )

    evidence_blocker = _strategy_evidence_card_blocker(strategy_evidence_card, settings=settings)
    if evidence_blocker:
        return _write_operator_report(
            report_path,
            status="blocked_strategy_evidence_card",
            profile=settings.profile,
            data_sufficiency_path=data_sufficiency_path,
            readiness_report_path=readiness_report_path,
            guarded_repeat_report_path=None,
            improvement_gate_path=None,
            candidate_queue_path=candidate_queue_path,
            can_claim_strategy_improvement=False,
            strategy_improvement_supported=False,
            next_actions=_strategy_evidence_card_next_actions(strategy_evidence_card, evidence_blocker),
            candidate_queue=queue,
            strategy_evidence_card_path=settings.strategy_evidence_card_path,
            strategy_evidence_card=strategy_evidence_card,
        )

    repeat_report = run_guarded_loop_repeat(
        GuardedLoopRepeatSettings(
            output_dir=output_dir,
            db_path=settings.db_path,
            config_path=settings.config_path,
            max_cycles=settings.max_cycles,
            iterations=settings.iterations,
            run_budget=settings.run_budget,
            paper_dashboard_path=settings.paper_dashboard_path,
            paper_postrun_summary_path=settings.paper_postrun_summary_path,
            paper_calibration_feedback_path=settings.paper_calibration_feedback_path,
        )
    )
    strategy_improvement_supported = bool(repeat_report.get("strategy_improvement_supported"))
    return _write_operator_report(
        report_path,
        status=str(repeat_report.get("status") or "completed"),
        profile=settings.profile,
        data_sufficiency_path=data_sufficiency_path,
        readiness_report_path=readiness_report_path,
        guarded_repeat_report_path=guarded_repeat_report_path,
        improvement_gate_path=_latest_improvement_gate_path(repeat_report),
        candidate_queue_path=candidate_queue_path,
        can_claim_strategy_improvement=strategy_improvement_supported and bool(data_sufficiency.get("improvement_ready")),
        strategy_improvement_supported=strategy_improvement_supported,
        next_actions=list(repeat_report.get("next_actions", [])) if isinstance(repeat_report.get("next_actions"), list) else [],
        candidate_queue=queue,
        strategy_evidence_card_path=settings.strategy_evidence_card_path,
        strategy_evidence_card=strategy_evidence_card,
    )


def record_candidate_queue_entry(
    queue_path: Path,
    *,
    study_payload: dict[str, object],
    config_path: Path,
    run_id: str,
    readiness: dict[str, object],
    failed_gates: list[str] | None = None,
    failure_taxonomy: list[str] | None = None,
    paper_hypotheses: list[str] | None = None,
    next_action_ids: list[str] | None = None,
    tested: bool = False,
    rejected: bool = False,
    promoted: bool = False,
    profile: str = "strict_v3",
) -> dict[str, object]:
    queue = load_candidate_queue(queue_path, profile=profile)
    candidate_id = build_candidate_id(study_payload)
    candidate = _find_candidate(queue, candidate_id)
    status = _candidate_status(
        readiness=readiness,
        tested=tested,
        rejected=rejected,
        promoted=promoted,
    )

    if candidate is None:
        candidate = {
            "candidate_id": candidate_id,
            "config_path": str(config_path),
            "status": status,
            "first_seen_run_id": run_id,
            "last_seen_run_id": run_id,
            "seen_count": 1,
            "readiness": _readiness_payload(readiness),
            "failed_gates": _string_list(failed_gates),
            "failure_taxonomy": _string_list(failure_taxonomy),
            "paper_hypotheses": _string_list(paper_hypotheses),
            "next_action_ids": _string_list(next_action_ids),
        }
        _candidate_list(queue).append(candidate)
    else:
        candidate["config_path"] = str(config_path)
        candidate["status"] = status
        candidate["last_seen_run_id"] = run_id
        candidate["seen_count"] = int(candidate.get("seen_count", 0) or 0) + 1
        candidate["readiness"] = _readiness_payload(readiness)
        candidate["failed_gates"] = _string_list(failed_gates)
        candidate["failure_taxonomy"] = _string_list(failure_taxonomy)
        candidate["paper_hypotheses"] = _string_list(paper_hypotheses)
        candidate["next_action_ids"] = _string_list(next_action_ids)

    write_candidate_queue(queue_path, queue)
    return queue


def build_candidate_id(study_payload: dict[str, object]) -> str:
    return f"sha256:{build_study_signature_from_payload(study_payload)}"


def load_candidate_queue(queue_path: Path, *, profile: str = "strict_v3") -> dict[str, object]:
    if not queue_path.exists():
        return _empty_candidate_queue(profile=profile)
    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return _empty_candidate_queue(profile=profile)
    payload.setdefault("artifact_type", "candidate_queue")
    payload.setdefault("version", CANDIDATE_QUEUE_VERSION)
    payload.setdefault("profile", profile)
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        payload["candidates"] = []
    return payload


def write_candidate_queue(queue_path: Path, queue: dict[str, object]) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(queue_path, queue, sort_keys=False)


def _empty_candidate_queue(*, profile: str) -> dict[str, object]:
    return {
        "artifact_type": "candidate_queue",
        "version": CANDIDATE_QUEUE_VERSION,
        "profile": profile,
        "candidates": [],
    }


def _find_candidate(queue: dict[str, object], candidate_id: str) -> dict[str, object] | None:
    for candidate in _candidate_list(queue):
        if isinstance(candidate, dict) and candidate.get("candidate_id") == candidate_id:
            return candidate
    return None


def _candidate_list(queue: dict[str, object]) -> list[dict[str, object]]:
    candidates = queue.get("candidates")
    if not isinstance(candidates, list):
        queue["candidates"] = []
        candidates = queue["candidates"]
    return candidates  # type: ignore[return-value]


def _candidate_status(
    *,
    readiness: dict[str, object],
    tested: bool,
    rejected: bool,
    promoted: bool,
) -> str:
    if promoted:
        return "promoted"
    if rejected:
        return "rejected"
    if tested:
        return "tested"
    if not bool(readiness.get("research_ready")):
        return "blocked_data"
    return "ready"


def _readiness_payload(readiness: dict[str, object]) -> dict[str, object]:
    return {
        "run_ready": bool(readiness.get("run_ready")),
        "research_ready": bool(readiness.get("research_ready")),
        "improvement_ready": bool(readiness.get("improvement_ready")),
        "blockers": _string_list(readiness.get("blockers")),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _operate_loop_data_blocker(data_sufficiency: dict[str, object], *, settings: OperateLoopSettings) -> str | None:
    if settings.require_improvement_ready and not bool(data_sufficiency.get("improvement_ready")):
        return "require_improvement_ready was set but data_sufficiency.improvement_ready is false."
    if settings.require_research_ready and not bool(data_sufficiency.get("research_ready")):
        return "require_research_ready was set but data_sufficiency.research_ready is false."
    if settings.allow_smoke:
        if not bool(data_sufficiency.get("run_ready")):
            return "allow_smoke was set but data_sufficiency.run_ready is false."
        return None
    if not bool(data_sufficiency.get("research_ready")):
        return "operate-loop requires research_ready data unless --allow-smoke is set."
    return None


def _data_sufficiency_next_actions(data_sufficiency: dict[str, object]) -> list[dict[str, object]]:
    blockers = _string_list(data_sufficiency.get("blockers"))
    missing = _string_list(data_sufficiency.get("missing_data_requirements"))
    actions: list[dict[str, object]] = []
    if "strict_v3_history" in missing or "insufficient_history_for_v3_improvement" in blockers:
        actions.append(
            _next_action(
                "collect_strict_v3_data",
                1,
                "Collect BTCUSDT/ETHUSDT 1h and 15m public archive history before claiming improvement.",
                [*blockers, *missing],
            )
        )
    if "observed_liquidation_sidecar" in missing or "liquidation_feature_missing_observed_sidecar" in blockers:
        actions.append(
            _next_action(
                "collect_observed_liquidation_sidecar",
                2,
                "Capture public forceOrder liquidation buckets; do not treat missing historical liquidations as zero.",
                [*blockers, *missing],
            )
        )
    if "paper_executor_feedback" in missing:
        actions.append(
            _next_action(
                "collect_paper_executor_feedback",
                3,
                "Collect paper dashboard, postrun summary, and calibration feedback before improvement claims.",
                missing,
            )
        )
    if not actions and blockers:
        actions.append(_next_action("repair_data_sufficiency", 4, "Repair strict data blockers before operating the loop.", blockers))
    return actions


def _write_operator_report(
    path: Path,
    *,
    status: str,
    profile: str,
    data_sufficiency_path: Path | None,
    readiness_report_path: Path | None,
    guarded_repeat_report_path: Path | None,
    improvement_gate_path: str | None,
    candidate_queue_path: Path,
    can_claim_strategy_improvement: bool,
    strategy_improvement_supported: bool,
    next_actions: list[object],
    candidate_queue: dict[str, object] | None = None,
    strategy_evidence_card_path: Path | None = None,
    strategy_evidence_card: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "artifact_type": "operator_loop_report",
        "status": status,
        "profile": profile,
        "can_claim_strategy_improvement": can_claim_strategy_improvement,
        "strategy_improvement_supported": strategy_improvement_supported,
        "data_sufficiency_path": str(data_sufficiency_path) if data_sufficiency_path else None,
        "readiness_report_path": str(readiness_report_path) if readiness_report_path else None,
        "guarded_repeat_report_path": str(guarded_repeat_report_path) if guarded_repeat_report_path else None,
        "improvement_gate_path": improvement_gate_path,
        "candidate_queue_path": str(candidate_queue_path),
        "strategy_evidence_card_path": str(strategy_evidence_card_path) if strategy_evidence_card_path else None,
        "next_actions": next_actions,
        "safe_operation_contract": {
            "private_live_trading_enabled": False,
            "secrets_required": False,
            "validation_gate_bypass_allowed": False,
            "risk_limit_widening_allowed": False,
            "production_executor_policy_mutation_allowed": False,
        },
    }
    if candidate_queue is not None:
        payload["candidate_queue_summary"] = {
            "candidate_count": len(candidate_queue.get("candidates", [])) if isinstance(candidate_queue.get("candidates"), list) else 0,
        }
    if strategy_evidence_card is not None:
        payload["strategy_evidence_card_summary"] = _strategy_evidence_card_summary(strategy_evidence_card)
    write_json_atomic(path, payload)
    return payload


def _load_strategy_evidence_card(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"strategy evidence card must be a JSON object: {path}")
    return payload


def _strategy_evidence_card_blocker(
    card: dict[str, object] | None,
    *,
    settings: OperateLoopSettings,
) -> str | None:
    if card is None:
        if settings.require_improvement_ready:
            return "require_improvement_ready was set but no strategy evidence card was provided."
        return None
    if bool(card.get("can_claim_strategy_improvement")):
        return None
    blockers = _string_list(card.get("blockers"))
    if blockers:
        return "strategy evidence card blocks improvement: " + ", ".join(blockers)
    return "strategy evidence card does not allow strategy-improvement claims."


def _strategy_evidence_card_next_actions(
    card: dict[str, object] | None,
    blocker: str,
) -> list[dict[str, object]]:
    if card is None:
        return [
            _next_action(
                "build_strategy_evidence_card",
                1,
                "Build a strategy evidence card before rerunning or promoting candidates under require-improvement-ready.",
                [blocker],
            )
        ]
    action = str(card.get("next_allowed_action") or "repair_strategy_evidence")
    blockers = _string_list(card.get("blockers")) or [blocker]
    return [_next_action(action, 1, "Repair blocked strategy evidence before operating the loop.", blockers)]


def _strategy_evidence_card_summary(card: dict[str, object]) -> dict[str, object]:
    return {
        "candidate_id": card.get("candidate_id"),
        "status": card.get("status"),
        "can_claim_strategy_improvement": bool(card.get("can_claim_strategy_improvement")),
        "next_allowed_action": card.get("next_allowed_action"),
        "blockers": _string_list(card.get("blockers")),
    }


def _latest_improvement_gate_path(repeat_report: dict[str, object]) -> str | None:
    cycles = repeat_report.get("cycles")
    if not isinstance(cycles, list):
        return None
    for cycle in reversed(cycles):
        if isinstance(cycle, dict) and cycle.get("improvement_gate_path"):
            return str(cycle["improvement_gate_path"])
    return None


def _next_action(action_id: str, priority: int, action: str, evidence: list[str]) -> dict[str, object]:
    return {
        "id": action_id,
        "priority": priority,
        "action": action,
        "evidence": sorted(dict.fromkeys(str(item) for item in evidence if item)),
    }
