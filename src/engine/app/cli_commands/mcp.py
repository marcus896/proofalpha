from __future__ import annotations

import argparse


MCP_PROFILE_CHOICES = ["read_only", "launcher", "discovery"]


def register_mcp_commands(subparsers: argparse._SubParsersAction) -> None:
    subparsers.add_parser("mcp-list-profiles", help="List available MCP agent profiles.")

    mcp_tools_parser = subparsers.add_parser(
        "mcp-list-tools",
        help="List MCP tools available in a given profile.",
    )
    mcp_tools_parser.add_argument(
        "--profile",
        default="read_only",
        choices=MCP_PROFILE_CHOICES,
        help="MCP agent profile (default: read_only).",
    )

    mcp_call_parser = subparsers.add_parser(
        "mcp-call",
        help="Call an MCP tool by name with a JSON params payload.",
    )
    mcp_call_parser.add_argument("--profile", default="read_only", choices=MCP_PROFILE_CHOICES)
    mcp_call_parser.add_argument("--tool", required=True, help="Tool name to call.")
    mcp_call_parser.add_argument("--params", default="{}", help="JSON params dict for the tool.")
    mcp_call_parser.add_argument("--output-dir", required=True, help="Engine output directory.")
    mcp_call_parser.add_argument("--db", default="outputs/research-memory.sqlite", help="SQLite memory DB path.")
