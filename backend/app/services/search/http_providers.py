from __future__ import annotations

import httpx

from app.config import Settings
from app.schemas.domain import SearchResultData
from app.services.search.provider import SearchProvider
from app.utils import publisher_from_url


class KeyedSearchProvider(SearchProvider):
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.api_key = settings.search_api_key.get_secret_value() if settings.search_api_key else ""
        self._client = client

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    async def _client_for_request(self) -> tuple[httpx.AsyncClient, bool]:
        if self._client:
            return self._client, False
        return httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds, follow_redirects=True
        ), True


class TavilySearchProvider(KeyedSearchProvider):
    name = "tavily"

    async def search(self, query: str, limit: int = 10) -> list[SearchResultData]:
        if not self.ready:
            raise RuntimeError("Tavily Search 未配置 SEARCH_API_KEY")
        client, own = await self._client_for_request()
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": limit,
                    "search_depth": "advanced",
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            return [
                SearchResultData(
                    title=item.get("title", ""),
                    url=item["url"],
                    snippet=item.get("content", ""),
                    publisher=publisher_from_url(item["url"]),
                )
                for item in response.json().get("results", [])
                if item.get("url") and item.get("title")
            ]
        finally:
            if own:
                await client.aclose()


class BraveSearchProvider(KeyedSearchProvider):
    name = "brave"

    async def search(self, query: str, limit: int = 10) -> list[SearchResultData]:
        if not self.ready:
            raise RuntimeError("Brave Search 未配置 SEARCH_API_KEY")
        client, own = await self._client_for_request()
        try:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": limit, "search_lang": "zh-hans"},
                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
            )
            response.raise_for_status()
            return [
                SearchResultData(
                    title=item.get("title", ""),
                    url=item["url"],
                    snippet=item.get("description", ""),
                    publisher=publisher_from_url(item["url"]),
                    published_at=item.get("page_age", ""),
                )
                for item in response.json().get("web", {}).get("results", [])
                if item.get("url") and item.get("title")
            ]
        finally:
            if own:
                await client.aclose()


class SerperSearchProvider(KeyedSearchProvider):
    name = "serper"

    async def search(self, query: str, limit: int = 10) -> list[SearchResultData]:
        if not self.ready:
            raise RuntimeError("Serper Search 未配置 SEARCH_API_KEY")
        client, own = await self._client_for_request()
        try:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                json={"q": query, "num": limit, "gl": "cn", "hl": "zh-cn"},
            )
            response.raise_for_status()
            return [
                SearchResultData(
                    title=item.get("title", ""),
                    url=item["link"],
                    snippet=item.get("snippet", ""),
                    publisher=publisher_from_url(item["link"]),
                    published_at=item.get("date", ""),
                )
                for item in response.json().get("organic", [])
                if item.get("link") and item.get("title")
            ]
        finally:
            if own:
                await client.aclose()
