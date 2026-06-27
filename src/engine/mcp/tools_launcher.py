from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from engine.mcp.config import MCPSettings

# These CLI verbs are unconditionally forbidden — no agent may invoke them
# through the LauncherMCP, regardless of profile.
LAUNCHER_FORBIDDEN_ACTIONS: frozenset[str] = frozenset(
    [
        # write / destructive filesystem ops
        "ingest-memory",
        "refresh-examples",
        "init-example",
        "init-example-bundle",
        # live exchange / order submission paths
        "trade",
        "order",
        "submit",
        "execute-live",
        # arbitrary shell
        "shell",
        "exec",
        "eval",
    ]
)

# Explicit allowlist of verbs that LocalLauncherMCP may call
LAUNCHER_ALLOWED_VERBS: frozenset[str] = frozenset(
    [
        "run",
        "autoresearch",
        "batch-autoresearch",
        "agent-loop",
        "run-campaign",
        "retry-campaign",
        "inspect-study",
        "inspect-campaign",
        "select-batch-variant",
        "continue-batch",
        "continue-accepted-duplicate",
        "accept-duplicate-match",
        "trace-lineage",
    ]
)


def _is_forbidden(verb: str) -> bool:
    if verb in LAUNCHER_FORBIDDEN_ACTIONS:
        return True
    if verb not in LAUNCHER_ALLOWED_VERBS:
        return True  # deny-by-default: if not explicitly allowed → blocked
    return False


def tool_create_study(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    if not settings.launcher_enabled:
        return {"error": "launcher is disabled in this profile"}
    verb = "run"
    config_path = params.get("config_path")
    if not isinstance(config_path, str):
        return {"error": "config_path is required"}
    extra_args: list[str] = []
    seed = params.get("seed")
    if isinstance(seed, int):
        extra_args += ["--seed", str(seed)]
    return _invoke_engine_cli(verb, [config_path, *extra_args])


def tool_create_autoresearch(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    if not settings.launcher_enabled:
        return {"error": "launcher is disabled in this profile"}
    verb = "autoresearch"
    config_path = params.get("config_path")
    if not isinstance(config_path, str):
        return {"error": "config_path is required"}
    extra_args: list[str] = []
    max_cycles = params.get("max_cycles")
    if isinstance(max_cycles, int):
        extra_args += ["--max-cycles", str(max_cycles)]
    return _invoke_engine_cli(verb, [config_path, *extra_args])


def tool_create_campaign(
    params: dict[str, object],
    *,
    settings: MCPSettings,
    output_dir: Path,
    db_path: Path,
) -> dict[str, object]:
    if not settings.launcher_enabled:
        return {"error": "launcher is disabled in this profile"}
    verb = "run-campaign"
    campaign_path = params.get("campaign_path")
    if not isinstance(campaign_path, str):
        return {"error": "campaign_path is required"}
    return _invoke_engine_cli(verb, [campaign_path])


def _invoke_engine_cli(verb: str, extra_args: list[str]) -> dict[str, object]:
    if _is_forbidden(verb):
        return {"error": f"verb '{verb}' is forbidden or not in the launcher allowlist"}
    cmd = [sys.executable, "-m", "engine.app.cli", verb, *extra_args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[-8000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"error": "engine CLI timed out after 300 seconds"}
    except Exception as exc:
        return {"error": str(exc)}


LAUNCHER_TOOL_CATALOG: list[dict[str, object]] = [
    {
        "name": "create_study",
        "description": "Launch a single research study run via the engine CLI ('run' verb).",
        "parameters": {
            "type": "object",
            "required": ["config_path"],
            "properties": {
                "config_path": {"type": "string", "description": "Absolute path to the study config JSON file"},
                "seed": {"type": "integer", "description": "Random seed override"},
            },
        },
    },
    {
        "name": "create_autoresearch",
        "description": "Launch an autonomous research cycle via the engine CLI ('autoresearch' verb).",
        "parameters": {
            "type": "object",
            "required": ["config_path"],
            "properties": {
                "config_path": {"type": "string"},
                "max_cycles": {"type": "integer", "description": "Maximum number of agent cycles to run"},
            },
        },
    },
    {
        "name": "create_campaign",
        "description": "Launch a campaign run via the engine CLI ('run-campaign' verb).",
        "parameters": {
            "type": "object",
            "required": ["campaign_path"],
            "properties": {"campaign_path": {"type": "string"}},
        },
    },
]
