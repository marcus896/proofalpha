from __future__ import annotations

import argparse


def register_project_status_commands(subparsers: argparse._SubParsersAction) -> None:
    project_status_parser = subparsers.add_parser(
        "project-status",
        help="Read or update the repo-enforced implementation status ledger.",
    )
    project_status_parser.add_argument(
        "--status-json",
        default="PLAN_STATUS.json",
        help="Path to the structured project status JSON ledger.",
    )
    project_status_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format.",
    )
    project_status_subparsers = project_status_parser.add_subparsers(dest="project_status_action")
    project_status_update_parser = project_status_subparsers.add_parser(
        "update",
        help="Update a phase or task in the project status ledger.",
    )
    project_status_update_parser.add_argument("--phase", required=True, help="Phase or task id to update.")
    project_status_update_parser.add_argument(
        "--status",
        required=True,
        choices=["planned", "in_progress", "done", "blocked", "deferred"],
        help="New phase status.",
    )
    project_status_update_parser.add_argument(
        "--status-json",
        default="PLAN_STATUS.json",
        help="Path to the structured project status JSON ledger.",
    )
    project_status_update_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format.",
    )
    project_status_update_parser.add_argument("--note", help="Optional note to append to the phase notes.")
    project_status_update_parser.add_argument("--set-next", help="Optional phase id to set as the next resume target.")
    project_status_update_parser.add_argument(
        "--execution-state",
        help="Optional top-level execution-state override.",
    )
