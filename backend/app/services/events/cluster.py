from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Event, Fact, Source, Topic
from app.schemas.domain import EventClusterResult
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.services.relevance import fact_matches_topic
from app.services.serialization import fact_dict
from app.utils import new_id, stable_json


class EventClusterer:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    def _fallback(self, facts: list[Fact]) -> list[dict]:
        groups: dict[tuple[str, str, str], list[Fact]] = defaultdict(list)
        for fact in facts:
            person = fact.people[0] if fact.people else ""
            groups[(fact.date, fact.fact_type, person)].append(fact)
        events: list[dict] = []
        for (_date, _type, _person), group in groups.items():
            events.append(
                {
                    "title": group[0].statement[:80],
                    "summary": "；".join(fact.statement for fact in group[:3]),
                    "date": group[0].date,
                    "event_type": group[0].fact_type,
                    "fact_ids": [fact.id for fact in group],
                    "people": list(
                        dict.fromkeys(person for fact in group for person in fact.people)
                    ),
                    "emotion": [],
                    "confidence": sum(fact.confidence for fact in group) / len(group),
                }
            )
        return events

    async def cluster(self, session: Session, topic: Topic) -> list[Event]:
        facts = list(
            session.scalars(select(Fact).where(Fact.topic_id == topic.id, Fact.confidence >= 0.5))
        )
        sources = list(session.scalars(select(Source).where(Source.topic_id == topic.id)))
        sources_by_id = {source.id: source for source in sources}
        facts = [fact for fact in facts if fact_matches_topic(fact, topic.title, sources_by_id)]
        if not facts:
            raise RuntimeError("没有可用事实，无法聚类事件")
        prompt = render_prompt(
            "event_cluster",
            topic=topic.title,
            facts=stable_json([fact_dict(fact) for fact in facts]),
        )
        try:
            result = await self.llm.generate_model(
                session,
                topic.id,
                "event_cluster",
                "来源与事实优先。只合并描述同一现实事件的事实。",
                prompt,
                EventClusterResult,
            )
            drafts = [draft.model_dump(mode="json") for draft in result.events]
        except Exception:
            drafts = self._fallback(facts)

        fact_by_id = {fact.id: fact for fact in facts}
        session.execute(delete(Event).where(Event.topic_id == topic.id))
        events: list[Event] = []
        assigned: set[str] = set()
        for draft in drafts:
            fact_ids = [fact_id for fact_id in draft["fact_ids"] if fact_id in fact_by_id]
            if not fact_ids:
                continue
            assigned.update(fact_ids)
            related = [fact_by_id[fact_id] for fact_id in fact_ids]
            source_ids = list(
                dict.fromkeys(source_id for fact in related for source_id in fact.source_ids)
            )
            event = Event(
                id=new_id("event"),
                topic_id=topic.id,
                title=draft["title"],
                summary=draft["summary"],
                date=draft.get("date", ""),
                event_type=str(draft["event_type"]),
                fact_ids=fact_ids,
                source_ids=source_ids,
                people=draft.get("people", []),
                emotion=draft.get("emotion", []),
                confidence=float(draft.get("confidence", 0.0)),
            )
            session.add(event)
            events.append(event)
        for fact in facts:
            if fact.id in assigned:
                continue
            event = Event(
                id=new_id("event"),
                topic_id=topic.id,
                title=fact.statement[:100],
                summary=fact.statement,
                date=fact.date,
                event_type=fact.fact_type,
                fact_ids=[fact.id],
                source_ids=fact.source_ids,
                people=fact.people,
                emotion=[],
                confidence=fact.confidence,
            )
            session.add(event)
            events.append(event)
        session.commit()
        return events
