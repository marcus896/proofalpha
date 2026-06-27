# Reference Review: questdb/questdb

License: Apache License, from `LICENSE.txt`.

Files inspected:

- `LICENSE.txt`
- `README.md`
- top-level ingestion and database project layout

Patterns to replicate:

- High-volume time-series storage concepts.
- Append-oriented ingestion discipline.
- Future scale-path ideas for market data and execution telemetry.

Patterns to avoid:

- Making QuestDB a required current dependency.
- Replacing the existing SQLite/local artifact path before a proven scale need.
- Moving implementation-roadmap state into experiment memory or telemetry stores.

Security/dependency concerns:

- Large database server dependency.
- Operational complexity exceeds the current paper-first roadmap.

Native implementation decision:

- Keep as optional future scale reference.
- Continue using existing local storage and SQLite boundaries unless a later phase proves a need.
