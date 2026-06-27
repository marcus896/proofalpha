from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BinanceError:
    code: int | None
    message: str
    reason_code: str


def normalize_binance_error(payload: object) -> BinanceError:
    if isinstance(payload, dict):
        code = payload.get("code")
        message = str(payload.get("msg") or payload.get("message") or "")
    else:
        code = None
        message = str(payload)
    reason = "binance_error"
    lower = message.lower()
    if "insufficient" in lower:
        reason = "insufficient_margin"
    elif "precision" in lower:
        reason = "precision_error"
    elif "min notional" in lower:
        reason = "min_notional_violation"
    return BinanceError(code=int(code) if isinstance(code, int) else None, message=message, reason_code=reason)
