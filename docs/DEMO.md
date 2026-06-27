# Safe Demo

ProofAlpha's first demo is intentionally safe: no exchange credentials, no private keys, and no live orders.

The point is not to show a profitable strategy. The point is to show the evidence gate: ProofAlpha can block a weak candidate before money can move.

## Run it

```bash
python -m pip install -e .
proofalpha doctor --format json
proofalpha run --config examples/minimal_builtin_study.json --output-dir outputs/example-run
```

Expected terminal shape:

```text
{
  "dashboard_path": "outputs/example-run/example-study.dashboard.json",
  "log_path": "outputs/example-run/example-study.events.jsonl",
  "run_id": "example-study",
  "runcard_path": "outputs/example-run/example-study.runcard.json",
  "status": "blocked"
}
```

## Why `blocked` is good

A `blocked` result means the strategy did not clear one or more promotion gates. That is a successful safety outcome.

Example blocker families include:

- capacity and market-impact concerns;
- turnover budget breaches;
- insufficient out-of-sample trade count;
- scenario or regime fragility;
- validation evidence that is too weak for promotion.

ProofAlpha treats these as engineering evidence, not as a failure of the demo.

## What you get after one run

```text
outputs/example-run/example-study.events.jsonl
outputs/example-run/example-study.runcard.json
outputs/example-run/example-study.dashboard.json
```

| Artifact | Purpose |
| --- | --- |
| `*.events.jsonl` | Lightweight event trail for audit and debugging. |
| `*.runcard.json` | Decision summary, status, blockers, and review-facing evidence. |
| `*.dashboard.json` | Structured metrics and validation details for deeper inspection. |

## Inspect before running

```bash
proofalpha inspect-study --config examples/minimal_builtin_study.json
```

Use inspection when a strategy config came from another person, a notebook, an agent, or a generated file.

## Docker version

```bash
docker compose run --rm proofalpha
docker compose --profile demo run --rm demo
```

The Docker demo uses paper/no-key behavior and writes demo outputs only to temporary storage.

## Safety rule

Do not treat a single backtest, dashboard, chart, or paper run as future-return evidence. Review the data period, cost model, validation protocol, stress matrix, paper evidence, and blocked reasons before drawing conclusions.
