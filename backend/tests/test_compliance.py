from __future__ import annotations

from app.services.production.compliance import build_entity_rules, sanitize, summarize


def test_real_company_and_index_are_generalised() -> None:
    rules = build_entity_rules(["SK海力士", "韩国交易所"], [])
    text = "KOSPI指数暴跌新闻标题，SK海力士股价急跌图表在大屏上滚动。"
    clean, hits = sanitize(text, rules)
    assert "SK海力士" not in clean
    assert "KOSPI" not in clean
    assert "大盘指数" in clean
    assert "一家大型企业" in clean
    assert {hit.category for hit in hits} == {"trademark"}


def test_self_harm_becomes_filmable_behaviour() -> None:
    clean, hits = sanitize("他留下遗书后自杀，房间里发现了尸体。")
    for word in ("遗书", "自杀", "尸体"):
        assert word not in clean
    assert "失去联系" in clean
    assert all(hit.category == "self_harm" for hit in hits)


def test_financial_hype_is_neutralised() -> None:
    clean, _ = sanitize("有人靠内幕消息一夜暴富，账户翻倍。")
    for word in ("内幕", "暴富", "翻倍"):
        assert word not in clean


def test_real_person_name_is_replaced() -> None:
    rules = build_entity_rules([], ["金敏俊"])
    clean, hits = sanitize("金敏俊坐在桌前。", rules)
    assert "金敏俊" not in clean
    assert "当事人" in clean
    assert hits[0].category == "real_person"


def test_clean_text_is_untouched() -> None:
    text = "当事人坐在桌前，手指停在屏幕边缘，视线先落到窗外再回到手上。"
    clean, hits = sanitize(text)
    assert clean == text
    assert hits == []


def test_sanitize_does_not_truncate_control_information() -> None:
    text = (
        "第一帧：当事人位于画面左三分之一，面向右侧窗户，距离窗台约一米二。"
        "KOSPI大屏在背景中景偏右。47°标准镜头，摄影机高度与视线齐平，单一横移。"
    )
    clean, _ = sanitize(text, build_entity_rules([], []))
    for keep in ("第一帧", "画面左三分之一", "一米二", "47°标准镜头", "单一横移"):
        assert keep in clean, "合规改写不能删掉控制信息"


def test_summary_is_human_readable() -> None:
    _, hits = sanitize("自杀 暴富", build_entity_rules([], []))
    assert "自伤与死亡" in summarize(hits)
    assert "金融夸大" in summarize(hits)
