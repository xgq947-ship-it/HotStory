from __future__ import annotations

from app.models import Event
from app.services.production.package import TIME_SEGMENT_PATTERN
from app.services.script.review import review_issue_is_blocking
from app.services.script.story import young_case_score
from app.services.script.writer import (
    normalize_script_format,
    script_format_issues,
)

# 模型实际交付过的形状：时间码写在 `### 旁白` 的下一行，而不是独立的二级标题。
# 这份剧本内容完全合格，却被格式门判成"上游剧本为空"，导致整条生产链降级。
INLINE_TIMECODE_SCRIPT = """# 人物纪实电影短片剧本《强平》

### 旁白
【0:00—0:05】7月28日，首尔。他的账户跳出三个字：强制平仓。

### 镜头
【0:00—0:05】手机屏幕特写，红色横幅弹出；镜头拉远到人物背影与窗外夜景。（影视化合成还原，不代表真实外貌或真实动作复刻）

### 叙事功能
- beat_id：beat_01（冷开场）
- 承接关系：提出核心悬念，后续段落追溯其成因。

### 事实依据
- event_e717176054b14055 / source_04143e1b7dd74c4d

### 旁白
【0:05—0:18】他四十岁，做贸易。妻子九月生二胎，女儿六岁。

### 镜头
【0:05—0:18】公寓晚餐，女儿敲玩具钢琴；他在阳台刷新行情。（影视化合成还原）

### 叙事功能
- beat_id：beat_02（人物起点）
- 承接关系：回答冷开场留下的"他是谁"。

### 事实依据
- event_06b53c734ebf4cc3 / source_04143e1b7dd74c4d

### 旁白
【0:18—0:31】五月，十六只杠杆产品上市。

### 镜头
【0:18—0:31】交易所外屏滚动名单；他手机上的开户广告写着收益翻倍。

### 叙事功能
- beat_id：beat_03（机会来临）
- 承接关系：引入让局势加速的系统工具。

### 事实依据
- event_b0ca68904526485f / source_2547c81874b843b8

## 结尾

停在最后一个已核验事实之后的未完成动作与环境余音。
"""


def test_review_separates_fact_blockers_from_style_advice() -> None:
    assert review_issue_is_blocking("金额异常，可能为笔误，建议核实")
    assert review_issue_is_blocking("该段没有来源ID，无法核验")
    assert review_issue_is_blocking("时间线略有跳跃，连续性不足")
    assert review_issue_is_blocking("结尾略有说教")
    assert not review_issue_is_blocking("可以减少一个装饰性形容词")


def test_young_case_score_prefers_explicit_young_adult() -> None:
    event = Event(
        id="event_test",
        topic_id="topic_test",
        title="31岁上班族韩先生遭遇亏损",
        summary="他买入杠杆产品。",
        event_type="PERSONAL_CASE",
    )
    assert young_case_score(event) == 1


def test_script_normalizer_converts_timecodes_and_removes_internal_fact_ids() -> None:
    script = """### 0—12秒

### 事实依据

- fact_1234567890abcdef / source_abcdef1234567890
"""

    normalized = normalize_script_format(script)

    assert "## 00:00 - 00:12" in normalized
    assert "fact_" not in normalized
    assert "source_abcdef1234567890" in normalized


def test_format_gate_names_the_missing_piece_instead_of_saying_empty() -> None:
    issues = script_format_issues(INLINE_TIMECODE_SCRIPT)

    assert issues, "行内时间码的原始稿本来就不该直接通过"
    assert any("00:00" in issue for issue in issues)
    assert not any("过短或为空" in issue for issue in issues)


def test_inline_timecodes_are_hoisted_into_parseable_segments() -> None:
    normalized = normalize_script_format(INLINE_TIMECODE_SCRIPT)

    # ① 格式门放行
    assert script_format_issues(normalized) == []
    assert "【0:00" not in normalized

    # ② 下游真的能切段。只断言①的话，文档结构已经切坏也会照样通过。
    segments = TIME_SEGMENT_PATTERN.findall(normalized)
    assert len(segments) == 3
    assert [(f"{a}:{b}", f"{c}:{d}") for a, b, c, d, _ in segments] == [
        ("00:00", "00:05"),
        ("00:05", "00:18"),
        ("00:18", "00:31"),
    ]
    for *_, body in segments:
        assert "### 旁白" in body
        assert "### 镜头" in body
        assert "### 事实依据" in body


