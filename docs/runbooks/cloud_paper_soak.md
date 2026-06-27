# Cloud Paper Soak Runbook

Purpose: run a 72h Oracle/VPS paper soak after local smoke and local soak pass.

Cloud deployment rule: research and promotion stay local. Only the paper executor daemon, public websocket ingestion, ledger, and reconciliation may run on cloud after local passes.

## Hard Blocks

- [ ] No live keys on the cloud host.
- [ ] Live trading remains disabled.
- [ ] No withdrawal permission exists anywhere in the workflow.
- [ ] No research, promotion, model approval, or risk-limit mutation runs on cloud.
- [ ] No agent or MCP tool can place orders, promote artifacts directly, change risk limits, edit venue translators, disable circuit breakers, or enable live mode.

## Preflight

- [ ] Local smoke passed.
- [ ] Local soak passed.
- [ ] Paper executor config is paper-only.
- [ ] Public websocket endpoints are configured.
- [ ] Ledger output path and backup path are configured.
- [ ] Reconciliation runs on a fixed schedule.
- [ ] Kill switch and halt procedure are reachable.
- [ ] SecretsGuard confirms no live private keys on the paper host.
- [ ] ModeGuard confirms live mode is disabled.
- [ ] ConfigDiff is recorded since the previous run.
- [ ] KillSwitch is tested before start.
- [ ] ProfilePermissions are loaded.
- [ ] AgentToolPolicy denies trade, risk, mode-mutation, and direct-promotion tools.

## Start

```powershell
python -m engine.app.cli project-status
python -m engine.app.cli paper-daemon --mode paper --cloud-profile oracle-vps --duration-hours 72
```

## Observe

- [ ] Paper executor daemon is healthy.
- [ ] Websocket freshness remains inside threshold.
- [ ] Ledger writes order, fill, funding, and risk events.
- [ ] Reconciliation blocks new exposure when status is not `PASS`.
- [ ] Dashboards show execution, risk, reconciliation, learning, universe, autoresearch, and journal state.
- [ ] No private live endpoint or live order path is called.

## Pass Criteria

- [ ] 72h completes with no unresolved safety failure.
- [ ] All repair events are journaled.
- [ ] P&L attribution and TCA are generated.
- [ ] Cloud logs prove paper-only operation.
