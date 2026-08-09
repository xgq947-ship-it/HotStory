from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select

from app.api.router import get_script, get_timeline, health
from app.config import Settings
from app.db.session import checkpoint_wal
from app.models import Source, Topic
from app.schemas.domain import ResearchPlanData, RewriteScriptRequest
from app.services.artifacts import ProjectStore
from app.services.pipeline import Pipeline, PipelineBusyError, PipelineRunner
from app.services.research.native_engine import NativeResearchEngine, heuristic_plan
from app.utils import new_id
from tests.fakes import FakeCrawlerProvider, FakeSearchProvider, ScenarioLLMProvider


class SlowPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.release = asyncio.Event()

    async def run(self, topic_id: str) -> None:
        await self.release.wait()

    async def aclose(self) -> None:
        return None


class FakeResponse:
    """站位的 fastapi Response，只需要 headers。"""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


class BrokenSearchProvider:
    name = "broken_search"

    async def search(self, query: str, limit: int = 10):
        raise RuntimeError("Ratelimit 202")


@pytest.mark.asyncio
async def test_runner_rejects_second_topic_while_one_is_running(test_settings) -> None:
    pipeline = SlowPipeline(test_settings)
    runner = PipelineRunner(pipeline)  # type: ignore[arg-type]
    assert runner.start("topic_a") is True
    with pytest.raises(PipelineBusyError):
        runner.start("topic_b")
    pipeline.release.set()
    await runner.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_running_pipeline_and_marks_topic(
    test_settings, session_factory
) -> None:
    topic_id = new_id("topic")
    with session_factory() as session:
        session.add(Topic(id=topic_id, title="被中断的主题", input_mode="manual"))
        session.commit()

    class HangingCrawler(FakeCrawlerProvider):
        async def fetch(self, url: str):
            await asyncio.sleep(60)
            raise AssertionError("unreachable")

    pipeline = Pipeline(
        test_settings,
        llm_provider=ScenarioLLMProvider(),
        search_provider=FakeSearchProvider(),
        crawler_provider=HangingCrawler(),
        session_factory=session_factory,
    )
    runner = PipelineRunner(pipeline)
    runner.start(topic_id)
    for _ in range(200):
        await asyncio.sleep(0.02)
        with session_factory() as session:
            topic = session.get(Topic, topic_id)
            if topic and topic.current_step == "fetch":
                break

    await runner.shutdown(wait_seconds=5)

    with session_factory() as session:
        topic = session.get(Topic, topic_id)
        assert topic is not None
        # 关键：不能停在 RUNNING 状态等下次启动才被修
        assert topic.status == "FAILED"
        assert "中断" in (topic.error or "")


def test_artifact_endpoints_return_304_when_unchanged(test_settings, session_factory) -> None:
    store = ProjectStore(test_settings)
    topic_id = new_id("topic")
    with session_factory() as session:
        session.add(Topic(id=topic_id, title="ETag 测试", input_mode="manual"))
        session.commit()
        store.save_json(session, topic_id, "timeline", {"events": []})
        session.commit()

        response = FakeResponse()
        payload = get_timeline(topic_id, response, session, store, None)  # type: ignore[arg-type]
        assert payload == {"events": []}
        etag = response.headers["ETag"]

        cached = get_timeline(topic_id, FakeResponse(), session, store, etag)  # type: ignore[arg-type]
        assert getattr(cached, "status_code", None) == 304

        store.save_json(session, topic_id, "timeline", {"events": [{"date": "2026-01-01"}]})
        session.commit()
        fresh = get_timeline(topic_id, FakeResponse(), session, store, etag)  # type: ignore[arg-type]
        assert fresh == {"events": [{"date": "2026-01-01"}]}


def test_script_endpoint_supports_etag(test_settings, session_factory) -> None:
    store = ProjectStore(test_settings)
    topic_id = new_id("topic")
    with session_factory() as session:
        session.add(Topic(id=topic_id, title="剧本 ETag", input_mode="manual"))
        session.commit()
        store.save_text(session, topic_id, "script", "# 剧本")
        session.commit()

        response = FakeResponse()
        payload = get_script(topic_id, response, session, store, None)  # type: ignore[arg-type]
        assert payload["script"] == "# 剧本"
        cached = get_script(
            topic_id, FakeResponse(), session, store, response.headers["ETag"]
        )  # type: ignore[arg-type]
        assert getattr(cached, "status_code", None) == 304


def test_prune_llm_raw_keeps_most_recent(test_settings) -> None:
    store = ProjectStore(test_settings)
    topic_id = new_id("topic")
    for index in range(10):
        store.save_json_file(topic_id, f"llm_raw/call_{index:02d}", {"index": index})
    assert store.prune_llm_raw(topic_id, keep=4) == 6
    remaining = list((test_settings.projects_dir / topic_id / "llm_raw").glob("*.json"))
    assert len(remaining) == 4
    assert store.prune_llm_raw(topic_id, keep=0) == 0


@pytest.mark.asyncio
async def test_search_failure_reports_provider_instead_of_failing_later(
    test_settings, session_factory
) -> None:
    topic_id = new_id("topic")
    with session_factory() as session:
        session.add(Topic(id=topic_id, title="搜索全挂", input_mode="manual"))
        session.commit()
        engine = NativeResearchEngine(
            session,
            topic_id,
            llm=None,  # type: ignore[arg-type]
            search_provider=BrokenSearchProvider(),  # type: ignore[arg-type]
            settings=test_settings,
        )
        with pytest.raises(RuntimeError) as error:
            await engine.search("测试", heuristic_plan("测试"))
    assert "broken_search" in str(error.value)


