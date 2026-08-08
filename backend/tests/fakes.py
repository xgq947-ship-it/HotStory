from __future__ import annotations

import json
import re

from app.schemas.domain import CrawledDocumentData, SearchResultData
from app.services.crawler.provider import CrawlerProvider
from app.services.llm.provider import LLMProvider, LLMResponse
from app.services.search.provider import SearchProvider


class FakeSearchProvider(SearchProvider):
    name = "fake_search"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, limit: int = 10) -> list[SearchResultData]:
        self.calls += 1
        return [
            SearchResultData(
                title=f"权威来源 {index}",
                url=f"https://agency{index}.gov/reports/story-{index}",
                snippet=f"测试热点第 {index} 份权威资料",
                publisher=f"agency{index}.gov",
            )
            for index in range(1, limit + 1)
        ]


class FakeCrawlerProvider(CrawlerProvider):
    name = "fake_crawler"

    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, url: str) -> CrawledDocumentData:
        self.calls += 1
        index = re.search(r"story-(\d+)", url).group(1)  # type: ignore[union-attr]
        content = (
            f"2026-01-{int(index):02d}，机构发布第 {index} 份公开记录。"
            f"记录包含样本数据 {int(index) * 100} 人。"
            "该资料用于测试来源追溯。" * 20
        )
        return CrawledDocumentData(
            url=url,
            title=f"权威来源 {index}",
            published_at=f"2026-01-{int(index):02d}",
            author="测试机构",
            raw_text=content,
            markdown=content,
            language="zh",
            crawler=self.name,
        )


class ScenarioLLMProvider(LLMProvider):
    name = "scenario"
    model = "scenario-v1"

    def __init__(self) -> None:
        self.calls = 0

    def _response(self, payload: dict | str) -> LLMResponse:
        self.calls += 1
        content = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload
        return LLMResponse(
            content=content, provider=self.name, model=self.model, raw={"test": True}
        )

    async def generate_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        if "research_questions" in user_prompt:
            return self._response(
                {
                    "research_questions": [f"测试研究问题 {index}" for index in range(1, 11)],
                    "keywords": {
                        "zh": ["测试热点", "测试热点 数据", "测试热点 案例"],
                        "en": ["test hotspot data"],
                        "local": [],
                    },
                }
            )
        if '"same_claim"' in user_prompt:
            return self._response({"groups": []})
        if "事实核查员" in user_prompt:
            source_id = re.search(r'"id":"(source_[^"]+)"', user_prompt).group(1)  # type: ignore[union-attr]
            suffix = source_id[-4:]
            return self._response(
                {
                    "facts": [
                        {
                            "statement": f"权威机构在 2026 年公开记录事件 {suffix}",
                            "fact_type": "BACKGROUND",
                            "date": "2026-01",
                            "people": [],
                            "organizations": [f"机构 {suffix}"],
                            "locations": ["测试地区"],
                            "numbers": [],
                            "confidence": 0.96,
                        },
                        {
                            "statement": f"公开记录的样本数据为 {int(source_id[-2:], 16) + 100} 人",
                            "fact_type": "DATA",
                            "date": "2026-01",
                            "people": [],
                            "organizations": [f"机构 {suffix}"],
                            "locations": ["测试地区"],
                            "numbers": [f"{int(source_id[-2:], 16) + 100} 人"],
                            "confidence": 0.95,
                        },
                        {
                            "statement": f"受访者 {suffix} 描述了自己的选择过程",
                            "fact_type": "PERSONAL_CASE",
                            "date": "2026-01",
                            "people": [f"受访者 {suffix}"],
                            "organizations": [],
                            "locations": ["测试地区"],
                            "numbers": [],
                            "confidence": 0.93,
                        },
                    ]
                }
            )
        if '"events"' in user_prompt:
            fact_ids = list(dict.fromkeys(re.findall(r'"id":"(fact_[^"]+)"', user_prompt)))
            return self._response(
                {
                    "events": [
                        {
                            "title": f"已核验事件 {index}",
                            "summary": f"第 {index} 个已核验事实构成事件。",
                            "date": f"2026-{index:02d}",
                            "event_type": "DATA" if index % 3 == 0 else "PERSONAL_CASE",
                            "fact_ids": [fact_id],
                            "people": [],
                            "emotion": ["变化"],
                            "confidence": 0.93,
                        }
                        for index, fact_id in enumerate(fact_ids, 1)
                    ]
                }
            )
        if '"timeline"' in user_prompt:
            event_ids = list(dict.fromkeys(re.findall(r'"id":"(event_[^"]+)"', user_prompt)))
            return self._response(
                {
                    "timeline": [
                        {
                            "date": f"2026-{index:02d}",
                            "title": f"时间节点 {index}",
                            "description": f"已核验时间节点 {index}",
                            "event_ids": [event_id],
                            "importance": 0.9,
                        }
                        for index, event_id in enumerate(event_ids[:12], 1)
                    ]
                }
            )
        if "central_theme" in user_prompt:
            event_ids = list(dict.fromkeys(re.findall(r"event_[a-f0-9]{16}", user_prompt)))
            return self._response(
                {
                    "central_theme": "选择、数据与社会变化",
                    "core_conflict": "个体选择与宏观变化",
                    "story_arc": [
                        {"stage": "背景", "event_ids": event_ids[:2]},
                        {"stage": "转折", "event_ids": event_ids[2:4]},
                        {"stage": "反思", "event_ids": event_ids[4:6]},
                    ],
                    "selected_events": event_ids[:8],
                    "selected_cases": event_ids[:2],
                    "selected_data": event_ids[2:4],
                }
            )
        if "human_lesson" in user_prompt:
            return self._response(
                {
                    "human_lesson": ["数据背后是普通人的选择"],
                    "positive_values": ["理性", "责任"],
                    "ending_direction": "让选择经得起时间",
                    "ending_sentence_candidates": ["真正重要的，是让选择服务生活。"],
                }
            )
        if '"score"' in user_prompt:
            return self._response({"score": 95, "issues": [], "passed": True})
        return self._response({})

    async def generate_text(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        event_ids = list(dict.fromkeys(re.findall(r"event_[a-f0-9]{16}", user_prompt)))
        source_ids = list(dict.fromkeys(re.findall(r"source_[a-f0-9]{16}", user_prompt)))
        event_id = event_ids[0]
        source_id = source_ids[0]
        script = f"""# 测试热点背后的选择

## 基本信息

预计时长：90 秒

核心主题：选择与责任

---

## 00:00 - 00:10

### 旁白

一份公开记录，把普通人的选择带到我们面前。

### 镜头

- S01：公开资料与城市空镜

### 事实依据

- {event_id}
- {source_id}

---

## 00:10 - 01:20

### 旁白

沿着已核验的时间线，数据与人物彼此照见。

### 镜头

- S02：数据图表与资料画面

### 事实依据

- {event_id}
- {source_id}

## 结尾

真正重要的，是让选择服务生活。

## 使用到的真实案例

- 已核验案例（{event_id}）

## 使用到的关键数据

- 已核验数据（{source_id}）

## 来源

- {source_id}
"""
        return self._response(script)
