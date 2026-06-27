# Governance

ProofAlpha is a maintainer-led open-source project.

## Roles

### Lead maintainer

Responsible for roadmap, release approval, security response, public API policy, and execution-safety policy.

### Core maintainer

Trusted to review and merge changes in assigned areas, triage issues, and participate in releases.

### Contributor

Submits code, documentation, tests, designs, or issue analysis under the contribution rules.

## Decision process

- Routine changes require maintainer review and passing checks.
- Public API or schema changes require documented compatibility and migration impact.
- Security-sensitive changes require targeted review and fault tests.
- Changes that expand live execution authority require a separate security and risk decision.
- Governance, license, or trademark changes require a public maintainer rationale.

## Releases

- Semantic versioning is used.
- Tagged releases include changelog entries and verification evidence.
- Security fixes may use an accelerated private process before public disclosure.
- Releases must not make unsupported performance or safety claims.

## Adding maintainers

Candidates should demonstrate sustained contributions, review quality, security judgment, respectful conduct, and commitment to the repository boundary. Maintainer appointments are documented in `MAINTAINERS.md`.

## Conflicts of interest

Maintainers must disclose material relationships that could affect connector, exchange, benchmark, or strategy decisions. Paid promotion must not be presented as neutral technical evaluation.
