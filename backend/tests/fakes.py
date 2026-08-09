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
            plans_heading = user_prompt.find("本批生成单元计划")
            plans_start = user_prompt.find("[", plans_heading)
            plans = (
                json.JSONDecoder().raw_decode(user_prompt[plans_start:])[0]
                if plans_heading >= 0 and plans_start >= 0
                else []
            )

            def prompt_for(plan: dict) -> str:
                internal_shots = plan.get("internal_shots") or []
                if len(internal_shots) <= 1:
                    format_mode = "单一连续长镜头，只使用一个摄影机设置。"
                    timeline = "0:00 至 0:10，入口动作持续推进，结果落在出口状态。"
                else:
                    format_mode = (
                        f"受控多镜头序列，共 {len(internal_shots)} 个内部镜头；"
                        "切镜只发生在指定时间点。"
                    )
                    timeline_lines: list[str] = []
                    for index, internal in enumerate(internal_shots):
                        if index:
                            timeline_lines.append(
                                f"0:{internal['start_offset_seconds']:02d} "
                                f"{internal['cut_in']}"
                            )
                        timeline_lines.append(
                            f"0:{internal['start_offset_seconds']:02d} 至 "
                            f"0:{internal['end_offset_seconds']:02d}，"
                            f"{internal['visual_action']}"
                        )
                    timeline = "\n".join(timeline_lines)
                return (
                    "场景上下文\n当前已核验事件的纪实还原空间。\n\n"
                    "连续性状态\n第一帧入口状态已经成立，生成单元结束时留下明确出口状态；"
                    "内部切镜保持人物身份、空间、视线、道具和灯光连续。\n\n"
                    "首帧与空间调度\n主体从第一帧就在中景清晰可见，身体朝向动作目标，"
                    "视线先于头部移动，手中事务在信息落下时短暂停住。\n\n"
                    f"格式模式\n{format_mode}\n\n"
                    "表演\n人物有明确目标、阻碍与失败代价；新信息进入后改变策略，"
                    "反应先于语言，状态不在切点复位。\n\n"
                    f"动作时间轴\n{timeline}\n\n"
                    "光学与摄影机\n每个内部镜头使用计划指定的视野，段内光学不漂移，"
                    "摄影机只执行一次有动机的运动。\n\n"
                    "物理\n脚掌真实落地，衣料带轻微惯性延迟。\n\n"
                    "灯光\n单侧现场实用光形成自然阴影，保持面部与环境层次。"
                )

            return self._response(
                {
                    "shots": [
                        {
                            "shot_id": plan["shot_id"],
                            "prompt_body_template": prompt_for(plan),
                            "ambient_audio": "与当前空间一致的低声环境底噪",
                        }
                        for plan in plans
                    ]
                }
            )
        if "目标生成单元数：" in user_prompt:
            count = int(
                re.search(r"目标生成单元数：(\d+)", user_prompt).group(1)  # type: ignore[union-attr]
            )
            duration = int(re.search(r"目标总时长：(\d+)", user_prompt).group(1))  # type: ignore[union-attr]
            character_ids = list(dict.fromkeys(re.findall(r"char_\d+", user_prompt)))
            event_ids = list(
                dict.fromkeys(re.findall(r"event_[a-f0-9]{16}", user_prompt))
            )
            source_ids = list(
                dict.fromkeys(re.findall(r"source_[a-f0-9]{16}", user_prompt))
            )
            functions = [
                "结果前置钩子",
                "人物起点",
                "承诺与机会",
                "压力升级",
                "局势转折",
                "代价显现",
                "选择与回应",
                "余波与行动收束",
            ]
            intensity_curve = [
                84
                if index == 0
                else (
                    35 + index * 4
                    if index < count * 0.65
                    else max(28, 95 - (index - int(count * 0.65)) * 10)
                )
                for index in range(count)
            ]
            shots = []
            for index in range(count):
                internal_count = (
                    1
                    if index == count - 1
                    else (2 if index == 0 or index % 2 == 0 else 3)
                )
                windows = (
                    [(0, 10)]
                    if internal_count == 1
                    else (
                        [(0, 4), (4, 10)]
                        if internal_count == 2
                        else [(0, 3), (3, 7), (7, 10)]
                    )
                )
                internal_shots = []
                carried_state = f"入口状态 {index + 1}"
                for internal_index, (start, end) in enumerate(windows):
                    internal_exit = (
                        f"出口状态 {index + 1}"
                        if internal_index == internal_count - 1
                        else f"单元 {index + 1} 内部状态 {internal_index + 1}"
                    )
                    internal_shots.append(
                        {
                            "internal_shot_id": (
                                f"shot_{index + 1:02d}_{chr(97 + internal_index)}"
                            ),
                            "start_offset_seconds": start,
                            "end_offset_seconds": end,
                            "shot_size": ("WS", "MS", "CU")[
                                min(internal_index, 2)
                            ],
                            "fov_degrees": (84, 47, 18)[min(internal_index, 2)],
                            "visual_action": (
                                f"完成单元 {index + 1} 的第 {internal_index + 1} 个可见动作变化"
                            ),
                            "camera": "摄影机保持在动作轴同侧，只执行一次有动机的运动。",
                            "performance": "眼神、呼吸和手中动作随压力发生可见变化。",
                            "entry_state": carried_state,
                            "exit_state": internal_exit,
                            "cut_in": "START" if internal_index == 0 else "HARD CUT",
                            "cut_motivation": "动作中断形成切点",
                            "intensity": min(100, intensity_curve[index] + internal_index * 3),
                        }
                    )
                    carried_state = internal_exit
                shots.append(
                    {
                            "shot_id": f"shot_{index + 1:02d}",
                            "title": f"纪实生成单元 {index + 1}",
                            "start_second": index * 10,
                            "end_second": min(duration, (index + 1) * 10),
                            "narration": "",
                            "dialogue": "",
                            "visual_brief": f"以已核验资料完成第 {index + 1} 个十秒局部叙事弧",
                            "active_character_ids": character_ids[:1],
                            "event_ids": event_ids[:1],
                            "source_ids": source_ids[:1],
                            "sequence_id": f"sequence_{min(8, index * 8 // count + 1):02d}",
                            "beat_id": f"beat_{min(8, index * 8 // count + 1):02d}",
                            "narrative_function": functions[min(7, index * 8 // count)],
                            "objective": "让当前事实改变局势",
                            "obstacle": "人物的原策略受到现实阻碍",
                            "stakes": "失败会让处境继续恶化",
                            "tactic": "先观察，再改变行动策略",
                            "beat_changes": [
                                "人物带着入口状态处理手中事务",
                                "新信息到达，手上动作中断",
                                "人物以改变后的身体状态结束",
                            ],
                            "entry_state": f"入口状态 {index + 1}",
                            "exit_state": f"出口状态 {index + 1}",
                            "value_before": f"价值 {index + 1}",
                            "value_after": f"价值 {index + 2}",
                            "cause_link": "回应上一节点留下的问题",
                            "cut_motivation": "动作中断形成切点",
                            "audio_bridge": "保留半秒动作余音",
                            "intensity": intensity_curve[index],
                            "format_mode": (
                                "single_take"
                                if internal_count == 1
                                else "controlled_multishot"
                            ),
                            "internal_shots": internal_shots,
                    }
                )
            return self._response(
                {
                    "shots": shots,
                    "audio_plan": {
                        "score_arc": "开场建立低频动机，转折抽空，结尾回收未解决音型。",
                        "music_rule": "同期声和静默优先于配乐。",
                        "silence_points": [duration * 2 // 3],
                        "cues": [
                            {
                                "start_second": 0,
                                "end_second": max(1, duration // 3),
                                "layer": "score",
                                "description": "低频动机建立。",
                            },
                            {
                                "start_second": max(1, duration // 3),
                                "end_second": max(2, duration * 2 // 3),
                                "layer": "ambient_bridge",
                                "description": "环境声用 J-cut 和 L-cut 跨镜连接。",
                            },
                            {
                                "start_second": max(2, duration * 2 // 3),
                                "end_second": duration,
                                "layer": "score",
                                "description": "未解决音型回收。",
                            },
                        ],
                    },
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
        if "新闻事件聚类专家" in user_prompt:
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
        if "按日期恢复完整时间线" in user_prompt:
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
            source_ids = list(
                dict.fromkeys(re.findall(r"source_[a-f0-9]{16}", user_prompt))
            )
            functions = [
                "结果前置钩子",
                "人物起点",
                "承诺与机会",
                "压力升级",
                "局势转折",
                "代价显现",
                "选择与回应",
                "余波与行动收束",
            ]
            intensities = [82, 34, 46, 63, 94, 79, 57, 29]
            return self._response(
                {
                    "central_theme": "选择、数据与社会变化",
                    "core_conflict": "个体选择与宏观变化",
                    "narrative_mode": "cinematic_human_story",
                    "protagonist_event_id": event_ids[0],
                    "dramatic_question": "一个具体选择会面对什么现实代价？",
                    "ending_device": "以未完成动作和环境余音收束",
                    "beats": [
                        {
                            "beat_id": f"beat_{index + 1:02d}",
                            "narrative_function": function,
                            "objective": "让当前事实改变观众判断",
                            "obstacle": "事实容易被平铺成列表",
                            "stakes": "局势必须发生变化",
                            "tactic": "用人物与资料交替推进",
                            "turn": "新信息进入",
                            "value_before": f"状态 {index + 1}",
                            "value_after": f"状态 {index + 2}",
                            "cause_link": ""
                            if index == 0
                            else "承接上一节拍留下的问题",
                            "causal_basis": "editorial_transition",
                            "dramatization_mode": "composite_reenactment"
                            if index in (1, 5)
                            else "archive_or_data",
                            "visual_action": "用一个明确动作承载当前已核验事实",
                            "event_ids": [event_ids[index % len(event_ids)]],
                            "source_ids": source_ids[:1],
                            "intensity": intensities[index],
                        }
                        for index, function in enumerate(functions)
                    ],
                    "story_arc": [
                        {"stage": function, "event_ids": [event_ids[index % len(event_ids)]]}
                        for index, function in enumerate(functions)
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
        duration_match = re.search(r"目标时长：(\d+)", user_prompt)
        if not duration_match:
            duration_match = re.search(r'"duration":(\d+)', user_prompt)
        duration = int(duration_match.group(1)) if duration_match else 90
        count = 8
        first_end = 5
        windows = [(0, first_end)]
        cursor = first_end
        for index in range(count - 1):
            slots = count - 1 - index
            length = (duration - cursor + slots - 1) // slots
            end = duration if index == count - 2 else cursor + length
            windows.append((cursor, end))
            cursor = end
        functions = [
            "结果前置钩子",
            "人物起点",
            "承诺与机会",
            "压力升级",
            "局势转折",
            "代价显现",
            "选择与回应",
            "余波与行动收束",
        ]
        lines = [
            "# 测试热点背后的选择",
            "",
            "## 基本信息",
            "",
            f"预计时长：{duration} 秒",
            "",
            "戏剧问题：一个具体选择会面对什么现实代价？",
            "",
            "---",
        ]
        for index, ((start, end), function) in enumerate(
            zip(windows, functions, strict=True)
        ):
            event_id = event_ids[index % len(event_ids)]
            source_id = source_ids[index % len(source_ids)]
            lines.extend(
                [
                    "",
                    f"## {start // 60:02d}:{start % 60:02d} - {end // 60:02d}:{end % 60:02d}",
                    "",
                    "### 旁白",
                    "",
                    "结果已经出现。" if index == 0 else f"第 {index + 1} 个事实改变了局势。",
                    "",
                    "### 镜头",
                    "",
                    "- 用已核验资料与一个明确人物动作推进当前节点。",
                    "",
                    "### 叙事功能",
                    "",
                    f"- 节拍：beat_{index + 1:02d} / {function}",
                    "- 承接：结果先出现，暂不解释。"
                    if index == 0
                    else "- 承接：回应上一节拍留下的问题。",
                    f"- 价值变化：状态 {index + 1} → 状态 {index + 2}",
                    "- 画面依据：公开资料或明确标注的影视化合成还原。",
                    "",
                    "### 事实依据",
                    "",
                    f"- {event_id}",
                    f"- {source_id}",
                    "",
                    "---",
                ]
            )
        lines.extend(
            [
                "",
                "## 结尾",
                "",
                "镜头停在最后一个未完成动作和未散的环境声上。",
                "",
                "## 使用到的真实案例",
                "",
                f"- 已核验案例（{event_ids[0]}）",
                "",
                "## 使用到的关键数据",
                "",
                f"- 已核验数据（{source_ids[0]}）",
                "",
                "## 来源",
                "",
                f"- {source_ids[0]}",
            ]
        )
        script = "\n".join(lines)
        return self._response(script)
