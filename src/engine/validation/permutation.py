from __future__ import annotations

import random
from collections.abc import Callable

from engine.config.models import BacktestResult, DataSnapshot, PermutationTestResult, StrategyGraph
from engine.data.snapshots import clone_snapshot
from engine.data.schema import Candle


StrategyEvaluator = Callable[[DataSnapshot, StrategyGraph], BacktestResult]


def permute_snapshot_path(snapshot: DataSnapshot, seed: int) -> DataSnapshot:
    candle_count = len(snapshot.candles)
    if candle_count <= 1:
        return snapshot

    rng = random.Random(seed)
    permutation = list(range(1, candle_count))
    rng.shuffle(permutation)

    original_candles = snapshot.candles
    permuted_candles: list[Candle] = [original_candles[0]]
    previous_close = original_candles[0].close

    for output_index, source_index in enumerate(permutation, start=1):
        source_candle = original_candles[source_index]
        prior_close = original_candles[source_index - 1].close
        close_return = 0.0 if prior_close == 0 else (source_candle.close / prior_close) - 1.0
        next_close = previous_close * (1.0 + close_return)
        candle_range = max(abs(source_candle.high - source_candle.low), abs(next_close - previous_close), 1e-6)
        permuted_candles.append(
            Candle(
                timestamp=original_candles[output_index].timestamp,
                open=previous_close,
                high=max(previous_close, next_close) + (0.25 * candle_range),
                low=max(1e-9, min(previous_close, next_close) - (0.25 * candle_range)),
                close=next_close,
                volume=source_candle.volume,
            )
        )
        previous_close = next_close

    return clone_snapshot(
        snapshot,
        snapshot_id=f"{snapshot.snapshot_id}:permuted:{seed}",
        candles=permuted_candles,
        funding_rates=[snapshot.funding_rates[0], *[snapshot.funding_rates[index] for index in permutation]],
        open_interest=[snapshot.open_interest[0], *[snapshot.open_interest[index] for index in permutation]],
        liquidation_notional=[snapshot.liquidation_notional[0], *[snapshot.liquidation_notional[index] for index in permutation]],
        provenance_updates={
            "transformation": "permutation",
            "seed": seed,
        },
    )


def run_in_sample_permutation_test(
    snapshot: DataSnapshot,
    strategy: StrategyGraph,
    evaluate_strategy: StrategyEvaluator,
    permutation_count: int,
    seed: int,
) -> PermutationTestResult:
    return _run_permutation_test(
        stage_name="in_sample_permutation",
        snapshot=snapshot,
        strategy=strategy,
        evaluate_strategy=evaluate_strategy,
        permutation_count=permutation_count,
        seed=seed,
    )


def run_walk_forward_permutation_test(
    snapshot: DataSnapshot,
    strategy: StrategyGraph,
    evaluate_strategy: StrategyEvaluator,
    permutation_count: int,
    seed: int,
) -> PermutationTestResult:
    return _run_permutation_test(
        stage_name="walk_forward_permutation",
        snapshot=snapshot,
        strategy=strategy,
        evaluate_strategy=evaluate_strategy,
        permutation_count=permutation_count,
        seed=seed,
    )


def _run_permutation_test(
    stage_name: str,
    snapshot: DataSnapshot,
    strategy: StrategyGraph,
    evaluate_strategy: StrategyEvaluator,
    permutation_count: int,
    seed: int,
) -> PermutationTestResult:
    effective_count = max(1, int(permutation_count))
    observed_metric = float(evaluate_strategy(snapshot, strategy).sharpe)

    exceedance_count = 0
    for offset in range(effective_count):
        permuted = permute_snapshot_path(snapshot, seed=seed + offset)
        permuted_metric = float(evaluate_strategy(permuted, strategy).sharpe)
        if permuted_metric >= observed_metric:
            exceedance_count += 1

    pvalue = (1 + exceedance_count) / (effective_count + 1)
    return PermutationTestResult(
        stage_name=stage_name,
        metric_name="sharpe",
        observed_metric=observed_metric,
        exceedance_count=exceedance_count,
        permutation_count=effective_count,
        pvalue=pvalue,
        seed=seed,
    )
