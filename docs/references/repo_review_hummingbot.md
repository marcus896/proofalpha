# Reference Review: hummingbot/hummingbot

License: Apache License, from `LICENSE`.

Files inspected:

- `LICENSE`
- `README.md`
- top-level connector and strategy layout

Patterns to replicate:

- Client order ID discipline.
- In-flight order state tracking.
- Order lifecycle event handling.
- User stream reconciliation concepts.

Patterns to avoid:

- Copying strategy logic.
- Treating connector behavior as final Binance USD-M semantics.
- Adding live connector dependencies.

Security/dependency concerns:

- Broad exchange-connector scope exceeds this project.
- Connector examples can drift from current official Binance docs.
- Live endpoint behavior must stay disabled without explicit approval.

Native implementation decision:

- Use as an OMS and lifecycle reference.
- Implement native `engine.execution` contracts and tests.
- Official Binance docs remain the source of truth for venue semantics.
