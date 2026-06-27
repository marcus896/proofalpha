from __future__ import annotations

import argparse


def register_memory_commands(subparsers: argparse._SubParsersAction) -> None:
    ingest_memory_parser = subparsers.add_parser("ingest-memory", help="Ingest saved run artifacts into local SQLite research memory.")
    ingest_memory_parser.add_argument("--dir", required=True, help="Directory containing saved *.runcard.json artifacts.")
    ingest_memory_parser.add_argument("--db", required=True, help="SQLite database file to create or update.")

    query_memory_parser = subparsers.add_parser("query-memory", help="Query local SQLite research memory explicitly.")
    query_memory_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    query_memory_parser.add_argument("--symbol", help="Optional symbol filter, e.g. SOLUSDT.")
    query_memory_parser.add_argument("--layer", help="Optional phase-layer filter, e.g. kama.")
    query_memory_parser.add_argument("--decision", help="Optional run decision filter, e.g. promoted.")
    query_memory_parser.add_argument("--quality-status", choices=["clean", "dirty"], help="Optional snapshot quality filter.")
    query_memory_parser.add_argument("--build-version", help="Optional snapshot build-version filter.")
    query_memory_parser.add_argument("--source-hash", help="Optional snapshot source-hash filter.")
    query_memory_parser.add_argument("--selected-variant", help="Optional lineage filter, e.g. balanced.")
    query_memory_parser.add_argument("--parent-batch-run-id", help="Optional parent batch run id filter.")
    query_memory_parser.add_argument("--accepted-duplicate-match-run-id", help="Optional accepted-duplicate lineage filter.")
    query_memory_parser.add_argument(
        "--candidate-pressure-only",
        action="store_true",
        help="Only return runs whose candidate trials recorded partial-fill pressure.",
    )
    query_memory_parser.add_argument(
        "--sort-by",
        choices=["sharpe", "candidate_worst_fill"],
        default="sharpe",
        help="Optional memory result ordering.",
    )
    query_memory_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of memory rows to return.")
    query_memory_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format for the memory query.")

    query_candidate_trials_parser = subparsers.add_parser("query-candidate-trials", help="Query first-class candidate trial lineage rows.")
    query_candidate_trials_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    query_candidate_trials_parser.add_argument("--run-id", help="Optional run id filter.")
    query_candidate_trials_parser.add_argument("--layer", help="Optional phase-layer filter, e.g. kama.")
    query_candidate_trials_parser.add_argument("--decision", help="Optional candidate decision filter, e.g. accept.")
    query_candidate_trials_parser.add_argument("--pressured-only", action="store_true", help="Only return candidate trials that recorded partial-fill pressure.")
    query_candidate_trials_parser.add_argument("--sort-by", choices=["rank", "worst_fill"], default="rank", help="Optional candidate-trial result ordering.")
    query_candidate_trials_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of candidate trials to return.")
    query_candidate_trials_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format for the candidate-trial query.")

    query_validation_runs_parser = subparsers.add_parser("query-validation-runs", help="Query first-class validation lineage rows.")
    query_validation_runs_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    query_validation_runs_parser.add_argument("--run-id", help="Optional run id filter.")
    query_validation_runs_parser.add_argument("--validation-status", help="Optional validation status filter.")
    query_validation_runs_parser.add_argument("--min-dsr", type=float, help="Optional minimum DSR filter.")
    query_validation_runs_parser.add_argument("--max-pbo", type=float, help="Optional maximum PBO filter.")
    query_validation_runs_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of validation rows to return.")
    query_validation_runs_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    query_stress_runs_parser = subparsers.add_parser("query-stress-runs", help="Query first-class stress lineage rows.")
    query_stress_runs_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    query_stress_runs_parser.add_argument("--run-id", help="Optional run id filter.")
    query_stress_runs_parser.add_argument("--scenario-name", help="Optional scenario-name filter.")
    query_stress_runs_parser.add_argument("--passed", choices=["true", "false"], help="Optional passed filter.")
    query_stress_runs_parser.add_argument("--target-regime", help="Optional target-regime filter.")
    query_stress_runs_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of stress rows to return.")
    query_stress_runs_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    query_agent_decisions_parser = subparsers.add_parser("query-agent-decisions", help="Query first-class agent decision lineage rows.")
    query_agent_decisions_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    query_agent_decisions_parser.add_argument("--run-id", help="Optional run id filter.")
    query_agent_decisions_parser.add_argument("--decision-family", help="Optional decision-family filter.")
    query_agent_decisions_parser.add_argument("--decision", help="Optional decision filter.")
    query_agent_decisions_parser.add_argument("--validation-status", help="Optional validation-status filter.")
    query_agent_decisions_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of decision rows to return.")
    query_agent_decisions_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    query_data_snapshots_parser = subparsers.add_parser("query-data-snapshots", help="Query first-class snapshot lineage rows.")
    query_data_snapshots_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    query_data_snapshots_parser.add_argument("--snapshot-id", help="Optional snapshot id filter.")
    query_data_snapshots_parser.add_argument("--symbol", help="Optional symbol filter.")
    query_data_snapshots_parser.add_argument("--venue", help="Optional venue filter.")
    query_data_snapshots_parser.add_argument("--build-version", help="Optional build-version filter.")
    query_data_snapshots_parser.add_argument("--source-hash", help="Optional source-hash filter.")
    query_data_snapshots_parser.add_argument("--quality-status", help="Optional quality-status filter.")
    query_data_snapshots_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of snapshot rows to return.")
    query_data_snapshots_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    query_resource_index_parser = subparsers.add_parser("query-resource-index", help="Query first-class resource provenance catalog rows.")
    query_resource_index_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    query_resource_index_parser.add_argument("--resource-group", help="Optional resource-group filter.")
    query_resource_index_parser.add_argument("--status", help="Optional status filter.")
    query_resource_index_parser.add_argument("--license", help="Optional license filter.")
    query_resource_index_parser.add_argument("--intended-usage", help="Optional intended-usage filter.")
    query_resource_index_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of resource rows to return.")
    query_resource_index_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    query_run_resource_links_parser = subparsers.add_parser("query-run-resource-links", help="Query explicit per-run resource provenance links.")
    query_run_resource_links_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    query_run_resource_links_parser.add_argument("--run-id", help="Optional run id filter.")
    query_run_resource_links_parser.add_argument("--resource-id", help="Optional resource id filter.")
    query_run_resource_links_parser.add_argument("--link-role", help="Optional link-role filter.")
    query_run_resource_links_parser.add_argument("--evidence-source", help="Optional evidence-source filter.")
    query_run_resource_links_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of resource-link rows to return.")
    query_run_resource_links_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    query_meta_policies_parser = subparsers.add_parser("query-meta-policies", help="Query first-class meta-policy lineage rows.")
    query_meta_policies_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    query_meta_policies_parser.add_argument("--run-id", help="Optional run id filter.")
    query_meta_policies_parser.add_argument("--policy-family", help="Optional policy-family filter.")
    query_meta_policies_parser.add_argument("--status", help="Optional status filter.")
    query_meta_policies_parser.add_argument("--eval-validation-run-id", help="Optional eval-validation-run-id filter.")
    query_meta_policies_parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of meta-policy rows to return.")
    query_meta_policies_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    summarize_memory_parser = subparsers.add_parser("summarize-memory", help="Summarize memory insights without running autoresearch.")
    summarize_memory_parser.add_argument("--db", required=True, help="SQLite database file created by ingest-memory.")
    summarize_memory_parser.add_argument("--symbol", help="Optional symbol filter, e.g. SOLUSDT.")
    summarize_memory_parser.add_argument("--limit", type=int, default=25, help="Maximum prior memory rows to summarize.")
    summarize_memory_parser.add_argument(
        "--memory-quality-policy",
        choices=["clean-only", "all"],
        default="clean-only",
        help="Which memory rows to use when building the summary.",
    )
    summarize_memory_parser.add_argument("--format", choices=["json", "text"], default="text", help="Output format for the memory summary.")
