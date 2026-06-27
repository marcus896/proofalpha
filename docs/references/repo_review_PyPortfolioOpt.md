# Reference Review: PyPortfolio/PyPortfolioOpt

License: MIT License, from `LICENSE`.

Files inspected:

- `LICENSE`
- `README.md`
- top-level optimization package layout

Patterns to replicate:

- Mean-variance optimization concepts.
- Black-Litterman and shrinkage ideas.
- Clear optimizer input/output contracts.

Patterns to avoid:

- Direct perp allocation authority.
- Long-only or equity-default assumptions without validation.
- Optimizer output bypassing risk vetoes.

Security/dependency concerns:

- Portfolio optimizer output can be unsafe if used as direct target authority.
- Needs adaptation to leverage, funding, liquidation, and concentration limits.

Native implementation decision:

- Replicate concepts only after tests.
- Keep portfolio target and delta contracts native under `engine.portfolio`.
- Optimizer outputs remain gated by artifacts and risk policy.
