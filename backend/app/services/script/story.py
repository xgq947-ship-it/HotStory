from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Topic
from app.schemas.domain import StoryArcData, StoryStage
from app.services.artifacts import ProjectStore
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.services.serialization import event_dict
from app.utils import stable_json


def young_case_score(event: Event) -> int:
    ages = [int(value) for value in re.findall(r"(\d{2})岁", f"{event.title} {event.summary}")]
    return 1 if any(18 <= age <= 35 for age in ages) else 0


class StoryBuilder:
    def __init__(self, llm: LLMService, store: ProjectStore) -> None:
        self.llm = llm
        self.store = store

    async def build(self, session: Session, topic: Topic) -> StoryArcData:
        events = list(session.scalars(select(Event).where(Event.topic_id == topic.id)))
        timeline = self.store.load_json(session, topic.id, "timeline") or {"timeline": []}
        context = {"events": [event_dict(event) for event in events], "timeline": timeline}
        prompt = render_prompt("story_builder", topic=topic.title, context=stable_json(context))
        try:
            result = await self.llm.generate_model(
                session,
                topic.id,
                "story_builder",
                "组织真实事件，不创造事实。所有选择必须引用已提供的 event_id。",
                prompt,
                StoryArcData,
            )
        except Exception:
            cases = [event.id for event in events if event.event_type == "PERSONAL_CASE"]
            data = [event.id for event in events if event.event_type == "DATA"]
            result = StoryArcData(
                central_theme=topic.title,
                core_conflict="个人选择与现实后果",
                story_arc=[
                    StoryStage(stage="背景", event_ids=[event.id for event in events[:2]]),
                    StoryStage(stage="转折", event_ids=[event.id for event in events[2:4]]),
                    StoryStage(stage="反思", event_ids=[event.id for event in events[4:6]]),
                ],
                selected_events=[event.id for event in events[:12]],
                selected_cases=cases[:3],
                selected_data=data[:4],
            )
        allowed = {event.id for event in events}
        selected_cases = [item for item in result.selected_cases if item in allowed]
        if "年轻" in topic.title:
            case_events = sorted(
                (event for event in events if event.event_type == "PERSONAL_CASE"),
                key=lambda event: (-young_case_score(event), -event.confidence),
            )
            selected_cases = list(
                dict.fromkeys(
                    [
                        *[event.id for event in case_events if young_case_score(event)],
                        *selected_cases,
                    ]
                )
            )[:3]
        return result.model_copy(
            update={
                "selected_events": [item for item in result.selected_events if item in allowed],
                "selected_cases": selected_cases,
                "selected_data": [item for item in result.selected_data if item in allowed],
                "story_arc": [
                    stage.model_copy(
                        update={"event_ids": [item for item in stage.event_ids if item in allowed]}
                    )
                    for stage in result.story_arc
                ],
            }
        )
