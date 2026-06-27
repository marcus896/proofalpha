from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class ExchangeSymbolRules:
    symbol: str
    tick_size: float | None
    step_size: float | None
    min_notional: float | None
    order_types: tuple[str, ...]
    leverage_brackets: tuple[dict[str, object], ...]
    margin_asset: str | None
    status: str | None = None
    contract_type: str | None = None
    quote_asset: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["order_types"] = list(self.order_types)
        payload["leverage_brackets"] = [dict(item) for item in self.leverage_brackets]
        return payload


@dataclass(frozen=True)
class ExchangeRulesCache:
    source: str
    created_at_utc: str
    symbols: dict[str, ExchangeSymbolRules]
    snapshot_hash: str

    @classmethod
    def from_exchange_info(
        cls,
        symbols: list[dict[str, Any]],
        *,
        source: str,
        created_at_utc: str,
    ) -> "ExchangeRulesCache":
        rules = {
            str(raw.get("symbol", "")): _parse_symbol_rules(raw)
            for raw in symbols
            if raw.get("symbol")
        }
        payload = {
            "source": source,
            "created_at_utc": created_at_utc,
            "symbols": {symbol: item.to_dict() for symbol, item in sorted(rules.items())},
        }
        return cls(
            source=source,
            created_at_utc=created_at_utc,
            symbols=rules,
            snapshot_hash=_stable_hash(payload),
        )

    def get(self, symbol: str) -> ExchangeSymbolRules:
        try:
            return self.symbols[symbol]
        except KeyError as exc:
            raise KeyError(f"missing_exchange_rules:{symbol}") from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "created_at_utc": self.created_at_utc,
            "snapshot_hash": self.snapshot_hash,
            "symbols": {symbol: item.to_dict() for symbol, item in sorted(self.symbols.items())},
        }


def _parse_symbol_rules(raw: dict[str, Any]) -> ExchangeSymbolRules:
    filters = _filter_map(raw.get("filters"))
    return ExchangeSymbolRules(
        symbol=str(raw.get("symbol", "")),
        tick_size=_float_filter(filters, "PRICE_FILTER", "tickSize"),
        step_size=_float_filter(filters, "LOT_SIZE", "stepSize"),
        min_notional=(
            _float_filter(filters, "MIN_NOTIONAL", "notional")
            or _float_filter(filters, "MIN_NOTIONAL", "minNotional")
        ),
        order_types=tuple(str(value) for value in raw.get("orderTypes", []) if isinstance(value, str)),
        leverage_brackets=tuple(
            dict(item) for item in raw.get("leverageBrackets", []) if isinstance(item, dict)
        ),
        margin_asset=(str(raw.get("marginAsset")) if raw.get("marginAsset") is not None else None),
        status=(str(raw.get("status")) if raw.get("status") is not None else None),
        contract_type=(str(raw.get("contractType")) if raw.get("contractType") is not None else None),
        quote_asset=(str(raw.get("quoteAsset")) if raw.get("quoteAsset") is not None else None),
    )


def _filter_map(raw: object) -> dict[str, dict[str, object]]:
    if isinstance(raw, dict):
        return {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}
    if isinstance(raw, list):
        return {
            str(item.get("filterType")): dict(item)
            for item in raw
            if isinstance(item, dict) and item.get("filterType")
        }
    return {}


def _float_filter(filters: dict[str, dict[str, object]], filter_name: str, key: str) -> float | None:
    try:
        return float(filters.get(filter_name, {}).get(key))
    except (TypeError, ValueError):
        return None


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
