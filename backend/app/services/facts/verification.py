from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fact, Source, Topic
from app.services.relevance import fact_matches_topic

SENSITIVE_PATTERN = re.compile(
    r"死亡|自杀|跳楼|暴力|犯罪|刑事|未成年|医疗|重伤|灾难|爆仓|重大损失|破产|死亡人数|"
    r"death|suicide|killed|minor|crime|medical|bankrupt|liquidat",
    re.IGNORECASE,
)


def _publisher_count(fact: Fact, sources_by_id: dict[str, Source]) -> int:
    publishers = {
        sources_by_id[source_id].publisher or sources_by_id[source_id].normalized_url
        for source_id in fact.source_ids
        if source_id in sources_by_id
    }
    return len(publishers)


def verify_facts(session: Session, topic_id: str) -> list[Fact]:
    facts = list(session.scalars(select(Fact).where(Fact.topic_id == topic_id)))
    sources = list(session.scalars(select(Source).where(Source.topic_id == topic_id)))
    sources_by_id = {source.id: source for source in sources}
    topic = session.get(Topic, topic_id)

    for fact in facts:
        fact.sensitive = bool(SENSITIVE_PATTERN.search(fact.statement))
        if topic and not fact_matches_topic(fact, topic.title, sources_by_id):
            fact.verification_status = "irrelevant"
            fact.verified = False
            continue
        if fact.verification_status == "conflicting":
            fact.verified = False
            continue
        independent_sources = _publisher_count(fact, sources_by_id)
        max_credibility = max(
            (
                sources_by_id[source_id].credibility_score
                for source_id in fact.source_ids
                if source_id in sources_by_id
            ),
            default=0.0,
        )
        if fact.confidence < 0.5:
            fact.verification_status = "discard"
            fact.verified = False
        elif fact.sensitive:
            if independent_sources >= 2 and fact.confidence >= 0.7:
                fact.verification_status = "confirmed"
                fact.verified = True
            else:
                fact.verification_status = "uncertain"
                fact.verified = False
        elif independent_sources >= 2 and fact.confidence >= 0.7:
            fact.verification_status = "confirmed"
            fact.verified = True
        elif fact.confidence >= 0.85 and max_credibility >= 0.75:
            fact.verification_status = "confirmed"
            fact.verified = True
        elif fact.confidence >= 0.7:
            fact.verification_status = "probable"
            fact.verified = False
        else:
            fact.verification_status = "uncertain"
            fact.verified = False

    # Detect likely numeric conflicts within the same entity/type group.
    grouped: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for fact in facts:
        entity = "|".join(sorted([*fact.people, *fact.organizations])[:2])
        if entity and fact.numbers:
            grouped[(fact.fact_type, entity)].append(fact)
    for candidates in grouped.values():
        for index, left in enumerate(candidates):
            for right in candidates[index + 1 :]:
                similarity = SequenceMatcher(None, left.statement, right.statement).ratio()
                if 0.35 <= similarity < 0.9 and set(left.numbers) != set(right.numbers):
                    left.verification_status = "conflicting"
                    right.verification_status = "conflicting"
                    left.verified = right.verified = False

    session.commit()
    return facts
