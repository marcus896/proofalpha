from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class SymbolDataHealthReport:
    symbol: str
    status: str
    passed: bool
    issues: list[str]
    max_staleness_seconds: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_symbol_data_health(
    *,
    symbol: str,
    now_utc: str,
    max_staleness_seconds: int,
    mark_price_ts_utc: str | None,
    funding_ts_utc: str | None,
    open_interest_ts_utc: str | None,
    book_ts_utc: str | None,
    book_gap_count: int = 0,
) -> SymbolDataHealthReport:
    issues: list[str] = []
    now = _parse_utc(now_utc) or datetime.now(timezone.utc)
    _check_timestamp(issues, now, mark_price_ts_utc, max_staleness_seconds, "mark_price")
    _check_timestamp(issues, now, funding_ts_utc, max_staleness_seconds, "funding")
    _check_timestamp(issues, now, open_interest_ts_utc, max_staleness_seconds, "open_interest")
    _check_timestamp(issues, now, book_ts_utc, max_staleness_seconds, "book")
    if book_gap_count > 0:
        issues.append(f"book_gap_count={book_gap_count}")
    return SymbolDataHealthReport(
        symbol=symbol,
        status="passed" if not issues else "failed",
        passed=not issues,
        issues=issues,
        max_staleness_seconds=max_staleness_seconds,
    )


def _check_timestamp(
    issues: list[str],
    now: datetime,
    value: str | None,
    max_staleness_seconds: int,
    field_name: str,
) -> None:
    parsed = _parse_utc(value)
    if parsed is None:
        issues.append(f"missing_{field_name}")
        return
    if (now - parsed).total_seconds() > max_staleness_seconds:
        issues.append(f"stale_{field_name}")


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
