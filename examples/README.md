# Examples

This directory is for runnable study inputs and schema references for ProofAlpha.

Bootstrap validation now keeps funding, open interest, and liquidation sidecars aligned with the resampled candle path by using the same moving-block indices for every series.

Saved `RunCard` and dashboard artifacts now also include the effective runtime settings, so venue-derived execution defaults are visible in the evidence trail even when they were not spelled out in the original study file.
`summarize-run` now prints those effective runtime settings too, so you can inspect them from the terminal without opening the raw dashboard JSON.

## Generate an Example Study from CSV

```powershell
python -m engine.app.cli init-example `
  --csv data\\solusdt_1h.csv `
  --config-out examples\\solusdt_builtin_study.json `
  --snapshot-id solusdt-1h `
  --symbol SOLUSDT `
  --venue binance `
  --timeframe 1h
```

The CSV loaders accept common export aliases too, so exchange files using headers like `open_time`, `Open`, `High`, `Low`, `Close`, `Volume`, `fundingRate`, `openInterest`, `oi`, `liquidation`, or `liquidations` can be used without manual column renaming. Header spacing/casing like ` Timestamp ` and formatted numeric values like `1,234.5` are also supported, and optional market fields accept null-like values such as `N/A`, `null`, and `--` without crashing while recording `invalid_*_count` quality flags. Optional sidecars with bad timestamps are skipped and recorded via `invalid_*_timestamp_count` flags. Timestamp fields can be ISO strings, naive datetimes treated as UTC, Unix epoch seconds, Unix epoch milliseconds, or float-style epoch exports like `1704067200.0`.

Required candle fields remain strict. If a candle timestamp or OHLCV value is invalid, the loader now raises a row-aware error that points to the exact row and field that failed.

## Run a Study

```powershell
python -m engine.app.cli run `
  --config examples\\solusdt_builtin_study.json `
  --output-dir outputs\\solusdt_run
```

If a study carries snapshot `quality_flags` and you want to fail fast instead of proceeding, add `--strict-quality`:

```powershell
python -m engine.app.cli run `
  --config examples\\solusdt_builtin_study.json `
  --output-dir outputs\\solusdt_run `
  --strict-quality
```

## Summarize a Completed Run

```powershell
python -m engine.app.cli summarize-run `
  --dashboard outputs\\solusdt_run\\example-study.dashboard.json
```

```powershell
python -m engine.app.cli summarize-autoresearch `
  --autoresearch-report outputs\\autoresearch_run\\example-study.autoresearch.json
```

```powershell
python -m engine.app.cli compare-duplicate-match `
  --autoresearch-report outputs\\autoresearch_run\\example-study.autoresearch.json `
  --config examples\\minimal_builtin_study.json `
  --db outputs\\research-memory.sqlite
```

```powershell
python -m engine.app.cli accept-duplicate-match `
  --autoresearch-report outputs\\autoresearch_run\\example-study.autoresearch.json `
  --config examples\\minimal_builtin_study.json `
  --db outputs\\research-memory.sqlite `
  --output-config outputs\\example-study.accepted-duplicate.json
```

```powershell
python -m engine.app.cli continue-accepted-duplicate `
  --autoresearch-report outputs\\autoresearch_run\\example-study.autoresearch.json `
  --output-dir outputs\\next_cycle `
  --db outputs\\research-memory.sqlite
