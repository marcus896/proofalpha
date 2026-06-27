from __future__ import annotations


def failed_validation_gate_names(raw_gate_results: object) -> list[str]:
    if not isinstance(raw_gate_results, dict):
        return []
    failed: list[str] = []
    for gate_name in sorted(raw_gate_results):
        if raw_gate_results.get(gate_name) is False:
            failed.append(str(gate_name))
    return failed


def normalize_validation_bundle(
    protocol: object,
    *,
    dsr_override: object = None,
    psr_override: object = None,
) -> dict[str, object]:
    if not isinstance(protocol, dict):
        return {}

    normalized: dict[str, object] = {}
    status = protocol.get("status")
    if status is not None:
        normalized["status"] = status

    dsr_value = dsr_override if dsr_override is not None else protocol.get("deflated_sharpe_ratio")
    if dsr_value is not None:
        normalized["deflated_sharpe_ratio"] = dsr_value

    psr_value = psr_override if psr_override is not None else protocol.get("probabilistic_sharpe_ratio")
    if psr_value is not None:
        normalized["probabilistic_sharpe_ratio"] = psr_value

    pbo_value = protocol.get("pbo_score")
    if pbo_value is not None:
        normalized["pbo_score"] = pbo_value

    spa_value = protocol.get("spa_pvalue")
    if spa_value is not None:
        normalized["spa_pvalue"] = spa_value

    for field_name in ("purge_bars", "embargo_bars", "n_blocks", "n_test_blocks", "min_backtest_length", "min_trade_count"):
        field_value = protocol.get(field_name)
        if field_value is not None:
            normalized[field_name] = field_value

    for field_name in ("cpcv_config", "in_sample_summary", "selection_oos_summary", "holdout_summary"):
        field_value = protocol.get(field_name)
        if isinstance(field_value, dict) and field_value:
            normalized[field_name] = dict(field_value)

    normalized["failed_gates"] = failed_validation_gate_names(protocol.get("validation_gate_results"))
    return normalized


def compare_validation_bundles(
    left_protocol: object,
    right_protocol: object,
    *,
    left_dsr_override: object = None,
    left_psr_override: object = None,
    right_dsr_override: object = None,
    right_psr_override: object = None,
) -> dict[str, object]:
    left_bundle = normalize_validation_bundle(
        left_protocol,
        dsr_override=left_dsr_override,
        psr_override=left_psr_override,
    )
    right_bundle = normalize_validation_bundle(
        right_protocol,
        dsr_override=right_dsr_override,
        psr_override=right_psr_override,
    )
    changed_fields = {
        field_name: {
            "left": left_bundle.get(field_name),
            "right": right_bundle.get(field_name),
        }
        for field_name in sorted(set(left_bundle) | set(right_bundle))
        if left_bundle.get(field_name) != right_bundle.get(field_name)
    }
    return {
        "left": left_bundle,
        "right": right_bundle,
        "changed_fields": changed_fields,
    }
