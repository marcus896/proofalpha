# ProofAlpha Architecture

ProofAlpha separates research authority from execution authority. Strategy ideas can produce experiments and paper evidence, but they cannot silently grant themselves live execution permission.

## System flow

```text
Study configuration or strategy thesis
    |
    v
Configuration and schema validation
    |
    v
Data snapshots, provenance, and quality checks
    |
    v
Feature generation and leakage controls
    |
    v
Strategy candidates and bounded search
    |
    v
Backtest with fees, funding, slippage, latency, and fills
    |
    v
Walk-forward, stress, overfit, and promotion validation
    |
    +--> reject or insufficient evidence
    |
    v
Paper execution, reconciliation, health, and TCA
    |
    v
Evidence cards, dashboards, and audit artifacts
    |
    v
Explicit risk gate for any separately configured execution connector
```

## Package layout

```text
src/proofalpha/     Public brand and version helpers
src/engine/app/     CLI, workflows, operator loops, and application services
src/engine/config/  Study and runtime configuration contracts
src/engine/data/    Ingestion, providers, snapshots, storage, and quality
src/engine/features/Feature contracts and leakage controls
src/engine/strategy/Strategy DSL, catalog, lifecycle, and artifacts
src/engine/backtest/Simulation, accounting, fills, and execution costs
src/engine/validation/Walk-forward, robustness, stress, and promotion gates
src/engine/optimizer/Bounded search and experiment budgets
src/engine/agent/   Research actions and orchestration
src/engine/memory/  Event history, decision journal, and research memory
src/engine/execution/Paper sessions, market streams, reconciliation, and TCA
src/engine/portfolio/Allocation, exposure, and rebalancing
src/engine/ops/     Operational guards, modes, and kill-switch support
src/engine/reporting/Evidence reports, comparisons, and dashboard artifacts
src/engine/forecasting/Forecasting adapters
src/engine/learning/Model and learning governance
src/engine/mcp/     Optional MCP integration
```

The distribution and console command are named `proofalpha`. The internal package remains `engine` to preserve tested imports and avoid a branding-only breaking refactor.

## Trust boundaries

Treat these as untrusted:

- strategy and plugin code;
- model-generated content;
- external market data;
- imported artifacts and bundles;
- exchange responses;
- dashboard and CLI input.

Trusted policy includes:

- versioned schemas;
- chronological data access rules;
- validation thresholds;
- experiment budgets;
- risk limits;
- execution-mode configuration;
- artifact hashes and audit records.

Model or agent output may propose work, but it must not silently modify trusted policy.

## Storage and evidence

The system uses explicit schemas, UTC timestamps, checksums, and atomic artifact writes. SQLite is used for structured metadata and event records; DuckDB and columnar storage support larger research datasets. Public artifacts must not contain credentials or private absolute paths.

Every reported result should identify:

- data source and period;
- strategy and configuration identity;
- transaction-cost assumptions;
- validation protocol;
- whether the result is historical, simulated, paper, or live;
- known limitations.

## Execution modes

```text
research   Build and evaluate evidence without order simulation
backtest   Historical order and portfolio simulation
paper      Simulated execution against replayed or public market events
live       Separate connector path requiring explicit operational approval
```

Paper mode is the public default. Live execution is not enabled merely because a strategy passes research validation.

## Public API stability

- Study and artifact schemas are versioned.
- Plugin contracts must declare compatibility.
- Breaking changes require migration notes and semantic-versioning review.
- Experimental interfaces must be labeled before publication.
