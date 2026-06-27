from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from engine.agent.controller import AgentLoopController, AgentLoopSettings
from engine.app.config import load_study_config
from engine.app.loop_evidence import build_loop_evidence_ledger
from engine.app.loop_improvement import build_loop_improvement_gate
from engine.app.loop_readiness import build_loop_readiness_report, build_loop_readiness_scan
from engine.app.study_hydration import hydrate_study_liquidations, verify_study_liquidations
from engine.io.artifacts import write_json_atomic


@dataclass(frozen=True)
class GuardedLoopCycleSettings:
    config_path: Path
    output_dir: Path
    db_path: Path
    liquidations_path: Path | None = None
    hydrated_config_path: Path | None = None
    iterations: int = 3
    run_budget: int = 3
    loop_mode: str = "auto"
    karpathy_execution: str = "auto"
    karpathy_target_path: str | None = None
    karpathy_target_kind: str = "json_config"
    karpathy_execute_git_actions: bool | None = None
    memory_limit: int = 25
    memory_quality_policy: str = "clean-only"
    trace_advisory_notes_path: str | None = None
    improvement_gate_path: str | None = None
    paper_dashboard_path: Path | None = None
    paper_postrun_summary_path: Path | None = None
    paper_calibration_feedback_path: Path | None = None
    max_abs_slip_bps: float = 25.0
    minimum_paper_orders: int = 10
    minimum_telemetry_quality: float = 0.70


@dataclass(frozen=True)
class GuardedLoopRepeatSettings:
    output_dir: Path
    db_path: Path
    study_dir: Path | None = None
    config_path: Path | None = None
    liquidations_path: Path | None = None
    hydrated_config_path: Path | None = None
    max_cycles: int = 3
    iterations: int = 3
    run_budget: int = 3
    loop_mode: str = "auto"
    karpathy_execution: str = "auto"
    karpathy_target_kind: str = "json_config"
    karpathy_execute_git_actions: bool | None = None
    memory_limit: int = 25
    memory_quality_policy: str = "clean-only"
    trace_advisory_notes_path: str | None = None
    paper_dashboard_path: Path | None = None
    paper_postrun_summary_path: Path | None = None
    paper_calibration_feedback_path: Path | None = None
    max_abs_slip_bps: float = 25.0
    minimum_paper_orders: int = 10
    minimum_telemetry_quality: float = 0.70


