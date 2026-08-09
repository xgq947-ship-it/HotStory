from __future__ import annotations

import httpx

from app.config import Settings, get_settings
from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.codex_cli import CodexCLIProvider
from app.services.llm.mock import MockLLMProvider
from app.services.llm.openai_compatible import DeepSeekProvider, OpenAICompatibleProvider
from app.services.llm.provider import LLMProvider


def create_llm_provider(
    settings: Settings | None = None, client: httpx.AsyncClient | None = None
) -> LLMProvider:
    settings = settings or get_settings()
    provider = settings.llm_provider.lower().strip()
    if provider == "deepseek":
        return DeepSeekProvider(settings, client=client)
    if provider == "codex_cli":
        return CodexCLIProvider(settings)
    if provider == "anthropic":
        return AnthropicProvider(settings, client=client)
    if provider == "mock":
        return MockLLMProvider()
    if provider == "openai":
        base_url = settings.llm_base_url or "https://api.openai.com/v1"
        return OpenAICompatibleProvider(settings, name="openai", base_url=base_url, client=client)
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(settings, client=client)
    raise ValueError(f"不支持的 LLM_PROVIDER：{settings.llm_provider}")
