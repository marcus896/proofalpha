# Local Smoke Runbook

Purpose: prove clean, replayable, auditable paper execution for 2-4h before any longer soak.

Mode: local only, paper only, live trading disabled.

## Preflight

- [ ] Confirm `PLAN_STATUS.json` shows strict v3 agent-operability tasks ready or done.
- [ ] Confirm artifact promotion manifest exists and is paper eligible.
- [ ] Confirm universe manifest allows only intended symbols.
- [ ] Confirm no private live keys are loaded.
- [ ] SecretsGuard confirms no live private keys on the paper host.
- [ ] ModeGuard confirms live mode is disabled.
- [ ] ConfigDiff is recorded since the previous run.
- [ ] KillSwitch is tested before start.
- [ ] ProfilePermissions are loaded.
- [ ] AgentToolPolicy denies trade, risk, mode-mutation, and direct-promotion tools.
- [ ] Confirm risk state starts at `NORMAL` or `CAUTION`, never `HALT`.
- [ ] Confirm reconciliation baseline is `PASS`.

## Start

```powershell
python -m engine.app.cli project-status
python -m unittest tests.app.test_project_status -v
python -m engine.app.cli paper-daemon --mode paper --symbols BTCUSDT ETHUSDT --duration-hours 4
```

## Observe

- [ ] Execution dashboard shows pending intents, translated orders, client order IDs, fills, fees, funding, websocket freshness, reconciliation status, risk state, and circuit breakers.
- [ ] Portfolio dashboard shows target weights, current weights, deltas, exposure, beta, turnover, and funding budget.
- [ ] Risk dashboard shows approvals, rejections, funding guard, liquidation guard, margin/leverage, and circuit breaker state.
- [ ] Every rejection has a human-readable reason.
- [ ] Every fill links back to client order ID and artifact authority.

## Pass Criteria

- [ ] No live order path used.
- [ ] No unmanifested symbol accepted.
- [ ] No reconciliation failure persists past one repair cycle.
- [ ] No missing fills, duplicate fills, or orphan orders remain unresolved.
- [ ] Run artifacts are replayable from ledger and dashboard payloads.

## Stop

- [ ] Stop paper daemon.
- [ ] Save ledger, dashboard payloads, and run journal.
- [ ] Record any safety or correctness finding in `docs/implementation/findings.md`.
