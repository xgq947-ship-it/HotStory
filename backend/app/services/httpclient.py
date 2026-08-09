from __future__ import annotations

import httpx

from app.config import Settings

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36 HotStory/0.1"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def _limits() -> httpx.Limits:
    return httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60.0)


def create_llm_client(settings: Settings) -> httpx.AsyncClient:
    """LLM 用的长连接客户端。单次请求可以再用 timeout= 覆盖。"""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0),
        follow_redirects=True,
        limits=_limits(),
    )


def create_crawl_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout_seconds, connect=10.0),
        follow_redirects=True,
        limits=_limits(),
        headers=BROWSER_HEADERS,
    )


async def aclose(*clients: httpx.AsyncClient | None) -> None:
    for client in clients:
        if client is None:
            continue
        try:
            await client.aclose()
        except Exception:  # 关闭失败不应该影响退出流程
            pass
