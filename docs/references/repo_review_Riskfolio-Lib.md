# Reference Review: dcajasn/Riskfolio-Lib

License: BSD-style license, from `LICENSE.txt`.

Files inspected:

- `LICENSE.txt`
- `README.md`
- top-level risk portfolio package layout

Patterns to replicate:

- Risk parity concepts.
- CVaR-aware allocation ideas.
- Drawdown-aware portfolio constraints.

Patterns to avoid:

- Direct live optimizer authority.
- Blind use of historical covariance estimates for leveraged perpetuals.
- Bypassing liquidation, funding, and turnover controls.

Security/dependency concerns:

- Risk optimizer assumptions must be tested against crypto perpetual stress scenarios.
- Native risk vetoes must remain stronger than allocation suggestions.

Native implementation decision:

- Use as a conceptual reference for portfolio risk methods.
- Implement native risk-budget checks with targeted tests.
- Do not import as a production dependency.
