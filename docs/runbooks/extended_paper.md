# Extended Paper Runbook

Purpose: run a 2-4 week paper period after local and cloud paper soaks pass.

Mode: paper only. This run measures operational cleanliness, not profit.

## Preflight

- [ ] Local smoke passed.
- [ ] Local soak passed.
- [ ] 72h cloud paper soak passed.
- [ ] Artifact rollback procedure tested in paper.
- [ ] Halt and repair runbook tested in paper.
- [ ] Dashboard payloads and ledger backups are reviewed.

## Run Protocol

```powershell
python -m engine.app.cli project-status
python -m engine.app.cli paper-daemon --mode paper --duration-days 28
```

## Daily Checklist

- [ ] Reconciliation status reviewed.
- [ ] Risk state and circuit breaker journal reviewed.
- [ ] Universe admissions, demotions, and quarantine reviewed.
- [ ] Model cards, shadow results, promotions, and rollbacks reviewed.
- [ ] P&L attribution reviewed for funding, fees, slippage, spread/impact, and residual alpha.
- [ ] Any safety or correctness finding recorded.

## Exit Criteria

- [ ] Every decision, rejection, fill, and state transition is explainable from artifacts.
- [ ] No live trading path used.
- [ ] No direct agent, MCP, forecast, or learning authority over execution decisions.
- [ ] No unresolved ledger or reconciliation defect.
