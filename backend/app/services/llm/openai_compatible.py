from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings
from app.services.llm.provider import LLMProvider, LLMResponse


class RetriableLLMError(RuntimeError):
    pass


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.name = name or settings.llm_provider.lower()
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.secret_for_llm()
        self.model = model or settings.llm_model
        self._client = client

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.model and self.base_url)

    async def _request(self, system_prompt: str, user_prompt: str, json_mode: bool) -> LLMResponse:
        if not self.ready:
            raise RuntimeError(f"{self.name} Provider 未配置 API Key、模型或 Base URL")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1 if json_mode else 0.45,
            "max_tokens": 8192,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds), follow_redirects=True
        )
        try:
            last_error: Exception | None = None
            for attempt in range(self.settings.llm_max_retries + 1):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise RetriableLLMError(
                            f"{self.name} temporary HTTP {response.status_code}"
                        )
                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    if not isinstance(content, str) or not content.strip():
                        raise RetriableLLMError(f"{self.name} 返回空内容")
                    return LLMResponse(
                        content=content.strip(), provider=self.name, model=self.model, raw=data
                    )
                except (httpx.TimeoutException, httpx.TransportError, RetriableLLMError) as exc:
                    last_error = exc
                    if attempt >= self.settings.llm_max_retries:
                        raise
                    await asyncio.sleep(min(2**attempt, 8))
            raise RuntimeError(str(last_error or "unknown LLM error"))
        finally:
            if own_client:
                await client.aclose()

    async def generate_text(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        return await self._request(system_prompt, user_prompt, json_mode=False)

    async def generate_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        return await self._request(system_prompt, user_prompt, json_mode=True)


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(
            settings,
            name="deepseek",
            base_url=settings.llm_base_url or "https://api.deepseek.com",
            api_key=settings.secret_for_llm(),
            model=settings.llm_model or "deepseek-v4-flash",
            client=client,
        )
