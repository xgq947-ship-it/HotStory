from __future__ import annotations

from app.models import Event, Fact, Source, StepRun, Topic


def topic_dict(topic: Topic) -> dict:
    return {
        "id": topic.id,
        "title": topic.title,
        "input_mode": topic.input_mode,
        "status": topic.status,
        "current_step": topic.current_step,
        "error": topic.error,
        "requested_duration": topic.requested_duration,
        "research_depth": topic.research_depth,
        "created_at": topic.created_at.isoformat(),
        "updated_at": topic.updated_at.isoformat(),
    }


def source_dict(source: Source, include_content: bool = True) -> dict:
    data = {
        "id": source.id,
        "topic_id": source.topic_id,
        "title": source.title,
        "url": source.url,
        "publisher": source.publisher,
        "published_at": source.published_at,
        "author": source.author,
        "language": source.language,
        "content_hash": source.content_hash,
        "source_type": source.source_type,
        "credibility_score": source.credibility_score,
        "crawler": source.crawler,
        "fetch_status": source.fetch_status,
        "fetch_error": source.fetch_error,
        "snippet": source.snippet,
    }
    if include_content:
        data["content"] = source.content
        data["markdown"] = source.markdown
    return data


def fact_dict(fact: Fact) -> dict:
    return {
        "id": fact.id,
        "topic_id": fact.topic_id,
        "statement": fact.statement,
        "fact_type": fact.fact_type,
        "date": fact.date,
        "people": fact.people,
        "organizations": fact.organizations,
        "locations": fact.locations,
        "numbers": fact.numbers,
        "source_ids": fact.source_ids,
        "confidence": fact.confidence,
        "verification_status": fact.verification_status,
        "verified": fact.verified,
        "sensitive": fact.sensitive,
    }


def event_dict(event: Event) -> dict:
    return {
        "id": event.id,
        "topic_id": event.topic_id,
        "title": event.title,
        "summary": event.summary,
        "date": event.date,
        "event_type": event.event_type,
        "fact_ids": event.fact_ids,
        "source_ids": event.source_ids,
        "people": event.people,
        "emotion": event.emotion,
        "confidence": event.confidence,
    }


def step_dict(step: StepRun) -> dict:
    return {
        "step": step.step,
        "status": step.status,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
        "error": step.error,
        "retry_count": step.retry_count,
    }
