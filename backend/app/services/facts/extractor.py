from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fact, Source, Topic
from app.schemas.domain import FactExtractionResult
from app.services.llm.service import LLMService
from app.services.prompts import render_prompt
from app.services.serialization import source_dict
from app.services.state import StepTracker
from app.utils import new_id, normalize_statement, stable_json


def split_content(content: str, chunk_size: int = 12_000, max_chunks: int = 3) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in content.splitlines() if paragraph.strip()]
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for paragraph in paragraphs:
        if current and length + len(paragraph) > chunk_size:
            chunks.append("\n".join(current))
            current, length = [], 0
            if len(chunks) >= max_chunks:
                break
        current.append(paragraph)
        length += len(paragraph) + 1
    if current and len(chunks) < max_chunks:
        chunks.append("\n".join(current))
    return chunks or [content[:chunk_size]]


PERSONAL_CASE_MARKERS = ("上班族", "大学生", "先生", "女士", "受访", "化名", "岁")


def personal_case_excerpt(content: str, max_chars: int = 12_000) -> str:
    paragraphs = [paragraph.strip() for paragraph in content.splitlines() if paragraph.strip()]
    matched = {
        neighbor
        for index, paragraph in enumerate(paragraphs)
        if any(marker in paragraph for marker in PERSONAL_CASE_MARKERS)
        for neighbor in range(max(0, index - 1), min(len(paragraphs), index + 2))
    }
    excerpt = "\n".join(paragraphs[index] for index in sorted(matched))
    return excerpt[:max_chars]


class FactExtractor:
    def __init__(self, llm: LLMService, tracker: StepTracker | None = None) -> None:
        self.llm = llm
        self.tracker = tracker or StepTracker()

    def _persist_drafts(
        self, session: Session, topic: Topic, source: Source, result: FactExtractionResult
    ) -> int:
        created = 0
        facts = list(session.scalars(select(Fact).where(Fact.topic_id == topic.id)))
        for draft in result.facts:
            key = normalize_statement(draft.statement)
            if not key:
                continue
            match = next(
                (
                    fact
                    for fact in facts
                    if fact.normalized_key == key
                    or SequenceMatcher(None, fact.normalized_key, key).ratio() >= 0.92
                ),
                None,
            )
            if match:
                match.source_ids = list(dict.fromkeys([*match.source_ids, source.id]))
                match.confidence = max(match.confidence, draft.confidence)
                match.people = list(dict.fromkeys([*match.people, *draft.people]))
                match.organizations = list(
                    dict.fromkeys([*match.organizations, *draft.organizations])
                )
                match.locations = list(dict.fromkeys([*match.locations, *draft.locations]))
                match.numbers = list(dict.fromkeys([*match.numbers, *draft.numbers]))
                continue
            fact = Fact(
                id=new_id("fact"),
                topic_id=topic.id,
                statement=draft.statement.strip(),
                normalized_key=key,
                fact_type=draft.fact_type.value,
                date=draft.date,
                people=draft.people,
                organizations=draft.organizations,
                locations=draft.locations,
                numbers=draft.numbers,
                source_ids=[source.id],
                confidence=draft.confidence,
            )
            session.add(fact)
            facts.append(fact)
            created += 1
        session.flush()
        return created

    async def extract_source(self, session: Session, topic: Topic, source: Source) -> int:
        created = 0
        for index, content in enumerate(split_content(source.content)):
            step = f"extract_source:{source.id}:{index}"
            if not self.tracker.start(session, topic, step):
                continue
            try:
                prompt = render_prompt(
                    "fact_extractor",
                    topic=topic.title,
                    source=stable_json(source_dict(source, include_content=False)),
                    content=content,
                )
                result = await self.llm.generate_model(
                    session,
                    topic.id,
                    step,
                    "真实性高于戏剧性。只抽取来源正文明确支持的事实。",
                    prompt,
                    FactExtractionResult,
                )
                created += self._persist_drafts(session, topic, source, result)
                self.tracker.complete(session, topic, step)
            except Exception as error:
                self.tracker.fail(session, topic, step, str(error))
                raise

        source_facts = [
            fact
            for fact in session.scalars(select(Fact).where(Fact.topic_id == topic.id))
            if source.id in fact.source_ids
        ]
        excerpt = personal_case_excerpt(source.content)
        if excerpt and not any(fact.fact_type == "PERSONAL_CASE" for fact in source_facts):
            step = f"extract_source:{source.id}:personal_cases"
            if self.tracker.start(session, topic, step):
                try:
                    prompt = render_prompt(
                        "fact_extractor",
                        topic=topic.title,
                        source=stable_json(source_dict(source, include_content=False)),
                        content=(
                            "只抽取正文明确记载的具体个人案例，包括年龄、身份、行为、损失和原话；"
                            "没有明确案例就返回空 facts。\n\n" + excerpt
                        ),
                    )
                    result = await self.llm.generate_model(
                        session,
                        topic.id,
                        step,
                        "只抽取可追溯的个人案例，不得把群体概括改写成人物。",
                        prompt,
                        FactExtractionResult,
                    )
                    created += self._persist_drafts(session, topic, source, result)
                    self.tracker.complete(session, topic, step)
                except Exception as error:
                    self.tracker.fail(session, topic, step, str(error))
                    raise
        return created
