from __future__ import annotations

from app.models import Event
from app.services.script.review import review_issue_is_blocking
from app.services.script.story import young_case_score
from app.services.script.writer import normalize_script_format


def test_review_separates_fact_blockers_from_style_advice() -> None:
    assert review_issue_is_blocking("金额异常，可能为笔误，建议核实")
    assert review_issue_is_blocking("该段没有来源ID，无法核验")
    assert not review_issue_is_blocking("时间线略有跳跃，可以更清晰")
    assert not review_issue_is_blocking("结尾略有说教")


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
