from __future__ import annotations

from typing import Any


STRICT_V3_MIN_BARS = {
    "1Hour": 13_140,
    "15Min": 52_560,
}

STRICT_V3_SYMBOLS = {"BTCUSDT", "ETHUSDT"}
PUBLIC_ONLY_ALLOWED_PROVIDERS = {
    "binance_perps",
    "binance_public_archive",
    "binance_public_ws_rest_bundle",
}

MIN_RUN_READY_CANDLES = 5
OBSERVED_LIQUIDATION_CONFIDENCE = "observed_public_forceorder_with_zero_buckets"
UNAVAILABLE_ARCHIVE_LIQUIDATION_CONFIDENCE = "unavailable_archive_sidecar_empty_do_not_treat_zero_as_truth"


def build_data_sufficiency_report(study: Any, *, profile: str = "strict_v3") -> dict[str, object]:
    snapshot = getattr(study, "snapshot", None)
    provenance = getattr(snapshot, "provenance", {}) if snapshot is not None else {}
    provenance = provenance if isinstance(provenance, dict) else {}
    field_confidence = provenance.get("field_confidence")
    field_confidence = field_confidence if isinstance(field_confidence, dict) else {}

    symbol = str(getattr(snapshot, "symbol", ""))
    venue = str(getattr(snapshot, "venue", ""))
    timeframe = str(getattr(snapshot, "timeframe", ""))
    candles = list(getattr(snapshot, "candles", []) or [])
    quality_flags = [str(flag) for flag in list(getattr(snapshot, "quality_flags", []) or [])]
    quality_issues = _quality_report_issues(getattr(snapshot, "quality_report", None))
    provider = provenance.get("provider")
    provider_text = str(provider) if provider is not None else ""
    minimum_candle_count = STRICT_V3_MIN_BARS.get(timeframe, 0)
    candle_count = len(candles)
    source_hash_present = bool(provenance.get("source_hash") or provenance.get("raw_source_hash"))
    fetch_manifest_present = bool(provenance.get("fetch_manifest"))
    liquidation_confidence = str(field_confidence.get("liquidation_notional") or "")
    liquidation_observed = liquidation_confidence == OBSERVED_LIQUIDATION_CONFIDENCE
    liquidation_unavailable = liquidation_confidence == UNAVAILABLE_ARCHIVE_LIQUIDATION_CONFIDENCE
    liquidation_dependent = _study_uses_liquidation_features(study)
    paper_evidence_present = _has_paper_evidence(provenance)

    blockers: list[str] = []
    research_blockers: list[str] = []
    improvement_blockers: list[str] = []
    missing_data_requirements: list[str] = []

    if profile != "strict_v3":
        _add(research_blockers, "unsupported_data_sufficiency_profile")
    if symbol not in STRICT_V3_SYMBOLS:
        _add(research_blockers, "unsupported_strict_v3_symbol")
    if venue.lower() != "binance":
        _add(research_blockers, "unsupported_strict_v3_venue")
    if timeframe not in STRICT_V3_MIN_BARS:
        _add(research_blockers, "unsupported_strict_v3_timeframe")
    if _looks_like_example_or_fixture(study):
        _add(research_blockers, "example_or_fixture_study")
    if not provider_text or provider_text not in PUBLIC_ONLY_ALLOWED_PROVIDERS:
        _add(research_blockers, "missing_real_source_provenance")
    if not source_hash_present:
        _add(research_blockers, "missing_source_hash")
    if not fetch_manifest_present:
        _add(research_blockers, "missing_fetch_manifest")
    if candle_count < minimum_candle_count:
        _add(research_blockers, "insufficient_history_for_v3_improvement")
        _add(missing_data_requirements, "strict_v3_history")
    if quality_flags:
        _add(research_blockers, "snapshot_quality_flags_present")
    if quality_issues:
        _add(research_blockers, "snapshot_quality_issues_present")
    if liquidation_dependent and not liquidation_observed:
        _add(research_blockers, "liquidation_feature_missing_observed_sidecar")

    if not liquidation_observed:
        _add(improvement_blockers, "liquidation_feature_missing_observed_sidecar")
        _add(missing_data_requirements, "observed_liquidation_sidecar")
    if not paper_evidence_present:
        _add(improvement_blockers, "missing_paper_executor_feedback")
        _add(missing_data_requirements, "paper_executor_feedback")

    research_ready = not research_blockers
    improvement_ready = research_ready and not improvement_blockers
    for blocker in [*research_blockers, *improvement_blockers]:
        _add(blockers, blocker)

    return {
        "artifact_type": "data_sufficiency_report",
        "profile": profile,
        "run_ready": candle_count >= MIN_RUN_READY_CANDLES,
        "research_ready": research_ready,
        "improvement_ready": improvement_ready,
        "can_claim_strategy_improvement": False,
        "symbol": symbol,
        "venue": venue,
        "timeframe": timeframe,
        "candle_count": candle_count,
        "minimum_candle_count": minimum_candle_count,
        "provider": provider,
        "source_hash_present": source_hash_present,
        "fetch_manifest_present": fetch_manifest_present,
        "quality_flags": quality_flags,
        "quality_issues": quality_issues,
        "blockers": blockers,
        "missing_data_requirements": missing_data_requirements,
        "feature_availability": {
            "liquidation_notional": _liquidation_availability(
                observed=liquidation_observed,
                unavailable=liquidation_unavailable,
            ),
            "liquidation_dependent_features_allowed": liquidation_observed,
            "liquidation_field_confidence": liquidation_confidence or None,
        },
        "strict_profile": {
            "symbols": sorted(STRICT_V3_SYMBOLS),
            "minimum_bars": dict(STRICT_V3_MIN_BARS),
            "public_only_allowed_providers": sorted(PUBLIC_ONLY_ALLOWED_PROVIDERS),
        },
        "paper_evidence_present": paper_evidence_present,
        "liquidation_dependent_strategy": liquidation_dependent,
    }


