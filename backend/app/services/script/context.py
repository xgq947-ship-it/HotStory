from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Fact, Source, Topic
from app.services.artifacts import ProjectStore
from app.services.serialization import event_dict, fact_dict, source_dict


def narrative_context(session: Session, topic: Topic, store: ProjectStore) -> dict:
    all_events = list(session.scalars(select(Event).where(Event.topic_id == topic.id)))
    story_arc = store.load_json(session, topic.id, "story_arc") or {}
    stage_ids = [
        event_id
        for stage in story_arc.get("story_arc", [])
        for event_id in stage.get("event_ids", [])[:1]
    ]
    selected_ids = list(
        dict.fromkeys(
            [
                *stage_ids,
                *story_arc.get("selected_cases", [])[:3],
                *story_arc.get("selected_data", [])[:4],
                *story_arc.get("selected_events", []),
            ]
        )
    )[:18]
    event_by_id = {event.id: event for event in all_events}
    events = [event_by_id[event_id] for event_id in selected_ids if event_id in event_by_id]
    if not events:
        events = all_events[:16]
    selected_fact_ids = {fact_id for event in events for fact_id in event.fact_ids}
    verified_facts = (
        list(
            session.scalars(
                select(Fact).where(
                    Fact.topic_id == topic.id,
                    Fact.verified.is_(True),
                    Fact.id.in_(selected_fact_ids),
                )
            )
        )
        if selected_fact_ids
        else []
    )
    source_ids = {source_id for event in events for source_id in event.source_ids}
    sources = (
        list(
            session.scalars(
                select(Source).where(Source.topic_id == topic.id, Source.id.in_(source_ids))
            )
        )
        if source_ids
        else []
    )
    timeline = store.load_json(session, topic.id, "timeline") or {"timeline": []}
    selected_event_ids = {event.id for event in events}
    timeline["timeline"] = [
        item
        for item in timeline.get("timeline", [])
        if set(item.get("event_ids", [])) & selected_event_ids
    ]
    return {
        "topic": topic.title,
        "events": [event_dict(event) for event in events],
        "facts": [fact_dict(fact) for fact in verified_facts],
        "sources": [source_dict(source, include_content=False) for source in sources],
        "timeline": timeline,
        "story_arc": story_arc,
        "value": store.load_json(session, topic.id, "value") or {},
    }
