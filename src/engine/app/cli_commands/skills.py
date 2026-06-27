from __future__ import annotations

import argparse


def register_skill_commands(subparsers: argparse._SubParsersAction) -> None:
    list_skills_parser = subparsers.add_parser("list-skills", help="List repo-local skill contracts.")
    list_skills_parser.add_argument("--format", choices=["json", "text"], default="text")

    inspect_skill_parser = subparsers.add_parser("inspect-skill", help="Show one repo-local skill contract.")
    inspect_skill_parser.add_argument("--name", required=True, help="Skill name, e.g. strategy-composer.")
    inspect_skill_parser.add_argument("--format", choices=["json", "text"], default="text")
