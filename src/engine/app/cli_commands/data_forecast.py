from __future__ import annotations

import argparse


TIMESFM_SYMBOL_CHOICES = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def register_data_forecast_commands(subparsers: argparse._SubParsersAction) -> None:
    microstructure_parser = subparsers.add_parser(
        "fetch-microstructure",
        help="Fetch a bounded public Binance futures microstructure sample for Phase 5.",
    )
    microstructure_parser.add_argument("--output-dir", required=True, help="Directory for raw events, features, and manifest.")
    microstructure_parser.add_argument("--symbol", default="BTCUSDT", help="Binance USD-M symbol, e.g. BTCUSDT.")
    microstructure_parser.add_argument("--depth-limit", type=int, default=100, help="Depth snapshot limit: 5..1000.")
    microstructure_parser.add_argument("--agg-trade-limit", type=int, default=1000, help="Aggregate trade limit: 1..1000.")
    microstructure_parser.add_argument("--samples", type=int, default=1, help="Number of depth snapshots to capture.")
    microstructure_parser.add_argument("--sample-interval-seconds", type=float, default=0.0, help="Delay between depth samples.")
    microstructure_parser.add_argument("--retention-hours", type=int, default=24, help="Approved local retention window.")
    microstructure_parser.add_argument("--max-raw-events", type=int, default=100000, help="Approved raw JSONL event cap.")

    hydrate_parser = subparsers.add_parser(
        "hydrate-study-liquidations",
        help="Rebuild a study snapshot with an observed public forceOrder liquidation sidecar.",
    )
    hydrate_parser.add_argument("--config", required=True, help="Study JSON config to hydrate.")
    hydrate_parser.add_argument("--liquidations", required=True, help="Observed liquidation_notional.csv sidecar.")
    hydrate_parser.add_argument("--output", required=True, help="Path to write the hydrated study JSON.")
    hydrate_parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Verify the sidecar first and do not write hydrated output unless it is ready.",
    )

    verify_liquidations_parser = subparsers.add_parser(
        "verify-study-liquidations",
        help="Verify an observed liquidation_notional.csv sidecar against a study without writing a hydrated study.",
    )
    verify_liquidations_parser.add_argument("--config", required=True, help="Study JSON config to check.")
    verify_liquidations_parser.add_argument("--liquidations", required=True, help="Observed liquidation_notional.csv sidecar.")
    verify_liquidations_parser.add_argument("--output", help="Optional path to write the sidecar verification JSON.")

    forceorder_parser = subparsers.add_parser(
        "export-forceorder-liquidations",
        help="Export recorded public Binance forceOrder stream events into a sparse liquidation sidecar CSV.",
    )
    forceorder_parser.add_argument("--db", required=True, help="SQLite memory DB containing paper_stream_events.")
    forceorder_parser.add_argument("--session-id", required=True, help="Paper/public stream session id to export.")
    forceorder_parser.add_argument("--output", required=True, help="Path for liquidation_notional.csv.")
    forceorder_parser.add_argument("--timeframe", choices=["1Min", "15Min", "1Hour", "1Day"], default="1Hour")
    forceorder_parser.add_argument(
        "--include-observed-zero-buckets",
        action="store_true",
        help="Write zero rows only for buckets with parsed public stream activity but no forceOrder event.",
    )

    timesfm_smoke_parser = subparsers.add_parser(
        "timesfm-smoke",
        help="Run an opt-in research-only TimesFM local smoke. Skips when deps or weights are absent.",
    )
    timesfm_smoke_parser.add_argument("--symbol", choices=TIMESFM_SYMBOL_CHOICES, default="BTCUSDT")
    timesfm_smoke_parser.add_argument("--horizon", type=int, default=3)
    timesfm_smoke_parser.add_argument("--backend", choices=["pytorch", "jax"], default="pytorch")
    timesfm_smoke_parser.add_argument("--model-id", default="google/timesfm-2.5-200m-pytorch")
    timesfm_smoke_parser.add_argument("--model-weights-path")
    timesfm_smoke_parser.add_argument("--sidecar-python-path")
    timesfm_smoke_parser.add_argument("--sidecar-timeout-seconds", type=float, default=120.0)
    timesfm_smoke_parser.add_argument("--fixture", action="store_true", help="Use bundled fixture forecast; no dependency probe.")

    timesfm_benchmark_parser = subparsers.add_parser(
        "timesfm-benchmark",
        help="Run a research-only TimesFM runtime benchmark and write a laptop-safe profile.",
    )
    timesfm_benchmark_parser.add_argument("--output", required=True, help="Path to write runtime profile JSON.")
    timesfm_benchmark_parser.add_argument("--fixture", action="store_true", help="Use fixture forecast; no model dependency.")
    timesfm_benchmark_parser.add_argument("--backend", choices=["pytorch", "jax"], default="pytorch")
    timesfm_benchmark_parser.add_argument("--model-id", default="google/timesfm-2.5-200m-pytorch")
    timesfm_benchmark_parser.add_argument("--model-weights-path")
    timesfm_benchmark_parser.add_argument("--sidecar-python-path")
    timesfm_benchmark_parser.add_argument("--sidecar-timeout-seconds", type=float, default=120.0)
    timesfm_benchmark_parser.add_argument("--context-length", action="append", type=int, default=[])
    timesfm_benchmark_parser.add_argument("--horizon", action="append", type=int, default=[])
    timesfm_benchmark_parser.add_argument("--batch-size", action="append", type=int, default=[])
    timesfm_benchmark_parser.add_argument("--device", action="append", default=[])
    timesfm_benchmark_parser.add_argument("--include-torch-compile", action="store_true")
    timesfm_benchmark_parser.add_argument("--warm-batch", action="store_true", help="Load TimesFM once and forecast batch symbols in one sidecar call.")
    timesfm_benchmark_parser.add_argument("--resident-sidecar", action="store_true", help="Use the optional resident TimesFM sidecar protocol for warm-batch benchmarks.")
    timesfm_benchmark_parser.add_argument("--warm-batch-symbol", action="append", choices=TIMESFM_SYMBOL_CHOICES, default=[])
    timesfm_benchmark_parser.add_argument("--include-forecast-campaign", action="store_true", help="Attach the Phase 5 forecast validation campaign contract to the runtime profile artifact.")
    timesfm_benchmark_parser.add_argument("--forecast-campaign-symbol", action="append", choices=TIMESFM_SYMBOL_CHOICES, default=[])

    profile_parser = subparsers.add_parser(
        "profile-local-harness",
        help="Run the O7 local profiling harness and write a runtime/SQL hotspot report.",
    )
    profile_parser.add_argument("--output", required=True, help="Path to write local profiling report JSON.")
    profile_parser.add_argument("--fixture", action="store_true", help="Use deterministic local fixture tasks.")

    matrix_parser = subparsers.add_parser(
        "dataset-matrix",
        help="Build a symbol/timeframe/year coverage matrix from a strict data inventory.",
    )
    matrix_parser.add_argument("--inventory", required=True, help="Strict data inventory JSON to inspect.")
    matrix_parser.add_argument("--output", required=True, help="Path to write dataset matrix JSON.")
    matrix_parser.add_argument("--workspace", default=".", help="Workspace root for relative inventory paths.")
    matrix_parser.add_argument("--symbol", action="append", default=[], help="Required symbol. Repeatable.")
    matrix_parser.add_argument("--timeframe", action="append", default=[], help="Required timeframe. Repeatable.")
    matrix_parser.add_argument(
        "--minimum-distinct-years",
        type=int,
        default=5,
        help="Minimum distinct UTC years required per symbol/timeframe.",
    )
    matrix_parser.add_argument(
        "--required-sidecar",
        action="append",
        default=[],
        help="Required sidecar field, e.g. liquidation_notional. Repeatable.",
    )

    archive_parser = subparsers.add_parser(
        "fetch-binance-archive",
        help="Build a versioned v3 snapshot from the public Binance USD-M archive.",
    )
    archive_parser.add_argument("--output-dir", required=True, help="Directory for raw archive files and normalized snapshot CSVs.")
    archive_parser.add_argument("--symbol", default="BTCUSDT", help="Binance USD-M symbol, e.g. BTCUSDT.")
    archive_parser.add_argument("--timeframe", choices=["1Hour", "15Min"], default="1Hour", help="Archive-backed v3 timeframe.")
    archive_parser.add_argument("--start-date", required=True, help="First archive date, YYYY-MM-DD.")
    archive_parser.add_argument("--end-date", required=True, help="Last archive date, YYYY-MM-DD.")
    archive_parser.add_argument("--skip-agg-trades", action="store_true", help="Only download klines; omit raw aggTrades ZIPs.")
