from __future__ import annotations

import pytest

from app.models import Topic
from app.services.pipeline import Pipeline
from app.utils import new_id
from tests.fakes import FakeCrawlerProvider, FakeSearchProvider, ScenarioLLMProvider


class RewriteFailureLLMProvider(ScenarioLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.script_calls = 0
        self.review_calls = 0

    async def generate_text(self, system_prompt: str, user_prompt: str):
        self.script_calls += 1
        if self.script_calls > 1:
            raise RuntimeError("上游返回空内容")
        return await super().generate_text(system_prompt, user_prompt)

    async def generate_json(self, system_prompt: str, user_prompt: str):
        if '"score"' in user_prompt:
            self.review_calls += 1
            if self.review_calls == 1:
                return self._response(
                    {"score": 40, "issues": ["缺少可核验来源"], "passed": False}
                )
        return await super().generate_json(system_prompt, user_prompt)


@pytest.mark.asyncio
async def test_pipeline_completes_and_resumes_without_duplicate_calls(
    test_settings, session_factory
) -> None:
    topic_id = new_id("topic")
    with session_factory() as session:
        session.add(Topic(id=topic_id, title="测试热点纪实", input_mode="manual"))
        session.commit()

    llm = ScenarioLLMProvider()
    search = FakeSearchProvider()
    crawler = FakeCrawlerProvider()
    pipeline = Pipeline(
        test_settings,
        llm_provider=llm,
        search_provider=search,
        crawler_provider=crawler,
        session_factory=session_factory,
    )

    await pipeline.run(topic_id)

    with session_factory() as session:
        topic = session.get(Topic, topic_id)
        assert topic is not None
        assert topic.status == "COMPLETED", topic.error

    project_dir = test_settings.projects_dir / topic_id
    expected = {
        "topic.json",
        "research_plan.json",
        "search_results.json",
        "sources.json",
        "facts.json",
        "events.json",
        "timeline.json",
        "story_arc.json",
        "value.json",
        "review.json",
        "script.md",
    }
    assert expected.issubset({path.name for path in project_dir.iterdir()})
    first_counts = (llm.calls, search.calls, crawler.calls)

    await pipeline.run(topic_id)

    assert (llm.calls, search.calls, crawler.calls) == first_counts


@pytest.mark.asyncio
async def test_pipeline_uses_safe_script_when_rewrite_provider_fails(
    test_settings, session_factory
) -> None:
    topic_id = new_id("topic")
    with session_factory() as session:
        session.add(Topic(id=topic_id, title="测试热点纪实", input_mode="manual"))
        session.commit()

    llm = RewriteFailureLLMProvider()
    pipeline = Pipeline(
        test_settings,
        llm_provider=llm,
        search_provider=FakeSearchProvider(),
        crawler_provider=FakeCrawlerProvider(),
        session_factory=session_factory,
    )

    await pipeline.run(topic_id)

    with session_factory() as session:
        topic = session.get(Topic, topic_id)
        review = pipeline.store.load_json(session, topic_id, "review")
        script = pipeline.store.load_text(session, topic_id, "script")

    assert topic is not None
    assert topic.status == "COMPLETED", topic.error
    assert review["fallback_used"] is True
    assert "### 事实依据" in script
