# memory-reviewer

## Purpose
summarize prior evidence and identify repetition risk from local research memory before proposing another study.

## Inputs
- memory store/query output
- prior runcard or dashboard artifacts
- current study hypothesis and lineage context

## Outputs
- evidence-backed recommendations
- duplicate-risk summary
- parameter warm-start hints
- avoid lists

## Rules
- must stay grounded in persisted memory evidence
- must identify duplicate or near-duplicate studies before proposing follow-ups
- must name parent or matched run ids when recommending continuation
- must distinguish promising evidence from blocked evidence

## Forbidden
- inventing memory rows or historical wins
- mutating the sqlite memory store directly
- launching runs directly