def _quality_report_issues(quality_report: object) -> list[str]:
    if quality_report is None:
        return []
    issues = getattr(quality_report, "issues", None)
    if isinstance(issues, list):
        return [str(issue) for issue in issues]
    if getattr(quality_report, "passed", True) is False:
        return ["quality_report_failed"]
    return []


def _looks_like_example_or_fixture(study: Any) -> bool:
    run_id = str(getattr(study, "run_id", ""))
    runtime_mode = str(getattr(study, "runtime_mode", ""))
    snapshot_id = str(getattr(getattr(study, "snapshot", None), "snapshot_id", ""))
    return runtime_mode == "fixture" or run_id.startswith("example-") or snapshot_id.startswith("example-")


def _study_uses_liquidation_features(study: Any) -> bool:
    values: list[object] = []
    incumbent = getattr(study, "incumbent", None)
    if incumbent is not None:
        values.append(getattr(incumbent, "backbone", ""))
        values.extend(list(getattr(incumbent, "layers", []) or []))
        values.extend(list(getattr(incumbent, "risk_guards", []) or []))
    for attr_name in ("directional_layers", "known_good_filters", "custom_filters", "exit_layers"):
        values.extend(list(getattr(study, attr_name, []) or []))
    return any(_object_mentions_liquidation(value) for value in values)


def _object_mentions_liquidation(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        lowered = value.lower()
        return "liquidation" in lowered or "liq_" in lowered or lowered.startswith("liq")
    name = getattr(value, "name", None)
    if isinstance(name, str) and _object_mentions_liquidation(name):
        return True
    rules = getattr(value, "eligibility_rules", None)
    return _nested_value_mentions_liquidation(rules)


def _nested_value_mentions_liquidation(value: object) -> bool:
    if isinstance(value, dict):
        return any(_nested_value_mentions_liquidation(key) or _nested_value_mentions_liquidation(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_nested_value_mentions_liquidation(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "liquidation" in lowered or "liq_" in lowered or lowered.startswith("liq")
    return False


def _has_paper_evidence(provenance: dict[str, object]) -> bool:
    for key in ("paper_evidence", "paper_feedback", "paper_dashboard", "paper_postrun_summary"):
        value = provenance.get(key)
        if isinstance(value, dict):
            if value.get("completed") or value.get("status") in {"completed", "healthy"}:
                return True
            if value.get("order_count", 0):
                return True
        elif value:
            return True
    return False


def _liquidation_availability(*, observed: bool, unavailable: bool) -> str:
    if observed:
        return "observed"
    if unavailable:
        return "unavailable"
    return "unknown"


def _add(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)
