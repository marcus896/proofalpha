# Contributing to ProofAlpha

Thank you for helping improve reproducible strategy research and paper-execution infrastructure.

## Before contributing

Read:

1. `AGENTS.md`
2. `README.md`
3. `docs/ARCHITECTURE.md`
4. `docs/OPEN_SOURCE_BOUNDARY.md`
5. `docs/SECURITY_MODEL.md`

Work only inside this repository. Do not contribute credentials, private account data, proprietary datasets, or code with unclear provenance.

## Good contribution areas

High-value contributions improve:

- correctness and reproducibility;
- test coverage and edge-case handling;
- data quality and leakage detection;
- accounting and execution-cost realism;
- chronological validation and stress testing;
- paper-execution safety and reconciliation;
- risk controls and operational guards;
- documentation and onboarding;
- plugin and schema compatibility;
- privacy and security.

Unverifiable performance screenshots and promotional signal content are not accepted as technical evidence.

## Development flow

1. Open or choose an issue with a clear acceptance condition.
2. Keep the change narrow and reviewable.
3. Add or update tests.
4. Update documentation for public behavior.
5. Run the required checks.
6. Explain compatibility, safety, and license impact in the pull request.

## Required checks

For changes that affect shared code or packaging, run:

```bash
python -m unittest discover -s tests -q
python -m compileall -q src tests scripts
python -m ruff check src --select F821,F811
python scripts/check_repository_secrets.py
python scripts/verify_public_export.py --root .
python -m pip_audit -r requirements-core.txt
proofalpha doctor --format json
python -m build
```

Pyright still reports legacy annotation debt. Do not describe the project as fully type-clean until that work is completed.

## Pull request contents

A pull request should explain:

- the user or maintainer problem;
- the implementation approach;
- tests and commands run;
- public API or schema impact;
- security and execution-safety impact;
- documentation changes;
- dependencies added and their licenses;
- migration steps for breaking changes.

## Strategy examples

Example strategies exist to exercise the infrastructure, not to recommend trades. Examples must:

- state their educational or testing purpose;
- use public, synthetic, or redistributable data;
- include realistic costs;
- avoid future-return claims;
- use paper or research mode by default.

## Dependencies

Before adding a dependency:

- explain why the standard library or an existing dependency is insufficient;
- declare a compatible version range;
- record purpose and license in `THIRD_PARTY_NOTICES.md`;
- consider supply-chain and maintenance risk;
- include it in vulnerability auditing.

## Security reports

Do not open a public issue for an exploitable vulnerability. Follow `SECURITY.md`.

## Contributor certification

By submitting a contribution, you confirm that you have the right to contribute it under the project license and that its provenance is accurately described.
