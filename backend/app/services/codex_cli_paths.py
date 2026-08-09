"""本机 Codex CLI 定位。

原来只用 shutil.which(path)，装在 ~/.local/bin 或 ChatGPT.app 里的 codex
会被判成"没装"。这里的候选顺序参考 AI 画布的 server/services/cliPaths.js。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

CHATGPT_CODEX_PATH = Path("/Applications/ChatGPT.app/Contents/Resources/codex")


def _candidates(environment: os._Environ[str] | dict[str, str]) -> Iterable[Path]:
    home = Path(environment.get("HOME") or Path.home())
    yield from (
        home / ".local" / "bin" / "codex",
        home / ".npm-global" / "bin" / "codex",
        Path("/opt/homebrew/bin/codex"),
        Path("/usr/local/bin/codex"),
        CHATGPT_CODEX_PATH,
    )


def resolve_codex_bin(
    configured_path: str = "",
    environment: os._Environ[str] | dict[str, str] | None = None,
) -> str:
    """返回可执行的 codex 路径；找不到时返回空字符串。"""
    environment = os.environ if environment is None else environment
    configured = (configured_path or "").strip()
    if configured and configured != "codex":
        expanded = Path(configured).expanduser()
        if expanded.is_file() and os.access(expanded, os.X_OK):
            return str(expanded)
        found = shutil.which(configured)
        if found:
            return found

    from_env = (environment.get("CODEX_CLI_PATH") or "").strip()
    if from_env:
        expanded = Path(from_env).expanduser()
        if expanded.is_file() and os.access(expanded, os.X_OK):
            return str(expanded)

    on_path = shutil.which("codex", path=environment.get("PATH"))
    if on_path:
        return on_path

    for candidate in _candidates(environment):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return ""


def describe_codex(configured_path: str = "") -> dict:
    """给设置界面用的检测结果：路径、版本、是否可用。"""
    resolved = resolve_codex_bin(configured_path)
    if not resolved:
        return {
            "available": False,
            "path": "",
            "version": "",
            "error": "没有找到 codex；请安装 Codex CLI 或在上方手动填写完整路径。",
            "searched": [str(path) for path in _candidates(os.environ)],
        }
    try:
        completed = subprocess.run(
            [resolved, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "available": False,
            "path": resolved,
            "version": "",
            "error": f"找到了 {resolved}，但无法执行：{error}",
            "searched": [],
        }
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-500:]
        return {
            "available": False,
            "path": resolved,
            "version": "",
            "error": f"codex --version 退出码 {completed.returncode}：{detail}",
            "searched": [],
        }
    return {
        "available": True,
        "path": resolved,
        "version": (completed.stdout or "").strip()[:200],
        "error": "",
        "searched": [],
    }


__all__ = ["describe_codex", "resolve_codex_bin"]
