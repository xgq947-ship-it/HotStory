from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.models import Topic
from app.schemas.domain import (
    CinematicShotData,
    ProductionPackageData,
    ShotPlanDraft,
    ShotPromptDraft,
)
from app.services.llm.openai_compatible import DeepSeekProvider
from app.services.pipeline import Pipeline
from app.services.production.package import ProductionPackageBuilder
from app.services.production.skills import load_verbatim_skill
from app.services.prompts import load_prompt
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


def test_cinematic_prompt_requires_physical_display_facing() -> None:
    prompt = load_prompt("cinematic_shots")

    assert "设备可见面几何（最高优先级）" in prompt
    assert "人物双眼 → 发光显示面 → 设备机身与背壳 → 摄影机" in prompt
    assert "屏幕内容语义隔离" in prompt
    assert "不得用红/绿/橙光暗示其具体含义" in prompt
    assert "跨逗号、分号和句号检查整篇" in prompt
    assert "推进、特写、对焦和放大只能指向人物双眼与面部反应" in prompt
    assert "越肩镜头、人物主观镜头或独立 INSERT CUT" in prompt


def test_display_geometry_guard_hides_screen_in_frontal_reaction_shot() -> None:
    plan = ShotPlanDraft(
        shot_id="shot_device",
        title="人物查看手机",
        start_second=0,
        end_second=8,
        visual_brief="人物面对摄影机拿起手机查看账户，镜头捕捉他的眼神和面部反应。",
        active_character_ids=["char_01"],
    )
    unsafe = (
        "首帧与空间调度\n人物面对摄影机，拿起手机查看账户；"
        "手机屏幕上的数字清晰可见。"
    )

    guarded = ProductionPackageBuilder._ensure_display_geometry(unsafe, plan)

    assert guarded.startswith("设备可见面几何（最高优先级）")
    assert "人物双眼 → 手机发光显示面 → 手机机身与背壳 → 摄影机" in guarded
    assert "背板与后置镜头模组始终朝向摄影机" in guarded
    assert "手机从拿起到放下不绕竖轴或横轴翻面" in guarded
    assert "屏幕上的数字清晰可见" not in guarded


def test_display_geometry_guard_removes_conflicts_from_existing_section() -> None:
    plan = ShotPlanDraft(
        shot_id="shot_insomnia",
        title="人物失眠",
        start_second=20,
        end_second=30,
        visual_brief=(
            "人物面对摄影机躺在床上，拿起手机看亏损数字；"
            "屏幕亮光映在脸上，显示亏损数字。"
        ),
        active_character_ids=["char_01"],
    )
    unsafe = (
        "场景上下文：他又一次被亏损数字拽醒，拿起手机确认。\n\n"
        "设备可见面几何：手机显示面朝向人物，亏损数字通过暖橙色暗示。\n\n"
        "动作时间轴：手机被拿到眼前，冷白屏幕光混着暖橙照亮面部。\n\n"
        "表演：他反复尝试入睡又被亏损数字拽醒。\n\n"
        "灯光：屏幕背光中的橙色是唯一的警示暖色。\n\n"
        "正向约束：手机屏幕内容不可见。"
    )

    guarded = ProductionPackageBuilder._ensure_display_geometry(unsafe, plan)

    assert guarded.count("设备可见面几何") == 1
    assert "亏损数字" not in guarded
    assert "屏幕内容" not in guarded
    assert "暖橙" not in guarded
    assert "警示暖色" not in guarded
    assert "因持续压力再次醒来" in guarded
    assert "中性屏幕光" in guarded
    assert ProductionPackageBuilder._ensure_display_geometry(guarded, plan) == guarded


def test_display_geometry_guard_preserves_readable_overshoulder_insert() -> None:
    plan = ShotPlanDraft(
        shot_id="shot_insert",
        title="人物查看数据",
        start_second=0,
        end_second=6,
        visual_brief="人物肩后越肩插入镜头，手机显示面朝向人物，账户数字清晰可读。",
        active_character_ids=["char_01"],
    )
    prompt = "场景上下文\n人物查看手机。\n\n摄影机\n越肩插入镜头看清账户数字。"

    guarded = ProductionPackageBuilder._ensure_display_geometry(prompt, plan)

    assert guarded.startswith("设备可见面几何（最高优先级）")
    assert "摄影机与人物双眼同在屏幕显示面一侧" in guarded
    assert "账户数字" in guarded


