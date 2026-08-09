from __future__ import annotations

from app.schemas.domain import StoryArcData, StoryBeatData
from app.services.script.narrative_quality import assess_story_arc


def _beat(index: int, function: str, intensity: int) -> StoryBeatData:
    return StoryBeatData(
        beat_id=f"beat_{index:02d}",
        narrative_function=function,
        objective="让当前事实改变观众对局势的理解",
        obstacle="事实容易被平铺成信息列表",
        stakes="局势必须发生变化",
        tactic="用人物与资料交替推进",
        turn="新信息进入",
        value_before=f"状态 {index}",
        value_after=f"状态 {index + 1}",
        cause_link="" if index == 1 else "承接上一节拍留下的问题",
        event_ids=[f"event_{index:02d}"],
        source_ids=[f"source_{index:02d}"],
        intensity=intensity,
    )


def test_story_quality_accepts_causal_rising_and_falling_arc() -> None:
    functions = [
        "结果前置钩子",
        "人物起点",
        "承诺与机会",
        "压力升级",
        "局势转折",
        "代价显现",
        "选择与回应",
        "余波与行动收束",
    ]
    intensities = [82, 34, 46, 63, 94, 79, 57, 29]
    story = StoryArcData(
        central_theme="测试主题",
        core_conflict="选择与后果",
        protagonist_event_id="event_02",
        dramatic_question="这个选择会面对什么代价？",
        ending_device="以未完成动作和环境余音收束",
        beats=[
            _beat(index, function, intensity)
            for index, (function, intensity) in enumerate(
                zip(functions, intensities, strict=True), 1
            )
        ],
    )
    events = [
        {
            "id": f"event_{index:02d}",
            "event_type": "PERSONAL_CASE" if index == 2 else "DATA",
        }
        for index in range(1, 9)
    ]

    quality = assess_story_arc(story, events)

    assert quality.passed is True
    assert quality.score >= 80


def test_story_quality_rejects_flat_topic_outline() -> None:
    story = StoryArcData(
        central_theme="测试主题",
        core_conflict="个人选择与现实后果",
        story_arc=[],
        beats=[
            StoryBeatData(
                beat_id=f"beat_{index:02d}",
                narrative_function="背景说明",
                event_ids=[f"event_{index:02d}"],
                intensity=50,
            )
            for index in range(1, 4)
        ],
    )
    events = [
        {"id": f"event_{index:02d}", "event_type": "DATA"}
        for index in range(1, 4)
    ]

    quality = assess_story_arc(story, events)

    assert quality.passed is False
    assert any("因果节拍不足" in issue for issue in quality.issues)
    assert any("强度曲线过平" in issue for issue in quality.issues)
