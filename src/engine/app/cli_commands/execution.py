from __future__ import annotations

import argparse


def register_execution_commands(subparsers: argparse._SubParsersAction) -> None:
    no_key_chaos_parser = subparsers.add_parser(
        "no-key-executor-chaos",
        help="Run Phase 2 fake Binance private execution chaos replay. Uses no private keys.",
    )
    no_key_chaos_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    no_key_chaos_parser.add_argument("--scenario", default="all", help="Scenario id or all.")
    no_key_chaos_parser.add_argument("--session-id", default="phase2-no-key")
    no_key_chaos_parser.add_argument("--symbol", required=True)
    no_key_chaos_parser.add_argument("--side", required=True, choices=["BUY", "SELL", "buy", "sell"])
    no_key_chaos_parser.add_argument("--qty", type=float, required=True)
    no_key_chaos_parser.add_argument("--price", type=float, required=True)
    no_key_chaos_parser.add_argument("--client-order-id", required=True)
    no_key_chaos_parser.add_argument("--output", required=True, help="Output Phase 2 chaos report JSON path.")

    phase3_reconcile_parser = subparsers.add_parser(
        "phase3-reconcile",
        help="Rebuild Phase 3 execution projection and reconcile against a fake gateway snapshot.",
    )
    phase3_reconcile_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    phase3_reconcile_parser.add_argument("--snapshot", required=True, help="Gateway snapshot JSON path.")
    phase3_reconcile_parser.add_argument("--operator-id", required=True, help="Operator id for safe-action journal.")
    phase3_reconcile_parser.add_argument("--artifact-id", required=True, help="Artifact id for pause/force-reconcile journal rows.")
    phase3_reconcile_parser.add_argument("--output", required=True, help="Output Phase 3 reconciliation report JSON path.")

    portfolio_plan_parser = subparsers.add_parser(
        "portfolio-plan",
        help="Build a bounded role-aware portfolio plan from approved artifact candidates.",
    )
    portfolio_plan_parser.add_argument("--input", required=True, help="JSON input with candidates, constraints, and active_regimes.")
    portfolio_plan_parser.add_argument("--output", help="Optional path to write portfolio artifact JSON.")
    portfolio_plan_parser.add_argument("--db", help="Optional SQLite memory DB for portfolio_plans persistence.")

    paper_portfolio_loop_parser = subparsers.add_parser(
        "paper-portfolio-loop",
        help="Run one Phase 9A paper portfolio allocator tick from DB telemetry.",
    )
    paper_portfolio_loop_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_portfolio_loop_parser.add_argument("--session-id", required=True, help="Paper session id.")
    paper_portfolio_loop_parser.add_argument("--input", required=True, help="JSON constraints and active regimes.")
    paper_portfolio_loop_parser.add_argument("--output", help="Optional path to write loop result JSON.")

    portfolio_override_parser = subparsers.add_parser(
        "portfolio-override",
        help="Apply a human portfolio override with confirmation and journal logging.",
    )
    portfolio_override_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    portfolio_override_parser.add_argument(
        "--action",
        required=True,
        choices=[
            "pause_artifact",
            "resume_artifact",
            "cancel_all",
            "flatten_all",
            "kill_switch",
            "rollback_artifact",
            "view_journal",
            "force_reconcile",
        ],
        help="Override action.",
    )
    portfolio_override_parser.add_argument("--operator-id", required=True, help="Operator identity.")
    portfolio_override_parser.add_argument("--artifact-id", help="Artifact id for artifact-scoped overrides.")
    portfolio_override_parser.add_argument("--confirmation", help="Required as CONFIRM:<action> for destructive overrides.")
    portfolio_override_parser.add_argument("--reason", help="Operator reason or closeout note.")

    calibrate_parser = subparsers.add_parser(
        "calibrate-cost-capacity",
        help="Build a v3 cost/capacity calibration artifact from order telemetry.",
    )
    calibrate_parser.add_argument("--db", required=True, help="SQLite memory DB containing order_telemetry.")
    calibrate_parser.add_argument("--output", required=True, help="Path to write the calibration artifact JSON.")
    calibrate_parser.add_argument("--baseline-edge-bps", type=float, required=True, help="Baseline edge in bps.")
    calibrate_parser.add_argument("--source-model-version", default="cost-v1", help="Source cost model version.")
    calibrate_parser.add_argument("--minimum-orders-per-bucket", type=int, default=200, help="Required symbol/regime sample count.")
    calibrate_parser.add_argument("--max-participation-rate", type=float, default=0.05, help="Capacity fill threshold.")

    paper_calibration_parser = subparsers.add_parser(
        "paper-calibration-feedback",
        help="Build conservative simulation-prior feedback from Phase 9A paper telemetry.",
    )
    paper_calibration_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_calibration_parser.add_argument("--session-id", required=True, help="Paper session id.")
    paper_calibration_parser.add_argument("--output", required=True, help="Path to write feedback artifact JSON.")
    paper_calibration_parser.add_argument("--source-model-version", default="cost-v1")
    paper_calibration_parser.add_argument("--minimum-samples-per-bucket", type=int, default=200)
    paper_calibration_parser.add_argument("--shrinkage-alpha", type=float, default=0.10)

    paper_post_run_parser = subparsers.add_parser(
        "paper-post-run-summary",
        help="Build compact agent post-run summary for a Phase 9A paper session.",
    )
    paper_post_run_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_post_run_parser.add_argument("--session-id", required=True, help="Paper session id.")
    paper_post_run_parser.add_argument("--output", required=True, help="Path to write post-run summary JSON.")
    paper_post_run_parser.add_argument("--max-items", type=int, default=5)

    lifecycle_status_parser = subparsers.add_parser(
        "lifecycle-status",
        help="Read artifact lifecycle state from memory without manual DB edits.",
    )
    lifecycle_status_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    lifecycle_status_parser.add_argument("--artifact-id", required=True, help="Artifact id to inspect.")
