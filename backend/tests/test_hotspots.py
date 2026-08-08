from __future__ import annotations

import httpx
import pytest

from app.schemas.domain import HotspotData
from app.services.integrations.hotspots import (
    DailyHotApiProvider,
    NativeHotspotProvider,
    is_political_hotspot,
    rank_social_hotspots,
    score_hotspot,
)


def test_social_events_are_ranked_before_generic_news_and_politics_are_removed() -> None:
    items = [
        HotspotData(title="总书记出席重要会议", platform="baidu", rank=1),
        HotspotData(title="某品牌发布新产品", platform="baidu", rank=2),
        HotspotData(
            title="年轻人遭遇租房退款困境",
            platform="weibo",
            rank=12,
            story_score=score_hotspot("年轻人遭遇租房退款困境"),
        ),
    ]

    ranked = rank_social_hotspots(items)

    assert [item.title for item in ranked] == ["年轻人遭遇租房退款困境", "某品牌发布新产品"]
    assert is_political_hotspot("郑丽文：台湾从来没有独立过")
    assert is_political_hotspot("博主：俄军现在专打乌要害")
    assert is_political_hotspot("人民的健康、体质、幸福一脉相承")
    assert score_hotspot("租房平台暴雷后年轻人退款难") > score_hotspot("某品牌发布新产品")
    assert score_hotspot("年轻人遭遇租房退款困境") > score_hotspot("某品牌发布新产品")


@pytest.mark.asyncio
async def test_dailyhot_merges_three_platforms(test_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        platform = request.url.path.strip("/")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "title": f"{platform} 年轻人事件调查与官方回应",
                        "hot": 999,
                        "url": f"https://example.com/{platform}",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DailyHotApiProvider(test_settings, client=client)
    items = await provider.fetch_hotspots()
    await client.aclose()

    assert {item.platform for item in items} == {"baidu", "weibo", "zhihu"}
    assert all(item.story_score > 50 for item in items)


@pytest.mark.asyncio
async def test_native_hotspots_parse_public_lists(test_settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "top.baidu.com":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "cards": [
                            {
                                "content": [
                                    {
                                        "content": [
                                            {
                                                "word": "百度社会事件调查",
                                                "url": "https://baidu.example",
                                            },
                                            {
                                                "word": "总书记出席重要会议",
                                                "url": "https://politics.example",
                                            },
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                },
            )
        if request.url.host == "weibo.com":
            return httpx.Response(
                200,
                json={"data": {"realtime": [{"word": "微博官方回应", "realpos": 1, "num": 88}]}},
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {"Title": "头条年轻人事件", "HotValue": "99", "Url": "https://toutiao.example"}
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = NativeHotspotProvider(test_settings, client=client)
    items = await provider.fetch_hotspots()
    await client.aclose()

    assert {item.platform for item in items} == {"baidu", "weibo", "toutiao"}
    assert all("总书记" not in item.title for item in items)
