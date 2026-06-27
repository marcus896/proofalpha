# Safe Demo

This demo shows ProofAlpha's research loop in action — safely. No exchange credentials, no private keys, no live orders. You get to see the agent generate, backtest, and judge a strategy candidate end to end.

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

## Try the full loop

```bash
proofalpha autoresearch \
  --config examples/minimal_builtin_study.json \
  --output-dir outputs/autoresearch \
  --db outputs/research-memory.sqlite
```

This is where ProofAlpha shines: it generates variations, backtests each one, remembers what it learned, and keeps refining — turning one idea into many tested improvements.

## Reading the result

A `blocked` status means a candidate didn't clear the promotion bar — and that's a feature. The system tells you *why*, so the next iteration can be better. Common reasons include:

- capacity or market-impact limits;
- turnover beyond budget;
- not enough out-of-sample evidence;
- fragility across scenarios or regimes.

ProofAlpha treats these as useful signal, not failure — it's how you avoid acting on a strategy that only looked good by luck.

## What you get after one run

```text
outputs/example-run/example-study.events.jsonl
outputs/example-run/example-study.runcard.json
outputs/example-run/example-study.dashboard.json
```

| Artifact | Purpose |
| --- | --- |
| `*.events.jsonl` | Line-by-line trail of what the agent did. |
| `*.runcard.json` | The keep/improve decision, with reasons and evidence. |
| `*.dashboard.json` | Structured metrics and validation details. |

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

## A note on reading results

Treat a single backtest, dashboard, or paper run as a starting point, not a verdict. The whole reason the loop validates across costs, time, and stress is so your conclusions rest on evidence rather than a single lucky chart.
