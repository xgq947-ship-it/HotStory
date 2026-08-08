from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Topic
from app.schemas.domain import TimelineItemData, TimelineResult
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.services.serialization import event_dict
from app.utils import stable_json


class TimelineBuilder:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def build(self, session: Session, topic: Topic) -> TimelineResult:
        events = list(session.scalars(select(Event).where(Event.topic_id == topic.id)))
        if not events:
            raise RuntimeError("没有已核验事件，无法构建时间线")
        prompt = render_prompt(
            "timeline_builder",
            topic=topic.title,
            events=stable_json([event_dict(event) for event in events]),
        )
        try:
            result = await self.llm.generate_model(
                session,
                topic.id,
                "timeline_builder",
                "严格按已核验事件恢复时间线，不补充输入之外的事实。",
                prompt,
                TimelineResult,
            )
        except Exception:
            sorted_events = sorted(events, key=lambda item: (item.date or "9999", item.id))
            result = TimelineResult(
                timeline=[
                    TimelineItemData(
                        date=event.date,
                        title=event.title,
                        description=event.summary,
                        event_ids=[event.id],
                        importance=min(1.0, max(0.5, event.confidence)),
                    )
                    for event in sorted_events
                ]
            )
        allowed = {event.id for event in events}
        result.timeline = [
            item.model_copy(
                update={
                    "event_ids": [event_id for event_id in item.event_ids if event_id in allowed]
                }
            )
            for item in result.timeline
            if any(event_id in allowed for event_id in item.event_ids)
        ]
        return result
