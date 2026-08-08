from __future__ import annotations

import asyncio

from ddgs import DDGS

from app.schemas.domain import SearchResultData
from app.services.search.provider import SearchProvider
from app.utils import publisher_from_url


class DuckDuckGoSearchProvider(SearchProvider):
    name = "duckduckgo"

    async def search(self, query: str, limit: int = 10) -> list[SearchResultData]:
        def _run() -> list[dict]:
            return list(DDGS().text(query, max_results=limit, safesearch="moderate"))

        rows = await asyncio.to_thread(_run)
        results: list[SearchResultData] = []
        for row in rows:
            url = row.get("href") or row.get("url") or ""
            title = row.get("title") or ""
            if not url or not title:
                continue
            results.append(
                SearchResultData(
                    title=title,
                    url=url,
                    snippet=row.get("body") or row.get("description") or "",
                    publisher=row.get("source") or publisher_from_url(url),
                    published_at=str(row.get("date") or ""),
                )
            )
        return results
