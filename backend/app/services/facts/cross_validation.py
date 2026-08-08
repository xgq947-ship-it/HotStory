from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fact, Source, Topic
from app.schemas.domain import FactVerificationResult
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.services.relevance import fact_matches_topic
from app.utils import stable_json


async def cross_validate_claims(
    session: Session, topic: Topic, llm: LLMService
) -> FactVerificationResult:
    facts = list(session.scalars(select(Fact).where(Fact.topic_id == topic.id)))
    sources = list(session.scalars(select(Source).where(Source.topic_id == topic.id)))
    sources_by_id = {source.id: source for source in sources}
    facts = [fact for fact in facts if fact_matches_topic(fact, topic.title, sources_by_id)]
    if len(facts) < 2:
        return FactVerificationResult()
    compact = [
        {
            "id": fact.id,
            "statement": fact.statement,
            "fact_type": fact.fact_type,
            "date": fact.date,
            "people": fact.people,
            "organizations": fact.organizations,
            "locations": fact.locations,
            "numbers": fact.numbers,
            "source_ids": fact.source_ids,
        }
        for fact in facts
    ]
    prompt = render_prompt("fact_verifier", topic=topic.title, facts=stable_json(compact))
    try:
        result = await llm.generate_model(
            session,
            topic.id,
            "fact_cross_validation",
            "多来源验证优先于单一来源。只能比较输入里的 fact_id，不得创造事实。",
            prompt,
            FactVerificationResult,
        )
    except Exception:
        return FactVerificationResult()

    fact_by_id = {fact.id: fact for fact in facts}
    accepted_groups = []
    for group in result.groups:
        ids = list(dict.fromkeys(fact_id for fact_id in group.fact_ids if fact_id in fact_by_id))
        if len(ids) < 2:
            continue
        members = [fact_by_id[fact_id] for fact_id in ids]
        if group.relationship == "same_claim":
            numeric_sets = {tuple(sorted(fact.numbers)) for fact in members if fact.numbers}
            date_sets = {fact.date for fact in members if fact.date}
            if len(numeric_sets) > 1 or len(date_sets) > 1:
                for fact in members:
                    fact.verification_status = "conflicting"
                    fact.verified = False
                continue
            source_ids = list(
                dict.fromkeys(source_id for fact in members for source_id in fact.source_ids)
            )
            for fact in members:
                fact.source_ids = source_ids
        else:
            for fact in members:
                fact.verification_status = "conflicting"
                fact.verified = False
        accepted_groups.append(group.model_copy(update={"fact_ids": ids}))
    session.commit()
    return FactVerificationResult(groups=accepted_groups)