def test_display_geometry_guard_removes_cross_clause_phone_readability() -> None:
    plan = ShotPlanDraft(
        shot_id="shot_phone_cross_clause",
        title="人物查看手机",
        start_second=0,
        end_second=8,
        visual_brief="人物正面面对摄影机，拿起手机查看亏损数字。",
        active_character_ids=["char_01"],
    )
    prompt = (
        "摄影机\n缓慢推近手机屏幕，突出清晰可读的亏损数字。\n\n"
        "表演\n人物盯着手机后呼吸停顿。"
    )

    guarded = ProductionPackageBuilder._ensure_display_geometry(prompt, plan)

    for conflict in ("推近手机屏幕", "清晰可读", "亏损数字", "未入镜的信息"):
        assert conflict not in guarded
    assert "摄影机只靠近人物双眼与面部反应" in guarded


def test_display_geometry_guard_removes_standalone_laptop_chart_terms() -> None:
    plan = ShotPlanDraft(
        shot_id="shot_laptop_chart",
        title="人物查看电脑",
        start_second=0,
        end_second=8,
        visual_brief="人物正面面对摄影机使用笔记本电脑查看交易图表。",
        active_character_ids=["char_01"],
    )
    prompt = (
        "首帧与空间调度\n人物坐在笔记本电脑后方，账户亏损和红绿K线清晰可见。\n\n"
        "动作时间轴\n0:03-0:05 红色下跌曲线刷新，人物肩膀僵住。"
    )

    guarded = ProductionPackageBuilder._ensure_display_geometry(prompt, plan)

    for conflict in ("账户", "亏损", "红绿", "K线", "下跌", "曲线", "刷新", "清晰可见"):
        assert conflict not in guarded
    assert "人物双眼 → 笔记本发光显示面 → 屏幕面板与外侧上盖 → 摄影机" in guarded
    assert "中性屏幕光" in guarded


def test_saved_prompt_repair_keeps_audio_and_needs_no_llm_call() -> None:
    shot = CinematicShotData(
        shot_id="shot_saved",
        title="人物查看手机",
        start_second=0,
        end_second=8,
        visual_brief="人物面对摄影机拿起手机，屏幕显示账户余额。",
        active_character_ids=["char_01"],
        duration_seconds=8,
        prompt_body_template=(
            "场景上下文\n人物拿起手机，手机屏幕上的账户余额清晰可见。\n\n"
            "音频（使用模型原生音频）\n旁白逐字：\"账户出现了亏损。\""
        ),
    )
    package = ProductionPackageData(
        topic_id="topic_saved",
        generated_at="2026-08-09T00:00:00Z",
        duration_seconds=8,
        style_bible="真实纪实电影质感与自然方向光。",
        skills=[],
        shots=[shot],
    )

    repaired, changed = ProductionPackageBuilder.repair_display_prompts(package)

    prompt = repaired.shots[0].prompt_body_template
    assert changed is True
    assert prompt.startswith("设备可见面几何（最高优先级）")
    assert "账户余额清晰可见" not in prompt
    assert "旁白逐字：\"账户出现了亏损。\"" in prompt


def test_display_geometry_guard_keeps_screen_only_insert_unchanged() -> None:
    plan = ShotPlanDraft(
        shot_id="shot_screen",
        title="数据屏幕",
        start_second=0,
        end_second=6,
        visual_brief="无人数据屏幕正面特写，图表缓慢刷新。",
    )
    prompt = "场景上下文\n无人数据屏幕正面特写，图表缓慢刷新。"

    assert ProductionPackageBuilder._ensure_display_geometry(prompt, plan) == prompt


def test_display_geometry_guard_ignores_negated_device_reference() -> None:
    plan = ShotPlanDraft(
        shot_id="shot_walk",
        title="人物步行",
        start_second=0,
        end_second=6,
        visual_brief="人物沿校园步道行走，画面不出现手机屏幕。",
        active_character_ids=["char_01"],
    )
    prompt = "正向约束\n人物平视前方自然步行，画面不出现手机屏幕。"

    assert ProductionPackageBuilder._ensure_display_geometry(prompt, plan) == prompt


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
