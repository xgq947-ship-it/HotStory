from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.schemas.domain import HotspotData

POLITICAL_MARKERS = (
    "习近平",
    "总书记",
    "中央政治局",
    "中共中央",
    "全国人大",
    "全国政协",
    "两会",
    "外交部",
    "国台办",
    "国防部",
    "代表委员",
    "领导人会见",
    "任免",
    "大选",
    "选举",
    "当选",
    "总统",
    "首相",
    "议会",
    "政党",
    "国民党",
    "民进党",
    "共和党",
    "民主党",
    "台独",
    "台湾独立",
    "一国两制",
    "台海",
    "南海",
    "黄岩岛",
    "海警",
    "中美关系",
    "中俄关系",
    "外交",
    "访华",
    "访美",
    "制裁",
    "关税战",
    "地缘政治",
    "军事演习",
    "军演",
    "俄乌",
    "俄军",
    "乌军",
    "乌克兰",
    "俄罗斯",
    "巴以",
    "加沙停火",
    "白宫",
    "克宫",
    "北约",
    "欧盟峰会",
    "导弹",
    "航母",
    "特朗普",
    "普京",
    "泽连斯基",
    "赖清德",
    "郑丽文",
    "马克龙",
    "人民的健康",
)

HUMAN_MARKERS = (
    "普通人",
    "年轻人",
    "老人",
    "老年人",
    "儿童",
    "孩子",
    "学生",
    "家长",
    "教师",
    "医生",
    "患者",
    "工人",
    "司机",
    "骑手",
    "消费者",
    "家庭",
)

SOCIAL_MARKERS = (
    "社会",
    "教育",
    "学校",
    "校园",
    "职场",
    "就业",
    "求职",
    "招聘",
    "失业",
    "裁员",
    "加班",
    "工资",
    "欠薪",
    "劳动",
    "外卖",
    "消费",
    "退款",
    "涨价",
    "闭店",
    "医疗",
    "医院",
    "养老",
    "房租",
    "租房",
    "住房",
    "物业",
    "社区",
    "婚恋",
    "婚姻",
    "离婚",
    "生育",
    "旅游",
    "出游",
    "健康",
    "减脂",
    "隐私",
    "搬家",
    "演唱会",
    "平台",
    "电商",
    "快递",
    "网约车",
    "地铁",
    "高铁",
    "航班",
    "直播",
    "网络暴力",
    "宠物",
    "餐饮",
    "金融",
    "炒股",
    "杠杆",
    "贷款",
    "公共安全",
    "食品安全",
)

DOCUMENTARY_MARKERS = (
    "事件",
    "事故",
    "火灾",
    "车祸",
    "坍塌",
    "坠落",
    "调查",
    "回应",
    "争议",
    "维权",
    "投诉",
    "诈骗",
    "纠纷",
    "侵权",
    "造假",
    "失联",
    "救援",
    "搜救",
    "通报",
    "判决",
    "数据",
    "暴跌",
    "损失",
    "危机",
    "困境",
    "暴雷",
    "烂尾",
    "跑路",
    "真相",
    "台风",
    "暴雨",
    "灾害",
    "偷拍",
    "谣言",
    "致癌",
    "取消",
    "下架",
)


def is_political_hotspot(title: str, summary: str = "") -> bool:
    text = f"{title} {summary}".lower()
    return any(marker.lower() in text for marker in POLITICAL_MARKERS)


def has_social_signal(title: str, summary: str = "") -> bool:
    text = f"{title} {summary}"
    return any(marker in text for marker in (*HUMAN_MARKERS, *SOCIAL_MARKERS, *DOCUMENTARY_MARKERS))


def score_hotspot(title: str, summary: str = "") -> int:
    text = f"{title} {summary}"
    score = 18
    score += sum(9 for marker in HUMAN_MARKERS if marker in text)
    score += sum(7 for marker in SOCIAL_MARKERS if marker in text)
    score += sum(6 for marker in DOCUMENTARY_MARKERS if marker in text)
    if 8 <= len(title) <= 40:
        score += 8
    return min(100, score)


