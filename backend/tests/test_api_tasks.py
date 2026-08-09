from __future__ import annotations

import asyncio

import pytest

from app.api.router import generate_production_package, rewrite_script, start_research
from app.config import Settings
from app.models import Topic
from app.schemas.domain import ResearchRequest, RewriteScriptRequest
from app.services.artifacts import ProjectStore
from app.services.pipeline import PipelineRunner


class StubPipeline:
    def __init__(self, settings=None) -> None:
        self.started = asyncio.Event()
        self.duration: int | None = None
        self.production_prepared = False
        self.settings = settings or Settings(_env_file=None, llm_provider="mock")

    async def run(self, topic_id: str) -> None:
        self.started.set()

    def prepare_rewrite(self, topic_id: str, duration: int) -> None:
        self.duration = duration

    def prepare_production(self, topic_id: str) -> None:
        self.production_prepared = True


@pytest.mark.asyncio
async def test_research_route_starts_background_task_on_event_loop(session_factory) -> None:
    with session_factory() as session:
        topic = Topic(id="topic_api_research", title="年轻人租房维权", input_mode="manual")
        session.add(topic)
        session.commit()
        pipeline = StubPipeline()
        runner = PipelineRunner(pipeline)  # type: ignore[arg-type]

        response = await start_research(
            topic.id,
            ResearchRequest(duration=90),
            session,
            runner,
        )
        await asyncio.wait_for(pipeline.started.wait(), timeout=1)

        assert response.accepted is True
        assert topic.requested_duration == 90


@pytest.mark.asyncio
async def test_rewrite_route_starts_background_task_on_event_loop(session_factory) -> None:
    with session_factory() as session:
        topic = Topic(id="topic_api_rewrite", title="消费者退款争议", input_mode="manual")
        session.add(topic)
        session.commit()
        pipeline = StubPipeline()
        runner = PipelineRunner(pipeline)  # type: ignore[arg-type]

        response = await rewrite_script(
            topic.id,
            RewriteScriptRequest(duration=180),
            session,
            runner,
        )
        await asyncio.wait_for(pipeline.started.wait(), timeout=1)

        assert response.accepted is True
        assert pipeline.duration == 180


@pytest.mark.asyncio
async def test_production_route_starts_from_existing_script(
    test_settings, session_factory
) -> None:
    with session_factory() as session:
        topic = Topic(id="topic_api_production", title="普通人的选择", input_mode="manual")
        session.add(topic)
        session.commit()
        store = ProjectStore(test_settings)
        store.save_text(session, topic.id, "script", "# 已审校剧本")
        session.commit()
        pipeline = StubPipeline()
        runner = PipelineRunner(pipeline)  # type: ignore[arg-type]

        response = await generate_production_package(
            topic.id,
            session,
            runner,
            store,
        )
        await asyncio.wait_for(pipeline.started.wait(), timeout=1)

        assert response.accepted is True
        assert pipeline.production_prepared is True
