from __future__ import annotations

from pathlib import Path
from typing import Sequence


def packaged_skills_dir() -> Path:
    return Path(__file__).resolve().parent / "_skills"


def configure_assets() -> None:
    skills_dir = packaged_skills_dir()
    if not skills_dir.is_dir():
        return
    import engine.agent.skills as skills_module

    def _skills_dir() -> Path:
        return skills_dir

    skills_module.default_skills_dir = _skills_dir


def main(argv: Sequence[str] | None = None) -> int:
    configure_assets()
    from engine.app.cli import main as engine_main

    return engine_main(None if argv is None else list(argv))