@pytest.mark.asyncio
async def test_fetch_does_not_inflate_retry_count_for_abandoned_sources(
    test_settings, session_factory
) -> None:
    topic_id = new_id("topic")
    settings = test_settings.model_copy(update={"max_retries": 0})
    with session_factory() as session:
        session.add(Topic(id=topic_id, title="重试计数", input_mode="manual"))
        session.add(
            Source(
                id=new_id("source"),
                topic_id=topic_id,
                url="https://example.com/a",
                normalized_url="https://example.com/a",
                title="a",
                fetch_status="FAILED",
                retry_count=1,
            )
        )
        session.commit()

    class AlwaysFailingCrawler(FakeCrawlerProvider):
        async def fetch(self, url: str):
            raise RuntimeError("boom")

    pipeline = Pipeline(
        settings,
        llm_provider=ScenarioLLMProvider(),
        search_provider=FakeSearchProvider(),
        crawler_provider=AlwaysFailingCrawler(),
        session_factory=session_factory,
    )
    with session_factory() as session:
        topic = session.get(Topic, topic_id)
        assert topic is not None
        with pytest.raises(RuntimeError):
            await pipeline._fetch(session, topic)

    with session_factory() as session:
        rows = list(session.scalars(select(Source).where(Source.topic_id == topic_id)))
    assert len(rows) == 1
    assert rows[0].retry_count == 1, "已经放弃的源不应该继续累加重试次数"


def test_checkpoint_wal_is_safe_on_sqlite(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.exec_driver_sql("CREATE TABLE t (id INTEGER)")
        connection.commit()
    checkpoint_wal(engine)
    engine.dispose()


def test_research_plan_defaults_are_still_valid() -> None:
    plan = heuristic_plan("测试")
    assert isinstance(plan, ResearchPlanData)
    assert len(plan.research_questions) >= 10


@pytest.mark.asyncio
async def test_health_probe_is_opt_in(test_settings) -> None:
    class Recorder:
        name = "mock"
        model = "mock-1"
        ready = True

        def __init__(self) -> None:
            self.calls = 0

        async def generate_text(self, system_prompt: str, user_prompt: str):
            self.calls += 1
            raise RuntimeError("上游 401")

    class FakeApp:
        pass

    class FakeRequest:
        def __init__(self, pipeline) -> None:
            self.app = FakeApp()
            self.app.state = type("S", (), {"pipeline": pipeline})()

    provider = Recorder()
    pipeline = type(
        "P", (), {"llm_provider": provider, "settings": test_settings}
    )()
    pipeline.search_provider = type("S", (), {"name": "fake"})()
    pipeline.crawler_provider = type("C", (), {"name": "fake"})()
    request = FakeRequest(pipeline)

    default = await health(request, probe=False)  # type: ignore[arg-type]
    assert default.llm_probe_ok is None
    assert provider.calls == 0

    probed = await health(request, probe=True)  # type: ignore[arg-type]
    assert probed.llm_probe_ok is False
    assert "401" in (probed.llm_probe_error or "")
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_busy_409_does_not_touch_target_topic_state(
    test_settings, session_factory
) -> None:
    """繁忙时必须在改状态之前就拒绝：prepare_* 会删 StepRun 并直接提交，
    先改后拒会把目标主题留在非终态却没人在跑的死局。"""
    from app.api.router import continue_research, rewrite_script
    from app.models import StepRun

    busy_id = new_id("topic")
    target_id = new_id("topic")
    with session_factory() as session:
        session.add(Topic(id=busy_id, title="占位任务", input_mode="manual"))
        session.add(
            Topic(
                id=target_id,
                title="被误伤的主题",
                input_mode="manual",
                status="COMPLETED",
                current_step="export",
                research_depth=0,
            )
        )
        session.add(StepRun(topic_id=target_id, step="write", status="SUCCESS"))
        session.commit()

    holder = SlowPipeline(test_settings)
    runner = PipelineRunner(holder)  # type: ignore[arg-type]
    runner.start(busy_id)

    real_pipeline = Pipeline(
        test_settings,
        llm_provider=ScenarioLLMProvider(),
        search_provider=FakeSearchProvider(),
        crawler_provider=FakeCrawlerProvider(),
        session_factory=session_factory,
    )
    runner.pipeline = real_pipeline  # type: ignore[assignment]

    with session_factory() as session:
        for endpoint, args in (
            (continue_research, ()),
            (rewrite_script, (RewriteScriptRequest(duration=60),)),
        ):
            with pytest.raises(HTTPException) as error:
                await endpoint(target_id, *args, session, runner)  # type: ignore[arg-type]
            assert error.value.status_code == 409

    with session_factory() as session:
        topic = session.get(Topic, target_id)
        assert topic is not None
        assert topic.status == "COMPLETED", "被拒绝的请求不应该改动目标主题状态"
        assert topic.research_depth == 0
        run = session.scalar(
            select(StepRun).where(StepRun.topic_id == target_id, StepRun.step == "write")
        )
        assert run is not None, "被拒绝的请求不应该删掉已完成的步骤记录"

    holder.release.set()
    await runner.shutdown(wait_seconds=5)
