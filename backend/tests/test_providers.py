from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.schemas.domain import CrawledDocumentData
from app.services.crawler.factory import AutoCrawler
from app.services.crawler.simple_http import SimpleHttpCrawler
from app.services.facts.extractor import personal_case_excerpt
from app.services.llm.openai_compatible import DeepSeekProvider
from app.utils import normalize_url


def test_normalize_url_removes_tracking_and_fragment() -> None:
    assert (
        normalize_url("https://Example.com/news/?utm_source=x&b=2&a=1#part")
        == "https://example.com/news?a=1&b=2"
    )


def test_personal_case_excerpt_keeps_neighboring_context() -> None:
    content = "背景段。\n31岁上班族韩先生买入杠杆产品。\n他表示亏损让自己失眠。\n无关结尾。"
    excerpt = personal_case_excerpt(content)
    assert "31岁上班族韩先生" in excerpt
    assert "他表示亏损" in excerpt


@pytest.mark.asyncio
async def test_deepseek_provider_uses_global_max_json_mode(tmp_path) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(__import__("json").loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "model": "deepseek-v4-flash",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        llm_provider="deepseek",
        llm_model="deepseek-v4-flash",
        llm_base_url="https://api.deepseek.com",
        deepseek_api_key="test-key",
    )
    provider = DeepSeekProvider(settings, client=client)
    response = await provider.generate_json("system", "output json")
    await client.aclose()

    assert response.content == '{"ok": true}'
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "max"
    assert captured["max_tokens"] == 65536
    assert "temperature" not in captured


@pytest.mark.asyncio
async def test_deepseek_provider_can_disable_reasoning(tmp_path) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "model": "deepseek-v4-flash",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        llm_provider="deepseek",
        llm_model="deepseek-v4-flash",
        llm_base_url="https://api.deepseek.com",
        deepseek_api_key="test-key",
        deepseek_thinking_enabled=False,
        llm_max_output_tokens=32768,
    )
    provider = DeepSeekProvider(settings, client=client)
    await provider.generate_json("system", "output json")
    await client.aclose()

    assert captured["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured
    assert captured["max_tokens"] == 32768
    assert captured["temperature"] == 0.1


@pytest.mark.asyncio
async def test_auto_crawler_keeps_usable_simple_result_without_browser(test_settings) -> None:
    crawler = AutoCrawler(test_settings)

    class UsableSimple:
        async def fetch(self, url: str) -> CrawledDocumentData:
            return CrawledDocumentData(
                url=url,
                raw_text="有效正文" * 45,
                markdown="有效正文" * 45,
                crawler="simple_http",
            )

    crawler.simple = UsableSimple()  # type: ignore[assignment]
    crawler.crawl4ai.available = lambda: False  # type: ignore[method-assign]
    result = await crawler.fetch("https://example.com/article")
    assert len(result.raw_text) >= 160


@pytest.mark.asyncio
async def test_simple_crawler_attributes_mirror_content_to_original_source(test_settings) -> None:
    html = """
    <html><head><title>转载正文</title></head><body>
      <a class="original-link" href="https://finance.ifeng.com/c/original">Read original</a>
      <article><p>这是一段用于核验来源归属的正文。</p></article>
    </body></html>
    """ + ("正文内容。" * 50)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    crawler = SimpleHttpCrawler(test_settings, client=client)
    result = await crawler.fetch("https://mirror.example/read/123")
    await client.aclose()

    assert result.url == "https://finance.ifeng.com/c/original"