```

When duplicate-baseline history exists in the batch report, `select-batch-variant` now also returns the chosen variant’s top successful and avoided resolved scenario profiles in its JSON output, so the selection step carries the same stress-shape rationale as the batch summary.
It now also returns `selected_top_runtime_profile` when that chosen history includes a promoted runtime-profile hint.
That JSON output now also includes `selected_duplicate_baseline_score`, so automation can rank or threshold the chosen history strength directly.
It now also includes `selected_duplicate_baseline_delta_vs_preferred`, so automation can compare the selected history against the preferred batch baseline numerically.

When duplicate-baseline history exists in the selected variant result, `continue-batch` now also returns those top successful and avoided resolved scenario profiles in its JSON output, so the kickoff payload carries the same stress-shape rationale as the selection step.
It now also returns `selected_top_runtime_profile` when the selected history includes a promoted runtime-profile hint.
It now also returns `selected_duplicate_baseline_score` for the selected variant.
It now also returns `selected_duplicate_baseline_delta_vs_preferred` for the selected variant when a preferred batch baseline exists.

When duplicate-baseline history exists for the recovered baseline, `continue-accepted-duplicate` now also returns those top successful and avoided resolved scenario profiles in its JSON output, so this kickoff path carries the same stress-shape rationale as the other continuation flows.
It now also returns `selected_duplicate_baseline_score` for that recovered baseline history.

Run artifacts and dashboards now carry snapshot quality provenance, so a study can proceed with warnings while still recording whether it was built from clean or dirty bundled data.

## Export the Study Schema

```powershell
python -m engine.app.cli export-schema --output examples\\study.schema.json
```

## Summarize Research Memory

```powershell
python -m engine.app.cli summarize-memory `
  --db outputs\\research-memory.sqlite `
  --symbol SOLUSDT `
  --memory-quality-policy clean-only
```

## Inspect a Campaign Manifest

```powershell
python -m engine.app.cli inspect-campaign `
  --manifest examples\\minimal_campaign.json
```

## Retry a Saved Campaign

```powershell
python -m engine.app.cli retry-campaign `
  --campaign-report outputs\\minimal-campaign.campaign.json `
  --output-report outputs\\minimal-campaign-retry.campaign.json `
  --entry-status failed
```

## Refresh Checked-In Example Artifacts

```powershell
python -m engine.app.cli refresh-examples --dir examples
```

## Release Doctor

```powershell
python -m engine.app.cli doctor
```

## Notes

