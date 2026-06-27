# Quickstart

This guide gets ProofAlpha running in paper/no-key mode. It does not require exchange credentials and does not submit live orders.

## Requirements

- Python 3.12 or 3.13.
- Optional: Docker, for the container demo.

## Install from a checkout

```bash
python -m pip install -e .
proofalpha doctor --format json
```

`doctor` verifies package metadata, example loading, schema freshness, the supported Python runtime, and core runtime dependencies.

## Run the safe built-in study

```bash
proofalpha run \
  --config examples/minimal_builtin_study.json \
  --output-dir outputs/example-run
```

This writes:

```text
outputs/example-run/example-study.events.jsonl
outputs/example-run/example-study.runcard.json
outputs/example-run/example-study.dashboard.json
```

A blocked result is not a demo failure. It means ProofAlpha found evidence that the strategy should not be promoted.

## Inspect before running

```bash
proofalpha inspect-study --config examples/minimal_builtin_study.json
```

Use inspection when reviewing a study from another person or from an agent. Study configs, strategy payloads, imported artifacts, and model output are untrusted input.

## Run bounded autoresearch

```bash
proofalpha autoresearch \
  --config examples/minimal_builtin_study.json \
  --output-dir outputs/autoresearch \
  --db outputs/research-memory.sqlite
```

Autoresearch uses explicit budgets and local memory. Generated follow-up suggestions remain subject to validation gates.

## Run the strict operator loop

```bash
proofalpha operate-loop \
  --config examples/minimal_builtin_study.json \
  --output-dir outputs/operator-loop \
  --db outputs/operator-memory.sqlite \
  --profile strict_v3
```

Use this for guarded research iterations. It is paper/no-key by default and does not grant live trading authority.

## Docker demo

```bash
docker compose run --rm proofalpha
docker compose --profile demo run --rm demo
```

The container runs as a non-root user, uses read-only filesystem settings, and writes demo outputs only to temporary storage.

## Troubleshooting

### `python` resolves to an unsupported version

ProofAlpha supports Python 3.12 and 3.13. On Windows, use the Python launcher explicitly:

```powershell
py -3.12 -m pip install -e .
py -3.12 -m engine.app.cli doctor --format json
```

### `ruff`, `build`, or `pip-audit` is missing

Install developer tools:

```bash
python -m pip install -e .[dev]
```

### A run writes generated files into the checkout

Generated outputs are ignored by Git. Before publishing, verify the export boundary:

```bash
python scripts/verify_public_export.py --root .
python scripts/check_repository_secrets.py
```

### A strategy looks profitable in one artifact

Do not treat one artifact as future-return evidence. Check costs, data period, validation protocol, stress tests, paper evidence, and blocked reasons before drawing conclusions.
