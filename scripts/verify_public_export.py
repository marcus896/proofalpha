"""Verify the sanitized ProofAlpha export before publication."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_ROOT_NAMES = {
    ".agents",
    ".private-core-staging",
    ".release-venv",
    ".claude",
    ".deps",
    ".vendor",
    ".venv312",
    ".venv-timesfm",
    "build",
    "dist",
    "external_repos",
    "models",
    "outputs",
    "planning",
    "public_overrides",
    "references",
    "vendor_duckdb",
    "vendor_duckdb_open",
}

FORBIDDEN_SUFFIXES = {
    ".db",
    ".key",
    ".log",
    ".p12",
    ".parquet",
    ".pem",
    ".pfx",
    ".pickle",
    ".pkl",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
}

FORBIDDEN_FINAL_PATHS = {
    Path("CODEX_AGENT_EXECUTION_PROMPT.md"),
    Path("IMPLEMENTATION_MASTER_PLAN.md"),
    Path("OPEN_SOURCE_LAUNCH_CHECKLIST.md"),
    Path("PLAN_STATUS.json"),
    Path(".github/CODEOWNERS"),
    Path("docs/ADOPTION_METRICS.md"),
    Path("docs/CODEX_FOR_OSS_READINESS.md"),
    Path("scripts/import_private_core.ps1"),
    Path("scripts/clean_export_artifacts.ps1"),
    Path("src/proofalpha/cli.py"),
    Path("src/proofalpha/__main__.py"),
}

REQUIRED_PATHS = {
    Path("README.md"),
    Path("LICENSE"),
    Path("DISCLAIMER.md"),
    Path("SECURITY.md"),
    Path("CONTRIBUTING.md"),
    Path("THIRD_PARTY_NOTICES.md"),
    Path("pyproject.toml"),
    Path("requirements-core.txt"),
    Path("src/engine/__init__.py"),
    Path("src/engine/app/cli.py"),
    Path("src/proofalpha/__init__.py"),
    Path("src/proofalpha/runtime.py"),
    Path("assets/brand/proofalpha-mark.svg"),
    Path("PUBLIC_EXPORT_MANIFEST.json"),
}

ABSOLUTE_USER_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:/Users/[^/\s]+/"),
    re.compile(r"(?i)(?<![A-Za-z0-9_])/home/[^/\s]+/"),
    re.compile(r"(?i)(?<![A-Za-z0-9_])/Users/[^/\s]+/"),
)

FORBIDDEN_PUBLIC_TEXT = (
    re.compile(r"\bOWNER/proofalpha\b"),
    re.compile(r"@OWNER\b"),
    re.compile(r"github\.com/OWNER/proofalpha", re.IGNORECASE),
    re.compile(r"private-source preflight", re.IGNORECASE),
    re.compile(r"allowlisted sanitized export", re.IGNORECASE),
    re.compile(r"separately maintained private repository", re.IGNORECASE),
)

TEXT_SUFFIXES = {
    "",
    ".cff",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

LOCAL_GENERATED_ROOT_NAMES = {
    ".pytest_cache",
    "build",
    "dist",
    "outputs",
}


def _is_local_generated_path(relative: Path) -> bool:
    if "__pycache__" in relative.parts:
        return True
    if relative.parts and (relative.parts[0] in LOCAL_GENERATED_ROOT_NAMES or relative.parts[0].startswith("test-output-")):
        return True
    if any(part.lower().endswith(".egg-info") for part in relative.parts):
        return True
    return relative.suffix.lower() in {".pyc", ".pyo"}


def _tracked_files(root: Path) -> list[Path]:
    process = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0 or not process.stdout:
        return []
    return [root / Path(item.decode("utf-8")) for item in process.stdout.split(b"\0") if item]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--allow-export-script", action="store_true")
    return parser.parse_args()


def iter_files(root: Path) -> list[Path]:
    tracked = _tracked_files(root)
    if tracked:
        return [path for path in tracked if path.is_file()]

    result: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if ".git" in relative.parts or _is_local_generated_path(relative):
            continue
        result.append(path)
    return result


def verify_structure(
    root: Path,
    files: list[Path],
    *,
    allow_export_script: bool = False,
) -> list[str]:
    findings: list[str] = []
    for required in sorted(REQUIRED_PATHS):
        if not (root / required).is_file():
            findings.append(f"missing required file: {required.as_posix()}")

    for forbidden in sorted(FORBIDDEN_FINAL_PATHS):
        if allow_export_script and forbidden == Path("scripts/import_private_core.ps1"):
            continue
        if (root / forbidden).exists():
            findings.append(f"internal export file remains: {forbidden.as_posix()}")

    for path in files:
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in FORBIDDEN_ROOT_NAMES:
            findings.append(f"forbidden root: {relative.as_posix()}")
        if any(part.lower().endswith(".egg-info") for part in relative.parts):
            findings.append(f"forbidden package build metadata: {relative.as_posix()}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"forbidden generated/private file: {relative.as_posix()}")
        if path.name.lower().startswith(".env") and path.name != ".env.example":
            findings.append(f"forbidden environment file: {relative.as_posix()}")
    return findings


def verify_text(root: Path, files: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in files:
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Dockerfile", "LICENSE"}:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        normalized = text.replace("\\", "/")
        relative = path.relative_to(root).as_posix()
        if relative != "scripts/verify_public_export.py" and any(
            pattern.search(normalized) for pattern in ABSOLUTE_USER_PATH_PATTERNS
        ):
            findings.append(f"absolute user path: {relative}")
        if relative != "scripts/verify_public_export.py" and any(
            pattern.search(normalized) for pattern in FORBIDDEN_PUBLIC_TEXT
        ):
            findings.append(f"unresolved internal/owner placeholder text: {relative}")
    return findings


def verify_python(root: Path, files: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in files:
        if path.suffix.lower() != ".py":
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path.relative_to(root)))
        except (UnicodeDecodeError, SyntaxError) as exc:
            findings.append(f"invalid Python {path.relative_to(root).as_posix()}: {exc}")
    return findings


def compute_engine_tree(root: Path) -> tuple[int, str]:
    engine_root = root / "src" / "engine"
    rows: list[str] = []
    if not engine_root.is_dir():
        return 0, ""
    for path in sorted(p for p in engine_root.rglob("*") if p.is_file()):
        relative_path = path.relative_to(root)
        if "__pycache__" in relative_path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        relative = relative_path.as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{relative}|{digest}")
    payload = ("\n".join(rows) + ("\n" if rows else "")).encode("utf-8")
    return len(rows), hashlib.sha256(payload).hexdigest() if rows else ""


def verify_manifest(root: Path) -> list[str]:
    path = root / "PUBLIC_EXPORT_MANIFEST.json"
    if not path.is_file():
        return ["missing PUBLIC_EXPORT_MANIFEST.json"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid export manifest: {exc}"]

    findings: list[str] = []
    if payload.get("source_path_recorded") is not False:
        findings.append("manifest must not record the private source path")
    if payload.get("live_execution_enabled") is not False:
        findings.append("manifest must keep live execution disabled")
    if payload.get("private_keys_required") is not False:
        findings.append("manifest must not require private keys")
    if not isinstance(payload.get("file_count"), int) or int(payload["file_count"]) <= 0:
        findings.append("manifest must record a positive exported file count")
    if not isinstance(payload.get("engine_file_count"), int) or int(payload["engine_file_count"]) <= 0:
        findings.append("manifest must record a positive engine file count")
    if not isinstance(payload.get("skill_file_count"), int) or int(payload["skill_file_count"]) <= 0:
        findings.append("manifest must record a positive skill file count")
    tree_hash = payload.get("engine_tree_sha256")
    if not isinstance(tree_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", tree_hash):
        findings.append("manifest must record a valid engine tree hash")
    if payload.get("source_hash_match") is not True:
        findings.append("manifest must confirm source hash match")

    current_count, current_hash = compute_engine_tree(root)
    if payload.get("engine_file_count") != current_count:
        findings.append("current engine file count does not match manifest")
    if payload.get("engine_tree_sha256") != current_hash:
        findings.append("current engine tree hash does not match manifest")

    source_skills = sorted((root / "skills").glob("*/SKILL.md"))
    packaged_root = root / "src" / "proofalpha" / "_skills"
    packaged_skills = sorted(packaged_root.glob("*/SKILL.md"))
    if payload.get("skill_file_count") != len(source_skills):
        findings.append("source skill count does not match manifest")
    if len(packaged_skills) != len(source_skills):
        findings.append("packaged skill count does not match source skills")
    for source_skill in source_skills:
        relative = source_skill.relative_to(root / "skills")
        packaged_skill = packaged_root / relative
        if not packaged_skill.is_file() or source_skill.read_bytes() != packaged_skill.read_bytes():
            findings.append(f"packaged skill mismatch: {relative.as_posix()}")
    return findings


def run_secret_scan(root: Path) -> list[str]:
    scanner = root / "scripts" / "check_repository_secrets.py"
    process = subprocess.run(
        [sys.executable, str(scanner)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode == 0:
        return []
    output = (process.stdout + process.stderr).strip()
    return [f"credential scan failed: {output}"]


def main() -> int:
    root = parse_args().root.resolve()
    if not root.is_dir():
        print(f"Repository root does not exist: {root}", file=sys.stderr)
        return 2

    files = iter_files(root)
    findings = [
        *verify_structure(root, files),
        *verify_text(root, files),
        *verify_python(root, files),
        *verify_manifest(root),
        *run_secret_scan(root),
    ]

    if findings:
        print("Public export verification failed:")
        for finding in sorted(set(findings)):
            print(f"- {finding}")
        return 1

    print(
        json.dumps(
            {
                "status": "passed",
                "root": ".",
                "file_count": len(files),
                "live_execution_enabled": False,
                "private_keys_required": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
