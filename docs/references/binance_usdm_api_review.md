# Binance USD-M API Review

Reviewed on 2026-05-07 against official Binance USD-M Futures docs. Connector repos remain reference only; venue semantics come from official docs.

## Sources

- New Order: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order
- Exchange Information: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information
- Event Order Update: https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Order-Update
- Mark Price and Funding Rate: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price
- Funding Rate History: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History
- Open Interest: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest
- Change Initial Leverage: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Change-Initial-Leverage
- Change Margin Type: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Change-Margin-Type
- Change Position Mode: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Change-Position-Mode
- Position Information: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Position-Information-V2

## Translator Requirements

- `ExchangeRulesCache` must use exchange information `status`, `contractType`, and `quoteAsset` to allow only trading USD-M perpetual symbols.
- `PRICE_FILTER` / `tickSize`, `LOT_SIZE` / `stepSize`, and `MIN_NOTIONAL` are the source of truth for price, quantity, and notional checks.
- Binance warns that precision fields are not tick/step substitutes, so translator logic must not derive tick size from `pricePrecision` or step size from `quantityPrecision`.
- Supported order types and time-in-force values come from exchange information. Current review includes `LIMIT`, `MARKET`, stop/take-profit variants, trailing-stop market, and `GTC`, `IOC`, `FOK`, `GTX`.
- GTX is the post-only time-in-force path. IOC and FOK must stay explicit tactic outputs.
- `positionSide` defaults to `BOTH` in one-way mode and is required as `LONG` or `SHORT` in hedge mode.
- `reduceOnly` cannot be sent in hedge mode. `closePosition` must stay separate from reduce-only quantity orders.
- `workingType` values include `MARK_PRICE` and `CONTRACT_PRICE`.
- `priceProtect`, `priceMatch`, `selfTradePreventionMode`, and `goodTillDate` are supported fields and must be rejected or passed only when the translator explicitly supports them.
- `newClientOrderId` must be unique among open orders and must match the documented length/character rule.
- Signed trade endpoints require `timestamp`; `recvWindow` is optional but should be bounded by config.
- User-data order updates use `ORDER_TRADE_UPDATE`; order events include execution type, order status, client order ID, side, order type, time in force, quantities, prices, and working type.
- Account and position update events are separate user-data stream events and must feed reconciliation rather than direct trading authority.
- Rate-limit accounting must respect order-count and request-weight headers.
- Leverage, margin type, and position mode endpoints are configuration/risk state operations, not agent tools.
- Error-code normalization belongs in `engine.execution.binance_errors`.

## Enforcement

- Paper translator remains live-disabled.
- No connector repo can override this review.
- Live private API work remains blocked until explicit user approval and key-permission evidence exist.
