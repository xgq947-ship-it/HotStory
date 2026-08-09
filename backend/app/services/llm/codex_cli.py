from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from app.config import PROJECT_ROOT, Settings
from app.services.codex_cli_paths import resolve_codex_bin
from app.services.llm.provider import LLMProvider, LLMResponse


class CodexCLIProvider(LLMProvider):
    name = "codex_cli"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.codex_cli_model or "codex-default"

    @property
    def binary(self) -> str:
        return resolve_codex_bin(self.settings.codex_cli_path)

    @property
    def ready(self) -> bool:
        return bool(self.binary)

    async def _run(self, system_prompt: str, user_prompt: str, json_mode: bool) -> LLMResponse:
        binary = self.binary
        if not binary:
            raise RuntimeError(
                f"找不到 Codex CLI：{self.settings.codex_cli_path or 'codex'}；"
                "可在设置里手动填写完整路径或点击自动检测。"
            )
        suffix = (
            "\n\n输出必须是合法 JSON 对象；不要运行命令，不要修改文件，不要输出代码围栏。"
            if json_mode
            else "\n\n只完成文本生成任务；不要运行命令，不要修改文件。"
        )
        prompt = f"{system_prompt}\n\n{user_prompt}{suffix}"
        with tempfile.TemporaryDirectory(prefix="hotstory-codex-") as temporary:
            output_path = Path(temporary) / "last-message.txt"
            args = [
                binary,
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-rules",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "-C",
                str(PROJECT_ROOT),
                "--output-last-message",
                str(output_path),
            ]
            if self.settings.codex_cli_model:
                args.extend(["--model", self.settings.codex_cli_model])
            args.append("-")
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=self.settings.codex_cli_timeout_seconds,
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                raise RuntimeError("Codex CLI 生成超时") from None
            if process.returncode != 0:
                safe_error = stderr.decode("utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"Codex CLI 失败（{process.returncode}）：{safe_error}")
            content = (
                output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
            )
            if not content:
                raise RuntimeError("Codex CLI 未返回最终内容")
            raw = {
                "returncode": process.returncode,
                "stdout_tail": stdout.decode("utf-8", errors="replace")[-2000:],
            }
            return LLMResponse(content=content, provider=self.name, model=self.model, raw=raw)

    async def generate_text(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        return await self._run(system_prompt, user_prompt, json_mode=False)

    async def generate_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        return await self._run(system_prompt, user_prompt, json_mode=True)
