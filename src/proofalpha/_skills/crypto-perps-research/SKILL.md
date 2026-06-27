# crypto-perps-research

## Purpose
Encode perpetual futures market structure and stress-model vocabulary for rigorous research on funding, open interest, liquidations, and regime behavior.

## Inputs
- perp snapshot context with funding, open interest, liquidation, and price action
- regime or stress hypothesis
- validation artifacts when available

## Outputs
- perp-aware research framing
- hypothesis language grounded in perp microstructure
- warnings when a claim ignores funding, open interest, or liquidation context

## Rules
- must ground hypotheses in the interaction between price, funding, open interest, and liquidation activity
- must not treat rising open interest alone as squeeze evidence
- must preserve the engine's validation-first posture

## Forbidden
- launching runs directly
- bypassing validation gates
- editing engine code
