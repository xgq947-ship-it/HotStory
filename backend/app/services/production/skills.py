from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import BACKEND_ROOT
from app.utils import sha256_text


@dataclass(frozen=True)
class VerbatimSkill:
    name: str
    content: str
    source_path: Path
    sha256: str


def _skill_candidates(name: str) -> list[Path]:
    candidates: list[Path] = []
    configured_root = os.getenv("HOTSTORY_SKILL_ROOT", "").strip()
    if configured_root:
        candidates.append(Path(configured_root).expanduser() / name / "SKILL.md")
    candidates.extend(
        [
            BACKEND_ROOT.parent / "skills" / name / "SKILL.md",
            Path.home() / ".agents" / "skills" / name / "SKILL.md",
            Path.home() / ".codex" / "skills" / name / "SKILL.md",
        ]
    )
    return candidates


@lru_cache
def load_verbatim_skill(name: str) -> VerbatimSkill:
    for path in _skill_candidates(name):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            continue
        return VerbatimSkill(
            name=name,
            content=content,
            source_path=path,
            sha256=sha256_text(content),
        )
    searched = "、".join(str(path) for path in _skill_candidates(name))
    raise FileNotFoundError(f"找不到完整 Skill：{name}；已检查 {searched}")


__all__ = ["VerbatimSkill", "load_verbatim_skill"]