def run_guarded_loop_repeat(settings: GuardedLoopRepeatSettings) -> dict[str, object]:
    output_dir = settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    repeat_report_path = output_dir / "guarded-loop-repeat.json"
    readiness_scan_path = output_dir / "loop-readiness-scan.json"
    scan_root = settings.config_path or settings.study_dir
    if scan_root is None:
        return _write_repeat_report(
            repeat_report_path,
            status="blocked_missing_initial_study",
            readiness_scan_path=readiness_scan_path,
            readiness_scan={
                "artifact_type": "loop_readiness_scan",
                "root": None,
                "study_count": 0,
                "eligible_count": 0,
                "blocked_count": 0,
                "blocked_by_reason": {},
                "eligible": [],
                "blocked": [],
                "errors": [],
            },
            cycles=[],
            candidate_readiness_reports=[],
        )
    readiness_scan = build_loop_readiness_scan(scan_root)
    write_json_atomic(readiness_scan_path, readiness_scan)

    eligible = readiness_scan.get("eligible")
    eligible_reports = eligible if isinstance(eligible, list) else []
    if settings.config_path is not None:
        active_config = settings.config_path
    elif eligible_reports:
        active_config = Path(str(eligible_reports[0]["config_path"]))
    else:
        return _write_repeat_report(
            repeat_report_path,
            status="blocked_no_eligible_study",
            readiness_scan_path=readiness_scan_path,
            readiness_scan=readiness_scan,
            cycles=[],
            candidate_readiness_reports=[],
        )

    cycles: list[dict[str, object]] = []
    candidate_readiness_reports: list[dict[str, object]] = []
    status = "completed_max_cycles"
    improvement_gate_path: str | None = None

    for cycle_number in range(1, max(0, settings.max_cycles) + 1):
        cycle_dir = output_dir / f"cycle-{cycle_number:03d}"
        cycle_payload = run_guarded_loop_cycle(
            GuardedLoopCycleSettings(
                config_path=active_config,
                output_dir=cycle_dir,
                db_path=settings.db_path,
                liquidations_path=settings.liquidations_path if cycle_number == 1 else None,
                hydrated_config_path=settings.hydrated_config_path if cycle_number == 1 else None,
                iterations=settings.iterations,
                run_budget=settings.run_budget,
                loop_mode=settings.loop_mode,
                karpathy_execution=settings.karpathy_execution,
                karpathy_target_kind=settings.karpathy_target_kind,
                karpathy_execute_git_actions=settings.karpathy_execute_git_actions,
                memory_limit=settings.memory_limit,
                memory_quality_policy=settings.memory_quality_policy,
                trace_advisory_notes_path=settings.trace_advisory_notes_path,
                improvement_gate_path=improvement_gate_path,
                paper_dashboard_path=settings.paper_dashboard_path,
                paper_postrun_summary_path=settings.paper_postrun_summary_path,
                paper_calibration_feedback_path=settings.paper_calibration_feedback_path,
                max_abs_slip_bps=settings.max_abs_slip_bps,
                minimum_paper_orders=settings.minimum_paper_orders,
                minimum_telemetry_quality=settings.minimum_telemetry_quality,
            )
        )
        cycles.append(_summarize_repeat_cycle(cycle_number, active_config, cycle_payload))
        if str(cycle_payload.get("status") or "").startswith("blocked_"):
            status = str(cycle_payload.get("status"))
            break
        if bool(cycle_payload.get("strategy_improvement_supported")):
            status = "completed_strategy_improvement_supported"
            break

        next_candidate_path = _next_candidate_from_cycle(cycle_payload)
        if next_candidate_path is None:
            status = "completed_no_next_candidate"
            break

        candidate_report = build_loop_readiness_report(load_study_config(next_candidate_path), config_path=next_candidate_path)
        candidate_report_path = output_dir / f"cycle-{cycle_number:03d}-next-candidate-readiness.json"
        write_json_atomic(candidate_report_path, candidate_report)
        candidate_readiness_reports.append(
            {
                "path": str(candidate_report_path),
                "config_path": str(next_candidate_path),
                "eligible": bool(candidate_report.get("eligible")),
                "blockers": list(candidate_report.get("blockers", [])),
            }
        )
        if not bool(candidate_report.get("eligible")):
            status = "stopped_next_candidate_not_ready"
            break

        active_config = next_candidate_path
        gate_path = cycle_payload.get("improvement_gate_path")
        improvement_gate_path = str(gate_path) if gate_path else None

    if not cycles and settings.max_cycles <= 0:
        status = "blocked_zero_cycle_budget"

    return _write_repeat_report(
        repeat_report_path,
        status=status,
        readiness_scan_path=readiness_scan_path,
        readiness_scan=readiness_scan,
        cycles=cycles,
        candidate_readiness_reports=candidate_readiness_reports,
    )


