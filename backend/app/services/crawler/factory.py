from __future__ import annotations

import httpx

from app.config import Settings, get_settings
from app.schemas.domain import CrawledDocumentData
from app.services.crawler.crawl4ai_provider import Crawl4AICrawler
from app.services.crawler.provider import CrawlerProvider
from app.services.crawler.simple_http import SimpleHttpCrawler


class AutoCrawler(CrawlerProvider):
    name = "auto"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.simple = SimpleHttpCrawler(settings, client=client)
        self.crawl4ai = Crawl4AICrawler(settings)

    async def fetch(self, url: str) -> CrawledDocumentData:
        first_error: Exception | None = None
        simple_result: CrawledDocumentData | None = None
        try:
            simple_result = await self.simple.fetch(url)
            if len(simple_result.raw_text) >= 400:
                return simple_result
        except Exception as error:
            first_error = error
        if self.crawl4ai.available():
            return await self.crawl4ai.fetch(url)
        if simple_result and len(simple_result.raw_text) >= 160:
            return simple_result
        if first_error:
            raise first_error
        raise RuntimeError("静态正文过短，且 Crawl4AI 未安装")


def create_crawler_provider(
    settings: Settings | None = None, client: httpx.AsyncClient | None = None
) -> CrawlerProvider:
    settings = settings or get_settings()
    provider = settings.crawler_provider.lower().strip()
    if provider == "auto":
        return AutoCrawler(settings, client=client)
    if provider in {"simple", "simple_http"}:
        return SimpleHttpCrawler(settings, client=client)
    if provider == "crawl4ai":
        return Crawl4AICrawler(settings)
    raise ValueError(f"不支持的 CRAWLER_PROVIDER：{settings.crawler_provider}")
