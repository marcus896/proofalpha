# Reference Review: TauricResearch/TradingAgents

License: Apache License, from `LICENSE`.

Pinned revision:

- Tag: `v0.2.3`
- HEAD: `4641c03340c70e0e75e74234c998325164c72b36`

Files inspected:

- `LICENSE`
- `README.md`
- top-level package and example layout

Patterns to replicate:

- Report-only multi-agent debate structure.
- Separate analyst, researcher, and risk-commentary viewpoints.
- Final advisory report summarizing disagreements and risks.

Patterns to avoid:

- Any promotion authority.
- Any portfolio sizing authority.
- Any execution authority.
- Any risk-limit mutation authority.

Security/dependency concerns:

- Multi-agent outputs can sound authoritative but must stay advisory.
- Do not let debate outputs create orders, artifacts, target weights, or risk overrides.

Native implementation decision:

- Use as a report-only reference for O6-style advisory debate.
- Implement native bounded report objects under existing agent/reporting modules.
- Do not import as a production dependency.
