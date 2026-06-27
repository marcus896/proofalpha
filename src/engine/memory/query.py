from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from engine.io.sqlite import connect_sqlite
from engine.validation.bundle import normalize_validation_bundle


def query_data_snapshots(
    db_path: Path,
    *,
    snapshot_id: str | None = None,
    symbol: str | None = None,
    venue: str | None = None,
    build_version: str | None = None,
    source_hash: str | None = None,
    quality_status: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[object] = []
    if snapshot_id is not None:
        clauses.append("snapshot_id = ?")
        params.append(snapshot_id)
    if symbol is not None:
        clauses.append("symbol = ?")
        params.append(symbol)
    if venue is not None:
        clauses.append("venue = ?")
        params.append(venue)
    if build_version is not None:
        clauses.append("build_version = ?")
        params.append(build_version)
    if source_hash is not None:
        clauses.append("source_hash = ?")
        params.append(source_hash)
    if quality_status is not None:
        clauses.append("quality_status = ?")
        params.append(quality_status)

    query = """
        SELECT
            snapshot_id,
            symbol,
            venue,
            build_version,
            source_hash,
            raw_source_id,
            raw_source_hash,
            parser_version,
            normalization_version,
            exchange_rules_version,
            feature_version,
            scenario_pack_version,
            cost_model_version,
            dataset_version,
            quality_status,
            quality_flag_count,
            feature_quality_status,
            feature_quality_issue_count,
            feature_quality_report_json,
            snapshot_quality_flags_json,
            snapshot_quality_report_json,
            snapshot_provenance_json,
            provider,
            build_mode,
            first_seen_run_id,
            last_seen_run_id,
            usage_count
        FROM data_snapshots
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY snapshot_id ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(max(0, limit))

    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()

    return [
        {
            "snapshot_id": str(row[0]),
            "symbol": str(row[1]) if row[1] is not None else None,
            "venue": str(row[2]) if row[2] is not None else None,
            "build_version": str(row[3]) if row[3] is not None else None,
            "source_hash": str(row[4]) if row[4] is not None else None,
            "raw_source_id": str(row[5]) if row[5] is not None else None,
            "raw_source_hash": str(row[6]) if row[6] is not None else None,
            "parser_version": str(row[7]) if row[7] is not None else None,
            "normalization_version": str(row[8]) if row[8] is not None else None,
            "exchange_rules_version": str(row[9]) if row[9] is not None else None,
            "feature_version": str(row[10]) if row[10] is not None else None,
            "scenario_pack_version": str(row[11]) if row[11] is not None else None,
            "cost_model_version": str(row[12]) if row[12] is not None else None,
            "dataset_version": str(row[13]) if row[13] is not None else None,
            "quality_status": str(row[14]) if row[14] is not None else None,
            "quality_flag_count": int(row[15]),
            "feature_quality_status": str(row[16]) if row[16] is not None else None,
            "feature_quality_issue_count": int(row[17]),
            "feature_quality_report": _load_json_dict(row[18]),
            "snapshot_quality_flags": _load_json_list(row[19]),
            "snapshot_quality_report": _load_json_dict(row[20]),
            "snapshot_provenance": _load_json_dict(row[21]),
            "provider": str(row[22]) if row[22] is not None else None,
            "build_mode": str(row[23]) if row[23] is not None else None,
            "first_seen_run_id": str(row[24]) if row[24] is not None else None,
            "last_seen_run_id": str(row[25]) if row[25] is not None else None,
            "usage_count": int(row[26]),
        }
        for row in rows
    ]


def query_meta_policies(
    db_path: Path,
    *,
    run_id: str | None = None,
    policy_family: str | None = None,
    status: str | None = None,
    eval_validation_run_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[object] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if policy_family is not None:
        clauses.append("policy_family = ?")
        params.append(policy_family)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if eval_validation_run_id is not None:
        clauses.append("eval_validation_run_id = ?")
        params.append(eval_validation_run_id)

    query = """
        SELECT
            run_id,
            policy_id,
            policy_family,
            status,
            action_map_json,
            training_stats_json,
            eval_validation_run_id,
            eval_stress_summary_json,
            artifact_path,
            payload_json
        FROM meta_policies
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY policy_id ASC, run_id ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(max(0, limit))

    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()

    return [
        {
            "run_id": str(row[0]),
            "policy_id": str(row[1]),
            "policy_family": str(row[2]),
            "status": str(row[3]) if row[3] is not None else None,
            "action_map": _load_json_dict(row[4]),
            "training_stats": _load_json_dict(row[5]),
            "eval_validation_run_id": str(row[6]) if row[6] is not None else None,
            "eval_stress_summary": _load_json_dict(row[7]),
            "artifact_path": str(row[8]) if row[8] is not None else None,
            "payload": _load_json_dict(row[9]),
        }
        for row in rows
    ]


def query_resource_index(
    db_path: Path,
    *,
    resource_group: str | None = None,
    status: str | None = None,
    license: str | None = None,
    intended_usage: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[object] = []
    if resource_group is not None:
        clauses.append("resource_group = ?")
        params.append(resource_group)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if license is not None:
        clauses.append("license = ?")
        params.append(license)
    if intended_usage is not None:
        clauses.append("intended_usage = ?")
        params.append(intended_usage)

    query = """
        SELECT
            resource_index.resource_id,
            resource_index.resource_group,
            resource_index.title,
            resource_index.url,
            resource_index.license,
            resource_index.status,
            resource_index.intended_usage,
            resource_index.local_destination,
            resource_index.pinned_ref,
            resource_index.payload_json,
            COUNT(run_resource_links.run_id) AS link_count,
            COUNT(DISTINCT run_resource_links.run_id) AS linked_run_count,
            GROUP_CONCAT(DISTINCT run_resource_links.run_id) AS linked_run_ids_csv
        FROM resource_index
        LEFT JOIN run_resource_links ON run_resource_links.resource_id = resource_index.resource_id
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " GROUP BY resource_index.resource_id ORDER BY resource_index.resource_id ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(max(0, limit))

    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()

    return [
        {
            "resource_id": str(row[0]),
            "resource_group": str(row[1]),
            "title": str(row[2]),
            "url": str(row[3]) if row[3] is not None else None,
            "license": str(row[4]) if row[4] is not None else None,
            "status": str(row[5]) if row[5] is not None else None,
            "intended_usage": str(row[6]) if row[6] is not None else None,
            "local_destination": str(row[7]) if row[7] is not None else None,
            "pinned_ref": str(row[8]) if row[8] is not None else None,
            "payload": _load_json_dict(row[9]),
            "link_count": int(row[10]) if row[10] is not None else 0,
            "linked_run_count": int(row[11]) if row[11] is not None else 0,
            "linked_run_ids": _split_csv_values(row[12]),
        }
        for row in rows
    ]


def query_run_resource_links(
    db_path: Path,
    *,
    run_id: str | None = None,
    resource_id: str | None = None,
    link_role: str | None = None,
    evidence_source: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[object] = []
    if run_id is not None:
        clauses.append("run_resource_links.run_id = ?")
        params.append(run_id)
    if resource_id is not None:
        clauses.append("run_resource_links.resource_id = ?")
        params.append(resource_id)
    if link_role is not None:
        clauses.append("run_resource_links.link_role = ?")
        params.append(link_role)
    if evidence_source is not None:
        clauses.append("run_resource_links.evidence_source = ?")
        params.append(evidence_source)

    query = """
        SELECT
            run_resource_links.run_id,
            run_resource_links.resource_id,
            run_resource_links.link_role,
            run_resource_links.evidence_source,
            run_resource_links.rationale,
            run_resource_links.payload_json,
            resource_index.resource_group,
            resource_index.title,
            resource_index.status
        FROM run_resource_links
        LEFT JOIN resource_index ON resource_index.resource_id = run_resource_links.resource_id
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY run_resource_links.run_id ASC, run_resource_links.resource_id ASC, run_resource_links.link_role ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(max(0, limit))

    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()

    return [
        {
            "run_id": str(row[0]),
            "resource_id": str(row[1]),
            "link_role": str(row[2]),
            "evidence_source": str(row[3]),
            "rationale": str(row[4]) if row[4] is not None else None,
            "payload": _load_json_dict(row[5]),
            "resource_group": str(row[6]) if row[6] is not None else None,
            "title": str(row[7]) if row[7] is not None else None,
            "status": str(row[8]) if row[8] is not None else None,
        }
        for row in rows
    ]


def query_candidate_trials(
    db_path: Path,
    *,
    run_id: str | None = None,
    layer_name: str | None = None,
    decision: str | None = None,
    pressured_only: bool = False,
    sort_by: str = "rank",
    limit: int | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[object] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if layer_name is not None:
        clauses.append("layer_name = ?")
        params.append(layer_name)
    if decision is not None:
        clauses.append("decision = ?")
        params.append(decision)

    query = """
        SELECT
            run_id,
            phase_name,
            layer_name,
            ordinal,
            decision,
            oos_sharpe,
            parameters_json,
            permutation_count,
            fill_event_count,
            partial_fill_event_count,
            average_fill_ratio,
            min_fill_ratio,
            search_source,
            seed_evidence_json,
            regime_similarity_json,
            payload_json
        FROM candidate_trials
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY run_id ASC, oos_sharpe DESC, phase_name ASC, layer_name ASC, ordinal ASC"

    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()

    payload = [
        {
            "run_id": str(row[0]),
            "phase_name": str(row[1]),
            "layer_name": str(row[2]),
            "ordinal": int(row[3]),
            "decision": str(row[4]),
            "oos_sharpe": _to_float_or_none(row[5]),
            "parameters": _load_json_dict(row[6]),
            "permutation_count": int(row[7]),
            "execution_pressure_summary": _candidate_execution_pressure_summary(
                fill_event_count=row[8],
                partial_fill_event_count=row[9],
                average_fill_ratio=row[10],
                min_fill_ratio=row[11],
                payload_json=row[15],
            ),
            "search_source": str(row[12]) if row[12] is not None else None,
            "seed_evidence": _load_json_dict(row[13]),
            "regime_similarity": _load_json_dict(row[14]),
            "payload": _load_json_dict(row[15]),
        }
        for row in rows
    ]
    if pressured_only:
        payload = [
            row
            for row in payload
            if _candidate_trial_is_pressured(row.get("execution_pressure_summary"))
        ]
    payload = _sort_candidate_trial_rows(payload, sort_by=sort_by)
    if limit is not None:
        return payload[: max(0, limit)]
    return payload


def query_stress_runs(
    db_path: Path,
    *,
    run_id: str | None = None,
    scenario_name: str | None = None,
    passed: bool | None = None,
    target_regime: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[object] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if scenario_name is not None:
        clauses.append("scenario_name = ?")
        params.append(scenario_name)
    if passed is not None:
        clauses.append("passed = ?")
        params.append(1 if passed else 0)

    query = """
        SELECT
            run_id,
            scenario_name,
            severity,
            passed,
            failure_reasons_json,
            sharpe,
            max_drawdown,
            resolved_profile_json,
            stress_metrics_json,
            target_regimes_json
        FROM stress_runs
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY run_id ASC, passed ASC, scenario_name ASC"

    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        raw_rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()

    rows = [
        {
            "run_id": str(row[0]),
            "scenario_name": str(row[1]),
            "severity": _to_float_or_none(row[2]),
            "passed": bool(int(row[3])),
            "failure_reasons": _load_json_list(row[4]),
            "sharpe": _to_float_or_none(row[5]),
            "max_drawdown": _to_float_or_none(row[6]),
            "resolved_profile": _load_json_dict(row[7]),
            "stress_metrics": _load_json_dict(row[8]),
            "target_regimes": _load_json_list(row[9]),
        }
        for row in raw_rows
    ]
    if target_regime is not None:
        rows = [
            row
            for row in rows
            if target_regime in row.get("target_regimes", [])
        ]
    if limit is not None:
        rows = rows[: max(0, limit)]
    return rows


def query_validation_runs(
    db_path: Path,
    *,
    run_id: str | None = None,
    validation_status: str | None = None,
    min_deflated_sharpe_ratio: float | None = None,
    max_pbo_score: float | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[object] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if validation_status is not None:
        clauses.append("validation_status = ?")
        params.append(validation_status)
    if min_deflated_sharpe_ratio is not None:
        clauses.append("deflated_sharpe_ratio >= ?")
        params.append(float(min_deflated_sharpe_ratio))
    if max_pbo_score is not None:
        clauses.append("pbo_score <= ?")
        params.append(float(max_pbo_score))

    query = """
        SELECT
            run_id,
            validation_status,
            probabilistic_sharpe_ratio,
            deflated_sharpe_ratio,
            pbo_score,
            spa_pvalue,
            min_backtest_length,
            min_trade_count,
            trial_count,
            failed_gates_json,
            gate_results_json,
            validation_bundle_json,
            validation_protocol_json
        FROM validation_runs
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY pbo_score ASC, run_id ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(max(0, limit))

    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()

    return [
        {
            "run_id": str(row[0]),
            "validation_status": str(row[1]) if row[1] is not None else None,
            "probabilistic_sharpe_ratio": _to_float_or_none(row[2]),
            "deflated_sharpe_ratio": _to_float_or_none(row[3]),
            "pbo_score": _to_float_or_none(row[4]),
            "spa_pvalue": _to_float_or_none(row[5]),
            "min_backtest_length": int(row[6]) if row[6] is not None else None,
            "min_trade_count": int(row[7]) if row[7] is not None else None,
            "trial_count": int(row[8]) if row[8] is not None else None,
            "failed_gates": _load_json_list(row[9]),
            "gate_results": _load_json_dict(row[10]),
            "validation_bundle": _load_json_dict(row[11]),
            "validation_protocol": _load_json_dict(row[12]),
        }
        for row in rows
    ]


def query_agent_decisions(
    db_path: Path,
    *,
    run_id: str | None = None,
    decision_family: str | None = None,
    decision: str | None = None,
    validation_status: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[object] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if decision_family is not None:
        clauses.append("decision_family = ?")
        params.append(decision_family)
    if decision is not None:
        clauses.append("decision = ?")
        params.append(decision)
    if validation_status is not None:
        clauses.append("validation_status = ?")
        params.append(validation_status)

    query = """
        SELECT
            run_id,
            decision_family,
            iteration,
            ordinal,
            decision,
            reason,
            validation_status,
            metric_name,
            metric_value,
            candidate_run_ids_json,
            kept_run_ids_json,
            payload_json
        FROM agent_decisions
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY iteration ASC, ordinal ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(max(0, limit))

    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()

    return [
        {
            "run_id": str(row[0]),
            "decision_family": str(row[1]),
            "iteration": int(row[2]),
            "ordinal": int(row[3]),
            "decision": str(row[4]),
            "reason": str(row[5]) if row[5] is not None else None,
            "validation_status": str(row[6]) if row[6] is not None else None,
            "metric_name": str(row[7]) if row[7] is not None else None,
            "metric_value": _to_float_or_none(row[8]),
            "candidate_run_ids": _load_json_list(row[9]),
            "kept_run_ids": _load_json_list(row[10]),
            "payload": _load_json_dict(row[11]),
        }
        for row in rows
    ]


def query_run_memory(
    db_path: Path,
    run_id: str | None = None,
    symbol: str | None = None,
    venue: str | None = None,
    layer: str | None = None,
    decision: str | None = None,
    quality_status: str | None = None,
    build_version: str | None = None,
    source_hash: str | None = None,
    selected_variant: str | None = None,
    parent_batch_run_id: str | None = None,
    accepted_duplicate_match_run_id: str | None = None,
    candidate_pressure_only: bool = False,
    sort_by: str = "sharpe",
    limit: int | None = None,
) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[object] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if symbol is not None:
        clauses.append("symbol = ?")
        params.append(symbol)
    if venue is not None:
        clauses.append("venue = ?")
        params.append(venue)
    if decision is not None:
        clauses.append("decision = ?")
        params.append(decision)
    if quality_status is not None:
        clauses.append("snapshot_quality_status = ?")
        params.append(quality_status)
    if build_version is not None:
        clauses.append("snapshot_build_version = ?")
        params.append(build_version)
    if source_hash is not None:
        clauses.append("snapshot_source_hash = ?")
        params.append(source_hash)
    if selected_variant is not None:
        clauses.append("selected_variant = ?")
        params.append(selected_variant)
    if parent_batch_run_id is not None:
        clauses.append("parent_batch_run_id = ?")
        params.append(parent_batch_run_id)
    if accepted_duplicate_match_run_id is not None:
        clauses.append("accepted_duplicate_match_run_id = ?")
        params.append(accepted_duplicate_match_run_id)
    if layer is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM research_phases phase_filter WHERE phase_filter.run_id = research_runs.run_id AND phase_filter.layer_name = ?)"
        )
        params.append(layer)

    query = """
        SELECT
            run_id,
            decision,
            symbol,
            venue,
            selection_oos_sharpe,
            selection_oos_net_pnl,
            selection_oos_drawdown,
            scenario_pass_rate,
            accepted_layers,
            probabilistic_sharpe_ratio,
            deflated_sharpe_ratio,
            in_sample_permutation_pvalue,
            walk_forward_permutation_pvalue,
            validation_trial_count,
            validation_status,
            validation_protocol_json,
            validation_gate_results_json,
            snapshot_quality_status,
            snapshot_quality_flag_count,
            snapshot_quality_flags_json,
            snapshot_quality_report_json,
            snapshot_provenance_json,
            snapshot_build_version,
            snapshot_source_hash,
            study_signature,
            selected_variant,
            parent_batch_run_id,
            parent_batch_report_path,
            source_config_path,
            accepted_duplicate_match_run_id,
            accepted_duplicate_match_type,
            accepted_duplicate_source_config_path,
            accepted_duplicate_source_report_path,
            scenario_profiles_json,
            regime_summary_json,
            bootstrap_summary_json,
            runtime_settings_json,
            selected_parameters_json,
            parameter_search_json,
            agent_loop_metadata_json,
            research_program_version
        FROM research_runs
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY selection_oos_sharpe DESC, run_id ASC"

    connection = connect_sqlite(db_path, read_only=True)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        rows = connection.execute(query, params).fetchall()
        run_ids = [str(row[0]) for row in rows]
        phase_rows_by_run: dict[str, list[tuple[object, object]]] = {run_id: [] for run_id in run_ids}
        agent_decision_summary_by_run = _load_agent_decision_summaries(connection, run_ids=run_ids)
        validation_summary_by_run = _load_validation_run_summaries(connection, run_ids=run_ids)
        stress_summary_by_run = _load_stress_run_summaries(connection, run_ids=run_ids)
        candidate_summary_by_run = _load_candidate_trial_summaries(connection, run_ids=run_ids)
        data_snapshot_summary_by_run = _load_data_snapshot_summaries(connection, run_ids=run_ids)
        meta_policy_summary_by_run = _load_meta_policy_summaries(connection, run_ids=run_ids)
        resource_link_summary_by_run = _load_run_resource_link_summaries(connection, run_ids=run_ids)
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            phase_rows = connection.execute(
                f"""
                SELECT run_id, layer_name, accepted
                FROM research_phases
                WHERE run_id IN ({placeholders})
                ORDER BY run_id ASC, layer_name ASC
                """,
                run_ids,
            ).fetchall()
            for phase_row in phase_rows:
                phase_rows_by_run[str(phase_row[0])].append((phase_row[1], phase_row[2]))
        payload = []
        for row in rows:
            run_id = str(row[0])
            phase_rows = phase_rows_by_run.get(run_id, [])
            phase_layers = [str(phase_row[0]) for phase_row in phase_rows]
            accepted_layers = [str(phase_row[0]) for phase_row in phase_rows if int(phase_row[1]) == 1]
            rejected_layers = [str(phase_row[0]) for phase_row in phase_rows if int(phase_row[1]) == 0]
            validation_protocol = _load_json_dict(row[15])
            validation_bundle = normalize_validation_bundle(
                validation_protocol,
                dsr_override=_to_float_or_none(row[10]),
                psr_override=_to_float_or_none(row[9]),
            )
            payload.append(
                {
                    "run_id": run_id,
                    "decision": str(row[1]),
                    "symbol": str(row[2]) if row[2] is not None else None,
                    "venue": str(row[3]) if row[3] is not None else None,
                    "selection_oos_sharpe": float(row[4]),
                    "selection_oos_net_pnl": float(row[5]),
                    "selection_oos_drawdown": float(row[6]),
                    "scenario_pass_rate": float(row[7]),
                    "accepted_layer_count": float(row[8]),
                    "probabilistic_sharpe_ratio": _to_float_or_none(row[9]),
                    "deflated_sharpe_ratio": _to_float_or_none(row[10]),
                    "in_sample_permutation_pvalue": _to_float_or_none(row[11]),
                    "walk_forward_permutation_pvalue": _to_float_or_none(row[12]),
                    "validation_trial_count": int(row[13]) if row[13] is not None else 0,
                    "validation_status": str(row[14]) if row[14] is not None else None,
                    "validation_protocol": validation_protocol,
                    "validation_bundle": validation_bundle,
                    "validation_gate_results": _load_json_dict(row[16]),
                    "snapshot_quality_status": str(row[17]) if row[17] is not None else None,
                    "snapshot_quality_flag_count": int(row[18]) if row[18] is not None else 0,
                    "snapshot_quality_flags": _load_json_list(row[19]),
                    "snapshot_quality_report": _load_json_dict(row[20]),
                    "snapshot_provenance": _load_json_dict(row[21]),
                    "snapshot_build_version": str(row[22]) if row[22] else None,
                    "snapshot_source_hash": str(row[23]) if row[23] else None,
                    "study_signature": str(row[24]) if row[24] is not None else None,
                    "selected_variant": str(row[25]) if row[25] is not None else None,
                    "parent_batch_run_id": str(row[26]) if row[26] is not None else None,
                    "parent_batch_report_path": str(row[27]) if row[27] is not None else None,
                    "source_config_path": str(row[28]) if row[28] is not None else None,
                    "accepted_duplicate_match_run_id": str(row[29]) if row[29] is not None else None,
                    "accepted_duplicate_match_type": str(row[30]) if row[30] is not None else None,
                    "accepted_duplicate_source_config_path": str(row[31]) if row[31] is not None else None,
                    "accepted_duplicate_source_report_path": str(row[32]) if row[32] is not None else None,
                    "scenario_profiles": _load_json_dict(row[33]),
                    "regime_summary": _load_json_dict(row[34]),
                    "bootstrap_summary": _load_json_dict(row[35]),
                    "runtime_settings": _load_json_dict(row[36]),
                    "accepted_layers": accepted_layers,
                    "rejected_layers": rejected_layers,
                    "phase_layers": phase_layers,
                    "selected_parameters": _load_json_dict(row[37]),
                    "parameter_search": _load_json_dict(row[38]),
                    "agent_loop_metadata": _load_json_dict(row[39]),
                    "agent_decision_summary": dict(agent_decision_summary_by_run.get(run_id, {})),
                    "validation_run_summary": dict(validation_summary_by_run.get(run_id, {})),
                    "stress_run_summary": dict(stress_summary_by_run.get(run_id, {})),
                    "candidate_trial_summary": dict(candidate_summary_by_run.get(run_id, {})),
                    "data_snapshot_summary": dict(data_snapshot_summary_by_run.get(run_id, {})),
                    "meta_policy_summary": dict(meta_policy_summary_by_run.get(run_id, {})),
                    "resource_link_summary": dict(resource_link_summary_by_run.get(run_id, {})),
                    "research_program_version": str(row[40]) if row[40] else None,
                }
            )
        if candidate_pressure_only:
            payload = [
                row
                for row in payload
                if _run_has_candidate_pressure(row.get("candidate_trial_summary"))
            ]
        payload = _sort_run_memory_rows(payload, sort_by=sort_by)
        if limit is not None:
            return payload[: max(0, limit)]
        return payload
    finally:
        connection.close()


def render_memory_query(rows: list[dict[str, object]], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(rows, sort_keys=True)

    lines = ["Research memory"]
    if not rows:
        lines.append("none")
        return "\n".join(lines)

    for index, row in enumerate(rows, start=1):
        accepted_layers = row.get("accepted_layers", [])
        accepted_label = ",".join(accepted_layers) if isinstance(accepted_layers, list) and accepted_layers else "none"
        rejected_layers = row.get("rejected_layers", [])
        rejected_label = ",".join(rejected_layers) if isinstance(rejected_layers, list) and rejected_layers else "none"
        variant_label = row.get("selected_variant") or "none"
        duplicate_label = row.get("accepted_duplicate_match_run_id") or "none"
        quality_label = row.get("snapshot_quality_status") or "unknown"
        build_label = row.get("snapshot_build_version") or "none"
        validation_label = row.get("validation_status") or "unknown"
        validation_protocol = row.get("validation_protocol", {})
        if isinstance(validation_protocol, dict):
            validation_bundle = normalize_validation_bundle(
                validation_protocol,
                dsr_override=row.get("deflated_sharpe_ratio"),
                psr_override=row.get("probabilistic_sharpe_ratio"),
            )
            dsr_label = _format_metric_value(validation_bundle.get("deflated_sharpe_ratio"))
            psr_label = _format_metric_value(validation_bundle.get("probabilistic_sharpe_ratio"))
            pbo_label = _format_metric_value(validation_bundle.get("pbo_score"))
            spa_label = _format_metric_value(validation_bundle.get("spa_pvalue"))
            failed_gates_label = _format_string_list(validation_bundle.get("failed_gates"))
        else:
            dsr_label = _format_metric_value(row.get("deflated_sharpe_ratio"))
            psr_label = _format_metric_value(row.get("probabilistic_sharpe_ratio"))
            pbo_label = "n/a"
            spa_label = "n/a"
            failed_gates_label = "none"
        scenario_profiles = row.get("scenario_profiles", {})
        if isinstance(scenario_profiles, dict) and scenario_profiles:
            scenario_label = ",".join(sorted(scenario_profiles))
        else:
            scenario_label = "none"
        runtime_settings = row.get("runtime_settings", {})
        if isinstance(runtime_settings, dict) and runtime_settings:
            runtime_label = _format_key_value_pairs(runtime_settings)
        else:
            runtime_label = "none"
        agent_loop_metadata = row.get("agent_loop_metadata", {})
        if isinstance(agent_loop_metadata, dict):
            loop_label = _format_failure_taxonomy_counts(agent_loop_metadata.get("failure_taxonomy_counts"))
            next_label = _format_first_next_hypothesis(agent_loop_metadata.get("next_hypotheses"))
        else:
            loop_label = "none"
            next_label = "none"
        agent_decision_summary = row.get("agent_decision_summary", {})
        if isinstance(agent_decision_summary, dict) and agent_decision_summary:
            decision_summary_label = (
                f"decision_count={agent_decision_summary.get('decision_count', 0)},"
                f"decision_family={agent_decision_summary.get('decision_family', 'none')},"
                f"latest_iteration={agent_decision_summary.get('latest_iteration', 'none')},"
                f"latest_decision={agent_decision_summary.get('latest_decision', 'none')}"
            )
        else:
            decision_summary_label = "none"
        validation_run_summary = row.get("validation_run_summary", {})
        if isinstance(validation_run_summary, dict) and validation_run_summary:
            validation_summary_label = (
                f"status={validation_run_summary.get('status', 'unknown')},"
                f"pbo={_format_metric_value(validation_run_summary.get('pbo_score'))},"
                f"spa={_format_metric_value(validation_run_summary.get('spa_pvalue'))},"
                f"failed_gates={validation_run_summary.get('failed_gate_count', 0)},"
                f"trials={validation_run_summary.get('trial_count', 'none')}"
            )
        else:
            validation_summary_label = "none"
        stress_run_summary = row.get("stress_run_summary", {})
        if isinstance(stress_run_summary, dict) and stress_run_summary:
            stress_summary_label = (
                f"scenarios={stress_run_summary.get('scenario_count', 0)},"
                f"failed={stress_run_summary.get('failed_scenario_count', 0)},"
                f"worst={stress_run_summary.get('worst_scenario', 'none')},"
                f"regimes={stress_run_summary.get('target_regime_count', 0)}"
            )
        else:
            stress_summary_label = "none"
        candidate_trial_summary = row.get("candidate_trial_summary", {})
        if isinstance(candidate_trial_summary, dict) and candidate_trial_summary:
            candidate_trial_label = (
                f"count={candidate_trial_summary.get('trial_count', 0)},"
                f"top={candidate_trial_summary.get('top_decision', 'none')},"
                f"top_sharpe={_format_metric_value(candidate_trial_summary.get('top_oos_sharpe'))},"
                f"layers={candidate_trial_summary.get('layer_count', 0)},"
                f"pressured={candidate_trial_summary.get('pressured_trial_count', 0)},"
                f"worst_fill={_format_metric_value(candidate_trial_summary.get('worst_min_fill_ratio'))}"
            )
        else:
            candidate_trial_label = "none"
        data_snapshot_summary = row.get("data_snapshot_summary", {})
        if isinstance(data_snapshot_summary, dict) and data_snapshot_summary:
            data_snapshot_label = (
                f"provider={data_snapshot_summary.get('provider', 'none')},"
                f"mode={data_snapshot_summary.get('build_mode', 'none')},"
                f"usage={data_snapshot_summary.get('usage_count', 0)},"
                f"first={data_snapshot_summary.get('first_seen_run_id', 'none')}"
            )
        else:
            data_snapshot_label = "none"
        meta_policy_summary = row.get("meta_policy_summary", {})
        if isinstance(meta_policy_summary, dict) and meta_policy_summary:
            meta_policy_label = (
                f"count={meta_policy_summary.get('policy_count', 0)},"
                f"family={meta_policy_summary.get('policy_family', 'none')},"
                f"status={meta_policy_summary.get('status', 'none')},"
                f"latest={meta_policy_summary.get('latest_policy_id', 'none')},"
                f"selected={meta_policy_summary.get('selected_action', 'none')},"
                f"train_examples={meta_policy_summary.get('training_example_count', 0)},"
                f"offline_eval={meta_policy_summary.get('offline_eval_method', 'none')}"
            )
        else:
            meta_policy_label = "none"
        resource_link_summary = row.get("resource_link_summary", {})
        if isinstance(resource_link_summary, dict) and resource_link_summary:
            resource_link_label = (
                f"count={resource_link_summary.get('link_count', 0)},"
                f"resources={resource_link_summary.get('linked_resource_count', 0)},"
                f"blocked={resource_link_summary.get('blocked_link_count', 0)},"
                f"groups={_format_string_list(resource_link_summary.get('resource_groups'))}"
            )
        else:
            resource_link_label = "none"
        lines.append(
            f"{index}. {row.get('run_id')} | symbol={row.get('symbol')} | decision={row.get('decision')} | validation={validation_label} | dsr={dsr_label} | psr={psr_label} | pbo={pbo_label} | spa={spa_label} | failed_gates={failed_gates_label} | validation_lineage={validation_summary_label} | stress_lineage={stress_summary_label} | candidate_trials={candidate_trial_label} | meta_policies={meta_policy_label} | snapshot_lineage={data_snapshot_label} | resource_links={resource_link_label} | sharpe={row.get('selection_oos_sharpe')} | quality={quality_label} | build={build_label} | variant={variant_label} | dup={duplicate_label} | scenarios={scenario_label} | runtime={runtime_label} | loop={loop_label} | next={next_label} | agent_decisions={decision_summary_label} | accepted={accepted_label} | rejected={rejected_label}"
        )
    return "\n".join(lines)


def render_candidate_trial_query(rows: list[dict[str, object]], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(rows, sort_keys=True)

    lines = ["Candidate trials"]
    if not rows:
        lines.append("none")
        return "\n".join(lines)

    for index, row in enumerate(rows, start=1):
        parameters = row.get("parameters", {})
        parameter_label = _format_key_value_pairs(parameters) if isinstance(parameters, dict) else "none"
        pressure = row.get("execution_pressure_summary", {})
        if isinstance(pressure, dict) and pressure:
            pressure_label = (
                f"fill_events={pressure.get('fill_event_count', 'n/a')},"
                f"partial={pressure.get('partial_fill_event_count', 'n/a')},"
                f"avg_fill={_format_metric_value(pressure.get('average_fill_ratio'))},"
                f"min_fill={_format_metric_value(pressure.get('min_fill_ratio'))}"
            )
        else:
            pressure_label = "none"
        seed = row.get("seed_evidence", {})
        if isinstance(seed, dict) and seed:
            seed_label = f"{seed.get('source', 'unknown')}:{seed.get('seed_count', 0)}"
        else:
            seed_label = "none"
        lines.append(
            f"{index}. run={row.get('run_id')} | phase={row.get('phase_name')} | layer={row.get('layer_name')} | ordinal={row.get('ordinal')} | source={row.get('search_source') or 'unknown'} | seed={seed_label} | decision={row.get('decision')} | sharpe={_format_metric_value(row.get('oos_sharpe'))} | permutations={row.get('permutation_count')} | params={parameter_label} | pressure={pressure_label}"
        )
    return "\n".join(lines)


def render_validation_run_query(rows: list[dict[str, object]], fmt: str) -> str:
    return _render_generic_query(
        rows,
        fmt,
        "Validation runs",
        lambda row: (
            f"run={row.get('run_id')} | status={row.get('validation_status')} | "
            f"dsr={_format_metric_value(row.get('deflated_sharpe_ratio'))} | "
            f"psr={_format_metric_value(row.get('probabilistic_sharpe_ratio'))} | "
            f"pbo={_format_metric_value(row.get('pbo_score'))} | "
            f"spa={_format_metric_value(row.get('spa_pvalue'))} | "
            f"failed={_format_string_list(row.get('failed_gates'))} | "
            f"trials={row.get('trial_count')}"
        ),
    )


def render_stress_run_query(rows: list[dict[str, object]], fmt: str) -> str:
    return _render_generic_query(
        rows,
        fmt,
        "Stress runs",
        lambda row: (
            f"run={row.get('run_id')} | scenario={row.get('scenario_name')} | "
            f"passed={row.get('passed')} | severity={_format_metric_value(row.get('severity'))} | "
            f"sharpe={_format_metric_value(row.get('sharpe'))} | "
            f"max_drawdown={_format_metric_value(row.get('max_drawdown'))} | "
            f"regimes={_format_string_list(row.get('target_regimes'))}"
        ),
    )


def render_agent_decision_query(rows: list[dict[str, object]], fmt: str) -> str:
    return _render_generic_query(
        rows,
        fmt,
        "Agent decisions",
        lambda row: (
            f"run={row.get('run_id')} | family={row.get('decision_family')} | "
            f"iteration={row.get('iteration')} | ordinal={row.get('ordinal')} | "
            f"decision={row.get('decision')} | validation={row.get('validation_status')} | "
            f"metric={row.get('metric_name')}:{_format_metric_value(row.get('metric_value'))} | "
            f"reason={row.get('reason') or 'none'}"
        ),
    )


def render_data_snapshot_query(rows: list[dict[str, object]], fmt: str) -> str:
    return _render_generic_query(
        rows,
        fmt,
        "Data snapshots",
        lambda row: (
            f"snapshot={row.get('snapshot_id')} | symbol={row.get('symbol')} | "
            f"venue={row.get('venue')} | build={row.get('build_version')} | "
            f"source_hash={row.get('source_hash')} | quality={row.get('quality_status')} | "
            f"feature_quality={row.get('feature_quality_status') or 'none'}:"
            f"{row.get('feature_quality_issue_count', 0)} | "
            f"dataset={row.get('dataset_version') or 'none'} | raw_hash={row.get('raw_source_hash') or 'none'} | "
            f"provider={row.get('provider') or 'none'} | mode={row.get('build_mode') or 'none'} | "
            f"usage={row.get('usage_count')}"
        ),
    )


def render_resource_index_query(rows: list[dict[str, object]], fmt: str) -> str:
    return _render_generic_query(
        rows,
        fmt,
        "Resource index",
        lambda row: (
            f"resource={row.get('resource_id')} | group={row.get('resource_group')} | "
            f"status={row.get('status') or 'unknown'} | license={row.get('license') or 'none'} | "
            f"usage={row.get('intended_usage') or 'none'} | linked_runs={row.get('linked_run_count', 0)}"
        ),
    )


def render_run_resource_link_query(rows: list[dict[str, object]], fmt: str) -> str:
    return _render_generic_query(
        rows,
        fmt,
        "Run resource links",
        lambda row: (
            f"run={row.get('run_id')} | resource={row.get('resource_id')} | "
            f"role={row.get('link_role')} | evidence={row.get('evidence_source')} | "
            f"group={row.get('resource_group') or 'none'} | status={row.get('status') or 'unknown'}"
        ),
    )


def render_meta_policy_query(rows: list[dict[str, object]], fmt: str) -> str:
    return _render_generic_query(
        rows,
        fmt,
        "Meta policies",
        _format_meta_policy_row,
    )


def _format_meta_policy_row(row: dict[str, object]) -> str:
    training_stats = row.get("training_stats")
    if not isinstance(training_stats, dict):
        training_stats = {}
    payload = row.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    offline_eval = payload.get("offline_evaluation")
    if not isinstance(offline_eval, dict):
        offline_eval = row.get("offline_evaluation")
    if not isinstance(offline_eval, dict):
        offline_eval = {}
    return (
        f"run={row.get('run_id')} | policy={row.get('policy_id')} | "
        f"family={row.get('policy_family')} | status={row.get('status') or 'unknown'} | "
        f"selected={training_stats.get('selected_action') or offline_eval.get('selected_action') or 'none'} | "
        f"train_examples={training_stats.get('training_example_count', 0)} | "
        f"offline_eval={offline_eval.get('method', 'none')} | "
        f"best_observed={offline_eval.get('best_observed_action') or 'none'} | "
        f"regret={offline_eval.get('regret_to_best_observed')} | "
        f"eval_validation={row.get('eval_validation_run_id') or 'none'} | "
        f"artifact={row.get('artifact_path') or 'none'}"
    )


def _render_generic_query(
    rows: list[dict[str, object]],
    fmt: str,
    title: str,
    formatter,
) -> str:
    if fmt == "json":
        return json.dumps(rows, sort_keys=True)

    lines = [title]
    if not rows:
        lines.append("none")
        return "\n".join(lines)
    for index, row in enumerate(rows, start=1):
        lines.append(f"{index}. {formatter(row)}")
    return "\n".join(lines)


def query_promoted_parameter_sets(
    db_path: Path,
    *,
    layer_name: str,
    symbol: str | None = None,
    limit: int = 5,
) -> list[dict[str, float | int]]:
    rows = query_run_memory(
        db_path,
        symbol=symbol,
        layer=layer_name,
        decision="promoted",
        limit=limit,
    )
    parameter_sets: list[dict[str, float | int]] = []
    for row in rows:
        selected_parameters = row.get("selected_parameters", {})
        if not isinstance(selected_parameters, dict):
            continue
        layer_parameters = selected_parameters.get(layer_name, {})
        if not isinstance(layer_parameters, dict) or not layer_parameters:
            continue
        typed_parameters = {
            str(name): value
            for name, value in layer_parameters.items()
            if isinstance(name, str) and isinstance(value, int | float) and not isinstance(value, bool)
        }
        if typed_parameters:
            parameter_sets.append(typed_parameters)
    return parameter_sets


def query_bayesian_seed_trials(
    db_path: Path,
    *,
    layer_name: str,
    symbol: str | None = None,
    venue: str | None = None,
    regime_label: str | None = None,
    scenario_names: list[str] | None = None,
    limit: int = 5,
    ) -> list[dict[str, object]]:
    rows = query_run_memory(
        db_path,
        symbol=None,
        layer=layer_name,
        decision="promoted",
        limit=None,
    )
    normalized_scenarios = {
        str(name).strip()
        for name in (scenario_names or [])
        if isinstance(name, str) and str(name).strip()
    }
    ranked: list[dict[str, object]] = []
    for row in rows:
        selected_parameters = row.get("selected_parameters", {})
        if not isinstance(selected_parameters, dict):
            continue
        layer_parameters = selected_parameters.get(layer_name, {})
        if not isinstance(layer_parameters, dict) or not layer_parameters:
            continue
        typed_parameters = {
            str(name): value
            for name, value in layer_parameters.items()
            if isinstance(name, str) and isinstance(value, int | float) and not isinstance(value, bool)
        }
        if not typed_parameters:
            continue

        scenario_profiles = row.get("scenario_profiles", {})
        regime_summary = row.get("regime_summary", {})
        regime_coverage = regime_summary.get("regime_coverage", {}) if isinstance(regime_summary, dict) else {}

        target_base = _extract_base_asset(symbol)
        row_symbol = row.get("symbol")
        row_base = _extract_base_asset(row_symbol) if isinstance(row_symbol, str) else None

        match_details = {
            "exact_symbol": 1.0 if symbol and row_symbol == symbol else 0.0,
            "similar_symbol": 1.0 if target_base and row_base and target_base == row_base and row_symbol != symbol else 0.0,
            "same_venue": 1.0 if venue and row.get("venue") == venue else 0.0,
            "matching_regime": 1.0 if regime_label and isinstance(regime_coverage, dict) and regime_label in regime_coverage else 0.0,
            "matching_scenario": (
                1.0
                if normalized_scenarios
                and isinstance(scenario_profiles, dict)
                and normalized_scenarios.intersection(str(key) for key in scenario_profiles.keys())
                else 0.0
            ),
        }
        rank_score = (
            6.0 * match_details["exact_symbol"]
            + 4.0 * match_details["similar_symbol"]
            + 2.0 * match_details["same_venue"]
            + 2.0 * match_details["matching_regime"]
            + 3.0 * match_details["matching_scenario"]
            + float(row.get("selection_oos_sharpe", 0.0))
        )
        ranked.append(
            {
                "run_id": row.get("run_id"),
                "parameters": typed_parameters,
                "selection_oos_sharpe": float(row.get("selection_oos_sharpe", 0.0)),
                "rank_score": float(rank_score),
                "match_details": match_details,
            }
        )

    deduped: dict[str, dict[str, object]] = {}
    for candidate in sorted(
        ranked,
        key=lambda item: (
            float(item["rank_score"]),
            float(item["selection_oos_sharpe"]),
            str(item["run_id"]),
        ),
        reverse=True,
    ):
        key = json.dumps(candidate["parameters"], sort_keys=True)
        deduped.setdefault(key, candidate)
    return list(deduped.values())[: max(0, limit)]


def _load_agent_decision_summaries(
    connection: sqlite3.Connection,
    *,
    run_ids: list[str],
) -> dict[str, dict[str, object]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = connection.execute(
        f"""
        SELECT run_id, decision_family, iteration, ordinal, decision
        FROM agent_decisions
        WHERE run_id IN ({placeholders})
        ORDER BY run_id ASC, iteration ASC, ordinal ASC
        """,
        run_ids,
    ).fetchall()
    grouped: dict[str, list[tuple[object, ...]]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        grouped[str(row[0])].append(row)

    summary_by_run: dict[str, dict[str, object]] = {}
    for run_id, entries in grouped.items():
        if not entries:
            summary_by_run[run_id] = {}
            continue
        latest = entries[-1]
        summary_by_run[run_id] = {
            "decision_count": len(entries),
            "decision_family": str(latest[1]),
            "latest_iteration": int(latest[2]),
            "latest_decision": str(latest[4]),
        }
    return summary_by_run


def _load_validation_run_summaries(
    connection: sqlite3.Connection,
    *,
    run_ids: list[str],
) -> dict[str, dict[str, object]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = connection.execute(
        f"""
        SELECT run_id, validation_status, pbo_score, spa_pvalue, trial_count, failed_gates_json
        FROM validation_runs
        WHERE run_id IN ({placeholders})
        ORDER BY run_id ASC
        """,
        run_ids,
    ).fetchall()
    summary_by_run = {run_id: {} for run_id in run_ids}
    for row in rows:
        failed_gates = _load_json_list(row[5])
        summary_by_run[str(row[0])] = {
            "status": str(row[1]) if row[1] is not None else None,
            "pbo_score": _to_float_or_none(row[2]),
            "spa_pvalue": _to_float_or_none(row[3]),
            "trial_count": int(row[4]) if row[4] is not None else None,
            "failed_gate_count": len(failed_gates),
        }
    return summary_by_run


def _load_stress_run_summaries(
    connection: sqlite3.Connection,
    *,
    run_ids: list[str],
) -> dict[str, dict[str, object]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = connection.execute(
        f"""
        SELECT run_id, scenario_name, passed, max_drawdown, target_regimes_json
        FROM stress_runs
        WHERE run_id IN ({placeholders})
        ORDER BY run_id ASC, scenario_name ASC
        """,
        run_ids,
    ).fetchall()
    grouped: dict[str, list[tuple[object, ...]]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        grouped[str(row[0])].append(row)

    summary_by_run: dict[str, dict[str, object]] = {}
    for run_id, entries in grouped.items():
        if not entries:
            summary_by_run[run_id] = {}
            continue
        target_regimes: set[str] = set()
        worst_scenario = "none"
        worst_drawdown: float | None = None
        failed_count = 0
        for entry in entries:
            if int(entry[2]) == 0:
                failed_count += 1
            drawdown = _to_float_or_none(entry[3])
            if drawdown is not None and (worst_drawdown is None or drawdown < worst_drawdown):
                worst_drawdown = drawdown
                worst_scenario = str(entry[1])
            for regime in _load_json_list(entry[4]):
                if isinstance(regime, str) and regime:
                    target_regimes.add(regime)
        summary_by_run[run_id] = {
            "scenario_count": len(entries),
            "failed_scenario_count": failed_count,
            "worst_scenario": worst_scenario,
            "target_regime_count": len(target_regimes),
        }
    return summary_by_run


def _load_candidate_trial_summaries(
    connection: sqlite3.Connection,
    *,
    run_ids: list[str],
) -> dict[str, dict[str, object]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = connection.execute(
        f"""
        SELECT run_id, layer_name, decision, oos_sharpe, partial_fill_event_count, min_fill_ratio
        FROM candidate_trials
        WHERE run_id IN ({placeholders})
        ORDER BY run_id ASC, oos_sharpe DESC, phase_name ASC, layer_name ASC, ordinal ASC
        """,
        run_ids,
    ).fetchall()
    grouped: dict[str, list[tuple[object, ...]]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        grouped[str(row[0])].append(row)

    summary_by_run: dict[str, dict[str, object]] = {}
    for run_id, entries in grouped.items():
        if not entries:
            summary_by_run[run_id] = {}
            continue
        best = entries[0]
        layers = {
            str(entry[1])
            for entry in entries
            if isinstance(entry[1], str) and str(entry[1])
        }
        pressured_trial_count = sum(
            1
            for entry in entries
            if entry[4] is not None and int(entry[4]) > 0
        )
        min_fill_candidates = [
            _to_float_or_none(entry[5])
            for entry in entries
            if _to_float_or_none(entry[5]) is not None
        ]
        summary_by_run[run_id] = {
            "trial_count": len(entries),
            "top_decision": str(best[2]),
            "top_oos_sharpe": _to_float_or_none(best[3]),
            "layer_count": len(layers),
            "pressured_trial_count": pressured_trial_count,
            "worst_min_fill_ratio": min(min_fill_candidates) if min_fill_candidates else None,
        }
    return summary_by_run


def _load_data_snapshot_summaries(
    connection: sqlite3.Connection,
    *,
    run_ids: list[str],
) -> dict[str, dict[str, object]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = connection.execute(
        f"""
        SELECT
            research_runs.run_id,
            data_snapshots.provider,
            data_snapshots.build_mode,
            data_snapshots.usage_count,
            data_snapshots.first_seen_run_id
        FROM research_runs
        LEFT JOIN data_snapshots ON data_snapshots.snapshot_id = research_runs.snapshot_id
        WHERE research_runs.run_id IN ({placeholders})
        ORDER BY research_runs.run_id ASC
        """,
        run_ids,
    ).fetchall()
    summary_by_run = {run_id: {} for run_id in run_ids}
    for row in rows:
        if row[1] is None and row[2] is None and row[3] is None and row[4] is None:
            summary_by_run[str(row[0])] = {}
            continue
        summary_by_run[str(row[0])] = {
            "provider": str(row[1]) if row[1] is not None else None,
            "build_mode": str(row[2]) if row[2] is not None else None,
            "usage_count": int(row[3]) if row[3] is not None else 0,
            "first_seen_run_id": str(row[4]) if row[4] is not None else None,
        }
    return summary_by_run


def _load_meta_policy_summaries(
    connection: sqlite3.Connection,
    *,
    run_ids: list[str],
) -> dict[str, dict[str, object]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = connection.execute(
        f"""
        SELECT run_id, policy_id, policy_family, status, training_stats_json, payload_json
        FROM meta_policies
        WHERE run_id IN ({placeholders})
        ORDER BY run_id ASC, policy_id ASC
        """,
        run_ids,
    ).fetchall()
    grouped: dict[str, list[tuple[object, ...]]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        grouped[str(row[0])].append(row)

    summary_by_run: dict[str, dict[str, object]] = {}
    for run_id, entries in grouped.items():
        if not entries:
            summary_by_run[run_id] = {}
            continue
        latest = entries[-1]
        summary_by_run[run_id] = {
            "policy_count": len(entries),
            "latest_policy_id": str(latest[1]),
            "policy_family": str(latest[2]) if latest[2] is not None else None,
            "status": str(latest[3]) if latest[3] is not None else None,
        }
        training_stats = _load_json_dict(latest[4])
        payload = _load_json_dict(latest[5])
        offline_eval = payload.get("offline_evaluation")
        if isinstance(training_stats, dict):
            summary_by_run[run_id]["selected_action"] = training_stats.get("selected_action")
            summary_by_run[run_id]["training_example_count"] = training_stats.get("training_example_count", 0)
        if isinstance(offline_eval, dict):
            summary_by_run[run_id]["offline_eval_method"] = offline_eval.get("method")
            summary_by_run[run_id]["best_observed_action"] = offline_eval.get("best_observed_action")
    return summary_by_run


def _load_run_resource_link_summaries(
    connection: sqlite3.Connection,
    *,
    run_ids: list[str],
) -> dict[str, dict[str, object]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = connection.execute(
        f"""
        SELECT
            run_resource_links.run_id,
            run_resource_links.resource_id,
            resource_index.resource_group,
            resource_index.status
        FROM run_resource_links
        LEFT JOIN resource_index ON resource_index.resource_id = run_resource_links.resource_id
        WHERE run_resource_links.run_id IN ({placeholders})
        ORDER BY run_resource_links.run_id ASC, run_resource_links.resource_id ASC, run_resource_links.link_role ASC
        """,
        run_ids,
    ).fetchall()
    grouped: dict[str, list[tuple[object, ...]]] = {run_id: [] for run_id in run_ids}
    for row in rows:
        grouped[str(row[0])].append(row)

    summary_by_run: dict[str, dict[str, object]] = {}
    for run_id, entries in grouped.items():
        if not entries:
            summary_by_run[run_id] = {}
            continue
        blocked_link_count = 0
        resource_ids: set[str] = set()
        resource_groups: set[str] = set()
        for entry in entries:
            resource_ids.add(str(entry[1]))
            if entry[2] is not None:
                resource_groups.add(str(entry[2]))
            status = str(entry[3]) if entry[3] is not None else ""
            if status.startswith("blocked"):
                blocked_link_count += 1
        summary_by_run[run_id] = {
            "link_count": len(entries),
            "linked_resource_count": len(resource_ids),
            "blocked_link_count": blocked_link_count,
            "resource_groups": sorted(resource_groups),
            "resource_ids": sorted(resource_ids),
        }
    return summary_by_run


def _load_json_dict(raw: object) -> dict[str, object]:
    if not isinstance(raw, str):
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _candidate_execution_pressure_summary(
    *,
    fill_event_count: object,
    partial_fill_event_count: object,
    average_fill_ratio: object,
    min_fill_ratio: object,
    payload_json: object,
) -> dict[str, object]:
    summary = {
        "fill_event_count": int(fill_event_count) if fill_event_count is not None else None,
        "partial_fill_event_count": int(partial_fill_event_count) if partial_fill_event_count is not None else None,
        "average_fill_ratio": _to_float_or_none(average_fill_ratio),
        "min_fill_ratio": _to_float_or_none(min_fill_ratio),
    }
    if any(value is not None for value in summary.values()):
        return {key: value for key, value in summary.items() if value is not None}
    payload = _load_json_dict(payload_json)
    nested = payload.get("execution_pressure_summary")
    return nested if isinstance(nested, dict) else {}


def _candidate_trial_is_pressured(summary: object) -> bool:
    if not isinstance(summary, dict):
        return False
    partial_fill_event_count = summary.get("partial_fill_event_count")
    return bool(
        isinstance(partial_fill_event_count, int | float)
        and not isinstance(partial_fill_event_count, bool)
        and partial_fill_event_count > 0
    )


def _run_has_candidate_pressure(summary: object) -> bool:
    if not isinstance(summary, dict):
        return False
    pressured_trial_count = summary.get("pressured_trial_count")
    return bool(
        isinstance(pressured_trial_count, int | float)
        and not isinstance(pressured_trial_count, bool)
        and pressured_trial_count > 0
    )


def _sort_candidate_trial_rows(
    rows: list[dict[str, object]],
    *,
    sort_by: str,
) -> list[dict[str, object]]:
    if sort_by == "worst_fill":
        return sorted(
            rows,
            key=lambda row: (
                _sort_float_ascending(
                    _to_float_or_none(
                        (row.get("execution_pressure_summary") or {}).get("min_fill_ratio")
                        if isinstance(row.get("execution_pressure_summary"), dict)
                        else None
                    )
                ),
                _sort_float_descending(_to_float_or_none(row.get("oos_sharpe"))),
                str(row.get("run_id") or ""),
                str(row.get("phase_name") or ""),
                str(row.get("layer_name") or ""),
                int(row.get("ordinal") or 0),
            ),
        )
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("run_id") or ""),
            _sort_float_descending(_to_float_or_none(row.get("oos_sharpe"))),
            str(row.get("phase_name") or ""),
            str(row.get("layer_name") or ""),
            int(row.get("ordinal") or 0),
        ),
    )


def _sort_run_memory_rows(
    rows: list[dict[str, object]],
    *,
    sort_by: str,
) -> list[dict[str, object]]:
    if sort_by == "candidate_worst_fill":
        return sorted(
            rows,
            key=lambda row: (
                _sort_float_ascending(
                    _to_float_or_none(
                        (row.get("candidate_trial_summary") or {}).get("worst_min_fill_ratio")
                        if isinstance(row.get("candidate_trial_summary"), dict)
                        else None
                    )
                ),
                _sort_float_descending(_to_float_or_none(row.get("selection_oos_sharpe"))),
                str(row.get("run_id") or ""),
            ),
        )
    return sorted(
        rows,
        key=lambda row: (
            _sort_float_descending(_to_float_or_none(row.get("selection_oos_sharpe"))),
            str(row.get("run_id") or ""),
        ),
    )


def _load_json_list(raw: object) -> list[object]:
    if not isinstance(raw, str):
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return payload


def _split_csv_values(raw: object) -> list[str]:
    if not isinstance(raw, str) or not raw:
        return []
    return sorted({part for part in raw.split(",") if part})


def _format_key_value_pairs(payload: dict[str, object]) -> str:
    if not payload:
        return "none"
    return ",".join(f"{key}={payload[key]}" for key in sorted(payload))


def _format_string_list(raw: object) -> str:
    if not isinstance(raw, list):
        return "none"
    rendered = [str(item) for item in raw if isinstance(item, str) and item]
    return ",".join(rendered) if rendered else "none"


def _format_metric_value(raw: object) -> str:
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return str(raw)
    return "n/a"


def _format_failure_taxonomy_counts(raw: object) -> str:
    if not isinstance(raw, dict) or not raw:
        return "none"
    parts: list[tuple[str, int]] = []
    for key, value in raw.items():
        if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int | float):
            continue
        parts.append((key, int(value)))
    if not parts:
        return "none"
    parts.sort(key=lambda item: (-item[1], item[0]))
    return ",".join(f"{label}={count}" for label, count in parts)


def _format_first_next_hypothesis(raw: object) -> str:
    if not isinstance(raw, list):
        return "none"
    for item in raw:
        if isinstance(item, str) and item:
            return item
    return "none"


def _to_float_or_none(raw: object) -> float | None:
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return float(raw)
    return None


def _sort_float_ascending(raw: float | None) -> tuple[int, float]:
    if raw is None:
        return (1, float("inf"))
    return (0, raw)


def _sort_float_descending(raw: float | None) -> tuple[int, float]:
    if raw is None:
        return (1, float("inf"))
    return (0, -raw)


def _extract_base_asset(symbol: str | None) -> str | None:
    if not isinstance(symbol, str) or not symbol:
        return None
    normalized = symbol.upper().replace("USDT", "").replace("USD", "").replace("BUSD", "").replace("USDC", "")
    for separator in ("/", "-", "_"):
        if separator in normalized:
            normalized = normalized.split(separator)[0]
    return normalized.strip()
