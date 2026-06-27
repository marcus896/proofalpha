from __future__ import annotations

import argparse


def register_paper_commands(subparsers: argparse._SubParsersAction) -> None:
    validate_artifact_parser = subparsers.add_parser(
        "validate-artifact",
        help="Validate an immutable strategy artifact and checksum.",
    )
    validate_artifact_parser.add_argument("--artifact", required=True, help="Path to a *.strategy-artifact.json file.")

    list_artifacts_parser = subparsers.add_parser(
        "list-artifacts",
        help="List immutable strategy artifacts in a directory.",
    )
    list_artifacts_parser.add_argument("--dir", required=True, help="Directory containing *.strategy-artifact.json files.")

    paper_run_artifact_parser = subparsers.add_parser(
        "paper-run-artifact",
        help="Run the fixture paper executor from an approved immutable artifact.",
    )
    paper_run_artifact_parser.add_argument("--artifact", required=True, help="Path to an approved strategy artifact.")
    paper_run_artifact_parser.add_argument("--market-fixture", required=True, help="Path to paper market fixture JSON.")

    paper_daemon_parser = subparsers.add_parser(
        "paper-daemon",
        help="Run the Phase 9A fixture paper daemon without network or private keys.",
    )
    paper_daemon_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_daemon_parser.add_argument("--artifact", action="append", required=True, help="Approved strategy artifact path. Can repeat.")
    paper_daemon_parser.add_argument("--market-fixture", required=True, help="Path to paper market fixture JSON.")
    paper_daemon_parser.add_argument("--session-id", help="Optional deterministic paper session id.")
    paper_daemon_parser.add_argument("--host-id", help="Optional executor host id.")
    paper_daemon_parser.add_argument("--portfolio-plan-id", help="Optional linked portfolio plan id.")
    paper_daemon_parser.add_argument("--dry-run", action="store_true", help="Required for the current fixture daemon.")
    paper_daemon_parser.add_argument("--max-per-symbol-notional", type=float, default=100000.0)
    paper_daemon_parser.add_argument("--max-aggregate-notional", type=float, default=250000.0)
    paper_daemon_parser.add_argument("--max-spread-bps", type=float, default=25.0)
    paper_daemon_parser.add_argument("--min-visible-depth-qty", type=float, default=0.0)
    paper_daemon_parser.add_argument("--max-order-rate-per-minute", type=int, default=60)

    paper_status_parser = subparsers.add_parser(
        "paper-status",
        help="Read Phase 9A paper session status from memory.",
    )
    paper_status_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_status_parser.add_argument("--session-id", help="Optional paper session id. Defaults to latest.")

    paper_dashboard_parser = subparsers.add_parser(
        "paper-session-dashboard",
        help="Build a compact Phase 9A paper session dashboard artifact.",
    )
    paper_dashboard_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_dashboard_parser.add_argument("--session-id", help="Optional paper session id. Defaults to latest.")
    paper_dashboard_parser.add_argument("--output", required=True, help="Path to write dashboard JSON.")
    paper_dashboard_parser.add_argument("--now", help="Optional UTC timestamp for freshness checks.")
    paper_dashboard_parser.add_argument("--max-stream-staleness-seconds", type=int, default=300)

    paper_ws_collect_parser = subparsers.add_parser(
        "paper-ws-collect",
        help="Run a Phase 9A public Binance WS collector from a deterministic fixture.",
    )
    paper_ws_collect_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_ws_collect_parser.add_argument("--artifact", action="append", required=True, help="Approved strategy artifact path. Can repeat.")
    paper_ws_collect_parser.add_argument("--fixture", required=True, help="JSON fixture with mocked public WS items.")
    paper_ws_collect_parser.add_argument("--session-id", help="Optional deterministic paper session id.")
    paper_ws_collect_parser.add_argument("--host-id", help="Optional executor host id.")
    paper_ws_collect_parser.add_argument("--symbol", action="append", default=[], help="Symbol to subscribe. Can repeat.")
    paper_ws_collect_parser.add_argument("--stream-kind", action="append", default=[], help="Stream kind to subscribe. Can repeat.")
    paper_ws_collect_parser.add_argument("--max-stream-staleness-seconds", type=int, default=300)

    paper_ws_run_parser = subparsers.add_parser(
        "paper-ws-run",
        help="Run a Phase 9A live public Binance WS collector. Uses no private keys.",
    )
    paper_ws_run_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_ws_run_parser.add_argument("--artifact", action="append", default=[], help="Approved strategy artifact path. Can repeat.")
    paper_ws_run_parser.add_argument("--capture-only", action="store_true", help="Allow public market-data capture without linking a strategy artifact.")
    paper_ws_run_parser.add_argument("--session-id", help="Optional deterministic paper session id.")
    paper_ws_run_parser.add_argument("--host-id", help="Optional executor host id.")
    paper_ws_run_parser.add_argument("--symbol", action="append", default=[], help="Symbol to subscribe. Can repeat.")
    paper_ws_run_parser.add_argument("--stream-kind", action="append", default=[], help="Stream kind to subscribe. Can repeat.")
    paper_ws_run_parser.add_argument("--max-stream-staleness-seconds", type=int, default=300)
    paper_ws_run_parser.add_argument("--max-messages", type=int, help="Optional stop after this many public WS messages.")
    paper_ws_run_parser.add_argument("--max-duration-seconds", type=float, help="Optional stop after this many wall-clock seconds.")
    paper_ws_run_parser.add_argument("--no-message-timeout-seconds", type=float, help="Optional stop when no public WS message arrives within this many seconds.")
    paper_ws_run_parser.add_argument("--heartbeat-interval-seconds", type=float, help="Optional executor health heartbeat cadence.")
    paper_ws_run_parser.add_argument("--reconnect-attempts", type=int, default=3)
    paper_ws_run_parser.add_argument("--backoff-seconds", type=float, default=1.0)

    paper_replay_parser = subparsers.add_parser(
        "paper-replay",
        help="Replay recorded paper stream events and emit deterministic checksums.",
    )
    paper_replay_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_replay_parser.add_argument("--session-id", required=True, help="Paper session id to replay.")
    paper_replay_parser.add_argument("--output", help="Optional path to write replay JSON.")

    paper_export_parser = subparsers.add_parser(
        "paper-export",
        help="Export a Phase 9A paper session bundle and optional restore smoke check.",
    )
    paper_export_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_export_parser.add_argument("--session-id", required=True, help="Paper session id to export.")
    paper_export_parser.add_argument("--output-dir", required=True, help="Directory for the export bundle.")
    paper_export_parser.add_argument("--restore-smoke-db", help="Optional fresh SQLite DB path for restore smoke.")

    paper_host_doctor_parser = subparsers.add_parser(
        "paper-host-doctor",
        help="Check Phase 9A hosted paper executor directories, SQLite, disk, and no-secret templates.",
    )
    paper_host_doctor_parser.add_argument("--repo-dir", default="/opt/trading-strategy")
    paper_host_doctor_parser.add_argument("--state-dir", default="/var/lib/trading-strategy")
    paper_host_doctor_parser.add_argument("--log-dir", default="/var/log/trading-strategy")
    paper_host_doctor_parser.add_argument("--backup-dir", default="/var/backups/trading-strategy")
    paper_host_doctor_parser.add_argument("--db", default="/var/lib/trading-strategy/memory.sqlite")
    paper_host_doctor_parser.add_argument("--template-root", default="deploy")
    paper_host_doctor_parser.add_argument("--min-free-mb", type=int, default=1024)
    paper_host_doctor_parser.add_argument(
        "--write-templates",
        action="store_true",
        help="Write safe systemd/env/logrotate templates under --template-root before checking.",
    )

    paper_book_replay_parser = subparsers.add_parser(
        "paper-book-replay",
        help="Rebuild and persist local paper order-book state from recorded depth events.",
    )
    paper_book_replay_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_book_replay_parser.add_argument("--session-id", required=True, help="Paper session id to replay.")
    paper_book_replay_parser.add_argument("--snapshot", required=True, help="JSON file with REST depth snapshots.")
    paper_book_replay_parser.add_argument("--now", help="Optional UTC timestamp for staleness checks.")
    paper_book_replay_parser.add_argument("--max-staleness-ms", type=int, default=5000)
    paper_book_replay_parser.add_argument("--output", help="Optional path to write book-state JSON.")

    paper_phase9a_closeout_parser = subparsers.add_parser(
        "paper-phase9a-closeout",
        help="Build Phase 9A closeout proof from a paper session.",
    )
    paper_phase9a_closeout_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_phase9a_closeout_parser.add_argument("--session-id", required=True, help="Paper session id.")
    paper_phase9a_closeout_parser.add_argument("--export-dir", required=True, help="Directory for closeout export bundle.")
    paper_phase9a_closeout_parser.add_argument("--restore-db", required=True, help="Fresh SQLite DB path for restore proof.")
    paper_phase9a_closeout_parser.add_argument("--hosted-repo-dir", required=True)
    paper_phase9a_closeout_parser.add_argument("--hosted-state-dir", required=True)
    paper_phase9a_closeout_parser.add_argument("--hosted-log-dir", required=True)
    paper_phase9a_closeout_parser.add_argument("--hosted-backup-dir", required=True)
    paper_phase9a_closeout_parser.add_argument("--hosted-template-root", required=True)
    paper_phase9a_closeout_parser.add_argument("--minimum-soak-seconds", type=int, default=0)
    paper_phase9a_closeout_parser.add_argument("--require-live-network-soak", action="store_true")
    paper_phase9a_closeout_parser.add_argument("--output", help="Optional path to write closeout report JSON.")

    paper_soak_closeout_parser = subparsers.add_parser(
        "paper-soak-closeout",
        help="Build strict Phase 1 public-WS soak closeout proof. Uses no private keys.",
    )
    paper_soak_closeout_parser.add_argument("--db", required=True, help="SQLite memory DB.")
    paper_soak_closeout_parser.add_argument("--session-id", required=True, help="Paper session id.")
    paper_soak_closeout_parser.add_argument("--export-dir", required=True, help="Directory for closeout export bundle.")
    paper_soak_closeout_parser.add_argument("--restore-db", required=True, help="Fresh SQLite DB path for restore proof.")
    paper_soak_closeout_parser.add_argument("--hosted-repo-dir", required=True)
    paper_soak_closeout_parser.add_argument("--hosted-state-dir", required=True)
    paper_soak_closeout_parser.add_argument("--hosted-log-dir", required=True)
    paper_soak_closeout_parser.add_argument("--hosted-backup-dir", required=True)
    paper_soak_closeout_parser.add_argument("--hosted-template-root", required=True)
    paper_soak_closeout_parser.add_argument("--minimum-soak-seconds", type=int, required=True)
    paper_soak_closeout_parser.add_argument("--output", required=True, help="Output public-WS soak closeout JSON path.")
