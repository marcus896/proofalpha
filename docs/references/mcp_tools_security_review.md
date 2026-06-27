# MCP Tools Security Review

Reviewed on 2026-05-07 against the official MCP tools specification.

Source: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

## Protocol Notes

- MCP tools are model-controlled: the model can discover and invoke exposed tools through the client/server protocol.
- Servers advertise tool support through the `tools` capability.
- `tools/list` discovers available tools and supports pagination.
- Each listed tool needs a name, description/title metadata, and an `inputSchema`.
- `tools/call` invokes a named tool with arguments and returns tool output or an error.
- The spec recommends a human in the loop for trust and safety; this project treats that as mandatory for promotion, model-promotion, and any authority-changing request.

## Project Controls

- Profile gating decides which tools appear before the model sees them.
- Forbidden tool list (forbidden tool list):
  - `place_order`
  - `submit_order`
  - `set_leverage`
  - `change_margin_mode`
  - `change_position_mode`
  - `promote_artifact_direct`
  - `approve_symbol_direct`
  - `disable_circuit_breaker`
  - `enable_live`
- Input validation must reject payload fields that imply order placement, leverage, margin mode, live mode, direct artifact promotion, symbol approval, or circuit-breaker disablement.
- Output schemas must not smuggle order requests or live-execution credentials.
- Every model-visible tool invocation should be audit logged with profile, tool name, input hash, output hash, decision, and reason.
- Kill switch state must block model-controlled tool calls when engaged.

## Enforcement

- MCP profiles expose only high-level research, validation, artifact listing, and reporting tools.
- Human approval is required for requests to promote artifacts or models; direct promotion is never exposed.
- No live-trade tools are exposed under any profile.
