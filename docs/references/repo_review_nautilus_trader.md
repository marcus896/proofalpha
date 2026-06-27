# Reference Review: nautechsystems/nautilus_trader

License: GNU Lesser General Public License, from `LICENSE`.

Files inspected:

- `LICENSE`
- `README.md`
- top-level actor, adapter, and execution-oriented layout

Patterns to replicate:

- Event-driven separation between strategy, execution, and venue adapters.
- Backtest/live parity discipline.
- Order lifecycle and reconciliation concepts.

Patterns to avoid:

- Replacing this engine wholesale.
- Introducing direct live trading paths.
- Copying LGPL code into this project without legal review and isolation.

Security/dependency concerns:

- Large external framework.
- License obligations require care.
- Native implementation must preserve this repo's artifact-only authority chain.

Native implementation decision:

- Replicate architectural concepts only.
- Keep implementation in existing `engine.execution`, `engine.backtest`, and `engine.portfolio` modules.
- Do not import as a production dependency.