def rank_social_hotspots(items: list[HotspotData], limit: int = 30) -> list[HotspotData]:
    """Remove political news and put documentary-style social events first."""

    deduplicated: dict[str, HotspotData] = {}
    for item in items:
        title = item.title.strip()
        if not title or is_political_hotspot(title, item.summary):
            continue
        current = deduplicated.get(title)
        if current is None or item.story_score > current.story_score:
            deduplicated[title] = item

    ranked = sorted(
        deduplicated.values(),
        key=lambda item: (
            not has_social_signal(item.title, item.summary),
            -item.story_score,
            item.rank,
        ),
    )
    return ranked[:limit]


class HotspotProvider(ABC):
    name: str

    @abstractmethod
    async def fetch_hotspots(self) -> list[HotspotData]:
        raise NotImplementedError


class DailyHotApiProvider(HotspotProvider):
    name = "dailyhot"
    platforms = ("baidu", "weibo", "zhihu")

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.base_url = settings.dailyhot_api_base_url.rstrip("/")
        self._client = client

    async def _fetch_platform(self, client: httpx.AsyncClient, platform: str) -> list[HotspotData]:
        response = await client.get(f"{self.base_url}/{platform}")
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", payload if isinstance(payload, list) else [])
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("list") or rows.get("data") or []
        hotspots: list[HotspotData] = []
        for index, row in enumerate(rows[:20], 1):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("name") or "").strip()
            if not title:
                continue
            summary = str(row.get("desc") or row.get("description") or row.get("summary") or "")
            hotspots.append(
                HotspotData(
                    title=title,
                    platform=platform,
                    rank=int(row.get("rank") or row.get("index") or index),
                    heat=row.get("hot") or row.get("heat") or row.get("hotValue") or 0,
                    url=str(row.get("url") or row.get("link") or row.get("mobileUrl") or ""),
                    summary=summary,
                    story_score=score_hotspot(title, summary),
                )
            )
        return hotspots

    async def fetch_hotspots(self) -> list[HotspotData]:
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds, follow_redirects=True
        )
        try:
            results = await asyncio.gather(
                *(self._fetch_platform(client, platform) for platform in self.platforms),
                return_exceptions=True,
            )
            merged: list[HotspotData] = []
            for result in results:
                if isinstance(result, list):
                    merged.extend(result)
            return rank_social_hotspots(merged)
        finally:
            if own_client:
                await client.aclose()


class TrendRadarProvider(HotspotProvider):
    name = "trendradar"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.base_url = settings.trendradar_api_base_url.rstrip("/")
        self._client = client

    async def fetch_hotspots(self) -> list[HotspotData]:
        if not self.base_url:
            raise RuntimeError("TrendRadar 未配置 TRENDRADAR_API_BASE_URL")
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)
        try:
            response = await client.get(self.base_url)
            response.raise_for_status()
            payload: Any = response.json()
            if isinstance(payload, dict):
                payload = (
                    payload.get("data") or payload.get("hotspots") or payload.get("items") or []
                )
            hotspots: list[HotspotData] = []
            for index, row in enumerate(payload[:50], 1):
                title = str(row.get("title") or row.get("name") or "").strip()
                if not title:
                    continue
                summary = str(row.get("summary") or row.get("description") or "")
                hotspots.append(
                    HotspotData(
                        title=title,
                        platform=str(row.get("platform") or row.get("source") or "trendradar"),
                        rank=int(row.get("rank") or index),
                        heat=row.get("heat") or 0,
                        url=str(row.get("url") or ""),
                        summary=summary,
                        first_seen_at=str(row.get("first_seen_at") or ""),
                        last_seen_at=str(row.get("last_seen_at") or ""),
                        story_score=score_hotspot(title, summary),
                    )
                )
            return rank_social_hotspots(hotspots)
        finally:
            if own_client:
                await client.aclose()


