from __future__ import annotations

from engine.config.models import DataSnapshot, SnapshotWindow, SplitPack
from engine.data.feature_store import assert_candidate_feature_quality
from engine.data.snapshots import slice_snapshot
from engine.validation.regimes import analyze_regimes_model


def build_split_pack(snapshot: DataSnapshot, *, regime_model: str = "deterministic", regime_n_states: int = 4) -> SplitPack:
    assert_candidate_feature_quality(snapshot)
    total = len(snapshot.candles)
    if total < 5:
        raise ValueError("snapshot must contain at least 5 candles")

    in_sample_end = int(total * 0.60)
    selection_end = in_sample_end + int(total * 0.20)

    in_sample = slice_snapshot(snapshot, 0, in_sample_end, "in-sample")
    selection_oos = slice_snapshot(snapshot, in_sample_end, selection_end, "selection-oos")
    final_holdout = slice_snapshot(snapshot, selection_end, total, "final-holdout")
    regime_analysis = analyze_regimes_model(snapshot, model_name=regime_model, n_states=regime_n_states)

    return SplitPack(
        in_sample=SnapshotWindow(in_sample, 0, len(in_sample.candles)),
        selection_oos=SnapshotWindow(selection_oos, in_sample_end, selection_end),
        final_holdout=SnapshotWindow(final_holdout, selection_end, total),
        bootstrap_source=SnapshotWindow(in_sample, 0, len(in_sample.candles)),
        crisis_windows=regime_analysis.crisis_windows,
        regime_labels=regime_analysis.regime_labels,
        regime_coverage=regime_analysis.regime_coverage,
        crisis_window_coverage=regime_analysis.crisis_window_coverage,
        regime_model=regime_analysis.model_name,
        regime_metadata=dict(regime_analysis.metadata or {}),
    )