- `runtime.mode = builtin` lets the engine compute evaluations and scenario results at runtime.
- `runtime.mode = fixture` keeps support for fully precomputed studies.
- `runtime.fail_on_quality_flags = true` can enforce the same preflight policy from inside the study file.
- builtin runtime settings now also include `position_side`, `position_leverage`, `maintenance_margin_ratio`, `maintenance_margin_schedule`, `liquidation_fee_bps`, `liquidation_fee_schedule`, `liquidation_mark_price_weight`, `liquidation_mark_premium_bps`, `partial_liquidation_ratio`, `liquidation_cooldown_bars`, and `liquidation_step_schedule`, so studies can make short-vs-long entry bias, scoring bias, scenario stress, liquidation behavior, and side-aware funding effects explicit instead of assuming long-only signal timing, long-calibrated evaluator bonuses, unlevered spot-like exits, one flat maintenance threshold for every leverage tier, one flat liquidation fee for every leverage tier, unsigned funding drag for every side, zero-penalty forced exits, wick-only liquidation triggers, zero mark/last divergence, all-or-nothing liquidations, immediate re-liquidation every bar, or one fixed liquidation size for every forced event.
- if a study leaves those execution knobs unspecified, venue-aware runtime presets can now fill in exchange-style defaults such as mark-weight and liquidation schedules; explicit runtime fields still override the venue preset value for that field.
- scenarios can now also include `funding_multiplier`, `liquidity_penalty_bps`, `latency_delta_bars`, `drawdown_multiplier`, and `mark_premium_bps` to make different stress families behave differently even when they share the same base severity, including changing execution-time slippage, delay, and liquidation pressure before the summary-level stress transform runs.
- stressed scenario results now keep `net_pnl` consistent with stressed gross PnL, fees, and funding, and raised funding pressure will penalize prior funding benefits instead of accidentally making them more favorable.
- if those knobs are omitted, built-in names like `attention-burst`, `liquidity-withdrawal`, `outage-shock`, and `short-squeeze` now pick up default venue-style presets automatically.
- those named presets are also venue-aware, so the same scenario name can pick up stronger or weaker defaults depending on the snapshot venue.
- completed run artifacts now surface the resolved scenario profile so you can see exactly which effective stress knobs were used after preset resolution.
- research memory now ingests those resolved profiles too, so memory queries can reflect the actual effective stress settings, not just the raw scenario names.
- local execution flows now also write `*.events.jsonl` files beside their artifacts, so you get a lightweight event trail for run, autoresearch, batch, continuation, and campaign workflows.
- `layer_parameters` can tune built-in behavior like `entry_stride`, `mean_threshold_offset`, `flat_range_threshold`, and `hold_bars`.
- local research memory can now distinguish `clean` vs `dirty` historical runs, and autoresearch only uses `clean` memory for follow-up suggestions by default.
- use `--memory-quality-policy all` on autoresearch commands when you intentionally want dirty historical runs included in follow-up suggestions.
- autoresearch also skips duplicate study signatures, so changing only `run_id` is not enough to force a redundant rerun of the same study definition.
- `summarize-autoresearch` is the fastest way to inspect the saved memory summary, hypotheses, and duplicate-match diagnostics from an `*.autoresearch.json` report.
- `summarize-autoresearch` will also print the accepted-duplicate config path when autoresearch already materialized that recovery artifact.
- `compare-duplicate-match` is the fastest way to compare the skipped study request against the already-matched prior run in memory.
- `accept-duplicate-match` converts that duplicate into a new study config with seeded `incumbent.layers` and carried-forward matched layer parameters.
- duplicate-skipped `autoresearch` runs now auto-write `<run-id>.accepted-duplicate.json` when the matched prior run is already available in memory.
- `continue-accepted-duplicate` uses that saved recovery config as the source for a brand-new autoresearch cycle, so you can promote the matched baseline into live follow-up research in one step.
- `query-memory --accepted-duplicate-match-run-id ...` lets you inspect only the runs that came from duplicate-recovery lineage.
- `query-memory` now also returns persisted effective runtime settings, so venue-derived execution defaults remain queryable after ingestion.
- `summarize-memory` now also shows how many clean historical runs came from duplicate recovery and which matched baselines they trace back to most often.
- `summarize-memory` now also shows the top effective runtime profile from promoted history, so execution-default drift is visible without opening raw artifact JSON.
- `summarize-memory` now also prints fragile scenario-profile evidence from repeated blocked runs, so you can inspect bad stress patterns before starting a new autoresearch cycle.
- `summarize-memory` now also shows the top avoided stress profile’s resolved knobs in text form, so you can inspect the actual bad stress shape without switching to JSON.
- `summarize-memory` now also shows the top successful stress profile’s resolved knobs in text form, so the text output lets you compare the best and worst stress shapes directly.
- `compare-runs --format text` now also surfaces resolved scenario-profile changes, so effective stress-shape differences show up alongside layer and parameter deltas.
- `compare-runs` JSON output now also includes field-level scenario-profile deltas under `scenario_profile_changes.changed.<scenario>.changed_fields`, which is useful for scripts and downstream tooling.
- `compare-runs` now also includes field-level runtime-setting diffs under `runtime_settings_changes.changed_fields`, and text mode prints `Runtime setting changes:` so effective execution-default drift is visible without opening raw artifact JSON.
- `compare-runs --kind autoresearch` can now compare saved `*.autoresearch.json` reports, including field-level duplicate-baseline rationale deltas.
- `compare-runs --kind batch` can now compare saved `*.variant-batch.json` reports, including preferred-variant changes, per-variant `duplicate_baseline_score` / `duplicate_baseline_delta_vs_preferred` deltas, and per-variant duplicate-baseline rationale diffs.
- that same batch compare flow now also surfaces duplicate-baseline scenario, fragile, and runtime-profile diffs, including preferred top-profile changes and per-variant field-level hint changes.
- text mode for `compare-runs --kind batch` now also prints `Likely preferred drivers:`, plus preferred top scenario/fragile/runtime profile changes and per-variant scenario-profile, fragile-profile, and runtime-profile hint sections, so the preferred-variant shift is explained with ranked duplicate-baseline evidence instead of only raw deltas.
- `run-campaign` can now execute a manifest of `run`, `autoresearch`, and `batch-autoresearch` entries sequentially and write a `*.campaign.json` artifact plus a campaign `*.events.jsonl` log.
- campaign manifests now also support `vars`, `defaults`, string-template expansion, and per-entry `matrix` expansion, so local sweeps can stay compact instead of duplicating nearly identical entry blocks.
- `inspect-campaign` expands those manifests non-destructively and prints the resolved entries before anything runs.
- `retry-campaign` can now derive a fresh retry manifest from a saved `*.campaign.json` artifact and rerun only the failed, skipped, non-promoted, or all entries.
- `summarize-campaign` gives that artifact a quick text view with entry counts, statuses, per-entry log paths, and any captured failures.
- `list-campaigns` can now rank and filter saved campaign artifacts, so local sweeps are inspectable without opening each JSON file manually.
- `compare-runs --kind campaign` can now diff saved `*.campaign.json` artifacts, including campaign-level completion/failure deltas and per-entry status changes.
- that campaign compare flow works in both JSON and text mode, so local sweeps can be inspected either by downstream tooling or directly from the terminal.
- the autoresearch JSON compare payload now also includes `duplicate_baseline_history_changes.net_rationale` with `direction`, `strength`, `label`, and a signed numeric `score` for sorting and thresholding in scripts.
- text mode for `compare-runs --kind autoresearch` now also highlights likely selection drivers like `success_rate` and `average_sharpe`, so the selected-variant change is easier to interpret quickly.
- those autoresearch driver lines are also ranked by weighted impact now, so larger rationale shifts surface before bookkeeping deltas.
- those driver lines now also carry `high`, `medium`, or `low` strength labels in text mode.
- negative duplicate-baseline changes now show up as `worsened` in text mode instead of the neutral `changed`.
- autoresearch text compare now also prints a one-line `Net rationale:` verdict above the ranked driver list.
- that top-line verdict now also includes a strength label, for example `improved (high)`.
- when the structured autoresearch diff includes it, text mode now also prints `Net rationale score: ...`, so the raw signed score is visible next to the human verdict.
- when gains and losses nearly offset each other, that verdict will render as `mixed (low)`.
- strongly negative duplicate-baseline drift is also covered explicitly now, for example `worsened (high)`.
- `summarize-autoresearch` now surfaces that same duplicate-recovery context for a single saved autoresearch run, including the top reused baseline when one stands out.
- `summarize-autoresearch` now also prints the top effective runtime profile from memory when that evidence exists, so a single saved run shows which execution-default shape has been working best.
- `summarize-autoresearch` now also prints `Selected scenario profile: ...` and `Selected fragile profile: ...` when the saved lineage includes duplicate-baseline scenario-profile evidence for the chosen follow-up.
- `summarize-autoresearch` now also prints `Selected runtime profile: ...` when the saved lineage includes duplicate-baseline runtime-profile evidence for the chosen follow-up.
- `summarize-autoresearch` now also surfaces `fragile_scenario_profile` hypotheses when repeated blocked stress profiles are influencing the next suggested study.
- `summarize-autoresearch` now also prints the top successful scenario profile’s resolved knobs from memory when that evidence exists, so a single saved run shows the stress shape that has been working best.
- `summarize-autoresearch` now also prints the top avoided scenario profile’s resolved knobs from memory when that evidence exists, so a single saved run shows both the best and worst stress shapes together.
- duplicate-skipped `batch-autoresearch` runs now expose that same accepted-duplicate path in the batch stdout and saved `*.variant-batch.json`.
- `summarize-batch` will print the accepted-duplicate config path directly when that recovery artifact exists.
- batch variant ranking now also looks at prior success for the same accepted-duplicate baseline, so `preferred_variant` can be influenced by what historically worked for that recovered baseline instead of only the current batch metrics.
- the saved `*.variant-batch.json` artifact now also stores `duplicate_baseline_score` and `duplicate_baseline_delta_vs_preferred` on each `variant_results` entry, so scripts can compare candidate baseline-history strength directly.
- batch variant ranking now also treats stronger repeated `scenario_profile_avoidance` history as a positive tie-breaker, so variants with better evidence for avoiding historically bad stress profiles can move ahead even when the higher-level duplicate-baseline success story is otherwise similar.
- `summarize-batch` now exposes that history in plain text too, so you can see when a preferred follow-up was backed by prior recovered-baseline success rather than only the current batch.
- `summarize-batch` now also prints the preferred variant’s top successful and avoided resolved scenario profiles when that duplicate-baseline history exists, so the recommendation shows the exact best and worst stress shapes behind it.
- `summarize-batch` now also prints `Preferred duplicate baseline score: ...`, so the preferred follow-up’s raw baseline-history strength is visible in text mode too.
- `summarize-batch` now also prints `Preferred top runtime profile: ...` when the preferred variant carries promoted runtime-profile evidence in its duplicate-baseline history.
- `summarize-batch` now also prints `History scenario profile: ...` and `History fragile profile: ...` for listed variant rows when their duplicate-baseline history includes scenario-profile evidence.
- `summarize-batch` now also prints `History runtime profile: ...` for listed variant rows when their duplicate-baseline history includes promoted runtime-profile evidence.
- `summarize-batch` now also prints `History score: ...` for each listed variant row when duplicate-baseline history exists, so text mode supports side-by-side numeric comparison too.
- `summarize-batch` now also prints `History delta vs preferred: ...` for each listed variant row when both scores exist, so text mode shows which histories are materially weaker or stronger than the preferred baseline.
- generated `*.next-study*.json` variants now use that duplicate-baseline history to reorder candidate layers too, so historically stronger recovered-baseline patterns get tested earlier in the follow-up configs.
- generated `*.next-study*.json` variants now also inherit variant-specific parameter hints from that duplicate-baseline history, so recovered-baseline settings can narrow grids and carry blocked-value avoidance into the follow-up configs.
- generated `*.next-study*.json` variants now also inherit variant-specific fragility from that duplicate-baseline history, so layers that repeatedly failed for the same recovered baseline can be pruned before that variant runs.
- generated `*.next-study*.json` variants can now also trim blocked parameter edges from a grid when recovered-baseline evidence says a boundary value repeatedly failed, even if the hint only supports partial tightening.
- generated `*.next-study*.json` variants can now also emit executable `excluded_values` for interior blocked parameter values, and the runtime grid expander will skip those values instead of only recording them as hints.
- generated `*.next-study*.json` variants now also reuse consensus resolved scenario profiles from memory, so venue-adjusted stress knobs that already worked can flow into the next suggestion without overwriting any explicit scenario values already present in the study.
- generated `*.next-study*.json` variants now also reuse the top effective runtime profile from promoted memory, so historically successful execution defaults can fill in omitted runtime fields without overwriting any explicit study runtime settings.
- generated `*.next-study*.json` variants now also include `scenario_profile_avoidance` for repeated blocked stress profiles, and exact resolved scenario profiles that repeatedly failed will be suppressed instead of being auto-carried into the next suggestion.
- `continue-batch` now carries the batch selection rationale into `research_lineage`, and `trace-lineage` will show the selection source and selection mode for the continued run.
- `trace-lineage` now also prints the selected best and worst resolved scenario profiles when that variant-selection rationale includes duplicate-baseline history.
- `trace-lineage` now also prints `Top runtime profile: ...` when that same rationale includes promoted runtime-profile evidence.
- `trace-lineage` now also prints `Duplicate baseline score: ...` when that rationale has enough numeric history to score directly.
- `examples\\minimal_builtin_study.json` is the committed minimal runnable study artifact.
- `examples\\minimal_campaign.json` is the committed minimal campaign manifest that runs a baseline `run` followed by an `autoresearch` pass.
- `examples\\study.schema.json` is the committed JSON schema for study files.
- `python -m engine.app.cli doctor` checks that those release-facing artifacts and package metadata are still in sync before a local release.
