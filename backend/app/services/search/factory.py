from __future__ import annotations

from app.config import Settings, get_settings
from app.services.search.duckduckgo import DuckDuckGoSearchProvider
from app.services.search.http_providers import (
    BraveSearchProvider,
    SerperSearchProvider,
    TavilySearchProvider,
)
from app.services.search.provider import SearchProvider


def create_search_provider(settings: Settings | None = None) -> SearchProvider:
    settings = settings or get_settings()
    provider = settings.search_provider.lower().strip()
    if provider in {"duckduckgo", "ddg"}:
        return DuckDuckGoSearchProvider()
    if provider == "tavily":
        return TavilySearchProvider(settings)
    if provider == "brave":
        return BraveSearchProvider(settings)
    if provider == "serper":
        return SerperSearchProvider(settings)
    raise ValueError(f"不支持的 SEARCH_PROVIDER：{settings.search_provider}")
