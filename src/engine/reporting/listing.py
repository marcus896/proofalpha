from __future__ import annotations

import json
from pathlib import Path

from engine.config.models import RunCard
from engine.reporting.runcards import load_runcard


def list_runcards(directory: Path) -> list[RunCard]:
    return load_runcard_records(directory)[0]


def load_runcard_records(directory: Path) -> tuple[list[RunCard], int]:
    if not directory.exists():
        return [], 0
    records: list[RunCard] = []
    skipped_malformed = 0
    for path in sorted(directory.glob("*.runcard.json")):
        try:
            records.append(load_runcard(path))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            skipped_malformed += 1
    return records, skipped_malformed


def filter_runcards(
    runcards: list[RunCard],
    decision: str | None = None,
    symbol: str | None = None,
    quality_status: str | None = None,
) -> list[RunCard]:
    filtered = list(runcards)
    if decision is not None:
        filtered = [card for card in filtered if card.decision.decision == decision]
    if symbol is not None:
        filtered = [card for card in filtered if card.artifacts.get("symbol") == symbol]
    if quality_status is not None:
        filtered = [card for card in filtered if card.artifacts.get("snapshot_quality_status") == quality_status]
    return filtered


def rank_runcards(runcards: list[RunCard], sort_by: str, limit: int | None = None) -> list[RunCard]:
    ranked = sorted(runcards, key=lambda card: float(card.metrics.get(sort_by, float("-inf"))), reverse=True)
    if limit is None:
        return ranked
    return ranked[: max(0, limit)]


def render_runcard_listing(runcards: list[RunCard], sort_by: str, fmt: str) -> str:
    if fmt == "json":
        payload = [
            {
                "run_id": card.run_id,
                "decision": card.decision.decision,
                "phase": card.phase,
                "sort_metric": card.metrics.get(sort_by),
                "metrics": dict(card.metrics),
                "artifacts": dict(card.artifacts),
            }
            for card in runcards
        ]
        return json.dumps(payload, sort_keys=True)

    lines = [f"Runs ranked by {sort_by}"]
    if not runcards:
        lines.append("none")
        return "\n".join(lines)
    for index, card in enumerate(runcards, start=1):
        build_version = card.artifacts.get("snapshot_build_version", "")
        build_suffix = f" | build={build_version}" if isinstance(build_version, str) and build_version else ""
        loop_metadata = _load_json_object(card.artifacts.get("agent_loop_metadata_json", "{}"))
        loop_suffix = ""
        loop_pressure = _format_failure_taxonomy_counts(loop_metadata.get("failure_taxonomy_counts"))
        if loop_pressure != "none":
            loop_suffix += f" | loop={loop_pressure}"
        next_hypotheses = loop_metadata.get("next_hypotheses")
        if isinstance(next_hypotheses, list):
            rendered_hypotheses = [str(item) for item in next_hypotheses if isinstance(item, str) and item]
            if rendered_hypotheses:
                loop_suffix += f" | next={rendered_hypotheses[0]}"
        lines.append(
            f"{index}. {card.run_id} | {sort_by}={card.metrics.get(sort_by)} | decision={card.decision.decision} | symbol={card.artifacts.get('symbol', 'unknown')} | quality={card.artifacts.get('snapshot_quality_status', 'unknown')}{build_suffix}{loop_suffix}"
        )
    return "\n".join(lines)


def list_campaign_reports(directory: Path) -> list[dict[str, object]]:
    return load_campaign_report_records(directory)[0]


def load_campaign_report_records(directory: Path) -> tuple[list[dict[str, object]], int]:
    if not directory.exists():
        return [], 0
    payloads: list[dict[str, object]] = []
    skipped_malformed = 0
    for path in sorted(directory.glob("*.campaign.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skipped_malformed += 1
            continue
        if not isinstance(payload, dict):
            skipped_malformed += 1
            continue
        payload["_path"] = str(path)
        payloads.append(payload)
    return payloads, skipped_malformed


def filter_campaign_reports(
    reports: list[dict[str, object]],
    *,
    status: str | None = None,
) -> list[dict[str, object]]:
    filtered = list(reports)
    if status is not None:
        filtered = [report for report in filtered if report.get("status") == status]
    return filtered


def rank_campaign_reports(
    reports: list[dict[str, object]],
    *,
    sort_by: str,
    limit: int | None = None,
) -> list[dict[str, object]]:
    ranked = sorted(reports, key=lambda report: _campaign_sort_value(report.get(sort_by)), reverse=True)
    if limit is None:
        return ranked
    return ranked[: max(0, limit)]


def render_campaign_listing(reports: list[dict[str, object]], *, sort_by: str, fmt: str) -> str:
    if fmt == "json":
        payload = [
            {
                "campaign_id": report.get("campaign_id"),
                "status": report.get("status"),
                "sort_metric": report.get(sort_by),
                "entry_count": report.get("entry_count"),
                "completed_entries": report.get("completed_entries"),
                "failed_entries": report.get("failed_entries"),
                "path": report.get("_path"),
            }
            for report in reports
        ]
        return json.dumps(payload, sort_keys=True)

    lines = [f"Campaigns ranked by {sort_by}"]
    if not reports:
        lines.append("none")
        return "\n".join(lines)
    for index, report in enumerate(reports, start=1):
        lines.append(
            f"{index}. {report.get('campaign_id', 'unknown')} | {sort_by}={report.get(sort_by)} | status={report.get('status', 'unknown')} | failed={report.get('failed_entries', 0)}"
        )
    return "\n".join(lines)


def _campaign_sort_value(value: object) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return float("-inf")


def _load_json_object(raw: object) -> dict[str, object]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


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
    return ", ".join(f"{label}={count}" for label, count in parts)
