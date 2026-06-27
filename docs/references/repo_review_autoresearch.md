# Reference Review: karpathy/autoresearch

License: no license file found in cloned repository. Treat as all-rights-reserved for code copying unless a valid license is later found.

Files inspected:

- `README.md`
- `program.md`
- `prepare.py`
- `train.py`
- `pyproject.toml`

Patterns to replicate:

- Fixed-budget experiment loops.
- Explicit metric-driven keep/discard decisions.
- Human-authored program context as the agent boundary.
- Short experiment logs that explain why a change survived or failed.

Patterns to avoid:

- Agent-edited production execution code.
- Self-modifying research loops without hard validation gates.
- GPU-training assumptions in the local trading engine path.

Security/dependency concerns:

- No license file means no code copying.
- Training workflow dependencies are not needed by this project.
- Agent autonomy must not cross into artifact promotion, portfolio sizing, risk limits, or execution.

Native implementation decision:

- Replicate only the bounded loop discipline conceptually in existing `engine.agent` and autoresearch surfaces.
- Do not import this repo or copy source code.