def run_guarded_loop_cycle(settings: GuardedLoopCycleSettings) -> dict[str, object]:
    output_dir = settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    cycle_report_path = output_dir / "guarded-loop-cycle.json"
    readiness_report_path = output_dir / "loop-readiness.json"
    evidence_ledger_path = output_dir / "loop-evidence-ledger.json"
    sidecar_verification_path = output_dir / "liquidation-sidecar-verification.json"
    improvement_gate_output_path = output_dir / "loop-improvement-gate.json"

    config_path = settings.config_path
    sidecar_verification = None
    hydration_payload = None
    hydrated_config_path = settings.hydrated_config_path or output_dir / "hydrated-study.json"

    if settings.liquidations_path is not None:
        try:
            sidecar_verification = verify_study_liquidations(
                config_path=config_path,
                liquidations_path=settings.liquidations_path,
                output_path=sidecar_verification_path,
            )
        except Exception as exc:
            sidecar_verification = {
                "artifact_type": "liquidation_sidecar_verification",
                "status": "not_ready",
                "config_path": str(config_path),
                "liquidations_path": str(settings.liquidations_path),
                "error": f"{type(exc).__name__}: {exc}",
            }
            write_json_atomic(sidecar_verification_path, sidecar_verification)
        if sidecar_verification["status"] != "ready":
            return _write_cycle_report(
                cycle_report_path,
                status="blocked_sidecar_not_ready",
                config_path=config_path,
                active_config_path=config_path,
                readiness_report_path=None,
                evidence_ledger_path=None,
                agent_loop_report_path=None,
                sidecar_verification_path=sidecar_verification_path,
                hydration_path=None,
                improvement_gate_path=None,
                stage_payloads={"sidecar_verification": sidecar_verification},
            )
        try:
            hydration_payload = hydrate_study_liquidations(
                config_path=config_path,
                liquidations_path=settings.liquidations_path,
                output_path=hydrated_config_path,
            )
        except Exception as exc:
            hydration_payload = {
                "artifact_type": "study_liquidation_hydration",
                "status": "hydration_error",
                "config_path": str(config_path),
                "liquidations_path": str(settings.liquidations_path),
                "output_path": str(hydrated_config_path),
                "error": f"{type(exc).__name__}: {exc}",
            }
        if hydration_payload["status"] != "hydrated":
            return _write_cycle_report(
                cycle_report_path,
                status="blocked_hydration_not_ready",
                config_path=config_path,
                active_config_path=config_path,
                readiness_report_path=None,
                evidence_ledger_path=None,
                agent_loop_report_path=None,
                sidecar_verification_path=sidecar_verification_path,
                hydration_path=hydrated_config_path,
                improvement_gate_path=None,
                stage_payloads={
                    "sidecar_verification": sidecar_verification,
                    "hydration": hydration_payload,
                },
            )
        config_path = hydrated_config_path

    study = load_study_config(config_path)
    readiness_report = build_loop_readiness_report(study, config_path=config_path)
    write_json_atomic(readiness_report_path, readiness_report)
    data_sufficiency_path = output_dir / "data-sufficiency.json"
    data_sufficiency = readiness_report.get("data_sufficiency")
    if isinstance(data_sufficiency, dict):
        write_json_atomic(data_sufficiency_path, data_sufficiency)
    if not bool(readiness_report.get("eligible", False)):
        evidence_ledger = build_loop_evidence_ledger(
            agent_loop_report_paths=[],
            readiness_report_paths=[readiness_report_path],
        )
        write_json_atomic(evidence_ledger_path, evidence_ledger)
        return _write_cycle_report(
            cycle_report_path,
            status="blocked_loop_readiness",
            config_path=settings.config_path,
            active_config_path=config_path,
            readiness_report_path=readiness_report_path,
            evidence_ledger_path=evidence_ledger_path,
            agent_loop_report_path=None,
            sidecar_verification_path=sidecar_verification_path if sidecar_verification else None,
            hydration_path=hydrated_config_path if hydration_payload else None,
            improvement_gate_path=None,
            stage_payloads={
                "sidecar_verification": sidecar_verification,
                "hydration": hydration_payload,
                "readiness": readiness_report,
                "evidence_ledger": evidence_ledger,
            },
        )

    paper_feedback_preflight = _paper_feedback_preflight(
        paper_dashboard_path=settings.paper_dashboard_path,
        paper_postrun_summary_path=settings.paper_postrun_summary_path,
        paper_calibration_feedback_path=settings.paper_calibration_feedback_path,
    )
    if paper_feedback_preflight["status"] == "incomplete":
        evidence_ledger = build_loop_evidence_ledger(
            agent_loop_report_paths=[],
            readiness_report_paths=[readiness_report_path],
        )
        write_json_atomic(evidence_ledger_path, evidence_ledger)
        return _write_cycle_report(
            cycle_report_path,
            status="blocked_paper_feedback_incomplete",
            config_path=settings.config_path,
            active_config_path=config_path,
            readiness_report_path=readiness_report_path,
            evidence_ledger_path=evidence_ledger_path,
            agent_loop_report_path=None,
            sidecar_verification_path=sidecar_verification_path if sidecar_verification else None,
            hydration_path=hydrated_config_path if hydration_payload else None,
            improvement_gate_path=None,
            stage_payloads={
                "sidecar_verification": sidecar_verification,
                "hydration": hydration_payload,
                "readiness": readiness_report,
                "evidence_ledger": evidence_ledger,
                "paper_feedback_preflight": paper_feedback_preflight,
            },
        )

    base_payload = json.loads(config_path.read_text(encoding="utf-8"))
    controller = AgentLoopController(
        settings=AgentLoopSettings(
            loop_mode=settings.loop_mode,
            karpathy_execution_mode=settings.karpathy_execution,
            karpathy_git_execute_actions=settings.karpathy_execute_git_actions,
            karpathy_target_path=settings.karpathy_target_path,
            karpathy_target_kind=settings.karpathy_target_kind,
            max_iterations=settings.iterations,
            run_budget=settings.run_budget,
            memory_limit=settings.memory_limit,
            memory_quality_policy=settings.memory_quality_policy,
            trace_advisory_notes_path=settings.trace_advisory_notes_path,
            improvement_gate_path=settings.improvement_gate_path,
            strict_quality=True,
        )
    )
    agent_loop_report = controller.run(
        initial_payload=base_payload,
        output_dir=output_dir,
        db_path=settings.db_path,
    )
    agent_loop_report_path = Path(str(agent_loop_report["report_path"]))
    evidence_ledger = build_loop_evidence_ledger(
        agent_loop_report_paths=[agent_loop_report_path],
        readiness_report_paths=[readiness_report_path],
        paper_dashboard_paths=[settings.paper_dashboard_path] if settings.paper_dashboard_path else [],
        paper_postrun_summary_paths=[settings.paper_postrun_summary_path] if settings.paper_postrun_summary_path else [],
        paper_calibration_feedback_paths=[settings.paper_calibration_feedback_path]
        if settings.paper_calibration_feedback_path
        else [],
    )
    write_json_atomic(evidence_ledger_path, evidence_ledger)

    improvement_gate = None
    if settings.paper_dashboard_path and settings.paper_postrun_summary_path and settings.paper_calibration_feedback_path:
        improvement_gate = build_loop_improvement_gate(
            ledger_path=evidence_ledger_path,
            paper_dashboard_path=settings.paper_dashboard_path,
            postrun_summary_path=settings.paper_postrun_summary_path,
            calibration_feedback_path=settings.paper_calibration_feedback_path,
            data_sufficiency_path=data_sufficiency_path,
            max_abs_slip_bps=settings.max_abs_slip_bps,
            minimum_paper_orders=settings.minimum_paper_orders,
            minimum_telemetry_quality=settings.minimum_telemetry_quality,
        )
        write_json_atomic(improvement_gate_output_path, improvement_gate)

    return _write_cycle_report(
        cycle_report_path,
        status=str(agent_loop_report.get("status") or "completed"),
        config_path=settings.config_path,
        active_config_path=config_path,
        readiness_report_path=readiness_report_path,
        evidence_ledger_path=evidence_ledger_path,
        agent_loop_report_path=agent_loop_report_path,
        sidecar_verification_path=sidecar_verification_path if sidecar_verification else None,
        hydration_path=hydrated_config_path if hydration_payload else None,
        improvement_gate_path=improvement_gate_output_path if improvement_gate else None,
        stage_payloads={
            "sidecar_verification": sidecar_verification,
            "hydration": hydration_payload,
            "readiness": readiness_report,
            "paper_feedback_preflight": paper_feedback_preflight,
            "agent_loop": agent_loop_report,
            "evidence_ledger": evidence_ledger,
            "improvement_gate": improvement_gate,
        },
    )


