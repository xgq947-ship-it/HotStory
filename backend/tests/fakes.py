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
        if '"prompt_body_template"' in user_prompt:
            shot_ids = list(dict.fromkeys(re.findall(r"shot_\d+", user_prompt)))[:4]
            return self._response(
                {
                    "shots": [
                        {
                            "shot_id": shot_id,
                            "prompt_body_template": (
                                "场景上下文\n当前已核验事件的纪实还原空间。\n\n"
                                "首帧与空间调度\n主体从第一帧就在中景清晰可见，身体朝向动作目标，"
                                "视线先于头部移动，手中事务在信息落下时短暂停住。\n\n"
                                "光学与摄影机\n47°自然标准视野，摄影机距主体四米，"
                                "只做一次缓慢微推进并持续跟随主要动作。\n\n"
                                "物理与灯光\n脚掌真实落地，衣料带轻微惯性延迟，"
                                "单侧现场实用光形成自然阴影，优先保持面部与环境层次。"
                            ),
                            "ambient_audio": "与当前空间一致的低声环境底噪",
                        }
                        for shot_id in shot_ids
                    ]
                }
            )
        if "目标镜头数：" in user_prompt:
            count = int(re.search(r"目标镜头数：(\d+)", user_prompt).group(1))  # type: ignore[union-attr]
            duration = int(re.search(r"目标总时长：(\d+)", user_prompt).group(1))  # type: ignore[union-attr]
            character_ids = list(dict.fromkeys(re.findall(r"char_\d+", user_prompt)))
            event_ids = list(
                dict.fromkeys(re.findall(r"event_[a-f0-9]{16}", user_prompt))
            )
            source_ids = list(
                dict.fromkeys(re.findall(r"source_[a-f0-9]{16}", user_prompt))
            )
            return self._response(
                {
                    "shots": [
                        {
                            "shot_id": f"shot_{index + 1:02d}",
                            "title": f"纪实镜头 {index + 1}",
                            "start_second": (index * duration) // count,
                            "end_second": ((index + 1) * duration) // count,
                            "narration": "",
                            "dialogue": "",
                            "visual_brief": "以已核验资料和克制人物反应呈现当前叙事节点",
                            "active_character_ids": character_ids[:1],
                            "event_ids": event_ids[:1],
                            "source_ids": source_ids[:1],
                        }
                        for index in range(count)
                    ]
                }
            )
        if "角色资产阶段" in user_prompt:
            fact_ids = list(dict.fromkeys(re.findall(r"fact_[a-f0-9]{16}", user_prompt)))
            return self._response(
                {
                    "style_bible": (
                        "真实社会纪实电影质感，自然生活化表演，克制低对比方向光，"
                        "中性色环境、深灰结构和少量现场暖色保持全片一致。"
                    ),
                    "characters": [
                        {
                            "prompt_label": "成年纪实还原当事人",
                            "role": "lead",
                            "story_function": "承载已核验个人案例的主要观察视角",
                            "source_fact_ids": fact_ids[:1],
                            "visual_anchor": (
                                "成年东亚纪实还原演员，普通真实体型，"
                                "自然生活痕迹与稳定面部比例"
                            ),
                            "wardrobe_anchor": (
                                "无品牌深灰日常外套与浅色内搭，"
                                "布料磨损状态跨镜头一致"
                            ),
                            "image_prompt": (
                                "三张同一位成年纪实还原演员的真实棚拍照片并排组成电影选角页。"
                                "左侧全身正面，中间完整背面，右侧头肩近景；同一张脸、体型和服装。"
                                "中性灰背景，单侧柔和方向光，真实皮肤和布料纹理，克制纪录片质感。"
                            ),
                            "acting_profile": (
                                "成年纪实还原当事人以略低重心和收紧肩背承载压力，目标是让自己的选择被认真听见。"
                                "开口前短暂停住手中事务，压力升高时拇指摩擦指节；礼貌神情在核心代价被提及时短暂松动。"
                                "眼神在对方、出口和手中物件之间微扫，保持真实眨眼并让视线先于头部到达目标。"
                            ),
                            "voice_prompt": "中低音自然声线，语速克制，压力上升时句尾略微收紧。",
                            "default_use_reference": True,
                        }
                    ],
                }
            )
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
