from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Topic
from app.schemas.domain import StoryArcData, StoryBeatData, StoryStage
from app.services.artifacts import ProjectStore
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.services.script.narrative_quality import assess_story_arc
from app.services.serialization import event_dict
from app.utils import stable_json


def young_case_score(event: Event) -> int:
    ages = [int(value) for value in re.findall(r"(\d{2})岁", f"{event.title} {event.summary}")]
    return 1 if any(18 <= age <= 35 for age in ages) else 0


def _failure_note(error: Exception) -> str:
    message = re.sub(r"https?://\S+", "上游接口", str(error).strip())
    return (message.splitlines()[0] if message else "上游未返回可用内容")[:240]


class StoryBuilder:
    def __init__(self, llm: LLMService, store: ProjectStore) -> None:
        self.llm = llm
        self.store = store

    async def build(self, session: Session, topic: Topic) -> StoryArcData:
        events = list(session.scalars(select(Event).where(Event.topic_id == topic.id)))
        event_payloads = [event_dict(event) for event in events]
        timeline = self.store.load_json(session, topic.id, "timeline") or {"timeline": []}
        context = {"events": event_payloads, "timeline": timeline}
        prompt = render_prompt("story_builder", topic=topic.title, context=stable_json(context))

        try:
            result = await self.llm.generate_model(
                session,
                topic.id,
                "story_builder",
                (
                    "组织真实事件，不创造事实。事实因果与编辑承接必须明确区分，"
                    "人物表演只能作为已标注的影视化合成还原。"
                ),
                prompt,
                StoryArcData,
            )
            result = self._normalize(result, events, topic, generation_mode="ai_generated")
        except Exception as error:
            return self._fallback(events, topic, _failure_note(error))

        if result.quality.passed:
            return result

        repair_prompt = render_prompt(
            "story_repair",
            topic=topic.title,
            context=stable_json(context),
            draft=stable_json(result.model_dump(mode="json")),
            issues=stable_json(result.quality.issues),
        )
        try:
            repaired = await self.llm.generate_model(
                session,
                topic.id,
                "story_builder:repair",
                (
                    "只修复叙事结构，不新增事实。必须保留事实因果与编辑承接的边界。"
                ),
                repair_prompt,
                StoryArcData,
            )
            repaired = self._normalize(
                repaired, events, topic, generation_mode="ai_generated"
            )
            if repaired.quality.passed:
                return repaired
            reason = "故事修复后仍未通过质量门：" + "；".join(repaired.quality.issues[:3])
        except Exception as error:
            reason = "故事修复调用失败：" + _failure_note(error)
        return self._fallback(events, topic, reason)

    def _normalize(
        self,
        result: StoryArcData,
        events: list[Event],
        topic: Topic,
        *,
        generation_mode: str,
        generation_note: str = "",
    ) -> StoryArcData:
        allowed = {event.id for event in events}
        event_by_id = {event.id: event for event in events}
        allowed_sources = {source_id for event in events for source_id in event.source_ids}
        selected_cases = [item for item in result.selected_cases if item in allowed]
        case_events = sorted(
            (event for event in events if event.event_type == "PERSONAL_CASE"),
            key=lambda event: (
                -young_case_score(event) if "年轻" in topic.title else 0,
                -event.confidence,
            ),
        )
        if "年轻" in topic.title:
            selected_cases = list(
                dict.fromkeys(
                    [
                        *[event.id for event in case_events if young_case_score(event)],
                        *selected_cases,
                    ]
                )
            )[:3]

        protagonist_event_id = result.protagonist_event_id
        if protagonist_event_id not in {event.id for event in case_events}:
            protagonist_event_id = (
                selected_cases[0]
                if selected_cases
                else (case_events[0].id if case_events else "")
            )

        beats: list[StoryBeatData] = []
        for index, beat in enumerate(result.beats[:16], 1):
            event_ids = [
                item for item in dict.fromkeys(beat.event_ids) if item in allowed
            ]
            supporting_sources = {
                source_id
                for event_id in event_ids
                for source_id in event_by_id[event_id].source_ids
            }
            source_ids = [
                item
                for item in dict.fromkeys(beat.source_ids)
                if item in allowed_sources
                and (not supporting_sources or item in supporting_sources)
            ]
            if not source_ids:
                source_ids = list(supporting_sources)
            beats.append(
                beat.model_copy(
                    update={
                        "beat_id": f"beat_{index:02d}",
                        "event_ids": event_ids,
                        "source_ids": source_ids,
                    }
                )
            )

        normalized = result.model_copy(
            update={
                "narrative_mode": "cinematic_human_story",
                "generation_mode": generation_mode,
                "generation_note": generation_note,
                "protagonist_event_id": protagonist_event_id,
                "beats": beats,
                "selected_events": [
                    item for item in result.selected_events if item in allowed
                ],
                "selected_cases": selected_cases,
                "selected_data": [item for item in result.selected_data if item in allowed],
                "story_arc": [
                    stage.model_copy(
                        update={
                            "event_ids": [
                                item for item in stage.event_ids if item in allowed
                            ]
                        }
                    )
                    for stage in result.story_arc
                ],
            }
        )
        quality = assess_story_arc(normalized, [event_dict(event) for event in events])
        return normalized.model_copy(update={"quality": quality})

    def _fallback(self, events: list[Event], topic: Topic, reason: str) -> StoryArcData:
        if not events:
            raise RuntimeError("没有可用于构建故事的已核验事件")

        cases = sorted(
            (event for event in events if event.event_type == "PERSONAL_CASE"),
            key=lambda event: (
                -young_case_score(event) if "年轻" in topic.title else 0,
                -event.confidence,
            ),
        )
        data_events = [event for event in events if event.event_type == "DATA"]
        turns = [
            event
            for event in events
            if event.event_type in {"TURNING_POINT", "CONSEQUENCE"}
        ]
        responses = [
            event for event in events if event.event_type in {"RESPONSE", "POLICY", "SOCIAL"}
        ]
        protagonist = cases[0] if cases else events[0]
        ordered_pool = list(
            {
                event.id: event
                for event in [
                    *(turns[-1:] or events[-1:]),
                    protagonist,
                    *events,
                    *data_events,
                    *turns,
                    *cases[1:],
                    *responses,
                ]
            }.values()
        )

        functions = [
            ("结果前置钩子", 82, "稳定", "疑问被立刻打开", "先给结果，再追问原因"),
            ("人物起点", 34, "陌生", "选择变得具体", "把宏观问题压到一个已核验案例"),
            ("承诺与机会", 46, "观望", "行动开始", "用机会或背景事实建立期待"),
            ("压力升级", 63, "可控", "风险开始累积", "让数据改变人物处境的理解"),
            ("局势转折", 94, "期待", "原判断失效", "用转折或后果事实改变方向"),
            ("代价显现", 79, "抽象风险", "生活代价可见", "回到人物与具体后果"),
            ("选择与回应", 57, "被动承受", "出现新的应对", "呈现回应而不替人物下结论"),
            ("余波与行动收束", 29, "事件结束", "影响仍在继续", "以未完成动作和环境余音收束"),
        ]
        beats: list[StoryBeatData] = []
        for index, (function, intensity, before, after, tactic) in enumerate(functions):
            event = ordered_pool[index % len(ordered_pool)]
            is_case = event.event_type == "PERSONAL_CASE"
            beats.append(
                StoryBeatData(
                    beat_id=f"beat_{index + 1:02d}",
                    narrative_function=function,
                    objective="让当前已核验事实改变观众对局势的判断",
                    obstacle="素材容易被平铺成互不相干的信息段落",
                    stakes="如果局势没有发生可见变化，这个节拍就不能进入成片",
                    tactic=tactic,
                    turn=event.summary,
                    value_before=before,
                    value_after=after,
                    cause_link=(
                        ""
                        if index == 0
                        else "承接上一节拍留下的问题，以编辑关系推进；不把未核验联系写成事实因果。"
                    ),
                    causal_basis="editorial_transition",
                    dramatization_mode=(
                        "composite_reenactment" if is_case else "archive_or_data"
                    ),
                    visual_action=(
                        "影视化合成还原：用不指向真人外貌的成年演员完成一项与素材相容的日常事务，"
                        "以动作中断承载信息；不宣称该动作真实发生。"
                        if is_case
                        else "用对应公开资料、环境主体或可核验数据完成一个明确视觉动作。"
                    ),
                    event_ids=[event.id],
                    source_ids=list(event.source_ids),
                    intensity=intensity,
                )
            )

        stages = [
            StoryStage(stage=beat.narrative_function, event_ids=beat.event_ids)
            for beat in beats
        ]
        draft = StoryArcData(
            central_theme=topic.title,
            core_conflict="一个具体选择如何在现实条件改变后承担后果",
            narrative_mode="cinematic_human_story",
            generation_mode="deterministic_fallback",
            generation_note=reason,
            protagonist_event_id=protagonist.id,
            dramatic_question="当外部条件改变时，这个已核验案例中的选择会面对什么现实代价？",
            ending_device="以最后一个已核验事实后的未完成动作与环境余音收束，不追加道理总结。",
            beats=beats,
            story_arc=stages,
            selected_events=list(dict.fromkeys(beat.event_ids[0] for beat in beats)),
            selected_cases=[event.id for event in cases[:3]],
            selected_data=[event.id for event in data_events[:4]],
        )
        return self._normalize(
            draft,
            events,
            topic,
            generation_mode="deterministic_fallback",
            generation_note=reason,
        )
