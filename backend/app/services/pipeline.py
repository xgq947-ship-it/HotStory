from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import Event, Fact, SearchRun, Source, StepRun, Topic
from app.schemas.domain import ResearchPlanData
from app.services.artifacts import ProjectStore
from app.services.crawler import create_crawler_provider
from app.services.crawler.provider import CrawlerProvider
from app.services.events import EventClusterer
from app.services.facts import FactExtractor, cross_validate_claims, verify_facts
from app.services.llm import LLMProvider, LLMService, create_llm_provider
from app.services.materials import material_counts, material_ready, material_shortage_message
from app.services.research import GPTResearcherEngine, NativeResearchEngine, ResearchEngine
from app.services.script import ScriptReviewer, ScriptWriter, StoryBuilder, ValueBuilder
from app.services.search import create_search_provider
from app.services.search.provider import SearchProvider
from app.services.serialization import event_dict, fact_dict, source_dict, topic_dict
from app.services.sources import (
    apply_crawled_content,
    refresh_credibility_scores,
    remove_content_duplicates,
    upsert_search_results,
)
from app.services.state import StepTracker
from app.services.timeline import TimelineBuilder
from app.utils import sha256_text, stable_json

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        llm_provider: LLMProvider | None = None,
        search_provider: SearchProvider | None = None,
        crawler_provider: CrawlerProvider | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = ProjectStore(self.settings)
        self.llm_provider = llm_provider or create_llm_provider(self.settings)
        self.search_provider = search_provider or create_search_provider(self.settings)
        self.crawler_provider = crawler_provider or create_crawler_provider(self.settings)
        self.session_factory = session_factory or SessionLocal
        self.tracker = StepTracker()

    def _engine(self, session: Session, topic: Topic, llm: LLMService) -> ResearchEngine:
        native = NativeResearchEngine(session, topic.id, llm, self.search_provider, self.settings)
        if self.settings.research_engine.lower() == "gpt_researcher":
            return GPTResearcherEngine(native)
        return native

    async def run(self, topic_id: str) -> None:
        session = self.session_factory()
        try:
            topic = session.get(Topic, topic_id)
            if not topic:
                raise LookupError(f"Topic 不存在：{topic_id}")
            llm = LLMService(self.llm_provider, self.store)
            engine = self._engine(session, topic, llm)
            await self._plan(session, topic, engine)
            await self._search(session, topic, engine)
            await self._fetch(session, topic)
            await self._extract(session, topic, llm)
            await self._cluster(session, topic, llm)
            await self._verify(session, topic, llm)
            await self._timeline(session, topic, llm)

            counts = material_counts(session, topic.id)
            if not material_ready(counts, self.settings):
                error = material_shortage_message(counts, self.settings)
                self.tracker.fail(session, topic, "timeline", error)
                return

            await self._story(session, topic, llm)
            await self._value(session, topic, llm)
            await self._write(session, topic, llm)
            await self._review(session, topic, llm)
            await self._export(session, topic)
            topic.status = "COMPLETED"
            topic.current_step = "export"
            topic.error = None
            session.commit()
            self.store.save_json(session, topic.id, "topic", topic_dict(topic))
            session.commit()
            logger.info("pipeline completed", extra={"topic_id": topic.id, "step": "export"})
        except Exception as error:
            session.rollback()
            topic = session.get(Topic, topic_id)
            if topic:
                step = topic.current_step or "unknown"
                self.tracker.fail(session, topic, step, str(error))
            logger.exception("pipeline failed", extra={"topic_id": topic_id})
        finally:
            session.close()

    async def _plan(self, session: Session, topic: Topic, engine: ResearchEngine) -> None:
        if not self.tracker.start(session, topic, "plan"):
            return
        try:
            plan = await engine.build_plan(topic.title)
            self.store.save_json(session, topic.id, "research_plan", plan)
            self.store.save_json(session, topic.id, "topic", topic_dict(topic))
            session.commit()
            self.tracker.complete(
                session, topic, "plan", sha256_text(stable_json(plan.model_dump()))
            )
        except Exception as error:
            self.tracker.fail(session, topic, "plan", str(error))
            raise

    async def _search(self, session: Session, topic: Topic, engine: ResearchEngine) -> None:
        if not self.tracker.start(session, topic, "search"):
            return
        try:
            raw_plan = self.store.load_json(session, topic.id, "research_plan")
            if not raw_plan:
                raise RuntimeError("缺少 research_plan 中间结果")
            plan = ResearchPlanData.model_validate(raw_plan)
            results, queries = await engine.search(topic.title, plan, topic.research_depth)
            upsert_search_results(session, topic.id, results)
            all_runs = list(
                session.scalars(
                    select(SearchRun).where(SearchRun.topic_id == topic.id).order_by(SearchRun.id)
                )
            )
            output = {
                "queries": [
                    {
                        "round": run.round_name,
                        "query": run.query,
                        "status": run.status,
                        "results": run.results_json,
                        "error": run.error,
                    }
                    for run in all_runs
                ],
                "executed_queries": queries,
            }
            self.store.save_json(session, topic.id, "search_results", output)
            session.commit()
            self.tracker.complete(session, topic, "search", sha256_text(stable_json(output)))
        except Exception as error:
            self.tracker.fail(session, topic, "search", str(error))
            raise

    async def _fetch(self, session: Session, topic: Topic) -> None:
        if not self.tracker.start(session, topic, "fetch"):
            return
        try:
            sources = list(session.scalars(select(Source).where(Source.topic_id == topic.id)))
            semaphore = asyncio.Semaphore(self.settings.fetch_concurrency)

            async def fetch_one(source: Source) -> tuple[str, Any, str | None]:
                if source.fetch_status == "SUCCESS":
                    return source.id, None, None
                if source.retry_count >= self.settings.max_retries + 1:
                    return source.id, None, source.fetch_error or "已达到最大重试次数"
                async with semaphore:
                    try:
                        document = await self.crawler_provider.fetch(source.url)
                        return source.id, document, None
                    except Exception as error:
                        return source.id, None, str(error)

            outcomes = await asyncio.gather(*(fetch_one(source) for source in sources))
            for source_id, document, error in outcomes:
                source = session.get(Source, source_id)
                if not source or (document is None and error is None):
                    continue
                if document is not None:
                    apply_crawled_content(source, document)
                    source.fetched_at = datetime.now(UTC)
                else:
                    source.fetch_status = "FAILED"
                    source.fetch_error = (error or "抓取失败")[:2000]
                    source.retry_count += 1
            session.commit()
            remove_content_duplicates(session, topic.id)
            sources = list(session.scalars(select(Source).where(Source.topic_id == topic.id)))
            self.store.save_json(
                session, topic.id, "sources", [source_dict(source) for source in sources]
            )
            session.commit()
            valid = sum(source.fetch_status == "SUCCESS" for source in sources)
            if valid == 0:
                raise RuntimeError("没有成功抓取到任何有效正文")
            self.tracker.complete(session, topic, "fetch")
        except Exception as error:
            self.tracker.fail(session, topic, "fetch", str(error))
            raise

    async def _extract(self, session: Session, topic: Topic, llm: LLMService) -> None:
        if not self.tracker.start(session, topic, "extract"):
            return
        try:
            extractor = FactExtractor(llm, self.tracker)
            sources = list(
                session.scalars(
                    select(Source)
                    .where(Source.topic_id == topic.id, Source.fetch_status == "SUCCESS")
                    .order_by(Source.credibility_score.desc())
                )
            )
            failures: list[str] = []
            for source in sources:
                try:
                    await extractor.extract_source(session, topic, source)
                except Exception as error:
                    failures.append(f"{source.id}: {error}")
                    continue
            facts = list(session.scalars(select(Fact).where(Fact.topic_id == topic.id)))
            self.store.save_json(session, topic.id, "facts", [fact_dict(fact) for fact in facts])
            session.commit()
            if not facts:
                raise RuntimeError("事实提取未产生任何可用事实；" + "；".join(failures[:3]))
            self.tracker.complete(session, topic, "extract")
        except Exception as error:
            self.tracker.fail(session, topic, "extract", str(error))
            raise

    async def _cluster(self, session: Session, topic: Topic, llm: LLMService) -> None:
        if not self.tracker.start(session, topic, "cluster"):
            return
        try:
            events = await EventClusterer(llm).cluster(session, topic)
            self.store.save_json(
                session, topic.id, "events", [event_dict(event) for event in events]
            )
            session.commit()
            self.tracker.complete(session, topic, "cluster")
        except Exception as error:
            self.tracker.fail(session, topic, "cluster", str(error))
            raise

    async def _verify(self, session: Session, topic: Topic, llm: LLMService) -> None:
        if not self.tracker.start(session, topic, "verify"):
            return
        try:
            refresh_credibility_scores(session, topic.id)
            await cross_validate_claims(session, topic, llm)
            facts = verify_facts(session, topic.id)
            verified_by_id = {fact.id: fact for fact in facts if fact.verified}
            events = list(session.scalars(select(Event).where(Event.topic_id == topic.id)))
            for event in events:
                event.fact_ids = [
                    fact_id for fact_id in event.fact_ids if fact_id in verified_by_id
                ]
                if not event.fact_ids:
                    session.delete(event)
                    continue
                related = [verified_by_id[fact_id] for fact_id in event.fact_ids]
                event.title = related[0].statement[:100]
                event.summary = "；".join(fact.statement for fact in related[:3])
                event.source_ids = list(
                    dict.fromkeys(source_id for fact in related for source_id in fact.source_ids)
                )
                event.confidence = min(fact.confidence for fact in related)
            session.commit()
            verified_facts = [fact for fact in facts if fact.verified]
            remaining_events = list(
                session.scalars(select(Event).where(Event.topic_id == topic.id))
            )
            self.store.save_json(session, topic.id, "facts", [fact_dict(fact) for fact in facts])
            self.store.save_json(
                session, topic.id, "events", [event_dict(event) for event in remaining_events]
            )
            session.commit()
            if not verified_facts:
                raise RuntimeError("事实核验后没有可进入时间线的事实")
            self.tracker.complete(session, topic, "verify")
        except Exception as error:
            self.tracker.fail(session, topic, "verify", str(error))
            raise

    async def _timeline(self, session: Session, topic: Topic, llm: LLMService) -> None:
        if not self.tracker.start(session, topic, "timeline"):
            return
        try:
            result = await TimelineBuilder(llm).build(session, topic)
            self.store.save_json(session, topic.id, "timeline", result)
            session.commit()
            self.tracker.complete(session, topic, "timeline")
        except Exception as error:
            self.tracker.fail(session, topic, "timeline", str(error))
            raise

    async def _story(self, session: Session, topic: Topic, llm: LLMService) -> None:
        if not self.tracker.start(session, topic, "story"):
            return
        try:
            result = await StoryBuilder(llm, self.store).build(session, topic)
            self.store.save_json(session, topic.id, "story_arc", result)
            session.commit()
            self.tracker.complete(session, topic, "story")
        except Exception as error:
            self.tracker.fail(session, topic, "story", str(error))
            raise

    async def _value(self, session: Session, topic: Topic, llm: LLMService) -> None:
        if not self.tracker.start(session, topic, "value"):
            return
        try:
            result = await ValueBuilder(llm, self.store).build(session, topic)
            self.store.save_json(session, topic.id, "value", result)
            session.commit()
            self.tracker.complete(session, topic, "value")
        except Exception as error:
            self.tracker.fail(session, topic, "value", str(error))
            raise

    async def _write(self, session: Session, topic: Topic, llm: LLMService) -> None:
        if not self.tracker.start(session, topic, "write"):
            return
        try:
            script = await ScriptWriter(llm, self.store).write(
                session, topic, topic.requested_duration
            )
            self.store.save_text(session, topic.id, "script", script)
            session.commit()
            self.tracker.complete(session, topic, "write", sha256_text(script))
        except Exception as error:
            self.tracker.fail(session, topic, "write", str(error))
            raise

    async def _review(self, session: Session, topic: Topic, llm: LLMService) -> None:
        if not self.tracker.start(session, topic, "review"):
            return
        try:
            writer = ScriptWriter(llm, self.store)
            reviewer = ScriptReviewer(llm)
            script = self.store.load_text(session, topic.id, "script") or ""
            review = await reviewer.review(session, topic, script)
            rewrite_count = 0
            fallback_used = False
            while not review.passed and rewrite_count < 2:
                try:
                    script = await writer.rewrite(
                        session,
                        topic,
                        script,
                        review.issues,
                        topic.requested_duration,
                    )
                except Exception as error:
                    logger.warning(
                        "script rewrite failed; using verified fallback",
                        extra={"topic_id": topic.id, "error": str(error)},
                    )
                    break
                self.store.save_text(session, topic.id, "script", script)
                session.commit()
                review = await reviewer.review(session, topic, script)
                rewrite_count += 1
            if not review.passed:
                script = writer.safe_fallback(session, topic, topic.requested_duration)
                self.store.save_text(session, topic.id, "script", script)
                session.commit()
                review = await reviewer.review(session, topic, script)
                fallback_used = True
            self.store.save_json(
                session,
                topic.id,
                "review",
                {
                    **review.model_dump(mode="json"),
                    "rewrite_count": rewrite_count,
                    "fallback_used": fallback_used,
                },
            )
            session.commit()
            if not review.passed:
                raise RuntimeError(
                    f"剧本质量检查未通过（{review.score} 分）：" + "；".join(review.issues)
                )
            self.tracker.complete(session, topic, "review")
        except Exception as error:
            self.tracker.fail(session, topic, "review", str(error))
            raise

    async def _export(self, session: Session, topic: Topic) -> None:
        if not self.tracker.start(session, topic, "export"):
            return
        try:
            self.store.save_json(session, topic.id, "topic", topic_dict(topic))
            sources = list(session.scalars(select(Source).where(Source.topic_id == topic.id)))
            facts = list(session.scalars(select(Fact).where(Fact.topic_id == topic.id)))
            events = list(session.scalars(select(Event).where(Event.topic_id == topic.id)))
            self.store.save_json(
                session, topic.id, "sources", [source_dict(item) for item in sources]
            )
            self.store.save_json(session, topic.id, "facts", [fact_dict(item) for item in facts])
            self.store.save_json(session, topic.id, "events", [event_dict(item) for item in events])
            session.commit()
            self.tracker.complete(session, topic, "export")
        except Exception as error:
            self.tracker.fail(session, topic, "export", str(error))
            raise

    def prepare_continue(self, topic_id: str) -> Topic:
        with self.session_factory() as session:
            topic = session.get(Topic, topic_id)
            if not topic:
                raise LookupError(f"Topic 不存在：{topic_id}")
            topic.research_depth += 1
            self.tracker.reset_from(session, topic, "search")
            return topic

    def prepare_rewrite(self, topic_id: str, duration: int) -> Topic:
        with self.session_factory() as session:
            topic = session.get(Topic, topic_id)
            if not topic:
                raise LookupError(f"Topic 不存在：{topic_id}")
            topic.requested_duration = duration
            self.tracker.reset_from(session, topic, "write")
            return topic


class PipelineRunner:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def running(self, topic_id: str) -> bool:
        task = self.tasks.get(topic_id)
        return bool(task and not task.done())

    def start(self, topic_id: str) -> bool:
        if self.running(topic_id):
            return False
        task = asyncio.create_task(self.pipeline.run(topic_id), name=f"hotstory:{topic_id}")
        self.tasks[topic_id] = task
        task.add_done_callback(lambda _task: self.tasks.pop(topic_id, None))
        return True


def recover_interrupted_topics(session: Session) -> int:
    terminal = {"CREATED", "COMPLETED", "FAILED"}
    topics = list(session.scalars(select(Topic).where(Topic.status.not_in(terminal))))
    for topic in topics:
        topic.status = "FAILED"
        topic.error = "上次运行被中断；点击继续即可从已保存步骤恢复。"
        if topic.current_step:
            run = session.scalar(
                select(StepRun).where(
                    StepRun.topic_id == topic.id, StepRun.step == topic.current_step
                )
            )
            if run and run.status == "RUNNING":
                run.status = "FAILED"
                run.error = topic.error
                run.completed_at = datetime.now(UTC)
    session.commit()
    return len(topics)
