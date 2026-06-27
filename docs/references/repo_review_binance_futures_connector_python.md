# Reference Review: binance/binance-futures-connector-python

License: MIT License, from `LICENSE.md`.

Files inspected:

- `LICENSE.md`
- `README.md`
- top-level futures connector examples and package layout

Patterns to replicate:

- USD-M endpoint naming examples.
- Request parameter naming examples.
- Basic connector error-handling shape.

Patterns to avoid:

- Blind wrapping.
- Treating connector examples as authority over official docs.
- Enabling private endpoints in this project.

Security/dependency concerns:

- Connector may be deprecated or drift from current API docs.
- Private API examples must not become runnable live code by default.

Native implementation decision:

- Use only as a historical Binance USD-M reference.
- Implement venue translation natively from official docs and fixture tests.
- Do not import as a production dependency.
