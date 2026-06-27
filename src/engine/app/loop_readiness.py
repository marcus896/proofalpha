from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.app.config import load_study_config
from engine.app.data_sufficiency import build_data_sufficiency_report


MIN_LOOP_CANDLE_COUNT = 5


def build_loop_readiness_report(study: Any, *, config_path: Path) -> dict[str, object]:
    snapshot = study.snapshot
    candles = list(getattr(snapshot, "candles", []) or [])
    quality_flags = list(getattr(snapshot, "quality_flags", []) or [])
    quality_issues = _quality_report_issues(getattr(snapshot, "quality_report", None))
    provenance = getattr(snapshot, "provenance", {})
    provenance = provenance if isinstance(provenance, dict) else {}
    total_candles = len(candles)
    blockers: list[str] = []

    if _looks_like_example(study, config_path):
        blockers.append("example_or_fixture_study")
    if not _has_real_source_provenance(provenance):
        blockers.append("missing_real_source_provenance")
    if not _has_liquidation_field_confidence(provenance):
        blockers.append("missing_liquidation_field_confidence")
    if total_candles <= 0:
        blockers.append("empty_snapshot")
    elif total_candles < MIN_LOOP_CANDLE_COUNT:
        blockers.append("insufficient_candle_count")
    if quality_flags:
        blockers.append("snapshot_quality_flags_present")
    if quality_issues:
        blockers.append("snapshot_quality_issues_present")

    liquidation_coverage = _series_coverage(
        total_candles=total_candles,
        quality_flags=quality_flags,
        series_name="liquidation_notional",
    )
    if liquidation_coverage["covered"] < total_candles:
        blockers.append("liquidation_notional_not_fully_observed")

    data_sufficiency = build_data_sufficiency_report(study)
    report = {
        "artifact_type": "loop_readiness_report",
        "eligible": not blockers,
        "run_ready": bool(data_sufficiency.get("run_ready")),
        "research_ready": bool(data_sufficiency.get("research_ready")),
        "improvement_ready": bool(data_sufficiency.get("improvement_ready")),
        "can_claim_strategy_improvement": bool(data_sufficiency.get("can_claim_strategy_improvement")),
        "config_path": str(config_path),
        "run_id": str(getattr(study, "run_id", "")),
        "snapshot_id": str(getattr(snapshot, "snapshot_id", "")),
        "symbol": str(getattr(snapshot, "symbol", "")),
        "venue": str(getattr(snapshot, "venue", "")),
        "timeframe": str(getattr(snapshot, "timeframe", "")),
        "candle_count": total_candles,
        "minimum_candle_count": MIN_LOOP_CANDLE_COUNT,
        "quality_flags": quality_flags,
        "quality_issues": quality_issues,
        "blockers": list(dict.fromkeys(blockers)),
        "real_source": _has_real_source_provenance(provenance),
        "source": {
            "provider": provenance.get("provider"),
            "fetch_manifest": provenance.get("fetch_manifest"),
            "source_hash": provenance.get("source_hash"),
            "field_confidence": provenance.get("field_confidence"),
        },
        "liquidation_coverage": liquidation_coverage,
        "data_sufficiency": data_sufficiency,
    }
    return report


def build_loop_readiness_scan(root: Path) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for config_path in _iter_candidate_study_paths(root):
        try:
            study = load_study_config(config_path)
            reports.append(build_loop_readiness_report(study, config_path=config_path))
        except Exception as exc:  # pragma: no cover - defensive reporting path
            errors.append(
                {
                    "config_path": str(config_path),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    eligible = [report for report in reports if report.get("eligible")]
    blocked = [report for report in reports if not report.get("eligible")]
    return {
        "artifact_type": "loop_readiness_scan",
        "root": str(root),
        "study_count": len(reports),
        "eligible_count": len(eligible),
        "blocked_count": len(blocked),
        "error_count": len(errors),
        "blocked_by_reason": _count_blockers(blocked),
        "eligible": eligible,
        "blocked": blocked,
        "errors": errors,
    }


def _looks_like_example(study: Any, config_path: Path) -> bool:
    run_id = str(getattr(study, "run_id", ""))
    normalized_path = str(config_path).replace("\\", "/").lower()
    return run_id.startswith("example-") or "/examples/" in f"/{normalized_path}" or normalized_path.startswith("examples/")


def _iter_candidate_study_paths(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if _is_candidate_study_path(root) else []
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.json") if _is_candidate_study_path(path))


def _is_candidate_study_path(path: Path) -> bool:
    name = path.name
    return (
        name == "study.json"
        or name == "minimal_builtin_study.json"
        or name.endswith(".study.json")
        or name.endswith(".next-study.json")
    )


def _count_blockers(reports: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in reports:
        for blocker in report.get("blockers", []):
            reason = str(blocker)
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _quality_report_issues(quality_report: object) -> list[str]:
    issues = getattr(quality_report, "issues", None)
    if not isinstance(issues, list):
        return []
    return [str(issue) for issue in issues]


def _has_real_source_provenance(provenance: dict[str, object]) -> bool:
    provider = str(provenance.get("provider") or "")
    fetch_manifest = provenance.get("fetch_manifest")
    source_hash = provenance.get("source_hash")
    source_paths = provenance.get("source_paths")
    return bool(provider and (fetch_manifest or source_hash or source_paths))


def _has_liquidation_field_confidence(provenance: dict[str, object]) -> bool:
    field_confidence = provenance.get("field_confidence")
    if not isinstance(field_confidence, dict):
        return False
    confidence = str(field_confidence.get("liquidation_notional") or "")
    return confidence == "observed_public_forceorder_with_zero_buckets"


def _series_coverage(*, total_candles: int, quality_flags: list[str], series_name: str) -> dict[str, object]:
    missing_count = _extract_quality_count(quality_flags, f"missing_{series_name}_count=")
    covered = max(0, total_candles - missing_count)
    return {
        "series": series_name,
        "covered": covered,
        "total": total_candles,
        "missing": missing_count,
        "coverage_ratio": (covered / total_candles) if total_candles else 0.0,
    }


def _extract_quality_count(quality_flags: list[str], prefix: str) -> int:
    for flag in quality_flags:
        if flag.startswith(prefix):
            try:
                return int(flag.split("=", 1)[1])
            except (IndexError, ValueError):
                return 0
    return 0
