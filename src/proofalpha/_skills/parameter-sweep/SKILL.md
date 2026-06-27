# parameter-sweep

## Purpose
Design deterministic grids and Bayesian warm-start search plans that are mathematically bounded and compatible with the repo's parameter schemas.

## Inputs
- layer parameter definitions
- search budget and runtime constraints
- prior memory hints or blocked ranges

## Outputs
- parameter sweep plan
- bounded grid definitions or optuna warm-start candidates
- narrowing recommendations for the next iteration

## Rules
- must keep ranges compatible with declared parameter types and step sizes
- should prefer `parameter_search_mode="optuna"` for wider spaces
- must justify broad ranges and narrowing moves with evidence
- must preserve deterministic parameter semantics in emitted payloads

## Forbidden
- hallucinating unsupported parameters
- exceeding explicit budget or size caps
- editing engine code
