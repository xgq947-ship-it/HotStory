from __future__ import annotations

import httpx

from app.config import Settings
from app.services.llm.provider import LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.model = settings.llm_model
        self.api_key = settings.secret_for_llm()
        self.base_url = (settings.llm_base_url or "https://api.anthropic.com/v1").rstrip("/")
        self._client = client

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.model)

    async def _request(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        if not self.ready:
            raise RuntimeError("Anthropic Provider 未配置 API Key 或模型")
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds * 4
        )
        try:
            response = await client.post(
                f"{self.base_url}/messages",
                timeout=httpx.Timeout(self.settings.llm_timeout_seconds, connect=10.0),
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 8192,
                    "temperature": 0.2,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
            content = "\n".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            ).strip()
            if not content:
                raise RuntimeError("Anthropic 返回空内容")
            return LLMResponse(content=content, provider=self.name, model=self.model, raw=data)
        finally:
            if own_client:
                await client.aclose()

    async def generate_text(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        return await self._request(system_prompt, user_prompt)

    async def generate_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        json_system = f"{system_prompt}\n只输出一个合法 JSON 对象，不要输出 Markdown 代码围栏。"
        return await self._request(json_system, user_prompt)
