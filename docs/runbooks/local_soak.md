# Local Soak Runbook

Purpose: run paper execution locally for 8-12h after local smoke passes.

Mode: local only, paper only, live trading disabled.

## Preflight

- [ ] Local smoke completed without unresolved reconciliation, websocket, risk, or artifact authority failures.
- [ ] Promotion and rollback manifests are present.
- [ ] Universe manifest and exposure caps are reviewed.
- [ ] Circuit breakers are armed.
- [ ] No private live keys are loaded.
- [ ] SecretsGuard confirms no live private keys on the paper host.
- [ ] ModeGuard confirms live mode is disabled.
- [ ] ConfigDiff is recorded since the previous run.
- [ ] KillSwitch is tested before start.
- [ ] ProfilePermissions are loaded.
- [ ] AgentToolPolicy denies trade, risk, mode-mutation, and direct-promotion tools.

## Start

```powershell
python -m engine.app.cli project-status
python -m engine.app.cli paper-daemon --mode paper --symbols BTCUSDT ETHUSDT --duration-hours 12
```

## Observe

- [ ] Websocket freshness remains inside configured threshold.
- [ ] Reconciliation status is `PASS` or enters repair without new open exposure.
- [ ] Risk state transitions are journaled.
- [ ] Circuit breaker transitions are journaled.
- [ ] Portfolio deltas remain explainable from target portfolio and current state.
- [ ] P&L attribution includes beta, symbol selection, timing, funding, fees, slippage, spread/impact, rebalance cost, and residual alpha.
- [ ] Learning dashboard records shadow results only; it does not mutate execution policy directly.

## Pass Criteria

- [ ] No live trading path used.
- [ ] No direct model, agent, MCP, or forecast buy/sell/size authority observed.
- [ ] No unresolved orphan orders, missing fills, duplicate fills, balance mismatch, or position mismatch.
- [ ] Run journal can explain every decision, rejection, fill, and state transition.

## Stop

- [ ] Stop paper daemon.
- [ ] Save ledger, reconciliation report, TCA report, dashboard payloads, and journal.
- [ ] Record safety or correctness findings in `docs/implementation/findings.md`.
