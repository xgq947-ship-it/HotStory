from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Event, Fact, Source


def material_counts(session: Session, topic_id: str) -> dict[str, int]:
    valid_sources = (
        session.scalar(
            select(func.count())
            .select_from(Source)
            .where(Source.topic_id == topic_id, Source.fetch_status == "SUCCESS")
        )
        or 0
    )
    verified_facts = (
        session.scalar(
            select(func.count())
            .select_from(Fact)
            .where(Fact.topic_id == topic_id, Fact.verified.is_(True))
        )
        or 0
    )
    personal_cases = (
        session.scalar(
            select(func.count())
            .select_from(Fact)
            .where(
                Fact.topic_id == topic_id,
                Fact.verified.is_(True),
                Fact.fact_type == "PERSONAL_CASE",
            )
        )
        or 0
    )
    key_data = (
        session.scalar(
            select(func.count())
            .select_from(Fact)
            .where(
                Fact.topic_id == topic_id,
                Fact.verified.is_(True),
                Fact.fact_type == "DATA",
            )
        )
        or 0
    )
    timeline_events = (
        session.scalar(select(func.count()).select_from(Event).where(Event.topic_id == topic_id))
        or 0
    )
    return {
        "valid_sources": int(valid_sources),
        "verified_facts": int(verified_facts),
        "personal_cases": int(personal_cases),
        "key_data": int(key_data),
        "timeline_events": int(timeline_events),
    }


def minimums(settings: Settings) -> dict[str, int]:
    return {
        "valid_sources": settings.min_valid_sources,
        "verified_facts": settings.min_verified_facts,
        "personal_cases": settings.min_personal_cases,
        "key_data": settings.min_key_data,
        "timeline_events": 5,
    }


def material_ready(counts: dict[str, int], settings: Settings) -> bool:
    return all(counts[key] >= value for key, value in minimums(settings).items())


def material_shortage_message(counts: dict[str, int], settings: Settings) -> str:
    missing = [
        f"{key} {counts.get(key, 0)}/{required}"
        for key, required in minimums(settings).items()
        if counts.get(key, 0) < required
    ]
    return "研究素材不足：" + "，".join(missing) + "。请点击“继续深挖”，系统不会重复已完成请求。"
