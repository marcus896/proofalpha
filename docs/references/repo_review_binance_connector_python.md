# Reference Review: binance/binance-connector-python

License: MIT License, from `LICENSE.md`.

Files inspected:

- `LICENSE.md`
- `README.md`
- top-level modular connector layout

Patterns to replicate:

- Current Binance connector package organization.
- Parameter naming examples.
- Error and response wrapper patterns.

Patterns to avoid:

- Replacing the native venue translator.
- Adding direct live exchange capability.
- Letting connector behavior override official Binance documentation.

Security/dependency concerns:

- Private endpoint support must remain disabled unless separately approved.
- Dependency updates can change behavior outside this project's audit trail.

Native implementation decision:

- Use as a connector-pattern reference only.
- Keep `engine.execution` contracts native and paper-first.
- Official Binance docs remain authoritative.
