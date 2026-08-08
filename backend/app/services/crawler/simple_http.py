from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura
from bs4 import BeautifulSoup

from app.config import Settings
from app.schemas.domain import CrawledDocumentData
from app.services.crawler.provider import CrawlerProvider


def discover_original_url(soup: BeautifulSoup, response_url: str) -> str:
    candidates = [
        soup.select_one('link[rel="canonical"][href]'),
        soup.select_one('meta[property="og:url"][content]'),
        soup.select_one("a.original-link[href]"),
    ]
    for element in candidates:
        if element is None:
            continue
        value = element.get("href") or element.get("content")
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = urljoin(response_url, value.strip())
        if urlsplit(candidate).scheme in {"http", "https"} and urlsplit(candidate).hostname:
            return candidate
    return response_url


def detect_language(text: str) -> str:
    sample = text[:3000]
    cjk = len(re.findall(r"[\u3400-\u9fff]", sample))
    hangul = len(re.findall(r"[\uac00-\ud7af]", sample))
    if hangul > max(cjk, 10):
        return "ko"
    if cjk > 20:
        return "zh"
    return "en" if sample else ""


class SimpleHttpCrawler(CrawlerProvider):
    name = "simple_http"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def fetch(self, url: str) -> CrawledDocumentData:
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(self.settings.request_timeout_seconds),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36 HotStory/0.1"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            },
        )
        try:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                raise ValueError(f"不支持的正文类型：{content_type or 'unknown'}")
            if len(response.content) > 8_000_000:
                raise ValueError("页面超过 8MB 安全上限")
            html = response.text
            raw_text = (
                trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=True,
                    favor_precision=True,
                    output_format="txt",
                )
                or ""
            )
            markdown = (
                trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=True,
                    favor_precision=True,
                    output_format="markdown",
                )
                or raw_text
            )
            metadata = trafilatura.extract_metadata(html)
            soup = BeautifulSoup(html, "html.parser")
            original_url = discover_original_url(soup, str(response.url))
            title = getattr(metadata, "title", None) or (
                soup.title.get_text(" ", strip=True) if soup.title else ""
            )
            author = getattr(metadata, "author", None) or ""
            published_at = getattr(metadata, "date", None) or ""
            if len(raw_text.strip()) < 160:
                fallback = soup.get_text("\n", strip=True)
                raw_text = fallback if len(fallback) > len(raw_text) else raw_text
                if not markdown:
                    markdown = raw_text
            return CrawledDocumentData(
                url=original_url,
                title=title or "",
                published_at=str(published_at or ""),
                author=author,
                raw_text=raw_text.strip(),
                markdown=markdown.strip(),
                language=detect_language(raw_text),
                crawler=self.name,
            )
        finally:
            if own_client:
                await client.aclose()
