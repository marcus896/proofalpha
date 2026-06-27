# Reference Review: skfolio/skfolio

License: BSD 3-Clause License, from `LICENSE`.

Files inspected:

- `LICENSE`
- `README.rst`
- top-level estimator and portfolio API layout

Patterns to replicate:

- Scikit-learn-style estimator discipline.
- Portfolio cross-validation concepts.
- Stress-test API organization.

Patterns to avoid:

- Adding a dependency before review-backed need exists.
- Treating estimator outputs as approved portfolio targets.
- Ignoring perpetual-specific execution and funding risks.

Security/dependency concerns:

- Portfolio ML APIs need hard input validation and audit records.
- Cross-validation concepts must match this repo's time-series leakage rules.

Native implementation decision:

- Use as a design reference.
- Keep implementation native unless a future reviewed dependency decision proves value.
