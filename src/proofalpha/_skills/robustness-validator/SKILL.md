# robustness-validator

## Purpose
Interpret the repo's quantitative validation protocol and turn statistical evidence into clear fragility or robustness guidance.

## Inputs
- runcard or dashboard validation artifacts
- stress scenario results
- bootstrap, permutation, PBO, DSR, and SPA outputs when present

## Outputs
- validation diagnosis
- evidence-backed next-study recommendations
- explicit naming of failed gates and likely causes

## Rules
- must treat validation metrics and stress evidence as authoritative
- must separate blocked, wash, and promoted outcomes cleanly
- should recommend lower-dimensional or better-filtered follow-ups when overfit risk is high
- must cite artifact evidence, not gut feel

## Forbidden
- overriding blocked outcomes
- relabeling failed runs as promoted
- changing promotion rules
