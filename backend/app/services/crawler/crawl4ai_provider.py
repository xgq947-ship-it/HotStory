from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup

from app.config import Settings
from app.schemas.domain import CrawledDocumentData
from app.services.crawler.provider import CrawlerProvider
from app.services.crawler.simple_http import detect_language


class Crawl4AICrawler(CrawlerProvider):
    name = "crawl4ai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def available() -> bool:
        try:
            import crawl4ai  # noqa: F401
        except ImportError:
            return False
        return True

    async def fetch(self, url: str) -> CrawledDocumentData:
        if not self.available():
            raise RuntimeError(
                "Crawl4AI 未安装；运行 uv pip install -r backend/requirements-optional.txt"
            )
        from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig

        config = CrawlerRunConfig(
            cache_mode=CacheMode.ENABLED,
            check_robots_txt=True,
            page_timeout=int(self.settings.request_timeout_seconds * 1000),
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)
        if not result.success:
            raise RuntimeError(result.error_message or "Crawl4AI 抓取失败")
        markdown_value = result.markdown
        if hasattr(markdown_value, "raw_markdown"):
            markdown = markdown_value.raw_markdown or ""
        else:
            markdown = str(markdown_value or "")
        cleaned_html = getattr(result, "cleaned_html", "") or ""
        raw_text = await asyncio.to_thread(
            lambda: BeautifulSoup(cleaned_html, "html.parser").get_text("\n", strip=True)
        )
        metadata = getattr(result, "metadata", {}) or {}
        return CrawledDocumentData(
            url=url,
            title=metadata.get("title", ""),
            published_at=metadata.get("published_time", "") or metadata.get("date", ""),
            author=metadata.get("author", ""),
            raw_text=raw_text or markdown,
            markdown=markdown,
            language=metadata.get("language", "") or detect_language(raw_text or markdown),
            crawler=self.name,
        )
