# Security Model

ProofAlpha processes untrusted market data, strategy code, model output, imported artifacts, and optional execution connectors. Security and trading safety are part of system correctness.

## Protected assets

- credentials and connector permissions;
- account, portfolio, and order state;
- execution authority;
- research and evidence integrity;
- audit history;
- user privacy;
- package and release integrity.

## Execution safety

Public examples and documented quickstarts use paper and no-key paths. Live-capable connector code, where present, does not grant itself authority: execution mode, credential scope, symbol scope, order types, exposure, loss limits, data freshness, and kill-switch state remain explicit operational controls.

Safety expectations:

- no live credentials in examples, tests, logs, reports, or bundles;
- least-privilege API permissions;
- withdrawal permission rejected;
- visible execution mode;
- stale required streams block new intents;
- duplicate-order prevention and reconciliation across retry and restart;
- deterministic client identifiers where supported;
- cancel-all and kill-switch support;
- fail-closed handling for missing policy or unhealthy state.

## Untrusted model and strategy output

Natural-language and model output is data, not authority. It may propose specifications or experiments, but must not silently change:

- execution mode;
- credentials;
- symbol or venue scope;
- risk limits;
- experiment budgets;
- trusted validation policy.

Third-party strategies and plugins execute code and must be reviewed before use. Imported bundles must not auto-execute embedded code.

## Data integrity

Controls include:

- source and checksum manifests;
- schema and timestamp validation;
- duplicate, missing, out-of-order, leading, internal, and terminal gap checks;
- sequence continuity where available;
- stale-data thresholds;
- point-in-time and leakage controls;
- provenance and quality evidence.

## File and web safety

- avoid executable serialization for public artifacts;
- normalize archive paths and limit extracted size and file count;
- verify checksums before import;
- use relative paths in exported artifacts;
- serve dashboard assets from an allowlist;
- bind local services to localhost by default;
- use read-only database access for read-only dashboard paths;
- apply input limits and browser security headers.

## Supply-chain controls

- minimal core dependencies;
- declared compatible version ranges;
- vulnerability and license audits;
- automated dependency updates;
- protected CI release workflow;
- package build verification;
- release checksums and SBOM where supported;
- no generated databases, credentials, build output, or local environments in source releases.

## Performance integrity

Every result should identify:

- data source and period;
- strategy and configuration identity;
- fees, funding, slippage, latency, and fill assumptions;
- validation protocol;
- whether results are historical, simulated, paper, or live;
- known limitations.

Backtests and paper runs are not guarantees of future performance.

## Required release checks

- full unit and integration suite;
- Python compilation;
- targeted static checks;
- release doctor;
- safe no-key example;
- secret and absolute-path scan;
- dependency vulnerability audit;
- package build and installation checks;
- export-manifest and source-hash verification;
- dashboard and file-boundary tests.

## Vulnerability disclosure

Do not report exploitable vulnerabilities in a public issue. Follow `SECURITY.md` and use the repository's private vulnerability-reporting channel when enabled.
