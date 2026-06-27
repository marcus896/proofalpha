from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RealtimeBackfillReconciliationReport:
    symbol: str
    passed: bool
    issues: list[str]
    matched_count: int
    mismatched_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def reconcile_realtime_with_backfill(
    *,
    symbol: str,
    realtime_hashes: dict[str, str],
    backfill_hashes: dict[str, str],
) -> RealtimeBackfillReconciliationReport:
    issues: list[str] = []
    matched = 0
    mismatched = 0
    for timestamp, realtime_hash in realtime_hashes.items():
        backfill_hash = backfill_hashes.get(timestamp)
        if backfill_hash is None:
            issues.append(f"missing_backfill:{timestamp}")
            mismatched += 1
        elif backfill_hash != realtime_hash:
            issues.append(f"hash_mismatch:{timestamp}")
            mismatched += 1
        else:
            matched += 1
    return RealtimeBackfillReconciliationReport(
        symbol=symbol,
        passed=not issues,
        issues=issues,
        matched_count=matched,
        mismatched_count=mismatched,
    )