def _write_cycle_report(
    path: Path,
    *,
    status: str,
    config_path: Path,
    active_config_path: Path,
    readiness_report_path: Path | None,
    evidence_ledger_path: Path | None,
    agent_loop_report_path: Path | None,
    sidecar_verification_path: Path | None,
    hydration_path: Path | None,
    improvement_gate_path: Path | None,
    stage_payloads: dict[str, object],
) -> dict[str, object]:
    next_actions = _cycle_next_actions(status=status, stage_payloads=stage_payloads)
    payload = {
        "artifact_type": "guarded_loop_cycle_report",
        "status": status,
        "config_path": str(config_path),
        "active_config_path": str(active_config_path),
        "cycle_report_path": str(path),
        "sidecar_verification_path": str(sidecar_verification_path) if sidecar_verification_path else None,
        "hydrated_config_path": str(hydration_path) if hydration_path else None,
        "readiness_report_path": str(readiness_report_path) if readiness_report_path else None,
        "agent_loop_report_path": str(agent_loop_report_path) if agent_loop_report_path else None,
        "evidence_ledger_path": str(evidence_ledger_path) if evidence_ledger_path else None,
        "improvement_gate_path": str(improvement_gate_path) if improvement_gate_path else None,
        "strategy_improvement_supported": _strategy_improvement_supported(stage_payloads.get("improvement_gate")),
        "strategy_improvement_evidence_status": _strategy_improvement_evidence_status(stage_payloads.get("improvement_gate")),
        "next_actions": next_actions,
        "safe_operation_contract": {
            "private_live_trading_enabled": False,
            "secrets_required": False,
            "validation_gate_bypass_allowed": False,
            "risk_limit_widening_allowed": False,
            "production_executor_policy_mutation_allowed": False,
            "strict_quality": True,
            "loop_readiness_required": True,
        },
        "stages": stage_payloads,
    }
    write_json_atomic(path, payload)
    return payload


