from __future__ import annotations

import argparse


def register_research_commands(subparsers: argparse._SubParsersAction) -> None:
    autoresearch_parser = subparsers.add_parser("autoresearch", help="Run a study with explicit memory preflight and post-run ingestion.")
    autoresearch_parser.add_argument("--config", required=True, help="Path to the study JSON config.")
    autoresearch_parser.add_argument("--output-dir", required=True, help="Directory for runcard and dashboard artifacts.")
    autoresearch_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    autoresearch_parser.add_argument("--memory-dir", help="Optional directory of prior artifacts to ingest before the run.")
    autoresearch_parser.add_argument("--memory-limit", type=int, default=25, help="Maximum prior memory rows to summarize.")
    autoresearch_parser.add_argument(
        "--memory-quality-policy",
        choices=["clean-only", "all"],
        default="clean-only",
        help="Which memory rows autoresearch should use for follow-up hypotheses.",
    )
    autoresearch_parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Block the run when the study snapshot carries quality flags.",
    )

    batch_autoresearch_parser = subparsers.add_parser("batch-autoresearch", help="Run autoresearch plus all generated next-study variants.")
    batch_autoresearch_parser.add_argument("--config", required=True, help="Path to the study JSON config.")
    batch_autoresearch_parser.add_argument("--output-dir", required=True, help="Directory for artifacts.")
    batch_autoresearch_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    batch_autoresearch_parser.add_argument("--memory-dir", help="Optional directory of prior artifacts to ingest before the run.")
    batch_autoresearch_parser.add_argument("--memory-limit", type=int, default=25, help="Maximum prior memory rows to summarize.")
    batch_autoresearch_parser.add_argument(
        "--memory-quality-policy",
        choices=["clean-only", "all"],
        default="clean-only",
        help="Which memory rows autoresearch should use for follow-up hypotheses.",
    )
    batch_autoresearch_parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Block the batch when the base study snapshot carries quality flags.",
    )

    agent_loop_parser = subparsers.add_parser("agent-loop", help="Run the phase-5 research loop over autoresearch.")
    agent_loop_parser.add_argument("--config", required=True, help="Path to the study JSON config.")
    agent_loop_parser.add_argument("--output-dir", required=True, help="Directory for loop artifacts and reports.")
    agent_loop_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    agent_loop_parser.add_argument("--iterations", type=int, default=3, help="Maximum loop iterations to execute.")
    agent_loop_parser.add_argument("--run-budget", type=int, default=3, help="Maximum total study runs across the loop.")
    agent_loop_parser.add_argument(
        "--loop-mode",
        choices=["auto", "bounded", "karpathy"],
        default="auto",
        help="Loop stop policy. 'auto' uses karpathy only for program-first python targets, bounded otherwise.",
    )
    agent_loop_parser.add_argument(
        "--karpathy-execution",
        choices=["auto", "artifact-native", "git-native"],
        default="auto",
        help="Karpathy execution backend. 'auto' uses local git in git workspaces and artifact mode otherwise.",
    )
    agent_loop_parser.add_argument(
        "--karpathy-target-path",
        help="Optional authoritative Karpathy target path. Defaults to <run_id>.karpathy-working.json in the output dir.",
    )
    agent_loop_parser.add_argument(
        "--karpathy-target-kind",
        choices=["json_config", "python_source"],
        default="json_config",
        help="Single-target format for Karpathy mode. 'python_source' stores PAYLOAD in one mutable .py file.",
    )
    agent_loop_parser.add_argument(
        "--karpathy-execute-git-actions",
        action="store_true",
        default=None,
        dest="karpathy_execute_git_actions",
        help="When git-native mode is requested and available, execute the planned local git branch/commit/reset actions.",
    )
    agent_loop_parser.add_argument(
        "--no-karpathy-execute-git-actions",
        action="store_false",
        dest="karpathy_execute_git_actions",
        help="Disable local git branch/commit/reset execution even in git-native Karpathy mode.",
    )
    agent_loop_parser.add_argument("--memory-limit", type=int, default=25, help="Maximum prior memory rows to summarize.")
    agent_loop_parser.add_argument(
        "--memory-quality-policy",
        choices=["clean-only", "all"],
        default="clean-only",
        help="Which memory rows the loop should use for follow-up hypotheses.",
    )
    agent_loop_parser.add_argument(
        "--trace-advisory-notes",
        help="Optional controlled trace advisory notes artifact to merge into follow-up hypotheses.",
    )
    agent_loop_parser.add_argument(
        "--improvement-gate",
        help="Optional loop-improvement-gate artifact whose next_actions are merged into follow-up hypotheses.",
    )
    agent_loop_parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Block the loop when the study snapshot carries quality flags.",
    )
    agent_loop_parser.add_argument(
        "--require-loop-readiness",
        action="store_true",
        help="Block the loop unless loop-readiness marks the initial study eligible.",
    )
    agent_loop_parser.add_argument(
        "--evidence-ledger-output",
        help="Optional path to write a loop evidence ledger for this agent-loop run.",
    )
    agent_loop_parser.add_argument(
        "--readiness-report-output",
        help="Optional path to write the loop-readiness preflight report before running or blocking.",
    )

    guarded_loop_parser = subparsers.add_parser(
        "guarded-loop-cycle",
        help="Run one fail-closed loop cycle: optional sidecar hydration, readiness, agent-loop, evidence ledger, and improvement gate.",
    )
    guarded_loop_parser.add_argument("--config", required=True, help="Path to the study JSON config.")
    guarded_loop_parser.add_argument("--output-dir", required=True, help="Directory for guarded cycle artifacts.")
    guarded_loop_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    guarded_loop_parser.add_argument("--liquidations", help="Optional observed liquidation_notional.csv sidecar.")
    guarded_loop_parser.add_argument("--hydrated-config", help="Optional path for the hydrated study JSON.")
    guarded_loop_parser.add_argument("--iterations", type=int, default=3, help="Maximum loop iterations to execute.")
    guarded_loop_parser.add_argument("--run-budget", type=int, default=3, help="Maximum total study runs across the loop.")
    guarded_loop_parser.add_argument(
        "--loop-mode",
        choices=["auto", "bounded", "karpathy"],
        default="auto",
        help="Loop stop policy.",
    )
    guarded_loop_parser.add_argument(
        "--karpathy-execution",
        choices=["auto", "artifact-native", "git-native"],
        default="auto",
        help="Karpathy execution backend.",
    )
    guarded_loop_parser.add_argument("--karpathy-target-path")
    guarded_loop_parser.add_argument(
        "--karpathy-target-kind",
        choices=["json_config", "python_source"],
        default="json_config",
    )
    guarded_loop_parser.add_argument(
        "--karpathy-execute-git-actions",
        action="store_true",
        default=None,
        dest="karpathy_execute_git_actions",
    )
    guarded_loop_parser.add_argument(
        "--no-karpathy-execute-git-actions",
        action="store_false",
        dest="karpathy_execute_git_actions",
    )
    guarded_loop_parser.add_argument("--memory-limit", type=int, default=25)
    guarded_loop_parser.add_argument(
        "--memory-quality-policy",
        choices=["clean-only", "all"],
        default="clean-only",
    )
    guarded_loop_parser.add_argument("--trace-advisory-notes")
    guarded_loop_parser.add_argument("--improvement-gate")
    guarded_loop_parser.add_argument("--paper-dashboard")
    guarded_loop_parser.add_argument("--paper-postrun-summary")
    guarded_loop_parser.add_argument("--paper-calibration-feedback")
    guarded_loop_parser.add_argument("--max-abs-slip-bps", type=float, default=25.0)
    guarded_loop_parser.add_argument("--minimum-paper-orders", type=int, default=10)
    guarded_loop_parser.add_argument("--minimum-telemetry-quality", type=float, default=0.70)

    guarded_repeat_parser = subparsers.add_parser(
        "guarded-loop-repeat",
        help="Scan eligible studies and run bounded guarded-loop-cycle handoffs until the cycle budget or a readiness gate stops.",
    )
    guarded_repeat_parser.add_argument("--study-dir", help="Directory or study file to scan for eligible configs.")
    guarded_repeat_parser.add_argument("--config", help="Initial study JSON config. Can be paired with --liquidations.")
    guarded_repeat_parser.add_argument("--liquidations", help="Optional observed liquidation_notional.csv sidecar for the initial config.")
    guarded_repeat_parser.add_argument("--hydrated-config", help="Optional hydrated study JSON path for the initial config.")
    guarded_repeat_parser.add_argument("--output-dir", required=True, help="Directory for repeat artifacts.")
    guarded_repeat_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    guarded_repeat_parser.add_argument("--max-cycles", type=int, default=3, help="Maximum guarded cycles to run.")
    guarded_repeat_parser.add_argument("--iterations", type=int, default=3, help="Maximum loop iterations per cycle.")
    guarded_repeat_parser.add_argument("--run-budget", type=int, default=3, help="Maximum study runs per cycle.")
    guarded_repeat_parser.add_argument(
        "--loop-mode",
        choices=["auto", "bounded", "karpathy"],
        default="auto",
    )
    guarded_repeat_parser.add_argument(
        "--karpathy-execution",
        choices=["auto", "artifact-native", "git-native"],
        default="auto",
    )
    guarded_repeat_parser.add_argument(
        "--karpathy-target-kind",
        choices=["json_config", "python_source"],
        default="json_config",
    )
    guarded_repeat_parser.add_argument(
        "--karpathy-execute-git-actions",
        action="store_true",
        default=None,
        dest="karpathy_execute_git_actions",
    )
    guarded_repeat_parser.add_argument(
        "--no-karpathy-execute-git-actions",
        action="store_false",
        dest="karpathy_execute_git_actions",
    )
    guarded_repeat_parser.add_argument("--memory-limit", type=int, default=25)
    guarded_repeat_parser.add_argument(
        "--memory-quality-policy",
        choices=["clean-only", "all"],
        default="clean-only",
    )
    guarded_repeat_parser.add_argument("--trace-advisory-notes")
    guarded_repeat_parser.add_argument("--paper-dashboard")
    guarded_repeat_parser.add_argument("--paper-postrun-summary")
    guarded_repeat_parser.add_argument("--paper-calibration-feedback")
    guarded_repeat_parser.add_argument("--max-abs-slip-bps", type=float, default=25.0)
    guarded_repeat_parser.add_argument("--minimum-paper-orders", type=int, default=10)
    guarded_repeat_parser.add_argument("--minimum-telemetry-quality", type=float, default=0.70)

    operate_loop_parser = subparsers.add_parser(
        "operate-loop",
        help="Agent-safe strict v3 loop operator that gates weak data before guarded execution.",
    )
    operate_loop_parser.add_argument("--config", help="Initial study JSON config.")
    operate_loop_parser.add_argument("--study-dir", help="Directory or study file to scan when --config is absent.")
    operate_loop_parser.add_argument("--output-dir", required=True, help="Directory for operate-loop artifacts.")
    operate_loop_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    operate_loop_parser.add_argument("--profile", default="strict_v3")
    operate_loop_parser.add_argument("--max-cycles", type=int, default=3)
    operate_loop_parser.add_argument("--iterations", type=int, default=3)
    operate_loop_parser.add_argument("--run-budget", type=int, default=3)
    operate_loop_parser.add_argument("--paper-dashboard")
    operate_loop_parser.add_argument("--paper-postrun-summary")
    operate_loop_parser.add_argument("--paper-calibration-feedback")
    operate_loop_parser.add_argument("--strategy-evidence-card")
    operate_loop_parser.add_argument("--require-research-ready", action="store_true")
    operate_loop_parser.add_argument("--require-improvement-ready", action="store_true")
    operate_loop_parser.add_argument("--allow-smoke", action="store_true")
    operate_loop_parser.add_argument("--candidate-queue")

    strict_data_parser = subparsers.add_parser(
        "strict-data-collect",
        help="Supervise strict v3 public-only data collection and write a data inventory artifact.",
    )
    strict_data_parser.add_argument("--data-root", default="outputs/data")
    strict_data_parser.add_argument("--public-ws-db", default="outputs/public-ws/public_stream.sqlite")
    strict_data_parser.add_argument("--inventory-output", default="outputs/data/strict-v3-data-inventory.json")
    strict_data_parser.add_argument("--plan-status", default="PLAN_STATUS.json")
    strict_data_parser.add_argument("--liquidation-output", default="outputs/public-ws/liquidation_notional.csv")
    strict_data_parser.add_argument("--session-id")
    strict_data_parser.add_argument("--min-forward-seconds", type=int, default=8 * 60 * 60)
    strict_data_parser.add_argument("--target-forward-seconds", type=int, default=12 * 60 * 60)
    strict_data_parser.add_argument("--strong-forward-seconds", type=int, default=72 * 60 * 60)
    strict_data_parser.add_argument("--max-observed-gap-seconds", type=int, default=300)
    strict_data_parser.add_argument("--export-timeframe", default="1Hour")
    strict_data_parser.add_argument("--export-liquidations-when-ready", action="store_true")
    strict_data_parser.add_argument("--no-observed-zero-buckets", action="store_true")
    strict_data_parser.add_argument("--sync-plan-status", action="store_true")

    campaign_parser = subparsers.add_parser("run-campaign", help="Run a manifest of study entries and write a campaign report.")
    campaign_parser.add_argument("--manifest", required=True, help="Path to a campaign JSON manifest.")
    campaign_parser.add_argument("--output-report", required=True, help="Path to write the campaign report JSON.")
