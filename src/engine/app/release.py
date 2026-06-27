from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from engine import __version__
from engine.app.campaigns import expand_campaign_manifest
from engine.app.config import load_study_config
from engine.app.schema import build_study_schema


def build_release_doctor_payload(repo_root: Path) -> dict[str, object]:
    checks = [
        _check_readme(repo_root),
        _check_pyproject(repo_root),
        _check_builtin_example(repo_root),
        _check_campaign_example(repo_root),
        _check_schema_artifact(repo_root),
        _check_python_runtime(),
        _check_websocket_dependency(),
    ]
    status = "ok" if all(check["status"] == "ok" for check in checks) else "failed"
    return {
        "status": status,
        "version": __version__,
        "repo_root": str(repo_root),
        "check_count": len(checks),
        "checks": checks,
    }


def render_release_doctor_payload(payload: dict[str, object], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(payload, sort_keys=True)

    lines = [
        f"Release doctor: {payload.get('status', 'unknown')}",
        f"Version: {payload.get('version', 'unknown')}",
        f"Checks: {payload.get('check_count', 0)}",
    ]
    for check in payload.get("checks", []):
        if not isinstance(check, dict):
            continue
        lines.append(f"- {check.get('name', 'unknown')}: {check.get('status', 'unknown')} | {check.get('detail', '')}")
    return "\n".join(lines)


def _check_readme(repo_root: Path) -> dict[str, object]:
    readme_path = repo_root / "README.md"
    if not readme_path.exists():
        return _failed_check("readme", "README.md is missing")
    content = readme_path.read_text(encoding="utf-8")
    required_snippets = [
        "# Crypto Perps Stress Research Engine",
        "python -m engine.app.cli run",
        "python -m engine.app.cli doctor",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in content]
    if missing:
        return _failed_check("readme", f"README.md is missing expected content: {', '.join(missing)}")
    return _ok_check("readme", "README.md present with quickstart and doctor guidance")


def _check_pyproject(repo_root: Path) -> dict[str, object]:
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        return _failed_check("pyproject", "pyproject.toml is missing")
    content = pyproject_path.read_text(encoding="utf-8")
    required_snippets = [
        'name = "proofalpha"',
        f'version = "{__version__}"',
        'readme = "README.md"',
        'proofalpha = "proofalpha.runtime:main"',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in content]
    if missing:
        return _failed_check("pyproject", f"pyproject.toml is missing expected metadata: {', '.join(missing)}")
    return _ok_check("pyproject", "project metadata and console script are present")


def _check_builtin_example(repo_root: Path) -> dict[str, object]:
    config_path = repo_root / "examples" / "minimal_builtin_study.json"
    if not config_path.exists():
        return _failed_check("builtin_example", "minimal builtin study is missing")
    study = load_study_config(config_path)
    if study.runtime_mode != "builtin":
        return _failed_check("builtin_example", f"unexpected runtime mode: {study.runtime_mode}")
    return _ok_check("builtin_example", f"{config_path.name} loads in builtin mode")


def _check_campaign_example(repo_root: Path) -> dict[str, object]:
    manifest_path = repo_root / "examples" / "minimal_campaign.json"
    if not manifest_path.exists():
        return _failed_check("campaign_example", "minimal campaign manifest is missing")
    payload = expand_campaign_manifest(manifest_path, manifest_path.with_suffix(".campaign.json"))
    entries = payload.get("entries", [])
    if not isinstance(entries, list) or len(entries) < 2:
        return _failed_check("campaign_example", "minimal campaign manifest did not expand to at least two entries")
    return _ok_check("campaign_example", f"{manifest_path.name} expands to {len(entries)} entries")


def _check_schema_artifact(repo_root: Path) -> dict[str, object]:
    schema_path = repo_root / "examples" / "study.schema.json"
    if not schema_path.exists():
        return _failed_check("schema_artifact", "study schema artifact is missing")
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    if payload != build_study_schema():
        return _failed_check("schema_artifact", "checked-in schema does not match runtime builder")
    return _ok_check("schema_artifact", "checked-in schema matches runtime builder")


def _check_python_runtime() -> dict[str, object]:
    version = sys.version_info
    if (version.major, version.minor) < (3, 12) or (version.major, version.minor) >= (3, 14):
        return _failed_check(
            "python_runtime",
            f"unsupported Python runtime: {version.major}.{version.minor}.{version.micro}; expected >=3.12,<3.14",
        )
    return _ok_check("python_runtime", f"supported Python runtime: {version.major}.{version.minor}.{version.micro}")


def _check_websocket_dependency() -> dict[str, object]:
    if importlib.util.find_spec("websockets.sync.client") is None:
        return _failed_check("websocket_dependency", "websockets.sync.client is unavailable")
    return _ok_check("websocket_dependency", "websockets sync client is available")


def _ok_check(name: str, detail: str) -> dict[str, object]:
    return {"name": name, "status": "ok", "detail": detail}


def _failed_check(name: str, detail: str) -> dict[str, object]:
    return {"name": name, "status": "failed", "detail": detail}
