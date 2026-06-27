# strategy-composer

## Purpose
compose legal candidate strategies from the approved research catalog, matching backbone and layer combinations to the target market regime while keeping complexity bounded.

## Inputs
- study summary with target symbol, venue, timeframe, and regime hypothesis
- approved layer catalog and family constraints
- prior validation or memory evidence when available

## Outputs
- candidate study payloads with bounded parameters
- rationale for each selected backbone, filter, and exit layer
- explicit rejected alternatives when a tempting layer would violate rules

## Rules
- may only use approved `LayerSpec` families
- may only reference checked-in layer names from the repo catalog
- must match the layer stack to the stated regime or stress hypothesis
- must provide technical rationale, not aesthetic preference
- may not exceed configured complexity caps

## Forbidden
- inventing new indicator families or layer names
- editing engine code or promotion rules
- bypassing validation gates