def _write_repeat_report(
    path: Path,
    *,
    status: str,
    readiness_scan_path: Path,
    readiness_scan: dict[str, object],
    cycles: list[dict[str, object]],
    candidate_readiness_reports: list[dict[str, object]],
) -> dict[str, object]:
    aggregate_learning_summary = _aggregate_learning_summary(cycles)
    next_actions = _repeat_next_actions(status=status, readiness_scan=readiness_scan, cycles=cycles)
    payload = {
        "artifact_type": "guarded_loop_repeat_report",
        "status": status,
        "repeat_report_path": str(path),
        "readiness_scan_path": str(readiness_scan_path),
        "study_count": readiness_scan.get("study_count", 0),
        "eligible_count": readiness_scan.get("eligible_count", 0),
        "blocked_count": readiness_scan.get("blocked_count", 0),
        "blocked_by_reason": dict(readiness_scan.get("blocked_by_reason", {})),
        "cycle_count": len(cycles),
        "cycles": cycles,
        "aggregate_learning_summary": aggregate_learning_summary,
        "candidate_readiness_reports": candidate_readiness_reports,
        "strategy_improvement_supported": any(bool(cycle.get("strategy_improvement_supported")) for cycle in cycles),
        "next_actions": next_actions,
        "safe_operation_contract": {
            "private_live_trading_enabled": False,
            "secrets_required": False,
            "validation_gate_bypass_allowed": False,
            "risk_limit_widening_allowed": False,
            "production_executor_policy_mutation_allowed": False,
            "strict_quality": True,
            "loop_readiness_required": True,
        },
    }
    write_json_atomic(path, payload)
    return payload


def _cycle_next_actions(*, status: str, stage_payloads: dict[str, object]) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    if status == "blocked_sidecar_not_ready":
        sidecar = stage_payloads.get("sidecar_verification")
        sidecar = sidecar if isinstance(sidecar, dict) else {}
        error = str(sidecar.get("error") or "")
        if "source_paths" in error:
            actions.append(
                _next_action(
                    "repair_hydratable_study_sources",
                    1,
                    "Use a real study with snapshot.provenance.source_paths for candles, funding, and open interest before sidecar hydration.",
                    [error],
                )
            )
        actions.append(
            _next_action(
                "provide_ready_liquidation_sidecar",
                2,
                "Provide observed public forceOrder liquidation_notional coverage that verify-study-liquidations marks ready.",
                _string_evidence([sidecar.get("status"), sidecar.get("liquidations")]),
            )
        )
    elif status == "blocked_hydration_not_ready":
        hydration = stage_payloads.get("hydration")
        hydration = hydration if isinstance(hydration, dict) else {}
        actions.append(
            _next_action(
                "repair_liquidation_sidecar_quality",
                1,
                "Fix liquidation sidecar missing coverage or quality issues before hydration can create clean input.",
                _string_evidence([hydration.get("status"), hydration.get("quality_issues"), hydration.get("error")]),
            )
        )
    elif status == "blocked_loop_readiness":
        readiness = stage_payloads.get("readiness")
        readiness = readiness if isinstance(readiness, dict) else {}
        shortfall_action = _readiness_shortfall_action(readiness)
        actions.append(
            shortfall_action
            if shortfall_action is not None
            else _next_action(
                    "build_clean_real_study",
                    1,
                    "Build or hydrate a non-fixture real-source study that passes loop-readiness before rerunning.",
                    _string_evidence(readiness.get("blockers")),
            )
        )
    elif status == "blocked_paper_feedback_incomplete":
        preflight = stage_payloads.get("paper_feedback_preflight")
        preflight = preflight if isinstance(preflight, dict) else {}
        actions.append(
            _next_action(
                "supply_complete_valid_paper_feedback_bundle",
                1,
                "Supply valid paper dashboard, postrun summary, and calibration feedback artifacts together.",
                _string_evidence([preflight.get("missing_inputs"), preflight.get("missing_files"), preflight.get("invalid_files")]),
            )
        )
    elif status != "completed":
        actions.extend(_agent_loop_failure_actions(stage_payloads))
        if not actions:
            actions.append(
                _next_action(
                    "inspect_guarded_cycle_status",
                    5,
                    "Inspect guarded cycle stages before rerunning.",
                    [status],
                )
            )
    return actions


