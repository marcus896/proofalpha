from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


REQUIRED_SECTIONS = ("Purpose", "Inputs", "Outputs", "Rules", "Forbidden")


@dataclass(frozen=True)
class SkillContract:
    name: str
    path: Path
    purpose: str
    inputs: list[str]
    outputs: list[str]
    rules: list[str]
    forbidden: list[str]


def default_skills_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "skills"


def load_repo_skill_contracts(skills_dir: Path | None = None) -> list[SkillContract]:
    root = skills_dir or default_skills_dir()
    if not root.exists():
        return []
    contracts = [load_skill_contract(path) for path in sorted(root.glob("*/SKILL.md"))]
    return sorted(contracts, key=lambda contract: contract.name)


def find_skill_contract(name: str, skills_dir: Path | None = None) -> SkillContract:
    normalized_name = name.strip().lower()
    for contract in load_repo_skill_contracts(skills_dir):
        if contract.name == normalized_name:
            return contract
    raise ValueError(f"unknown skill '{name}'")


def load_skill_contract(path: Path) -> SkillContract:
    content = path.read_text(encoding="utf-8")
    sections = _parse_sections(content)
    for section_name in REQUIRED_SECTIONS:
        if section_name not in sections:
            raise ValueError(f"{path}: missing required section '{section_name}'")
    skill_name = path.parent.name.strip().lower()
    return SkillContract(
        name=skill_name,
        path=path,
        purpose=_join_section(sections["Purpose"]),
        inputs=_normalize_bullets(sections["Inputs"]),
        outputs=_normalize_bullets(sections["Outputs"]),
        rules=_normalize_bullets(sections["Rules"]),
        forbidden=_normalize_bullets(sections["Forbidden"]),
    )


def _parse_sections(content: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_name: str | None = None
    for raw_line in content.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", raw_line)
        if heading:
            current_name = heading.group(1).strip()
            sections[current_name] = []
            continue
        if current_name is not None:
            sections[current_name].append(raw_line.rstrip())
    return sections


def _normalize_bullets(lines: list[str]) -> list[str]:
    values: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            values.append(stripped[2:])
    return values


def _join_section(lines: list[str]) -> str:
    return " ".join(line.strip() for line in lines if line.strip())
