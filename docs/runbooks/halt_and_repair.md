# Halt And Repair Runbook

Purpose: stop exposure growth, preserve evidence, and repair paper state after HALT, LOCKDOWN, or reconciliation failure.

## Trigger Conditions

- [ ] Risk state enters `HALT`, `LOCKDOWN`, or unexpected `REDUCE_ONLY`.
- [ ] Reconciliation status is not `PASS`.
- [ ] Websocket freshness exceeds threshold.
- [ ] Missing fill, duplicate fill, orphan order, balance mismatch, or position mismatch appears.
- [ ] Circuit breaker trips.

## Immediate Actions

```powershell
python -m engine.app.cli project-status
python -m engine.app.cli paper-daemon --mode paper --halt-new-exposure
python -m engine.app.cli paper-reconcile --repair-plan
```

## Evidence Preservation

- [ ] Save ledger snapshot.
- [ ] Save reconciliation report.
- [ ] Save open order and fill state.
- [ ] Save dashboard payloads.
- [ ] Save run journal.

## Repair

- [ ] Keep open/increase blocked until reconciliation returns `PASS`.
- [ ] Allow reduce/close only if risk policy permits.
- [ ] Resolve missing fills, duplicate fills, orphan orders, balance mismatch, and position mismatch.
- [ ] Record repair action and evidence references.
- [ ] Rebuild state projection from ledger.

## Resume Criteria

- [ ] Reconciliation status is `PASS`.
- [ ] Risk state is `NORMAL`, `CAUTION`, or approved `DEFENSIVE`.
- [ ] Circuit breakers are armed and not tripped.
- [ ] Operator can explain root cause and repair evidence.
