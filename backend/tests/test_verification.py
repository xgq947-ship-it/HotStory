from __future__ import annotations

import pytest

from app.models import Fact, Source, Topic
from app.services.artifacts import ProjectStore
from app.services.facts.cross_validation import cross_validate_claims
from app.services.facts.verification import verify_facts
from app.services.llm.mock import MockLLMProvider
from app.services.llm.service import LLMService
from app.utils import new_id


def test_sensitive_fact_requires_two_independent_sources(session_factory) -> None:
    with session_factory() as session:
        topic = Topic(id=new_id("topic"), title="有人因事件死亡的敏感事实测试")
        source_a = Source(
            id=new_id("source"),
            topic_id=topic.id,
            title="来源 A",
            url="https://a.gov/report",
            normalized_url="https://a.gov/report",
            publisher="a.gov",
            credibility_score=0.9,
        )
        source_b = Source(
            id=new_id("source"),
            topic_id=topic.id,
            title="来源 B",
            url="https://b.gov/report",
            normalized_url="https://b.gov/report",
            publisher="b.gov",
            credibility_score=0.9,
        )
        fact = Fact(
            id=new_id("fact"),
            topic_id=topic.id,
            statement="报道称有人因事件死亡",
            normalized_key="报道称有人因事件死亡",
            fact_type="CONSEQUENCE",
            source_ids=[source_a.id],
            confidence=0.95,
        )
        session.add_all([topic, source_a, source_b, fact])
        session.commit()

        verify_facts(session, topic.id)
        assert fact.sensitive is True
        assert fact.verified is False

        fact.source_ids = [source_a.id, source_b.id]
        session.commit()
        verify_facts(session, topic.id)
        assert fact.verified is True
        assert fact.verification_status == "confirmed"


@pytest.mark.asyncio
async def test_cross_validation_merges_only_existing_claim_sources(
    session_factory, test_settings
) -> None:
    with session_factory() as session:
        topic = Topic(id=new_id("topic"), title="机构公布参与人数交叉验证")
        source_a = Source(
            id=new_id("source"),
            topic_id=topic.id,
            title="来源 A",
            url="https://a.example/report",
            normalized_url="https://a.example/report",
            publisher="a.example",
        )
        source_b = Source(
            id=new_id("source"),
            topic_id=topic.id,
            title="来源 B",
            url="https://b.example/report",
            normalized_url="https://b.example/report",
            publisher="b.example",
        )
        fact_a = Fact(
            id=new_id("fact"),
            topic_id=topic.id,
            statement="机构公布参与人数为 100 人",
            normalized_key="机构公布参与人数为100人",
            fact_type="DATA",
            date="2026-01",
            numbers=["100 人"],
            source_ids=[source_a.id],
            confidence=0.9,
        )
        fact_b = Fact(
            id=new_id("fact"),
            topic_id=topic.id,
            statement="官方数据称共有 100 人参与",
            normalized_key="官方数据称共有100人参与",
            fact_type="DATA",
            date="2026-01",
            numbers=["100 人"],
            source_ids=[source_b.id],
            confidence=0.9,
        )
        session.add_all([topic, source_a, source_b, fact_a, fact_b])
        session.commit()

        provider = MockLLMProvider(
            [
                {
                    "groups": [
                        {
                            "fact_ids": [fact_a.id, fact_b.id],
                            "relationship": "same_claim",
                            "reason": "同一日期和数字的同一主张",
                        }
                    ]
                }
            ]
        )
        llm = LLMService(provider, ProjectStore(test_settings))
        await cross_validate_claims(session, topic, llm)

        assert set(fact_a.source_ids) == {source_a.id, source_b.id}
        assert set(fact_b.source_ids) == {source_a.id, source_b.id}
