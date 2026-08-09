from __future__ import annotations

from collections.abc import Iterable

from app.schemas.domain import NarrativeQualityData, StoryArcData

HOOK_MARKERS = ("hook", "钩子", "结果前置", "后果前置", "悬念")
REVERSAL_MARKERS = ("reversal", "转折", "反转", "失控", "逆转")
COST_MARKERS = ("cost", "代价", "后果", "损失", "选择")
ENDING_MARKERS = ("aftermath", "余波", "尾声", "回环", "行动收束", "开放结尾")


def _contains(value: str, markers: Iterable[str]) -> bool:
    normalized = value.strip().lower()
    return any(marker in normalized for marker in markers)


def assess_story_arc(story: StoryArcData, events: list[dict]) -> NarrativeQualityData:
    """Deterministic gate: a valid fact list is not automatically a dramatic story."""

    issues: list[str] = []
    severe = False
    score = 100
    beats = story.beats
    allowed_ids = {item.get("id", "") for item in events}
    personal_case_ids = {
        item.get("id", "")
        for item in events
        if str(item.get("event_type", "")) == "PERSONAL_CASE"
    }

    if len(beats) < 6:
        issues.append("因果节拍不足 6 个，无法形成完整递进")
        score -= 30
        severe = True
    elif len(beats) > 12:
        issues.append("核心节拍超过 12 个，主线容易分散")
        score -= 8

    if personal_case_ids and story.protagonist_event_id not in personal_case_ids:
        issues.append("没有把一个已核验个人案例锁定为主角锚点")
        score -= 20
        severe = True
    if not story.dramatic_question.strip():
        issues.append("缺少贯穿全片、可在结尾回应的戏剧问题")
        score -= 12

    invalid_ids = sorted(
        {
            event_id
            for beat in beats
            for event_id in beat.event_ids
            if event_id not in allowed_ids
        }
    )
    empty_evidence = [beat.beat_id for beat in beats if not beat.event_ids]
    if invalid_ids:
        issues.append("节拍引用了不存在的 event_id")
        score -= 25
        severe = True
    if empty_evidence:
        issues.append("存在没有事实锚点的节拍：" + "、".join(empty_evidence[:4]))
        score -= 20
        severe = True

    incomplete_pressure = [
        beat.beat_id
        for beat in beats
        if not all(
            value.strip()
            for value in (beat.objective, beat.obstacle, beat.stakes, beat.tactic)
        )
    ]
    if beats and len(incomplete_pressure) > max(1, len(beats) // 4):
        issues.append("多数节拍缺少目标、阻碍、代价或策略，人物无法在压力下行动")
        score -= 18

    missing_links = [beat.beat_id for beat in beats[1:] if not beat.cause_link.strip()]
    if missing_links:
        issues.append("相邻节拍缺少因果或明确的编辑承接：" + "、".join(missing_links[:4]))
        score -= min(20, 4 * len(missing_links))

    functions = [beat.narrative_function for beat in beats]
    if beats and not _contains(functions[0], HOOK_MARKERS):
        issues.append("开场不是结果前置或悬念钩子")
        score -= 10
    if not any(_contains(item, REVERSAL_MARKERS) for item in functions):
        issues.append("主线缺少改变局势的转折节拍")
        score -= 12
    if not any(_contains(item, COST_MARKERS) for item in functions):
        issues.append("主线缺少可见代价或后果")
        score -= 12
    if beats and not _contains(functions[-1], ENDING_MARKERS):
        issues.append("结尾没有使用行动、余波或回环收束")
        score -= 8

    values_changed = sum(
        bool(
            beat.value_before.strip()
            and beat.value_after.strip()
            and beat.value_before.strip() != beat.value_after.strip()
        )
        for beat in beats
    )
    if beats and values_changed < max(3, len(beats) // 2):
        issues.append("价值状态变化不足，镜头容易只是在重复说明")
        score -= 12

    intensities = [beat.intensity for beat in beats]
    if len(set(intensities)) < min(4, len(intensities)):
        issues.append("强度曲线过平，缺少张弛和峰值")
        score -= 15
    if len(intensities) >= 4:
        peak_index = max(range(len(intensities)), key=intensities.__getitem__)
        if peak_index in (0, len(intensities) - 1):
            issues.append("最高强度落在片头或片尾，递进没有形成中后段峰值")
            score -= 8
        if intensities[-1] >= max(intensities):
            issues.append("结尾没有从高潮回落，缺少余韵")
            score -= 6

    if not story.ending_device.strip():
        issues.append("缺少非说教式结尾装置")
        score -= 8

    score = max(0, min(100, score))
    return NarrativeQualityData(score=score, issues=issues, passed=score >= 80 and not severe)
