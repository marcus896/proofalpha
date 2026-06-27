# Reference Review: microsoft/qlib

License: MIT License, from `LICENSE`.

Files inspected:

- `LICENSE`
- `README.md`
- top-level workflow, data, model, and backtest layout

Patterns to replicate:

- Clear research workflow separation.
- Model registry and experiment tracking concepts.
- Data/model/backtest/portfolio/execution boundaries.

Patterns to avoid:

- Equity-market assumptions.
- Direct dependency on Qlib abstractions.
- Letting model workflow output become execution authority.

Security/dependency concerns:

- Large dependency surface.
- Research pipeline is not tailored to Binance USD-M perpetuals.
- Forecast/model artifacts must remain research-only unless promoted through this project's gates.

Native implementation decision:

- Use for conceptual workflow separation only.
- Extend existing data, validation, memory, and forecasting modules.
- Do not import as a production dependency.
