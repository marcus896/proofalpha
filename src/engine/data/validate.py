from __future__ import annotations

from datetime import datetime


_EXPECTED_STEP_SECONDS = {
    "1Min": 60,
    "5Min": 300,
    "15Min": 900,
    "30Min": 1_800,
    "1Hour": 3_600,
    "2Hour": 7_200,
    "4Hour": 14_400,
    "1Day": 86_400,
}


def validate_snapshot_bundle(
    *,
    candle_timestamps: list[str],
    candle_opens: list[float] | None = None,
    candle_highs: list[float] | None = None,
    candle_lows: list[float] | None = None,
    candle_closes: list[float] | None = None,
    candle_volumes: list[float] | None = None,
    funding_rates: list[float],
    open_interest: list[float],
    liquidation_notional: list[float],
    timeframe: str,
) -> dict[str, object]:
    warnings: list[str] = []
    parsed_timestamps = [datetime.fromisoformat(value) for value in candle_timestamps]
    expected_step_seconds = _EXPECTED_STEP_SECONDS.get(timeframe, 3_600)

    duplicate_timestamp_count = max(0, len(candle_timestamps) - len(set(candle_timestamps)))
    if duplicate_timestamp_count > 0:
        warnings.append(f"duplicate_timestamp_count={duplicate_timestamp_count}")

    gap_count = 0
    for left, right in zip(parsed_timestamps, parsed_timestamps[1:]):
        if int((right - left).total_seconds()) != expected_step_seconds:
            gap_count += 1
    if gap_count > 0:
        warnings.append(f"timestamp_gap_count={gap_count}")

    length_mismatch_count = _length_mismatch_count(
        len(candle_timestamps),
        funding_rates,
        open_interest,
        liquidation_notional,
        candle_opens,
        candle_highs,
        candle_lows,
        candle_closes,
        candle_volumes,
    )
    if length_mismatch_count > 0:
        warnings.append(f"series_length_mismatch_count={length_mismatch_count}")

    price_sanity_count = _price_sanity_count(
        candle_opens or [],
        candle_highs or [],
        candle_lows or [],
        candle_closes or [],
    )
    if price_sanity_count > 0:
        warnings.append(f"price_sanity_count={price_sanity_count}")

    negative_volume_count = sum(1 for value in (candle_volumes or []) if value < 0.0)
    if negative_volume_count > 0:
        warnings.append(f"negative_volume_count={negative_volume_count}")

    negative_open_interest_count = sum(1 for value in open_interest if value < 0.0)
    if negative_open_interest_count > 0:
        warnings.append(f"negative_open_interest_count={negative_open_interest_count}")

    negative_liquidation_count = sum(1 for value in liquidation_notional if value < 0.0)
    if negative_liquidation_count > 0:
        warnings.append(f"negative_liquidation_notional_count={negative_liquidation_count}")

    funding_rate_clamp_count = sum(1 for value in funding_rates if abs(value) > 0.20)
    if funding_rate_clamp_count > 0:
        warnings.append(f"funding_rate_clamp_count={funding_rate_clamp_count}")

    return {
        "warnings": warnings,
        "passed": not warnings,
    }


def _length_mismatch_count(expected_length: int, *series: list[float] | None) -> int:
    mismatches = 0
    for values in series:
        if values is not None and len(values) != expected_length:
            mismatches += 1
    return mismatches


def _price_sanity_count(
    candle_opens: list[float],
    candle_highs: list[float],
    candle_lows: list[float],
    candle_closes: list[float],
) -> int:
    sanity_failures = 0
    for open_price, high_price, low_price, close_price in zip(
        candle_opens, candle_highs, candle_lows, candle_closes
    ):
        if min(open_price, high_price, low_price, close_price) <= 0.0:
            sanity_failures += 1
            continue
        if high_price < low_price:
            sanity_failures += 1
            continue
        if high_price < max(open_price, close_price):
            sanity_failures += 1
            continue
        if low_price > min(open_price, close_price):
            sanity_failures += 1
    return sanity_failures