class NativeHotspotProvider(HotspotProvider):
    """Direct public-list adapters used when a DailyHot deployment is unavailable."""

    name = "native_hotlists"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def _get(self, client: httpx.AsyncClient, url: str, referer: str = "") -> Any:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            )
        }
        if referer:
            headers["Referer"] = referer
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    async def _baidu(self, client: httpx.AsyncClient) -> list[HotspotData]:
        payload = await self._get(
            client, "https://top.baidu.com/api/board?platform=wise&tab=realtime"
        )
        rows = (
            payload.get("data", {}).get("cards", [{}])[0].get("content", [{}])[0].get("content", [])
        )
        return [
            HotspotData(
                title=str(row.get("word") or ""),
                platform="baidu",
                rank=index,
                heat=0,
                url=str(row.get("url") or ""),
                story_score=score_hotspot(str(row.get("word") or "")),
            )
            for index, row in enumerate(rows[:20], 1)
            if row.get("word")
        ]

    async def _weibo(self, client: httpx.AsyncClient) -> list[HotspotData]:
        payload = await self._get(
            client, "https://weibo.com/ajax/side/hotSearch", "https://weibo.com/"
        )
        rows = payload.get("data", {}).get("realtime", [])
        items: list[HotspotData] = []
        for index, row in enumerate(rows[:20], 1):
            title = str(row.get("word") or "").strip()
            if not title:
                continue
            query = str(row.get("word_scheme") or title)
            items.append(
                HotspotData(
                    title=title,
                    platform="weibo",
                    rank=int(row.get("realpos") or row.get("rank") or index),
                    heat=row.get("num") or row.get("raw_hot") or 0,
                    url=f"https://s.weibo.com/weibo?q={quote(query)}",
                    story_score=score_hotspot(title),
                )
            )
        return items

    async def _toutiao(self, client: httpx.AsyncClient) -> list[HotspotData]:
        payload = await self._get(
            client,
            "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
            "https://www.toutiao.com/",
        )
        rows = payload.get("data", [])
        return [
            HotspotData(
                title=str(row.get("Title") or ""),
                platform="toutiao",
                rank=index,
                heat=row.get("HotValue") or 0,
                url=str(row.get("Url") or ""),
                summary=str(row.get("Label") or ""),
                story_score=score_hotspot(str(row.get("Title") or ""), str(row.get("Label") or "")),
            )
            for index, row in enumerate(rows[:20], 1)
            if row.get("Title")
        ]

    async def fetch_hotspots(self) -> list[HotspotData]:
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds, follow_redirects=True
        )
        try:
            results = await asyncio.gather(
                self._baidu(client),
                self._weibo(client),
                self._toutiao(client),
                return_exceptions=True,
            )
            merged = [item for result in results if isinstance(result, list) for item in result]
            return rank_social_hotspots(merged)
        finally:
            if own_client:
                await client.aclose()


class FallbackHotspotProvider(HotspotProvider):
    def __init__(self, providers: list[HotspotProvider]) -> None:
        self.providers = providers
        self.name = "auto"

    async def fetch_hotspots(self) -> list[HotspotData]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                items = await provider.fetch_hotspots()
                if items:
                    return items
            except Exception as error:
                errors.append(f"{provider.name}: {error}")
        if errors:
            raise RuntimeError("；".join(errors))
        return []


class CachedHotspotProvider(HotspotProvider):
    def __init__(self, provider: HotspotProvider, ttl_seconds: int = 600) -> None:
        self.provider = provider
        self.name = provider.name
        self.ttl_seconds = ttl_seconds
        self._cached_at = 0.0
        self._items: list[HotspotData] = []

    async def fetch_hotspots(self) -> list[HotspotData]:
        now = time.monotonic()
        if self._items and now - self._cached_at < self.ttl_seconds:
            return self._items
        self._items = await self.provider.fetch_hotspots()
        self._cached_at = now
        return self._items


def create_hotspot_provider(settings: Settings) -> HotspotProvider:
    provider = settings.hotspot_provider.lower().strip()
    if provider == "auto":
        return CachedHotspotProvider(
            FallbackHotspotProvider(
                [NativeHotspotProvider(settings), DailyHotApiProvider(settings)]
            )
        )
    if provider == "dailyhot":
        return CachedHotspotProvider(DailyHotApiProvider(settings))
    if provider in {"native", "native_hotlists"}:
        return CachedHotspotProvider(NativeHotspotProvider(settings))
    if provider == "trendradar":
        return CachedHotspotProvider(TrendRadarProvider(settings))
    raise ValueError(f"不支持的 HOTSPOT_PROVIDER：{settings.hotspot_provider}")
