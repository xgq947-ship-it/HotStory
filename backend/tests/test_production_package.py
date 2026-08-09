from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.models import Topic
from app.schemas.domain import ShotPlanDraft, ShotPromptDraft
from app.services.llm.openai_compatible import DeepSeekProvider
from app.services.pipeline import Pipeline
from app.services.production.package import ProductionPackageBuilder
from app.services.production.skills import load_verbatim_skill
from app.utils import new_id
from tests.fakes import FakeCrawlerProvider, FakeSearchProvider, ScenarioLLMProvider


class ConcurrentShotLLMProvider(ScenarioLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.active_shot_calls = 0
        self.max_active_shot_calls = 0

    async def generate_json(self, system_prompt: str, user_prompt: str):
        if '"prompt_body_template"' not in user_prompt:
            return await super().generate_json(system_prompt, user_prompt)
        self.active_shot_calls += 1
        self.max_active_shot_calls = max(
            self.max_active_shot_calls, self.active_shot_calls
        )
        try:
            await asyncio.sleep(0.03)
            return await super().generate_json(system_prompt, user_prompt)
        finally:
            self.active_shot_calls -= 1


def test_shot_schema_hard_rejects_more_than_ten_seconds() -> None:
    with pytest.raises(ValidationError, match="不得超过 10 秒"):
        ShotPlanDraft(
            shot_id="shot_01",
            title="超长镜头",
            start_second=0,
            end_second=11,
            visual_brief="这是一个不应通过校验的超长镜头计划",
        )


def test_prompt_schema_does_not_shorten_long_prompt() -> None:
    original = "完整有效控制信息" * 3000
    prompt = ShotPromptDraft(
        shot_id="shot_01",
        prompt_body_template=original,
    )
    assert prompt.prompt_body_template == original


def test_verbatim_skill_loader_preserves_every_character(tmp_path, monkeypatch) -> None:
    original = "---\nname: exact-skill\n---\n\n第一行  \nSecond line.\n"
    skill_path = tmp_path / "exact-skill" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(original, encoding="utf-8")
    monkeypatch.setenv("HOTSTORY_SKILL_ROOT", str(tmp_path))
    load_verbatim_skill.cache_clear()
    loaded = load_verbatim_skill("exact-skill")
    load_verbatim_skill.cache_clear()
    assert loaded.content == original


def test_lossless_rewrite_rejects_shortened_or_missing_sections() -> None:
    previous = "场景上下文\n完整事件。\n\n光学\n47°自然标准。\n\n灯光\n单侧方向光。"
    assert ProductionPackageBuilder._is_lossless_rewrite(previous, previous + "\n补强信息")
    assert not ProductionPackageBuilder._is_lossless_rewrite(previous, "场景上下文\n完整事件。")


def test_production_deepseek_profile_is_real_max(
    test_settings, session_factory
) -> None:
    settings = test_settings.__class__.model_validate(
        {
            **test_settings.model_dump(),
            "llm_provider": "deepseek",
            "llm_model": "deepseek-v4-flash",
            "deepseek_api_key": "test-key",
        }
    )
    pipeline = Pipeline(
        settings,
        llm_provider=DeepSeekProvider(settings),
        search_provider=FakeSearchProvider(),
        crawler_provider=FakeCrawlerProvider(),
        session_factory=session_factory,
    )

    llm, profile = pipeline._production_llm()

    assert isinstance(llm.provider, DeepSeekProvider)
    assert llm.provider.thinking_enabled is True
    assert llm.provider.settings.deepseek_reasoning_effort == "max"
    assert llm.provider.settings.llm_timeout_seconds == 240
    assert llm.provider.settings.llm_max_output_tokens == 65536
    assert profile == "deepseek-v4-flash · MAX"


@pytest.mark.asyncio
async def test_shot_prompt_batches_run_concurrently(
    test_settings, session_factory
) -> None:
    topic_id = new_id("topic")
    with session_factory() as session:
        session.add(Topic(id=topic_id, title="测试热点纪实", input_mode="manual"))
        session.commit()

    llm = ConcurrentShotLLMProvider()
    pipeline = Pipeline(
        test_settings,
        llm_provider=llm,
        search_provider=FakeSearchProvider(),
        crawler_provider=FakeCrawlerProvider(),
        session_factory=session_factory,
    )
    await pipeline.run(topic_id)

    assert llm.max_active_shot_calls >= 2


@pytest.mark.asyncio
async def test_single_shot_regeneration_preserves_other_shots(
    test_settings, session_factory
) -> None:
    topic_id = new_id("topic")
    with session_factory() as session:
        session.add(Topic(id=topic_id, title="测试热点纪实", input_mode="manual"))
        session.commit()

    pipeline = Pipeline(
        test_settings,
        llm_provider=ScenarioLLMProvider(),
        search_provider=FakeSearchProvider(),
        crawler_provider=FakeCrawlerProvider(),
        session_factory=session_factory,
    )
    await pipeline.run(topic_id)
    with session_factory() as session:
        before = pipeline.store.load_json(session, topic_id, "production_package")

    result = await pipeline.regenerate_production_shot(
        topic_id,
        "shot_03",
        "请保持克制表演并使用 @userProvidedReference",
    )
    with session_factory() as session:
        persisted = pipeline.store.load_json(session, topic_id, "production_package")

    before_by_id = {shot["shot_id"]: shot for shot in before["shots"]}
    after_by_id = {shot.shot_id: shot for shot in result.shots}
    assert after_by_id["shot_03"].revision == 2
    assert after_by_id["shot_03"].duration_seconds <= 10
    assert "@userProvidedReference" not in after_by_id["shot_03"].prompt_body_template
    for shot_id, original in before_by_id.items():
        if shot_id != "shot_03":
            assert after_by_id[shot_id].model_dump(mode="json") == original
    assert persisted["shots"][2]["revision"] == 2