def test_hoisting_leaves_already_correct_scripts_untouched() -> None:
    script = (
        "# 标题\n\n## 00:00 - 00:05\n\n### 旁白\n\n结果先出现，账户跳出强制平仓四个字。\n\n"
        "### 镜头\n\n手机屏幕特写后拉远到人物背影，窗外是城市夜景与成排亮着的窗口。\n\n"
        "### 叙事功能\n\n- beat_id：beat_01（冷开场）\n- 承接关系：提出核心悬念。\n"
        "- 价值状态变化：从持有希望跌入本金告急。\n\n"
        "### 事实依据\n\n- event_e717176054b14055\n- source_04143e1b7dd74c4d\n\n"
        "## 结尾\n\n停在最后一个已核验事实之后的未完成动作与环境余音，不追加总结。\n"
    )

    normalized = normalize_script_format(script)

    assert normalized.count("## 00:00 - 00:05") == 1
    assert script_format_issues(normalized) == []


def test_mixed_heading_and_inline_marker_does_not_duplicate_a_segment() -> None:
    """模型常混着写：正确的二级标题下面又留一个行内标记。

    重复补一个标题会切出一个空段落，而格式门照样放行——正是这个修复要挡住的
    那种"静默切坏"。
    """
    mixed = (
        "# 标题\n\n## 00:00 - 00:05\n\n"
        "### 旁白\n【0:00—0:05】结果先出现，账户跳出强制平仓四个字，屏幕一片通红。\n\n"
        "### 镜头\n【0:00—0:05】手机屏幕特写后拉远到人物背影，窗外是成排亮着的窗口。\n\n"
        "### 叙事功能\n- beat_id：beat_01\n\n"
        "### 事实依据\n- event_e717176054b14055\n\n"
        "### 旁白\n【0:05—0:18】他四十岁，做贸易，妻子九月生二胎，女儿六岁在学钢琴。\n\n"
        "### 镜头\n【0:05—0:18】公寓晚餐，他在阳台反复刷新行情，屏幕的光打在脸上。\n\n"
        "### 叙事功能\n- beat_id：beat_02\n\n"
        "### 事实依据\n- event_06b53c734ebf4cc3\n\n"
        "## 结尾\n\n停在未完成的动作与环境余音，不追加总结。\n"
    )

    normalized = normalize_script_format(mixed)
    segments = TIME_SEGMENT_PATTERN.findall(normalized)

    assert normalized.count("## 00:00 - 00:05") == 1
    assert len(segments) == 2
    assert all(body.strip() for *_, body in segments)
    assert script_format_issues(normalized) == []


def test_clock_range_written_as_a_third_level_heading_is_promoted() -> None:
    """真实输出里出现过 `### 00:00 - 00:05（钩子·5秒）`，下游只认二级标题。"""
    script = (
        "# 标题\n\n### 00:00 - 00:05（钩子·5秒）\n\n"
        "### 旁白\n\n结果先出现，账户跳出强制平仓四个字。\n\n"
        "### 镜头\n\n手机屏幕特写后拉远到人物背影与城市夜景。\n\n"
        "### 叙事功能\n\n- beat_id：beat_01（冷开场）\n- 承接关系：提出核心悬念。\n\n"
        "### 事实依据\n\n- event_e717176054b14055\n- source_04143e1b7dd74c4d\n\n"
        "## 结尾\n\n停在未完成的动作与环境余音，不追加任何总结。\n"
    )

    normalized = normalize_script_format(script)

    assert "## 00:00 - 00:05" in normalized
    assert script_format_issues(normalized) == []
    assert len(TIME_SEGMENT_PATTERN.findall(normalized)) == 1
