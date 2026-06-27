from __future__ import annotations

import argparse


def register_report_commands(subparsers: argparse._SubParsersAction) -> None:
    summary_parser = subparsers.add_parser("summarize-run", help="Print a human-readable summary from a dashboard artifact.")
    summary_parser.add_argument("--dashboard", required=True, help="Path to a saved dashboard JSON artifact.")
    summary_parser.add_argument(
        "--phase-filter",
        choices=["accepted", "rejected", "all"],
        default="accepted",
        help="Which phase rows to include in the summary.",
    )
    summary_parser.add_argument("--top", type=int, default=None, help="Limit how many top parameter combos to show per phase.")

    autoresearch_summary_parser = subparsers.add_parser("summarize-autoresearch", help="Print a human-readable summary from an autoresearch artifact.")
    autoresearch_summary_parser.add_argument("--autoresearch-report", required=True, help="Path to a saved *.autoresearch.json artifact.")

    batch_summary_parser = subparsers.add_parser("summarize-batch", help="Print a human-readable summary from a batch autoresearch artifact.")
    batch_summary_parser.add_argument("--batch-report", required=True, help="Path to a saved *.variant-batch.json artifact.")
    batch_summary_parser.add_argument("--top", type=int, default=None, help="Limit how many variant rows to show.")

    campaign_summary_parser = subparsers.add_parser("summarize-campaign", help="Print a human-readable summary from a campaign artifact.")
    campaign_summary_parser.add_argument("--campaign-report", required=True, help="Path to a saved *.campaign.json artifact.")

    inspect_campaign_parser = subparsers.add_parser("inspect-campaign", help="Expand a campaign manifest and summarize the resolved entries without running them.")
    inspect_campaign_parser.add_argument("--manifest", required=True, help="Path to a campaign JSON manifest.")

    retry_campaign_parser = subparsers.add_parser("retry-campaign", help="Retry selected entries from a saved campaign report.")
    retry_campaign_parser.add_argument("--campaign-report", required=True, help="Path to a saved *.campaign.json artifact.")
    retry_campaign_parser.add_argument("--output-report", required=True, help="Path to write the retry campaign report JSON.")
    retry_campaign_parser.add_argument(
        "--entry-status",
        choices=["failed", "skipped", "non-promoted", "all"],
        default="failed",
        help="Which prior entry statuses should be retried.",
    )

    select_batch_variant_parser = subparsers.add_parser("select-batch-variant", help="Select a follow-up study config from a batch autoresearch artifact.")
    select_batch_variant_parser.add_argument("--batch-report", required=True, help="Path to a saved *.variant-batch.json artifact.")
    select_batch_variant_parser.add_argument(
        "--variant",
        choices=["preferred", "balanced", "conservative", "exploratory"],
        default="preferred",
        help="Which variant config to select.",
    )
    select_batch_variant_parser.add_argument("--output-config", help="Optional path to copy the selected config to.")

    continue_batch_parser = subparsers.add_parser("continue-batch", help="Run a selected batch follow-up config through a new autoresearch cycle.")
    continue_batch_parser.add_argument("--batch-report", required=True, help="Path to a saved *.variant-batch.json artifact.")
    continue_batch_parser.add_argument(
        "--variant",
        choices=["preferred", "balanced", "conservative", "exploratory"],
        default="preferred",
        help="Which variant config to continue with.",
    )
    continue_batch_parser.add_argument("--output-dir", required=True, help="Directory for the continued autoresearch artifacts.")
    continue_batch_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    continue_batch_parser.add_argument("--memory-dir", help="Optional directory of prior artifacts to ingest before the continued run.")
    continue_batch_parser.add_argument("--memory-limit", type=int, default=25, help="Maximum prior memory rows to summarize.")
    continue_batch_parser.add_argument(
        "--memory-quality-policy",
        choices=["clean-only", "all"],
        default="clean-only",
        help="Which memory rows autoresearch should use for follow-up hypotheses.",
    )
    continue_batch_parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Block the continued run when the selected study snapshot carries quality flags.",
    )

    trace_lineage_parser = subparsers.add_parser("trace-lineage", help="Print lineage metadata from an autoresearch report.")
    trace_lineage_parser.add_argument("--autoresearch-report", required=True, help="Path to a saved *.autoresearch.json artifact.")

    trace_audit_export_parser = subparsers.add_parser("trace-audit-export", help="Export a compact report-only trace audit artifact from an agent-loop report.")
    trace_audit_export_parser.add_argument("--agent-loop-report", required=True, help="Path to a saved agent-loop report JSON artifact.")
    trace_audit_export_parser.add_argument("--output", required=True, help="Path to write the trace audit export JSON.")

    loop_evidence_parser = subparsers.add_parser(
        "loop-evidence-ledger",
        help="Build a compact evidence ledger from agent-loop reports and readiness scans.",
    )
    loop_evidence_parser.add_argument(
        "--agent-loop-report",
        action="append",
        default=[],
        help="Path to a saved agent-loop report JSON artifact. Repeatable.",
    )
    loop_evidence_parser.add_argument(
        "--readiness-scan",
        action="append",
        default=[],
        help="Path to a loop-readiness-scan JSON artifact. Repeatable.",
    )
    loop_evidence_parser.add_argument(
        "--readiness-report",
        action="append",
        default=[],
        help="Path to a loop-readiness report JSON artifact. Repeatable.",
    )
    loop_evidence_parser.add_argument(
        "--paper-dashboard",
        action="append",
        default=[],
        help="Path to a paper-session dashboard JSON artifact. Repeatable.",
    )
    loop_evidence_parser.add_argument(
        "--paper-postrun-summary",
        action="append",
        default=[],
        help="Path to a paper post-run summary JSON artifact. Repeatable.",
    )
    loop_evidence_parser.add_argument(
        "--paper-calibration-feedback",
        action="append",
        default=[],
        help="Path to a paper calibration feedback JSON artifact. Repeatable.",
    )
    loop_evidence_parser.add_argument("--output", required=True, help="Path to write the evidence ledger JSON.")

    feature_causality_parser = subparsers.add_parser(
        "feature-causality-audit",
        help="Build a Robustness Ladder feature causality audit from precomputed sentinel signals.",
    )
    feature_causality_parser.add_argument("--input", required=True, help="Feature causality audit input JSON.")
    feature_causality_parser.add_argument("--output", required=True, help="Path to write the audit JSON.")

    tournament_parser = subparsers.add_parser(
        "strategy-tournament",
        help="Build a Robustness Ladder strategy tournament scorecard.",
    )
    tournament_parser.add_argument("--input", required=True, help="Candidate bucket metrics JSON.")
    tournament_parser.add_argument("--output", required=True, help="Path to write the tournament JSON.")
    tournament_parser.add_argument("--minimum-bucket-count", type=int, default=2)

    robust_eval_parser = subparsers.add_parser(
        "robust-evaluate",
        help="Build a Robustness Ladder robust evaluation aggregate scorecard.",
    )
    robust_eval_parser.add_argument("--input", required=True, help="Candidate evidence JSON.")
    robust_eval_parser.add_argument("--output", required=True, help="Path to write the robust evaluation JSON.")

    sealed_holdout_parser = subparsers.add_parser(
        "sealed-holdout-check",
        help="Build a sealed holdout pass/fail report without exposing tunable metrics to the agent.",
    )
    sealed_holdout_parser.add_argument("--input", required=True, help="Sealed holdout input JSON.")
    sealed_holdout_parser.add_argument("--output", required=True, help="Path to write the sealed holdout JSON.")

    paper_forward_parser = subparsers.add_parser(
        "paper-forward-score",
        help="Build a paper-forward execution realism score from public WS and paper telemetry.",
    )
    paper_forward_parser.add_argument("--input", help="Optional combined paper-forward-score input JSON.")
    paper_forward_parser.add_argument("--candidate-id", default="unknown")
    paper_forward_parser.add_argument("--data-inventory")
    paper_forward_parser.add_argument("--public-ws")
    paper_forward_parser.add_argument("--paper-dashboard")
    paper_forward_parser.add_argument("--postrun-summary")
    paper_forward_parser.add_argument("--calibration-feedback")
    paper_forward_parser.add_argument("--capacity-report")
    paper_forward_parser.add_argument("--liquidation-sidecar")
    paper_forward_parser.add_argument("--output", required=True, help="Path to write the paper-forward-score JSON.")
    paper_forward_parser.add_argument("--minimum-paper-orders", type=int, default=10)
    paper_forward_parser.add_argument("--minimum-telemetry-quality", type=float, default=0.70)
    paper_forward_parser.add_argument("--max-abs-slip-bps", type=float, default=25.0)
    paper_forward_parser.add_argument("--max-latency-ms", type=float, default=2000.0)

    evidence_card_parser = subparsers.add_parser(
        "strategy-evidence-card",
        help="Build one compact Strategy Evidence Card for operate-loop candidate decisions.",
    )
    evidence_card_parser.add_argument("--input", help="Optional combined strategy-evidence-card input JSON.")
    evidence_card_parser.add_argument("--candidate-id", default="unknown")
    evidence_card_parser.add_argument("--data-matrix")
    evidence_card_parser.add_argument("--feature-audit")
    evidence_card_parser.add_argument("--strategy-tournament")
    evidence_card_parser.add_argument("--robust-evaluation")
    evidence_card_parser.add_argument("--sealed-holdout")
    evidence_card_parser.add_argument("--paper-forward-score")
    evidence_card_parser.add_argument("--promotion-governance-approved", action="store_true")
    evidence_card_parser.add_argument("--output", required=True, help="Path to write the strategy evidence card JSON.")

    improvement_parser = subparsers.add_parser(
        "loop-improvement-gate",
        help="Gate any strategy-improvement claim on loop, validation, and paper evidence.",
    )
    improvement_parser.add_argument("--ledger", required=True, help="Path to a loop-evidence-ledger JSON artifact.")
    improvement_parser.add_argument("--paper-dashboard", required=True, help="Path to a paper-session dashboard JSON artifact.")
    improvement_parser.add_argument("--postrun-summary", required=True, help="Path to a paper post-run summary JSON artifact.")
    improvement_parser.add_argument("--calibration-feedback", required=True, help="Path to a paper calibration feedback JSON artifact.")
    improvement_parser.add_argument("--data-sufficiency", help="Path to a strict data sufficiency JSON artifact.")
    improvement_parser.add_argument("--output", required=True, help="Path to write the improvement gate JSON.")
    improvement_parser.add_argument("--max-abs-slip-bps", type=float, default=25.0)
    improvement_parser.add_argument("--minimum-paper-orders", type=int, default=10)
    improvement_parser.add_argument("--minimum-telemetry-quality", type=float, default=0.70)

    trace_audit_ingest_parser = subparsers.add_parser("trace-audit-ingest", help="Ingest advisory findings as controlled taxonomy hints and planner notes.")
    trace_audit_ingest_parser.add_argument("--advisory-report", required=True, help="Path to a report-only advisory JSON artifact.")
    trace_audit_ingest_parser.add_argument("--trace-export", help="Optional trace audit export JSON to attach source-loop metadata.")
    trace_audit_ingest_parser.add_argument("--output", required=True, help="Path to write controlled trace advisory notes JSON.")

    research_debate_parser = subparsers.add_parser("research-debate-report", help="Write an internal report-only research debate artifact.")
    research_debate_parser.add_argument("--candidate-report", required=True, help="Path to a candidate report JSON artifact.")
    research_debate_parser.add_argument("--trace-advisory-notes", help="Optional controlled trace advisory notes JSON artifact.")
    research_debate_parser.add_argument("--output", required=True, help="Path to write the research debate report JSON.")

    compare_parser = subparsers.add_parser("compare-runs", help="Compare two dashboard artifacts and emit JSON deltas.")
    compare_parser.add_argument("--left", required=True, help="Path to the left dashboard JSON artifact.")
    compare_parser.add_argument("--right", required=True, help="Path to the right dashboard JSON artifact.")
    compare_parser.add_argument(
        "--kind",
        choices=["dashboard", "runcard", "autoresearch", "batch", "campaign"],
        default="dashboard",
        help="Which artifact type is being compared.",
    )
    compare_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format for the comparison.")
    compare_parser.add_argument("--output", help="Optional file path to write the comparison JSON.")

    compare_duplicate_parser = subparsers.add_parser("compare-duplicate-match", help="Compare a skipped autoresearch report against its matched prior run from memory.")
    compare_duplicate_parser.add_argument("--autoresearch-report", required=True, help="Path to a saved *.autoresearch.json artifact.")
    compare_duplicate_parser.add_argument("--config", required=True, help="Path to the study JSON config that produced the skipped autoresearch report.")
    compare_duplicate_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    compare_duplicate_parser.add_argument("--format", choices=["json", "text"], default="text", help="Output format for the duplicate comparison.")

    accept_duplicate_parser = subparsers.add_parser("accept-duplicate-match", help="Materialize a skipped duplicate autoresearch match as a new follow-up study config.")
    accept_duplicate_parser.add_argument("--autoresearch-report", required=True, help="Path to a saved *.autoresearch.json artifact.")
    accept_duplicate_parser.add_argument("--config", required=True, help="Path to the study JSON config that produced the skipped autoresearch report.")
    accept_duplicate_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    accept_duplicate_parser.add_argument("--output-config", required=True, help="Path to write the accepted follow-up study config.")

    continue_accepted_duplicate_parser = subparsers.add_parser(
        "continue-accepted-duplicate",
        help="Run an accepted-duplicate recovery config through a new autoresearch cycle.",
    )
    continue_accepted_duplicate_parser.add_argument("--autoresearch-report", required=True, help="Path to a saved *.autoresearch.json artifact.")
    continue_accepted_duplicate_parser.add_argument("--output-dir", required=True, help="Directory for the continued autoresearch artifacts.")
    continue_accepted_duplicate_parser.add_argument("--db", required=True, help="SQLite database file for research memory.")
    continue_accepted_duplicate_parser.add_argument("--memory-dir", help="Optional directory of prior artifacts to ingest before the continued run.")
    continue_accepted_duplicate_parser.add_argument("--memory-limit", type=int, default=25, help="Maximum prior memory rows to summarize.")
    continue_accepted_duplicate_parser.add_argument(
        "--memory-quality-policy",
        choices=["clean-only", "all"],
        default="clean-only",
        help="Which memory rows autoresearch should use for follow-up hypotheses.",
    )
    continue_accepted_duplicate_parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Block the continued run when the accepted-duplicate study snapshot carries quality flags.",
    )

    list_parser = subparsers.add_parser("list-runs", help="List saved RunCard artifacts from a directory.")
    list_parser.add_argument("--dir", required=True, help="Directory containing *.runcard.json artifacts.")
    list_parser.add_argument("--sort-by", default="selection_oos_sharpe", help="Metric name to rank by.")
    list_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of runs to show.")
    list_parser.add_argument("--decision", help="Optional decision filter, e.g. promoted or blocked.")
    list_parser.add_argument("--symbol", help="Optional symbol filter, e.g. SOLUSDT.")
    list_parser.add_argument("--quality-status", choices=["clean", "dirty"], help="Optional snapshot quality filter.")
    list_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format for the run listing.")

    list_campaigns_parser = subparsers.add_parser("list-campaigns", help="List saved campaign artifacts from a directory.")
    list_campaigns_parser.add_argument("--dir", required=True, help="Directory containing *.campaign.json artifacts.")
    list_campaigns_parser.add_argument("--sort-by", default="completed_entries", help="Campaign metric to rank by.")
    list_campaigns_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of campaigns to show.")
    list_campaigns_parser.add_argument("--status", help="Optional campaign status filter.")
    list_campaigns_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format for the campaign listing.")
