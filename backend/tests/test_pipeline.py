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
        self.production_ai_calls = 0

    async def generate_text(self, system_prompt: str, user_prompt: str):
        self.script_calls += 1
        if self.script_calls > 1:
            raise RuntimeError("上游返回空内容")
        return await super().generate_text(system_prompt, user_prompt)

    async def generate_json(self, system_prompt: str, user_prompt: str):
        if "角色资产阶段" in user_prompt or "生成单元成片提示词阶段" in user_prompt:
            self.production_ai_calls += 1
        if "允许引用的事件和来源 ID" in user_prompt:
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
        session.add(
            Topic(
                id=topic_id,
                title="测试热点纪实",
                input_mode="manual",
                requested_duration=60,
            )
        )
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
        "script_meta.json",
        "review.json",
        "script.md",
        "production_package.json",
    }
    assert expected.issubset({path.name for path in project_dir.iterdir()})
    with session_factory() as session:
        package = pipeline.store.load_json(session, topic_id, "production_package")
    assert package["max_shot_duration_seconds"] == 10
    assert package["generation_strategy"] == "fast_multishot"
    assert package["generation_unit_duration_seconds"] == 10
    assert package["prompt_preservation"] == "lossless"
    assert len(package["shots"]) == 6
    assert package["generation_unit_count"] == 6
    assert package["internal_shot_count"] > package["generation_unit_count"]
    assert all(shot["duration_seconds"] == 10 for shot in package["shots"])
    assert all(1 <= len(shot["internal_shots"]) <= 3 for shot in package["shots"])
    assert any(len(shot["internal_shots"]) == 3 for shot in package["shots"])
    assert any(len(shot["internal_shots"]) == 1 for shot in package["shots"])
    assert {
        beat_id
        for shot in package["shots"]
        for beat_id in shot["beat_ids"]
    } == {f"beat_{index:02d}" for index in range(1, 9)}
    assert package["ready_for_generation"] is True, package["readiness"]
    assert package["animatic"]["passed"] is True
    assert package["animatic"]["generation_unit_count"] == 6
    assert package["animatic"]["internal_shot_count"] == package["internal_shot_count"]
    assert package["audio_plan"]["silence_points"]
    assert all(shot["entry_state"] and shot["exit_state"] for shot in package["shots"])
    assert [stage["skill"] for stage in package["skills"]] == [
        "lira-image-prompts",
        "acting-ai-video",
        "cinedance-higgsfield",
    ]
    assert all(stage["instruction_mode"] == "verbatim" for stage in package["skills"])
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
        package = pipeline.store.load_json(session, topic_id, "production_package")

    assert topic is not None
    assert topic.status == "COMPLETED", topic.error
    assert review["fallback_used"] is True
    assert "### 事实依据" in script
    assert package["ready_for_generation"] is False
    assert package["generation_mode"] == "fallback"
    assert len(package["shots"]) == 9
    assert any(
        "受控多镜头序列" in shot["prompt_body_template"]
        for shot in package["shots"]
    )
    assert llm.production_ai_calls == 0

    prepared = pipeline.prepare_production(topic_id)
    assert prepared.current_step == "write"
