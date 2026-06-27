from __future__ import annotations

import argparse


def register_core_commands(subparsers: argparse._SubParsersAction) -> None:
    run_parser = subparsers.add_parser("run", help="Run a study JSON config.")
    run_parser.add_argument("--config", required=True, help="Path to the study JSON config.")
    run_parser.add_argument("--output-dir", required=True, help="Directory for runcard and dashboard artifacts.")
    run_parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Block the run when the study snapshot carries quality flags.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect-study",
        help="Inspect a study config and summarize snapshot quality.",
    )
    inspect_parser.add_argument("--config", required=True, help="Path to the study JSON config.")

    readiness_parser = subparsers.add_parser(
        "loop-readiness",
        help="Check whether a study is eligible for strict repeated agent-loop operation.",
    )
    readiness_parser.add_argument("--config", required=True, help="Path to the study JSON config.")
    readiness_parser.add_argument("--output", help="Optional path to write the readiness report JSON.")

    readiness_scan_parser = subparsers.add_parser(
        "loop-readiness-scan",
        help="Scan a directory for study configs and summarize loop-readiness eligibility.",
    )
    readiness_scan_parser.add_argument("--dir", required=True, help="Directory or study config path to scan.")
    readiness_scan_parser.add_argument("--output", help="Optional path to write the scan report JSON.")
    readiness_scan_parser.add_argument(
        "--require-eligible",
        action="store_true",
        help="Return exit code 2 when the scan finds no eligible study configs.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run local release-readiness checks for docs, examples, and package metadata.",
    )
    doctor_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format for the release checks.",
    )

    init_parser = subparsers.add_parser(
        "init-example",
        help="Create a runnable example study from CSV market data.",
    )
    init_parser.add_argument("--csv", required=True, help="Path to OHLCV CSV input.")
    init_parser.add_argument("--config-out", required=True, help="Path to write the generated study JSON.")
    init_parser.add_argument("--snapshot-id", required=True, help="Snapshot identifier.")
    init_parser.add_argument("--symbol", required=True, help="Market symbol, e.g. SOLUSDT.")
    init_parser.add_argument("--venue", required=True, help="Venue identifier, e.g. binance.")
    init_parser.add_argument("--timeframe", required=True, help="Timeframe label, e.g. 1h.")
    init_parser.add_argument("--run-id", default="example-study", help="Run identifier for the generated study.")
    init_parser.add_argument("--seed", type=int, default=7, help="Seed for the generated study.")
    init_parser.add_argument("--maker-fee-bps", type=float, default=2.0, help="Maker fee in basis points.")
    init_parser.add_argument("--taker-fee-bps", type=float, default=5.0, help="Taker fee in basis points.")

    init_bundle_parser = subparsers.add_parser(
        "init-example-bundle",
        help="Create a runnable example study from separate candles and market sidecar CSVs.",
    )
    init_bundle_parser.add_argument("--candles-csv", required=True, help="Path to OHLCV candles CSV input.")
    init_bundle_parser.add_argument("--funding-csv", help="Optional path to funding-rate CSV.")
    init_bundle_parser.add_argument("--open-interest-csv", help="Optional path to open-interest CSV.")
    init_bundle_parser.add_argument("--liquidations-csv", help="Optional path to liquidation-notional CSV.")
    init_bundle_parser.add_argument("--config-out", required=True, help="Path to write the generated study JSON.")
    init_bundle_parser.add_argument("--snapshot-id", required=True, help="Snapshot identifier.")
    init_bundle_parser.add_argument("--symbol", required=True, help="Market symbol, e.g. SOLUSDT.")
    init_bundle_parser.add_argument("--venue", required=True, help="Venue identifier, e.g. binance.")
    init_bundle_parser.add_argument("--timeframe", required=True, help="Timeframe label, e.g. 1h.")
    init_bundle_parser.add_argument("--run-id", default="example-study", help="Run identifier for the generated study.")
    init_bundle_parser.add_argument("--seed", type=int, default=7, help="Seed for the generated study.")
    init_bundle_parser.add_argument("--maker-fee-bps", type=float, default=2.0, help="Maker fee in basis points.")
    init_bundle_parser.add_argument("--taker-fee-bps", type=float, default=5.0, help="Taker fee in basis points.")

    schema_parser = subparsers.add_parser("export-schema", help="Write the study JSON schema to disk.")
    schema_parser.add_argument("--output", required=True, help="Path to write the schema JSON.")

    refresh_parser = subparsers.add_parser(
        "refresh-examples",
        help="Write checked-in example artifacts to a directory.",
    )
    refresh_parser.add_argument("--dir", default="examples", help="Directory where example artifacts should be written.")
