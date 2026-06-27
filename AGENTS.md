# ProofAlpha Agent Contract

## Scope

Work only inside this repository. Do not inspect sibling projects, local credentials, account data, generated trading outputs, or unrelated files.

## Product defaults

- Paper and no-key modes are the public defaults.
- Live execution is not approved by default.
- Do not widen risk limits or bypass validation to make a demo pass.
- Do not advertise guaranteed profits, passive income, win rates, or backtests as evidence of future returns.
- Label performance evidence as historical, simulated, paper, or live and include costs and limitations.

## Engineering rules

- Preserve the internal `engine` package name unless a tested major-version migration justifies changing it.
- Extend existing modules before creating parallel implementations.
- Treat strategies, plugins, model output, external data, and imported artifacts as untrusted.
- Do not use unsafe serialization or auto-execute imported bundle code.
- Keep dashboard access read-only and static-file serving allowlisted.
- Keep Python support at `>=3.12,<3.14` until the test matrix changes.
- Update package metadata, requirements, notices, and audits together when dependencies change.

## Verification

Before claiming completion, run the checks relevant to the change. Multi-module and release changes require:

```text
python -m unittest discover -s tests -q
python -m compileall -q src tests scripts
python -m ruff check src --select F821,F811
python scripts/check_repository_secrets.py
python scripts/verify_public_export.py --root .
python -m pip_audit -r requirements-core.txt
proofalpha doctor --format json
python -m build
```

Pyright currently reports legacy annotation debt. Do not claim full type cleanliness until it is separately resolved.

## Documentation

README and user documentation must describe current behavior only. Planned work must be clearly labeled. Security, financial-risk, and execution limitations must remain visible.
