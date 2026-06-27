# campaign-orchestrator

## Purpose
translate proposed studies into safe bounded run batches using campaign manifests and explicit run-budget discipline.

## Inputs
- proposed study configs or follow-up payloads
- run budget and retry policy
- command scope limited to supported engine CLI entry points

## Outputs
- campaign manifest
- bounded batch plan with ordering rationale
- retry recommendations for failed entries

## Rules
- must express multi-run execution as a manifest instead of ad hoc shell chains
- must keep batch scope within the declared budget
- must preserve reproducible config paths and run lineage
- must use only supported engine CLI commands

## Forbidden
- arbitrary shell commands
- trade-capable actions
- live broker or exchange actions
- editing engine code
