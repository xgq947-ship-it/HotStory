from __future__ import annotations

from functools import lru_cache

from app.config import BACKEND_ROOT


@lru_cache
def load_prompt(name: str) -> str:
    path = BACKEND_ROOT / "app" / "prompts" / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt 不存在：{name}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **values: object) -> str:
    content = load_prompt(name)
    for key, value in values.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    return content