def _repeat_next_actions(
    *,
    status: str,
    readiness_scan: dict[str, object],
    cycles: list[dict[str, object]],
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    if status in {"blocked_missing_initial_study", "blocked_no_eligible_study"}:
        shortfall_action = _readiness_scan_shortfall_action(readiness_scan)
        actions.append(
            shortfall_action
            if shortfall_action is not None
            else _next_action(
                    "build_clean_real_study",
                    1,
                    "Create at least one real-source study that passes loop-readiness before repeat execution.",
                    _string_evidence(readiness_scan.get("blocked_by_reason")),
            )
        )
    elif status == "blocked_zero_cycle_budget":
        actions.append(_next_action("raise_cycle_budget", 1, "Set --max-cycles above zero.", []))
    elif status == "stopped_next_candidate_not_ready":
        actions.append(
            _next_action(
                "repair_next_candidate_readiness",
                1,
                "Repair the generated next-study candidate until loop-readiness marks it eligible.",
                [],
            )
        )
    for cycle in cycles:
        cycle_report_path = cycle.get("cycle_report_path")
        if not isinstance(cycle_report_path, str) or not cycle_report_path:
            continue
        path = Path(cycle_report_path)
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        for action in payload.get("next_actions", []):
            if isinstance(action, dict):
                actions.append(dict(action))
    return _dedupe_actions(actions)


def _next_action(action_id: str, priority: int, action: str, evidence: list[str]) -> dict[str, object]:
    return {
        "id": action_id,
        "priority": priority,
        "action": action,
        "evidence": evidence,
    }


def _dedupe_actions(actions: list[dict[str, object]]) -> list[dict[str, object]]:
    by_id: dict[str, dict[str, object]] = {}
    for action in actions:
        action_id = action.get("id")
        if not isinstance(action_id, str) or not action_id:
            continue
        current = by_id.get(action_id)
        if current is None or _int_value(action.get("priority")) < _int_value(current.get("priority")):
            by_id[action_id] = action
            continue
        if current is not None:
            current_evidence = current.get("evidence")
            extra_evidence = action.get("evidence")
            if isinstance(current_evidence, list) and isinstance(extra_evidence, list):
                current["evidence"] = list(dict.fromkeys([*current_evidence, *extra_evidence]))
    return sorted(by_id.values(), key=lambda item: _int_value(item.get("priority")))


def _string_evidence(value: object) -> list[str]:
    if isinstance(value, dict):
        return [f"{key}={value[key]}" for key in sorted(value)]
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(_string_evidence(item))
        return items
    if value is None:
        return []
    text = str(value)
    return [text] if text else []


def _readiness_scan_shortfall_action(readiness_scan: dict[str, object]) -> dict[str, object] | None:
    blocked = readiness_scan.get("blocked")
    if not isinstance(blocked, list):
        return None
    best: dict[str, object] | None = None
    for item in blocked:
        if not isinstance(item, dict):
            continue
        action = _readiness_shortfall_action(item)
        if action is None:
            continue
        if best is None or _missing_bucket_count(action) < _missing_bucket_count(best):
            best = action
    return best


def _readiness_shortfall_action(readiness: dict[str, object]) -> dict[str, object] | None:
    blockers = readiness.get("blockers")
    if not isinstance(blockers, list) or "insufficient_candle_count" not in blockers:
        return None
    candle_count = _int_value(readiness.get("candle_count"))
    minimum = _int_value(readiness.get("minimum_candle_count"))
    missing = max(0, minimum - candle_count)
    return _next_action(
        "collect_minimum_observed_buckets",
        1,
        f"Collect at least {missing} more observed public forceOrder-aligned candle buckets, then rebuild and hydrate the study.",
        [
            f"candle_count={candle_count}",
            f"minimum_candle_count={minimum}",
            f"missing_candle_count={missing}",
            *_string_evidence(readiness.get("blockers")),
        ],
    )


def _missing_bucket_count(action: dict[str, object]) -> int:
    evidence = action.get("evidence")
    if not isinstance(evidence, list):
        return 0
    for item in evidence:
        if not isinstance(item, str) or not item.startswith("missing_candle_count="):
            continue
        try:
            return int(item.split("=", 1)[1])
        except ValueError:
            return 0
    return 0


def _agent_loop_failure_actions(stage_payloads: dict[str, object]) -> list[dict[str, object]]:
    agent_loop = stage_payloads.get("agent_loop")
    agent_loop = agent_loop if isinstance(agent_loop, dict) else {}
    errors = _agent_loop_crash_errors(agent_loop)
    if not errors:
        return []
    if "signal_tf_not_allowed" in errors:
        return [
            _next_action(
                "repair_strategy_timeframe_contract",
                1,
                "Adjust generated strategy signal timeframe to an allowed value before rerunning this clean study.",
                errors,
            )
        ]
    return [
        _next_action(
            "route_agent_loop_crash_to_hypothesis",
            2,
            "Turn the agent-loop crash reason into a concrete next-study hypothesis before rerunning.",
            errors,
        )
    ]


def _agent_loop_crash_errors(agent_loop: dict[str, object]) -> list[str]:
    errors: list[str] = []
    events = agent_loop.get("events")
    if not isinstance(events, list):
        return errors
    for event in events:
        if not isinstance(event, dict) or event.get("event") != "iteration_crashed":
            continue
        details = event.get("details")
        details = details if isinstance(details, dict) else {}
        error = details.get("error")
        if isinstance(error, str) and error and error not in errors:
            errors.append(error)
    return errors


def _action_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _aggregate_learning_summary(cycles: list[dict[str, object]]) -> dict[str, object]:
    stop_reasons: list[str] = []
    failed_gate_counts: dict[str, int] = {}
    failure_taxonomy_counts: dict[str, int] = {}
    readiness_blocker_counts: dict[str, int] = {}
    memory_effect_count = 0
    next_candidate_count = 0
    next_candidate_paths: list[str] = []
    paper_feedback_cycle_count = 0
    run_count = 0
    promoted_run_count = 0
    for cycle in cycles:
        learning = cycle.get("learning_summary")
        if not isinstance(learning, dict):
            continue
        run_count += _int_value(learning.get("run_count"))
        promoted_run_count += _int_value(learning.get("promoted_run_count"))
        for reason in learning.get("stop_reasons", []):
            if isinstance(reason, str) and reason and reason not in stop_reasons:
                stop_reasons.append(reason)
        _merge_counts(failed_gate_counts, learning.get("failed_gate_counts"))
        _merge_counts(failure_taxonomy_counts, learning.get("failure_taxonomy_counts"))
        _merge_counts(readiness_blocker_counts, learning.get("readiness_blocker_counts"))
        memory_effects = learning.get("memory_effects")
        if isinstance(memory_effects, list):
            memory_effect_count += len(memory_effects)
        next_candidates = learning.get("next_candidates")
        if isinstance(next_candidates, list):
            next_candidate_count += len(next_candidates)
            for candidate in next_candidates:
                if not isinstance(candidate, dict):
                    continue
                path = candidate.get("path")
                if isinstance(path, str) and path and path not in next_candidate_paths:
                    next_candidate_paths.append(path)
        paper_feedback = learning.get("paper_feedback")
        if isinstance(paper_feedback, dict) and paper_feedback:
            paper_feedback_cycle_count += 1
    return {
        "run_count": run_count,
        "promoted_run_count": promoted_run_count,
        "stop_reasons": stop_reasons,
        "failed_gate_counts": dict(sorted(failed_gate_counts.items())),
        "failure_taxonomy_counts": dict(sorted(failure_taxonomy_counts.items())),
        "readiness_blocker_counts": dict(sorted(readiness_blocker_counts.items())),
        "memory_effect_count": memory_effect_count,
        "next_candidate_count": next_candidate_count,
        "next_candidate_paths": next_candidate_paths,
        "paper_feedback_cycle_count": paper_feedback_cycle_count,
    }


def _merge_counts(target: dict[str, int], source: object) -> None:
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        if not isinstance(key, str):
            continue
        target[key] = target.get(key, 0) + _int_value(value)


def _paper_feedback_preflight(
    *,
    paper_dashboard_path: Path | None,
    paper_postrun_summary_path: Path | None,
    paper_calibration_feedback_path: Path | None,
) -> dict[str, object]:
    inputs = {
        "paper_dashboard": paper_dashboard_path,
        "paper_postrun_summary": paper_postrun_summary_path,
        "paper_calibration_feedback": paper_calibration_feedback_path,
    }
    provided = {name: path for name, path in inputs.items() if path is not None}
    if not provided:
        return {
            "artifact_type": "paper_feedback_preflight",
            "status": "not_requested",
            "provided_inputs": [],
            "missing_inputs": [],
            "missing_files": [],
            "invalid_files": [],
        }
    missing_inputs = [name for name, path in inputs.items() if path is None]
    missing_files = [str(path) for path in provided.values() if not path.exists()]
    invalid_files = _invalid_paper_feedback_files(provided)
    return {
        "artifact_type": "paper_feedback_preflight",
        "status": "ready" if not missing_inputs and not missing_files and not invalid_files else "incomplete",
        "provided_inputs": sorted(provided),
        "missing_inputs": missing_inputs,
        "missing_files": missing_files,
        "invalid_files": invalid_files,
    }


def _invalid_paper_feedback_files(provided: dict[str, Path]) -> list[dict[str, str]]:
    invalid: list[dict[str, str]] = []
    for name, path in sorted(provided.items()):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            invalid.append({"input": name, "path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not isinstance(payload, dict):
            invalid.append({"input": name, "path": str(path), "error": "paper feedback artifact must be a JSON object"})
    return invalid


def _summarize_repeat_cycle(cycle_number: int, config_path: Path, payload: dict[str, object]) -> dict[str, object]:
    learning_summary = _cycle_learning_summary(payload)
    return {
        "cycle": cycle_number,
        "status": payload.get("status"),
        "config_path": str(config_path),
        "active_config_path": payload.get("active_config_path"),
        "cycle_report_path": payload.get("cycle_report_path"),
        "readiness_report_path": payload.get("readiness_report_path"),
        "agent_loop_report_path": payload.get("agent_loop_report_path"),
        "evidence_ledger_path": payload.get("evidence_ledger_path"),
        "improvement_gate_path": payload.get("improvement_gate_path"),
        "strategy_improvement_supported": bool(payload.get("strategy_improvement_supported")),
        "strategy_improvement_evidence_status": payload.get("strategy_improvement_evidence_status"),
        "sidecar_error": _cycle_stage_error(payload, "sidecar_verification"),
        "hydration_error": _cycle_stage_error(payload, "hydration"),
        "paper_feedback_error": _cycle_stage_error(payload, "paper_feedback_preflight"),
        "learning_summary": learning_summary,
        "next_actions": _action_list(payload.get("next_actions")),
    }


def _next_candidate_from_cycle(payload: dict[str, object]) -> Path | None:
    ledger_path_raw = payload.get("evidence_ledger_path")
    if not isinstance(ledger_path_raw, str) or not ledger_path_raw:
        return None
    ledger_path = Path(ledger_path_raw)
    if not ledger_path.exists():
        return None
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(ledger, dict):
        return None
    runs = ledger.get("runs")
    if not isinstance(runs, list):
        return None
    for run in runs:
        if not isinstance(run, dict) or not bool(run.get("next_candidate_exists")):
            continue
        candidate_path = run.get("next_candidate_path")
        if isinstance(candidate_path, str) and candidate_path:
            return Path(candidate_path)
    return None


def _cycle_learning_summary(payload: dict[str, object]) -> dict[str, object]:
    ledger = _load_cycle_ledger(payload)
    if not ledger:
        return {
            "run_count": 0,
            "promoted_run_count": 0,
            "stop_reasons": [],
            "failed_gate_counts": {},
            "failure_taxonomy_counts": {},
            "readiness_blocker_counts": {},
            "memory_effects": [],
            "next_candidates": [],
            "paper_feedback": {},
        }
    runs = ledger.get("runs")
    run_maps = [run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []
    return {
        "run_count": _int_value(ledger.get("run_count")),
        "promoted_run_count": _int_value(ledger.get("promoted_run_count")),
        "stop_reasons": _unique_strings(run.get("stop_reason") for run in run_maps),
        "failed_gate_counts": _count_cycle_values(run.get("failed_gates") for run in run_maps),
        "failure_taxonomy_counts": _count_cycle_values(run.get("failure_taxonomy") for run in run_maps),
        "readiness_blocker_counts": dict(ledger.get("readiness_blocker_counts", {}))
        if isinstance(ledger.get("readiness_blocker_counts"), dict)
        else {},
        "memory_effects": [dict(run["memory_effect"]) for run in run_maps if isinstance(run.get("memory_effect"), dict)],
        "next_candidates": [
            {
                "path": str(run.get("next_candidate_path")),
                "exists": bool(run.get("next_candidate_exists")),
            }
            for run in run_maps
            if isinstance(run.get("next_candidate_path"), str) and run.get("next_candidate_path")
        ],
        "paper_feedback": dict(ledger.get("paper_feedback", {})) if isinstance(ledger.get("paper_feedback"), dict) else {},
    }


def _load_cycle_ledger(payload: dict[str, object]) -> dict[str, object]:
    ledger_path_raw = payload.get("evidence_ledger_path")
    if not isinstance(ledger_path_raw, str) or not ledger_path_raw:
        return {}
    ledger_path = Path(ledger_path_raw)
    if not ledger_path.exists():
        return {}
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    return ledger if isinstance(ledger, dict) else {}


def _cycle_stage_error(payload: dict[str, object], stage_name: str) -> str | None:
    stages = payload.get("stages")
    if not isinstance(stages, dict):
        return None
    stage = stages.get(stage_name)
    if not isinstance(stage, dict):
        return None
    error = stage.get("error")
    return str(error) if isinstance(error, str) and error else None


def _count_cycle_values(values: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, str):
                continue
            counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items()))


def _unique_strings(values: object) -> list[str]:
    seen: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.append(value)
    return seen


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _strategy_improvement_supported(improvement_gate: object) -> bool:
    if not isinstance(improvement_gate, dict):
        return False
    return bool(improvement_gate.get("strategy_improvement_supported"))


def _strategy_improvement_evidence_status(improvement_gate: object) -> str:
    if not isinstance(improvement_gate, dict):
        return "not_evaluated_missing_paper_artifacts"
    return str(improvement_gate.get("status") or "not_supported")
